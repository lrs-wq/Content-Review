"""HTTP routes for video moderation, multipart upload, URL input, and health checks."""

from __future__ import annotations

import json
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.core.auditor import VideoAuditInput, VideoAuditor
from app.core.brief import to_brief_response
from app.core.config import Settings, get_settings
from app.core.errors import VideoAuditError
from app.core.video_loader import LoadedVideoFile, RemoteVideoLoader
from app.schemas.moderation import (
    BriefModerationResponse,
    HealthResponse,
    VideoModerationRequest,
    VideoModerationResponse,
)


router = APIRouter()


@lru_cache(maxsize=1)
def get_auditor() -> VideoAuditor:
    """Reuse one auditor instance so optional models/clients can cache state across requests."""

    return VideoAuditor(get_settings())


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return dependency and policy status for readiness checks and the web test page."""

    auditor = get_auditor()
    return HealthResponse(
        status="ok",
        service="video-audit-service",
        policy_version=auditor.policy_version,
        max_duration_seconds=auditor.settings.max_duration_seconds,
        frame_sample_fps=auditor.settings.frame_sample_fps,
        max_sampled_frames=auditor.settings.max_sampled_frames,
        ffmpeg_status=auditor.ffmpeg_status,
        image_audit_status=auditor.image_audit_status,
        text_audit_status=auditor.text_audit_status,
        asr_status=auditor.asr_status,
        selective_ocr_status=auditor.selective_ocr_status,
    )


@router.post("/v1/moderation/video/upload", response_model=VideoModerationResponse | BriefModerationResponse)
async def moderate_video_upload(
    content_id: str = Form(...),
    user_id: str = Form(...),
    scene: str = Form("general"),
    video_url: str | None = Form(None),
    related_text: str | None = Form(None),
    provided_asr_text: str | None = Form(None),
    skip_ocr: bool = Form(False),
    context: str | None = Form(None),
    brief: bool = Query(True),
    file: UploadFile | None = File(None),
) -> VideoModerationResponse | BriefModerationResponse:
    """Accept a multipart video file or video_url form field and run moderation.

    Both input styles are normalized into a temporary local file because ffprobe, ffmpeg, frame
    extraction, and optional ASR all work against filesystem paths.
    """

    settings = get_settings()
    context_payload = _parse_context_form(context)
    loaded = await _load_form_video(file=file, video_url=video_url, settings=settings)
    return _audit_loaded_video(
        loaded=loaded,
        content_id=content_id,
        user_id=user_id,
        scene=scene,
        related_text=related_text,
        provided_asr_text=provided_asr_text,
        skip_ocr=skip_ocr,
        context=context_payload,
        brief=brief,
    )


@router.post("/v1/moderation/video", response_model=VideoModerationResponse | BriefModerationResponse)
async def moderate_video_url(
    payload: VideoModerationRequest,
    brief: bool = Query(True),
) -> VideoModerationResponse | BriefModerationResponse:
    """Accept a JSON video_url request and run the same moderation pipeline."""

    loaded = RemoteVideoLoader(get_settings()).download(payload.video_url)
    return _audit_loaded_video(
        loaded=loaded,
        content_id=payload.content_id,
        user_id=payload.user_id,
        scene=payload.scene,
        related_text=payload.related_text,
        provided_asr_text=payload.provided_asr_text,
        skip_ocr=payload.skip_ocr,
        context=payload.context,
        brief=brief,
    )


async def _load_form_video(
    file: UploadFile | None,
    video_url: str | None,
    settings: Settings,
) -> LoadedVideoFile:
    """Load the first available video source from multipart form fields."""

    if file is not None:
        return await _store_uploaded_video(file, settings)
    if video_url and video_url.strip():
        return RemoteVideoLoader(settings).download(video_url)
    raise VideoAuditError(400, "missing_video_source", "provide file or video_url")


async def _store_uploaded_video(file: UploadFile, settings: Settings) -> LoadedVideoFile:
    """Stream an uploaded video into a bounded temporary file for ffprobe/ffmpeg."""

    suffix = Path(file.filename or "").suffix or ".video"
    temp_path = ""
    total_bytes = 0
    try:
        # Stream the upload in chunks so the API does not hold the full video in memory. The byte
        # limit is enforced during streaming before any expensive processing starts.
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_path = temp_file.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.max_video_bytes:
                    raise HTTPException(status_code=413, detail="视频文件过大")
                temp_file.write(chunk)
        return LoadedVideoFile(
            path=Path(temp_path),
            filename=file.filename or Path(temp_path).name,
            mime_type=file.content_type or "application/octet-stream",
            bytes=total_bytes,
        )
    except Exception:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
        raise


def _audit_loaded_video(
    loaded: LoadedVideoFile,
    content_id: str,
    user_id: str,
    scene: str,
    related_text: str | None,
    provided_asr_text: str | None,
    skip_ocr: bool,
    context: dict[str, Any],
    brief: bool,
) -> VideoModerationResponse | BriefModerationResponse:
    """Run the shared moderation pipeline for uploaded and downloaded video files."""

    try:
        payload = VideoAuditInput(
            content_id=content_id,
            user_id=user_id,
            scene=scene,
            related_text=related_text,
            provided_asr_text=provided_asr_text,
            skip_ocr=skip_ocr,
            context=context,
            video_path=loaded.path,
            filename=loaded.filename,
            mime_type=loaded.mime_type,
            bytes=loaded.bytes,
        )
        response = get_auditor().audit(payload)
        if brief:
            return to_brief_response(response)
        return response
    finally:
        loaded.path.unlink(missing_ok=True)


def _parse_context_form(context: str | None) -> dict[str, Any]:
    """Parse the optional multipart context JSON object before expensive video work."""

    if not context:
        return {}
    try:
        parsed_context = json.loads(context)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="上下文必须是 JSON 对象") from exc
    if not isinstance(parsed_context, dict):
        raise HTTPException(status_code=400, detail="上下文必须是 JSON 对象")
    return parsed_context
