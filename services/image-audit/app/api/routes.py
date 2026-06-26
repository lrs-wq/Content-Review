from __future__ import annotations

import json
from functools import lru_cache

from fastapi import APIRouter, File, Form, UploadFile

from app.core.auditor import ImageAuditor
from app.core.config import get_settings
from app.schemas.moderation import (
    HealthResponse,
    ImageModerationRequest,
    ImageModerationResponse,
)


router = APIRouter()


@lru_cache(maxsize=1)
def get_auditor() -> ImageAuditor:
    return ImageAuditor(get_settings())


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
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


@router.post("/v1/moderation/image", response_model=ImageModerationResponse)
def moderate_image(payload: ImageModerationRequest) -> ImageModerationResponse:
    return get_auditor().audit(payload)


@router.post("/v1/moderation/image/upload", response_model=ImageModerationResponse)
async def moderate_image_upload(
    content_id: str = Form(...),
    user_id: str = Form(...),
    scene: str = Form("general"),
    related_text: str | None = Form(None),
    provided_ocr_text: str | None = Form(None),
    skip_ocr: bool = Form(False),
    context: str | None = Form(None),
    file: UploadFile = File(...),
) -> ImageModerationResponse:
    context_payload = {}
    if context:
        parsed_context = json.loads(context)
        if isinstance(parsed_context, dict):
            context_payload = parsed_context

    payload = ImageModerationRequest(
        content_id=content_id,
        user_id=user_id,
        scene=scene,
        related_text=related_text,
        provided_ocr_text=provided_ocr_text,
        skip_ocr=skip_ocr,
        image_bytes=await file.read(),
        image_mime=file.content_type,
        image_filename=file.filename,
        context=context_payload,
    )
    return get_auditor().audit(payload)
