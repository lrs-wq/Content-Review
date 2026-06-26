from functools import lru_cache

from fastapi import APIRouter

from app.core.auditor import TextAuditor
from app.core.config import get_settings
from app.schemas.moderation import HealthResponse, TextModerationRequest, TextModerationResponse


router = APIRouter()


@lru_cache(maxsize=1)
def get_auditor() -> TextAuditor:
    return TextAuditor(get_settings())


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    auditor = get_auditor()
    return HealthResponse(
        status="ok",
        service="text-audit-service",
        policy_version=auditor.policy_version,
        model_status=auditor.model_status,
        classifier_status=auditor.classifier_status,
        agent_status=auditor.agent_status,
    )


@router.post("/v1/moderation/text", response_model=TextModerationResponse)
def moderate_text(payload: TextModerationRequest) -> TextModerationResponse:
    return get_auditor().audit(payload)
