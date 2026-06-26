from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import Settings
from app.core.decision import ImageDecisionMaker
from app.core.image_loader import ImageLoader
from app.core.ocr import OcrEngine
from app.core.text_client import TextAuditClient
from app.core.visual_analyzer import VisualAnalyzer, VisualResult
from app.core.vision_safety_agent import VisionSafetyAgent, VisionSafetyResult
from app.schemas.moderation import (
    ImageModerationRequest,
    ImageModerationResponse,
    OcrPayload,
)


class ImageAuditor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.policy_version = settings.policy_version
        self.loader = ImageLoader(settings)
        self.visual = VisualAnalyzer(
            settings.thresholds_path,
            settings.enable_nsfw_model,
            settings.nsfw_model_name,
            settings.nsfw_model_device,
            settings.nsfw_download_on_request,
            settings.enable_nudenet,
        )
        self.ocr = OcrEngine(settings)
        self.text_client = TextAuditClient(settings)
        self.vision_safety = VisionSafetyAgent(settings)
        self.decider = ImageDecisionMaker(settings.thresholds_path)

    @property
    def visual_status(self) -> str:
        return self.visual.status

    @property
    def ocr_status(self) -> str:
        return self.ocr.status

    @property
    def text_audit_status(self) -> str:
        return self.text_client.status

    @property
    def vision_safety_status(self) -> str:
        return self.vision_safety.status

    def audit(self, payload: ImageModerationRequest) -> ImageModerationResponse:
        started = time.perf_counter()
        loaded = self.loader.load(payload)
        visual_result = self.visual.analyze(loaded.pil_image, loaded.metadata)
        if payload.skip_ocr:
            from app.core.ocr import OcrResult

            ocr_result = OcrResult(
                status="skipped",
                text="",
                lines=[],
                provider="skip_ocr",
                elapsed_ms=0.0,
                error="skipped_by_request",
            )
        else:
            ocr_result = self.ocr.recognize(loaded.pil_image, payload.provided_ocr_text)
        text_review = self.text_client.review_ocr_text(payload, ocr_result.text)
        vision_safety_result = self.vision_safety.review(
            loaded.pil_image,
            payload,
            visual_result,
            ocr_result.text,
        )
        if vision_safety_result.detections:
            from app.core.visual_analyzer import VisualResult

            visual_result = VisualResult(
                scores={**visual_result.scores, **vision_safety_result.scores},
                detections=[*visual_result.detections, *vision_safety_result.detections],
            )
        visual_result, skin_exposure_review_status = self._gate_skin_exposure_with_vision_safety(
            visual_result,
            vision_safety_result,
        )
        decision = self.decider.decide(visual_result, text_review)

        return ImageModerationResponse(
            trace_id=self._trace_id(),
            content_id=payload.content_id,
            risk_level=decision.risk_level,
            action=decision.action,
            labels=decision.labels,
            scores=decision.scores,
            image=loaded.metadata,
            ocr=OcrPayload(
                status=ocr_result.status,
                text=ocr_result.text,
                lines=ocr_result.lines,
                provider=ocr_result.provider,
                elapsed_ms=ocr_result.elapsed_ms,
                error=ocr_result.error,
            ),
            text_review=text_review,
            detections=visual_result.detections,
            policy_version=self.policy_version,
            model_status={
                "visual": self.visual_status,
                "vision_safety": self.vision_safety_status,
                "vision_safety_review": vision_safety_result.status,
                "skin_exposure_review": skin_exposure_review_status,
                "ocr": self.ocr_status,
                "text_audit": self.text_audit_status,
            },
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    @staticmethod
    def _gate_skin_exposure_with_vision_safety(
        visual_result: VisualResult,
        vision_safety_result: VisionSafetyResult,
    ) -> tuple[VisualResult, str]:
        has_skin_heuristic = any(
            detection.label == "skin_exposure_heuristic" for detection in visual_result.detections
        )
        if not has_skin_heuristic:
            return visual_result, "not_present"
        if not vision_safety_result.status.startswith("no_risk:"):
            return visual_result, "kept:vision_safety_not_clear"

        nsfw_score = float(visual_result.scores.get("nsfw", 0.0))
        nudity_score = float(visual_result.scores.get("nudity", 0.0))
        has_sexual_model_support = nsfw_score >= 0.20 or nudity_score >= 0.20 or any(
            detection.label in {"nsfw", "nudity", "vision_sexual"}
            for detection in visual_result.detections
            if detection.label != "skin_exposure_heuristic"
        )
        if has_sexual_model_support:
            return visual_result, "kept:model_support"

        filtered_detections = [
            detection
            for detection in visual_result.detections
            if detection.label != "skin_exposure_heuristic"
        ]
        return (
            VisualResult(scores=visual_result.scores, detections=filtered_detections),
            "suppressed:vision_safety_no_risk",
        )

    @staticmethod
    def _trace_id() -> str:
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"img_tr_{now}_{uuid4().hex[:8]}"
