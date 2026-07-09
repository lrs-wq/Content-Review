"""Unified moderation routes for text, image, and video requests."""

from __future__ import annotations

import json
import mimetypes
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.client import ForwardedResponse, GatewayClient
from app.core.config import get_settings
from app.core.errors import GatewayError
from app.core.job_store import generate_content_id, get_job_store
from app.core.response_format import content_type_label, status_label


router = APIRouter()

CONTENT_TYPE_ALIASES = {
    "text": "text",
    "txt": "text",
    "文本": "text",
    "image": "image",
    "img": "image",
    "picture": "image",
    "图片": "image",
    "video": "video",
    "vid": "video",
    "视频": "video",
}

META_FIELDS = {"content_type", "media_type", "audit_type", "type", "brief"}


@lru_cache(maxsize=1)
def get_gateway_client() -> GatewayClient:
    """Reuse the gateway client settings across requests."""

    return GatewayClient(get_settings())


@router.get("/health")
async def health(client: GatewayClient = Depends(get_gateway_client)) -> dict[str, Any]:
    """Return gateway settings and downstream dependency availability."""

    settings = get_settings()
    downstream = await client.health()
    return {
        "status": "ok",
        "status_label": status_label("ok"),
        "service": "content-review-gateway",
        "policy_version": settings.policy_version,
        "port": settings.port,
        "downstream": downstream,
    }


@router.post("/v1/moderation")
async def moderate(
    request: Request,
    brief: bool | None = Query(default=None),
    client: GatewayClient = Depends(get_gateway_client),
) -> JSONResponse:
    """Accept one text/image/video moderation request and route it to the matching service.

    JSON requests are used for text and image URL/base64 inputs. Multipart requests are used for
    image/video uploads, and can also carry text-only requests for callers that prefer forms.
    """

    payload = await _parse_request(request)
    content_id = _ensure_content_id(payload.fields)
    use_brief = _resolve_brief(brief, payload.fields)
    content_type = _resolve_content_type(payload.fields, payload.file)
    forwarded = await _forward_by_content_type(client, payload, content_type, use_brief)
    return _response(forwarded, content_id=content_id)


@router.post("/v1/moderation/async")
async def submit_moderation_async(
    request: Request,
    background_tasks: BackgroundTasks,
    brief: bool | None = Query(default=None),
    client: GatewayClient = Depends(get_gateway_client),
) -> JSONResponse:
    """Create an async moderation job and return its content id immediately."""

    payload = await _parse_request(request)
    content_id = _ensure_content_id(payload.fields)
    use_brief = _resolve_brief(brief, payload.fields)
    content_type = _resolve_content_type(payload.fields, payload.file)
    store = get_job_store()
    background_payload = await _prepare_background_payload(payload, store, content_id)
    store.create(content_id=content_id, content_type=content_type, brief=use_brief)
    background_tasks.add_task(_run_async_moderation, content_id, content_type, background_payload, use_brief, client)
    return JSONResponse(
        status_code=202,
        content={
            "content_id": content_id,
            "status": "queued",
            "status_label": status_label("queued"),
            "content_type": content_type,
            "content_type_label": content_type_label(content_type),
            "result_path": f"/v1/moderation/result/{content_id}",
            "result_url": _result_url(request, content_id),
        },
    )


@router.get("/v1/moderation/result/{content_id}")
async def get_moderation_result(content_id: str) -> JSONResponse:
    """Return async moderation status/result for polling clients."""

    return _job_response(content_id)


@router.get("/v1/moderation/result")
async def get_moderation_result_by_query(content_id: str = Query(...)) -> JSONResponse:
    """Query async moderation status/result with a query parameter."""

    return _job_response(content_id)


@router.post("/v1/moderation/text")
async def moderate_text_compat(
    request: Request,
    brief: bool | None = Query(default=None),
    client: GatewayClient = Depends(get_gateway_client),
) -> JSONResponse:
    """Compatibility endpoint for callers that still use the text-audit path on gateway port."""

    payload = await _parse_request(request)
    content_id = _ensure_content_id(payload.fields)
    use_brief = _resolve_brief(brief, payload.fields)
    forwarded = await client.post_json(
        get_settings().text_audit_url,
        _text_payload(payload.fields),
        use_brief,
    )
    return _response(forwarded, content_id=content_id)


@router.post("/v1/moderation/image")
@router.post("/v1/moderation/image/upload")
async def moderate_image_compat(
    request: Request,
    brief: bool | None = Query(default=None),
    client: GatewayClient = Depends(get_gateway_client),
) -> JSONResponse:
    """Compatibility endpoints for callers that still use image-audit paths on gateway port."""

    payload = await _parse_request(request)
    content_id = _ensure_content_id(payload.fields)
    use_brief = _resolve_brief(brief, payload.fields)
    forwarded = await _forward_image(client, payload, use_brief)
    return _response(forwarded, content_id=content_id)


@router.post("/v1/moderation/video/upload")
async def moderate_video_compat(
    request: Request,
    brief: bool | None = Query(default=None),
    client: GatewayClient = Depends(get_gateway_client),
) -> JSONResponse:
    """Compatibility endpoint for callers that still use the video-audit path on gateway port."""

    payload = await _parse_request(request)
    content_id = _ensure_content_id(payload.fields)
    use_brief = _resolve_brief(brief, payload.fields)
    forwarded = await _forward_video(client, payload, use_brief)
    return _response(forwarded, content_id=content_id)


async def _forward_by_content_type(
    client: GatewayClient,
    payload: "ParsedPayload",
    content_type: str,
    brief: bool,
) -> ForwardedResponse:
    """Forward a parsed payload to the matching downstream moderation service."""

    if content_type == "text":
        return await client.post_json(
            get_settings().text_audit_url,
            _text_payload(payload.fields),
            brief,
        )
    if content_type == "image":
        return await _forward_image(client, payload, brief)
    if content_type == "video":
        return await _forward_video(client, payload, brief)
    raise GatewayError(400, "unsupported_content_type", f"unsupported content_type: {content_type}")


async def _run_async_moderation(
    content_id: str,
    content_type: str,
    payload: "ParsedPayload",
    brief: bool,
    client: GatewayClient,
) -> None:
    """Run downstream moderation after the async submit response has been sent."""

    store = get_job_store()
    try:
        store.mark_processing(content_id)
        forwarded = await _forward_by_content_type(client, payload, content_type, brief)
        store.mark_completed(content_id, forwarded.status_code, _response_body(forwarded, content_id))
    except GatewayError as exc:
        store.mark_failed(content_id, exc.error, exc.detail, http_status=exc.status_code)
    except Exception as exc:  # pragma: no cover - defensive background boundary
        store.mark_failed(content_id, "async_job_failed", str(exc), http_status=500)
    finally:
        store.remove_upload(payload.stored_file_path)


async def _forward_image(client: GatewayClient, payload: "ParsedPayload", brief: bool) -> ForwardedResponse:
    """Forward an image request either to the upload endpoint or the JSON endpoint."""

    settings = get_settings()
    if payload.file or payload.stored_file_path:
        file_bytes = await payload.read_file_bytes()
        return await client.post_multipart(
            settings.image_audit_upload_url,
            _image_upload_fields(payload.fields),
            file_bytes,
            payload.filename or "image",
            payload.content_type or "application/octet-stream",
            brief,
        )
    return await client.post_json(settings.image_audit_json_url, _image_json_payload(payload.fields), brief)


async def _forward_video(client: GatewayClient, payload: "ParsedPayload", brief: bool) -> ForwardedResponse:
    """Forward a video request as either multipart upload or JSON video_url."""

    settings = get_settings()
    if payload.file or payload.stored_file_path:
        file_bytes = await payload.read_file_bytes()
        return await client.post_multipart(
            settings.video_audit_upload_url,
            _video_upload_fields(payload.fields),
            file_bytes,
            payload.filename or "video",
            payload.content_type or "application/octet-stream",
            brief,
        )
    if _first_scalar(payload.fields.get("video_url")):
        return await client.post_json(settings.video_audit_json_url, _video_json_payload(payload.fields), brief)
    raise GatewayError(400, "missing_video_source", "video moderation requires file or video_url")


class ParsedPayload:
    """Normalized request body with scalar fields and an optional uploaded file."""

    def __init__(
        self,
        fields: dict[str, Any],
        file: StarletteUploadFile | None,
        stored_file_path: str | None = None,
        stored_filename: str | None = None,
        stored_content_type: str | None = None,
    ) -> None:
        self.fields = fields
        self.file = file
        self.stored_file_path = stored_file_path
        self.stored_filename = stored_filename
        self.stored_content_type = stored_content_type

    @property
    def filename(self) -> str | None:
        """Return the original upload filename when a request includes a file."""

        if self.file:
            return self.file.filename
        return self.stored_filename

    @property
    def content_type(self) -> str | None:
        """Return the upload content type when available."""

        if self.file:
            return self.file.content_type
        return self.stored_content_type

    async def read_file_bytes(self) -> bytes:
        """Read upload bytes from either the request upload or async job storage."""

        if self.file:
            return await self.file.read()
        if self.stored_file_path:
            from pathlib import Path

            return Path(self.stored_file_path).read_bytes()
        return b""


async def _prepare_background_payload(payload: ParsedPayload, store, content_id: str) -> ParsedPayload:
    """Detach request data from FastAPI upload objects before background processing starts."""

    fields = dict(payload.fields)
    if not payload.file:
        return ParsedPayload(fields=fields, file=None)
    file_bytes = await payload.read_file_bytes()
    stored_path = store.save_upload(content_id, payload.filename or "upload.bin", file_bytes)
    return ParsedPayload(
        fields=fields,
        file=None,
        stored_file_path=str(stored_path),
        stored_filename=payload.filename or stored_path.name,
        stored_content_type=payload.content_type or "application/octet-stream",
    )


def _job_response(content_id: str) -> JSONResponse:
    """Return one async job record in the polling API shape."""

    record = get_job_store().get(content_id)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={
                "content_id": content_id,
                "status": "not_found",
                "status_label": status_label("not_found"),
                "message": "未找到该 content_id 的审核任务",
                "result": None,
            },
        )
    return JSONResponse(status_code=200, content=record)


def _result_url(request: Request, content_id: str) -> str:
    """Build the same-port polling URL for a submitted async job."""

    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/v1/moderation/result/{content_id}"


async def _parse_request(request: Request) -> ParsedPayload:
    """Parse JSON or multipart/form-data into a common payload object."""

    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        body = await request.json()
        if not isinstance(body, dict):
            raise GatewayError(400, "invalid_json_body", "JSON body must be an object")
        return ParsedPayload(fields=body, file=None)
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        fields: dict[str, Any] = {}
        upload: StarletteUploadFile | None = None
        for key, value in form.multi_items():
            if isinstance(value, StarletteUploadFile):
                if key == "file" or upload is None:
                    upload = value
                continue
            _append_form_field(fields, key, str(value))
        return ParsedPayload(fields=fields, file=upload)
    raise GatewayError(415, "unsupported_media_type", "use application/json or multipart/form-data")


def _append_form_field(fields: dict[str, Any], key: str, value: str) -> None:
    """Preserve repeated form fields as lists while keeping single fields scalar."""

    if key not in fields:
        fields[key] = value
        return
    current = fields[key]
    if isinstance(current, list):
        current.append(value)
    else:
        fields[key] = [current, value]


def _resolve_content_type(fields: dict[str, Any], file: StarletteUploadFile | None) -> str:
    """Resolve content_type from explicit fields or infer it from file/text/image fields."""

    for key in ("content_type", "media_type", "audit_type", "type"):
        raw = _first_scalar(fields.get(key))
        if raw:
            normalized = CONTENT_TYPE_ALIASES.get(raw.strip().lower())
            if normalized:
                return normalized
            raise GatewayError(400, "unsupported_content_type", f"unsupported content_type: {raw}")
    if file:
        guessed = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
        if guessed.startswith("image/"):
            return "image"
        if guessed.startswith("video/"):
            return "video"
        raise GatewayError(400, "unknown_file_type", "file content type must be image/* or video/*")
    if _first_scalar(fields.get("text")):
        return "text"
    if _first_scalar(fields.get("image_base64")) or _first_scalar(fields.get("image_url")):
        return "image"
    if _first_scalar(fields.get("video_url")):
        return "video"
    raise GatewayError(400, "missing_content_type", "provide content_type or enough fields to infer it")


def _resolve_brief(query_brief: bool | None, fields: dict[str, Any]) -> bool:
    """Resolve brief mode with query parameter taking precedence over body/form fields."""

    if query_brief is not None:
        return query_brief
    return _to_bool(fields.get("brief"), True)


def _text_payload(fields: dict[str, Any]) -> dict[str, Any]:
    """Build the downstream text-audit JSON request body."""

    return {
        "content_id": _required(fields, "content_id"),
        "user_id": _required(fields, "user_id"),
        "scene": _first_scalar(fields.get("scene")) or "general",
        "text": _required(fields, "text"),
        "related_text": _first_scalar(fields.get("related_text")),
        "image_ocr_text": _list_field(fields.get("image_ocr_text")),
        "video_transcript": _first_scalar(fields.get("video_transcript")),
        "context": _context_dict(fields.get("context")),
    }


def _image_json_payload(fields: dict[str, Any]) -> dict[str, Any]:
    """Build the downstream image JSON request body, dropping gateway-only fields."""

    allowed = {
        "content_id",
        "user_id",
        "scene",
        "image_base64",
        "image_url",
        "related_text",
        "provided_ocr_text",
        "skip_ocr",
        "context",
    }
    payload = {key: value for key, value in fields.items() if key in allowed}
    payload["content_id"] = _required(payload, "content_id")
    payload["user_id"] = _required(payload, "user_id")
    payload.setdefault("scene", "general")
    payload["skip_ocr"] = _to_bool(payload.get("skip_ocr"), False)
    payload["context"] = _context_dict(payload.get("context"))
    return payload


def _image_upload_fields(fields: dict[str, Any]) -> dict[str, str]:
    """Build multipart form fields accepted by image-audit-service."""

    return _upload_fields(
        fields,
        optional=("related_text", "provided_ocr_text", "skip_ocr", "context"),
        text_aliases={},
    )


def _video_upload_fields(fields: dict[str, Any]) -> dict[str, str]:
    """Build multipart form fields accepted by video-audit-service."""

    return _upload_fields(
        fields,
        optional=("video_url", "related_text", "provided_asr_text", "skip_ocr", "context"),
        text_aliases={"provided_asr_text": ("provided_asr_text", "video_transcript")},
    )


def _video_json_payload(fields: dict[str, Any]) -> dict[str, Any]:
    """Build the downstream video JSON request body for URL-based moderation."""

    payload = {
        "content_id": _required(fields, "content_id"),
        "user_id": _required(fields, "user_id"),
        "scene": _first_scalar(fields.get("scene")) or "general",
        "video_url": _required(fields, "video_url"),
        "related_text": _first_scalar(fields.get("related_text")),
        "provided_asr_text": _first_scalar(fields.get("provided_asr_text"))
        or _first_scalar(fields.get("video_transcript")),
        "skip_ocr": _to_bool(fields.get("skip_ocr"), False),
        "context": _context_dict(fields.get("context")),
    }
    return payload


def _upload_fields(
    fields: dict[str, Any],
    optional: tuple[str, ...],
    text_aliases: dict[str, tuple[str, ...]],
) -> dict[str, str]:
    """Build common upload fields while keeping context as a JSON string."""

    result = {
        "content_id": _required(fields, "content_id"),
        "user_id": _required(fields, "user_id"),
        "scene": _first_scalar(fields.get("scene")) or "general",
    }
    for key in optional:
        aliases = text_aliases.get(key, (key,))
        value = next((_first_scalar(fields.get(alias)) for alias in aliases if _first_scalar(fields.get(alias))), None)
        if value is None and key == "context":
            value = json.dumps(_context_dict(fields.get("context")), ensure_ascii=False)
        elif key == "skip_ocr":
            value = str(_to_bool(fields.get("skip_ocr"), False)).lower()
        if value is not None:
            result[key] = value
    return result


def _context_dict(value: Any) -> dict[str, Any]:
    """Parse context from object or JSON string, returning an empty object when omitted."""

    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    raw = _first_scalar(value)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GatewayError(400, "invalid_context", "context must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise GatewayError(400, "invalid_context", "context must be a JSON object")
    return parsed


def _list_field(value: Any) -> list[str]:
    """Parse repeated, JSON-array, comma-separated, or newline-separated string fields."""

    if value is None or value == "":
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_list_field(item))
        return result
    if isinstance(value, tuple):
        return _list_field(list(value))
    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    separators = "\n" if "\n" in raw else ","
    return [item.strip() for item in raw.split(separators) if item.strip()]


def _required(fields: dict[str, Any], key: str) -> str:
    """Read a required scalar field or raise a gateway validation error."""

    value = _first_scalar(fields.get(key))
    if value is None or value == "":
        raise GatewayError(400, "missing_required_field", f"{key} is required")
    return value


def _ensure_content_id(fields: dict[str, Any]) -> str:
    """Ensure downstream services always receive a content_id, generating one when omitted."""

    content_id = _first_scalar(fields.get("content_id"))
    if content_id:
        fields["content_id"] = content_id
        return content_id
    generated = generate_content_id()
    fields["content_id"] = generated
    return generated


def _first_scalar(value: Any) -> str | None:
    """Return the first scalar string from form/JSON values."""

    if value is None:
        return None
    if isinstance(value, list):
        return _first_scalar(value[0]) if value else None
    if isinstance(value, tuple):
        return _first_scalar(list(value))
    if isinstance(value, (dict, bool, int, float)):
        return str(value)
    return str(value)


def _to_bool(value: Any, default: bool) -> bool:
    """Parse common boolean forms used by JSON, form fields, and query strings."""

    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    raw = _first_scalar(value)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _response(forwarded: ForwardedResponse, content_id: str | None) -> JSONResponse:
    """Return downstream JSON without wrapping so callers see the final moderation result."""

    return JSONResponse(status_code=forwarded.status_code, content=_response_body(forwarded, content_id))


def _response_body(forwarded: ForwardedResponse, content_id: str | None) -> Any:
    """Build the response body while preserving the downstream moderation shape."""

    if isinstance(forwarded.body, dict) and content_id:
        body = dict(forwarded.body)
        body.setdefault("content_id", content_id)
        return body
    return forwarded.body
