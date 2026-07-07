"""HTTP routes for video moderation, multipart upload, and health checks."""

from __future__ import annotations

import json
import tempfile
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.core.auditor import VideoAuditInput, VideoAuditor
from app.core.brief import to_brief_response
from app.core.config import get_settings
from app.schemas.moderation import BriefModerationResponse, HealthResponse, VideoModerationResponse


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
    related_text: str | None = Form(None),
    provided_asr_text: str | None = Form(None),
    skip_ocr: bool = Form(False),
    context: str | None = Form(None),
    brief: bool = Query(True),
    file: UploadFile = File(...),
) -> VideoModerationResponse | BriefModerationResponse:
    """Accept a multipart video upload and run synchronous moderation.

    The endpoint writes the upload to a temporary file because ffprobe/ffmpeg and optional ASR
    tools operate on filesystem paths. The temp file is always removed after the request.
    """

    settings = get_settings()
    context_payload = {}
    if context:
        # Video upload uses a form field for context, so validate that it is a JSON object before
        # the expensive file/probe/model work begins.
        parsed_context = json.loads(context)
        if not isinstance(parsed_context, dict):
            raise HTTPException(status_code=400, detail="context must be a JSON object")
        context_payload = parsed_context

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
                    raise HTTPException(status_code=413, detail="video_file_too_large")
                temp_file.write(chunk)

        payload = VideoAuditInput(
            content_id=content_id,
            user_id=user_id,
            scene=scene,
            related_text=related_text,
            provided_asr_text=provided_asr_text,
            skip_ocr=skip_ocr,
            context=context_payload,
            video_path=Path(temp_path),
            filename=file.filename or Path(temp_path).name,
            mime_type=file.content_type or "application/octet-stream",
            bytes=total_bytes,
        )
        response = get_auditor().audit(payload)
        if brief:
            return to_brief_response(response)
        return response
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
