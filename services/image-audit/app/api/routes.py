"""HTTP routes for image moderation, multipart upload, and health checks."""

from __future__ import annotations

import json
from functools import lru_cache

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.core.auditor import ImageAuditor
from app.core.brief import to_brief_response
from app.core.config import get_settings
from app.schemas.moderation import (
    BriefModerationResponse,
    HealthResponse,
    ImageModerationRequest,
    ImageModerationResponse,
)


router = APIRouter()


@lru_cache(maxsize=1)
def get_auditor() -> ImageAuditor:
    """Reuse the auditor so OCR/model objects are cached across requests."""

    return ImageAuditor(get_settings())


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Expose model/provider status for readiness checks and the web tester."""

    auditor = get_auditor()
    return HealthResponse(
        status="ok",
        service="image-audit-service",
        policy_version=auditor.policy_version,
        visual_status=auditor.visual_status,
        vision_safety_status=auditor.vision_safety_status,
        ocr_status=auditor.ocr_status,
        text_audit_status=auditor.text_audit_status,
    )


@router.post("/v1/moderation/image", response_model=ImageModerationResponse | BriefModerationResponse)
def moderate_image(
    payload: ImageModerationRequest,
    brief: bool | None = Query(default=None),
) -> ImageModerationResponse | BriefModerationResponse:
    """Moderate a JSON image request using base64 or URL input."""

    response = get_auditor().audit(payload)
    use_brief = payload.brief if brief is None else brief
    if use_brief:
        return to_brief_response(response)
    return response


@router.post("/v1/moderation/image/upload", response_model=ImageModerationResponse | BriefModerationResponse)
async def moderate_image_upload(
    content_id: str = Form(...),
    user_id: str = Form(...),
    scene: str = Form("general"),
    image_url: str | None = Form(None),
    related_text: str | None = Form(None),
    provided_ocr_text: str | None = Form(None),
    skip_ocr: bool = Form(False),
    context: str | None = Form(None),
    brief: bool = Query(True),
    file: UploadFile | None = File(None),
) -> ImageModerationResponse | BriefModerationResponse:
    """Accept multipart image upload or image_url and convert it into the shared request schema."""

    context_payload = {}
    if context:
        # Invalid context is ignored here for backwards compatibility with early manual tests; the
        # JSON API path still benefits from Pydantic validation.
        parsed_context = json.loads(context)
        if isinstance(parsed_context, dict):
            context_payload = parsed_context

    if file is None and not (image_url and image_url.strip()):
        raise HTTPException(status_code=400, detail="必须提供图片文件或 image_url")

    image_bytes = await file.read() if file is not None else None
    payload = ImageModerationRequest(
        # Upload bytes are stored on the model but excluded from the serialized response schema.
        content_id=content_id,
        user_id=user_id,
        scene=scene,
        related_text=related_text,
        provided_ocr_text=provided_ocr_text,
        skip_ocr=skip_ocr,
        image_url=image_url.strip() if image_url else None,
        image_bytes=image_bytes,
        image_mime=file.content_type if file is not None else None,
        image_filename=file.filename if file is not None else None,
        context=context_payload,
        brief=brief,
    )
    response = get_auditor().audit(payload)
    if brief:
        return to_brief_response(response)
    return response
