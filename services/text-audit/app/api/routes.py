"""HTTP routes for text moderation and health checks."""

from functools import lru_cache

from fastapi import APIRouter, Query

from app.core.auditor import TextAuditor
from app.core.brief import to_brief_response
from app.core.config import get_settings
from app.schemas.moderation import (
    BriefModerationResponse,
    HealthResponse,
    TextModerationRequest,
    TextModerationResponse,
)


router = APIRouter()


@lru_cache(maxsize=1)
def get_auditor() -> TextAuditor:
    """Reuse one auditor so rule tables and optional models are loaded only once."""

    return TextAuditor(get_settings())


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Expose policy/model readiness for the web tester and deployment probes."""

    auditor = get_auditor()
    return HealthResponse(
        status="ok",
        service="text-audit-service",
        policy_version=auditor.policy_version,
        model_status=auditor.model_status,
        classifier_status=auditor.classifier_status,
        agent_status=auditor.agent_status,
    )


@router.post("/v1/moderation/text", response_model=TextModerationResponse | BriefModerationResponse)
def moderate_text(
    payload: TextModerationRequest,
    brief: bool | None = Query(default=None),
) -> TextModerationResponse | BriefModerationResponse:
    """Run synchronous text moderation for one request payload.

    Brief output is enabled by default for external callers. Internal services and debugging tools
    can pass ``brief=false`` in either the query string or JSON body to receive the full response.
    """

    response = get_auditor().audit(payload)
    use_brief = payload.brief if brief is None else brief
    if use_brief:
        return to_brief_response(response)
    return response
