"""Decision fusion for image moderation signals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import load_yaml
from app.core.visual_analyzer import VisualResult
from app.schemas.moderation import DetectionPayload, TextReviewPayload


@dataclass(frozen=True)
class ImageDecision:
    """Internal final image decision before API serialization."""

    risk_level: str
    action: str
    labels: list[str]
    scores: dict[str, float]


class ImageDecisionMaker:
    """Combines visual detections and OCR text review into one action."""

    def __init__(self, thresholds_path: Path) -> None:
        thresholds = load_yaml(thresholds_path)
        image_thresholds = thresholds.get("image", {}) if isinstance(thresholds.get("image", {}), dict) else {}
        self.nsfw_block_score = float(image_thresholds.get("nsfw_block_score", 0.9))
        self.nsfw_review_score = float(image_thresholds.get("nsfw_review_score", 0.6))
        self.nudity_block_score = float(image_thresholds.get("nudity_block_score", 0.88))
        self.nudity_review_score = float(image_thresholds.get("nudity_review_score", 0.55))
        self.qr_review_score = float(image_thresholds.get("qr_review_score", 0.65))
        self.ocr_review_score = float(image_thresholds.get("ocr_review_score", 0.65))

    def decide(self, visual: VisualResult, text_review: TextReviewPayload) -> ImageDecision:
        """Apply conservative image decision rules."""

        scores = dict(visual.scores)
        scores["ocr_text"] = round(float(text_review.score), 4)
        scores["overall"] = round(max(scores.values(), default=0.0), 4)

        labels = self._labels(visual.detections, text_review, scores)
        # Explicit block signals from text or vision dominate because one strong image/OCR cue is
        # enough to make the upload unsafe.
        if text_review.action == "block":
            return ImageDecision(risk_level="high", action="block", labels=labels, scores=scores)
        if scores.get("nsfw", 0.0) >= self.nsfw_block_score:
            return ImageDecision(risk_level="high", action="block", labels=labels, scores=scores)
        if scores.get("nudity", 0.0) >= self.nudity_block_score:
            return ImageDecision(risk_level="high", action="block", labels=labels, scores=scores)
        if any(detection.action == "block" for detection in visual.detections):
            return ImageDecision(risk_level="high", action="block", labels=labels, scores=scores)

        if text_review.action == "review":
            return ImageDecision(
                risk_level=self._max_risk("medium", text_review.risk_level),
                action="review",
                labels=labels,
                scores=scores,
            )
        if scores.get("nsfw", 0.0) >= self.nsfw_review_score:
            return ImageDecision(risk_level="medium", action="review", labels=labels, scores=scores)
        if scores.get("nudity", 0.0) >= self.nudity_review_score:
            return ImageDecision(risk_level="medium", action="review", labels=labels, scores=scores)
        if scores.get("qr_code", 0.0) >= self.qr_review_score:
            return ImageDecision(risk_level="medium", action="review", labels=labels, scores=scores)
        review_detections = [detection for detection in visual.detections if detection.action == "review"]
        if review_detections:
            return ImageDecision(
                risk_level=self._max_detection_risk(review_detections),
                action="review",
                labels=labels,
                scores=scores,
            )
        if scores.get("image_quality", 0.0) > 0:
            return ImageDecision(risk_level="low", action="review", labels=labels, scores=scores)

        if scores["overall"] > 0:
            return ImageDecision(risk_level="low", action="allow", labels=labels, scores=scores)
        return ImageDecision(risk_level="none", action="allow", labels=labels, scores=scores)

    def _labels(
        self,
        detections: list[DetectionPayload],
        text_review: TextReviewPayload,
        scores: dict[str, float],
    ) -> list[str]:
        """Collect unique labels from thresholded scores, detections, and OCR review."""

        labels: list[str] = []
        if scores.get("nsfw", 0.0) >= self.nsfw_review_score:
            labels.append("nsfw")
        if scores.get("nudity", 0.0) >= self.nudity_review_score:
            labels.append("nudity")
        if scores.get("qr_code", 0.0) >= self.qr_review_score:
            labels.append("qr_code")
        for detection in detections:
            if detection.label not in labels:
                labels.append(detection.label)
        if text_review.used and text_review.action in {"review", "block"}:
            labels.append("ocr_sensitive")
            labels.extend(label for label in text_review.labels if label not in labels)
        return list(dict.fromkeys(labels))

    @staticmethod
    def _max_risk(current: str, incoming: str) -> str:
        """Return the higher risk level."""

        rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        return incoming if rank.get(incoming, 0) > rank.get(current, 0) else current

    @staticmethod
    def _max_detection_risk(detections: list[DetectionPayload]) -> str:
        """Return the highest risk level among visual detections."""

        rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        return max((detection.risk_level for detection in detections), key=lambda value: rank.get(value, 0), default="low")
