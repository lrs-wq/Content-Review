"""Final decision fusion for sampled frames, OCR text, and ASR transcript risk."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.moderation import EvidencePayload, FrameAuditPayload, TextReviewPayload


@dataclass(frozen=True)
class VideoDecision:
    """Final moderation decision after frame and text risk fusion."""

    action: str
    risk_level: str
    labels: list[str]
    scores: dict[str, float]
    evidence: list[EvidencePayload]


class VideoDecisionMaker:
    """Combines image-frame decisions with aggregated video text decisions."""

    def decide(
        self,
        frame_results: list[FrameAuditPayload],
        text_review: TextReviewPayload,
        asr_has_text: bool,
    ) -> VideoDecision:
        """Apply conservative fusion: any block signal blocks the whole video."""

        labels = self._labels(frame_results, text_review, asr_has_text)
        evidence = self._evidence(frame_results, text_review)

        # Overall score is the strongest signal from either the frame path or the text path. Ratios
        # are useful for dashboards and threshold tuning, even though the first version uses simple
        # rule-based fusion.
        frame_score = max((float(frame.scores.get("overall", 0.0)) for frame in frame_results), default=0.0)
        text_score = float(text_review.score) if text_review.used else 0.0
        block_count = sum(1 for frame in frame_results if frame.action == "block")
        review_count = sum(1 for frame in frame_results if frame.action == "review")
        scores = {
            "frame": round(frame_score, 4),
            "video_text": round(text_score, 4),
            "overall": round(max(frame_score, text_score), 4),
            "block_frame_ratio": round(block_count / max(1, len(frame_results)), 4),
            "review_frame_ratio": round(review_count / max(1, len(frame_results)), 4),
        }

        # A single block frame is enough to block the video because the user can publish harmful
        # content in only one short segment.
        if block_count > 0 or text_review.action == "block":
            return VideoDecision(action="block", risk_level="high", labels=labels, scores=scores, evidence=evidence)

        # Review is sticky: any reviewed frame or reviewed transcript sends the video to manual
        # review. This is safer than averaging frame scores, which can hide brief unsafe segments.
        if review_count > 0 or text_review.action == "review":
            risk_level = "medium"
            if any(frame.risk_level == "high" for frame in frame_results) or text_review.risk_level == "high":
                risk_level = "high"
            return VideoDecision(action="review", risk_level=risk_level, labels=labels, scores=scores, evidence=evidence)
        if scores["overall"] > 0:
            return VideoDecision(action="allow", risk_level="low", labels=labels, scores=scores, evidence=evidence)
        return VideoDecision(action="allow", risk_level="none", labels=labels, scores=scores, evidence=evidence)

    @staticmethod
    def _labels(frame_results: list[FrameAuditPayload], text_review: TextReviewPayload, asr_has_text: bool) -> list[str]:
        """Collect unique labels while adding video-level rollup labels."""

        labels: list[str] = []
        for frame in frame_results:
            labels.extend(frame.labels)
            if frame.action in {"review", "block"} and "video_frame_risk" not in labels:
                labels.append("video_frame_risk")
        if text_review.used and text_review.action in {"review", "block"}:
            labels.append("video_text_sensitive")
            labels.extend(text_review.labels)
        if asr_has_text and text_review.action in {"review", "block"} and "video_asr_sensitive" not in labels:
            labels.append("video_asr_sensitive")
        return list(dict.fromkeys(label for label in labels if label))

    @staticmethod
    def _evidence(frame_results: list[FrameAuditPayload], text_review: TextReviewPayload) -> list[EvidencePayload]:
        """Build compact evidence for UI/debugging without returning every raw model field."""

        evidence: list[EvidencePayload] = []
        for frame in frame_results:
            if frame.action not in {"review", "block"}:
                continue
            evidence.append(
                EvidencePayload(
                    type="frame",
                    label=",".join(frame.labels) or "frame_risk",
                    action=frame.action,
                    risk_level=frame.risk_level,
                    score=float(frame.scores.get("overall", 0.0)),
                    source="image-audit-service",
                    timestamp_seconds=frame.timestamp_seconds,
                    text=_frame_evidence_text(frame),
                )
            )
        if text_review.used and text_review.action in {"review", "block"}:
            evidence.append(
                EvidencePayload(
                    type="text",
                    label=",".join(text_review.labels) or "video_text_sensitive",
                    action=text_review.action,
                    risk_level=text_review.risk_level,
                    score=text_review.score,
                    source="text-audit-service",
                    text=_compact_text_evidence(text_review.evidence) or text_review.error,
                )
            )
        # Limit evidence volume in the synchronous response. A future async/manual-review pipeline
        # can store full evidence separately.
        return evidence[:20]


def _compact_text_evidence(values: list[str]) -> str | None:
    """Return a short deduplicated evidence string suitable for brief responses."""

    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return None
    return "、".join(list(dict.fromkeys(cleaned))[:5])


def _frame_evidence_text(frame: FrameAuditPayload) -> str | None:
    """Prefer matched text evidence, then explain frame audit failures, then raw OCR fallback."""

    text_evidence = _compact_text_evidence(frame.text_evidence)
    if text_evidence:
        return text_evidence
    if frame.error:
        return _friendly_frame_error(frame.error)
    return (frame.ocr_text or "")[:200] or None


def _friendly_frame_error(error: str) -> str:
    """Turn transport errors into a short business-facing explanation."""

    lowered = error.lower()
    if "timed out" in lowered or "timeout" in lowered or "readtimeout" in lowered:
        return "图片帧审核服务超时，未完成OCR/视觉审核"
    if "connection" in lowered or "connect" in lowered:
        return "图片帧审核服务连接失败，未完成OCR/视觉审核"
    return str(error)[:120]
