from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.core.config import load_yaml
from app.schemas.moderation import DetectionPayload, ImageMetadata


@dataclass(frozen=True)
class VisualResult:
    scores: dict[str, float]
    detections: list[DetectionPayload]


@dataclass(frozen=True)
class NsfwPrediction:
    score: float
    label: str
    evidence: str


@dataclass(frozen=True)
class NudeDetection:
    label: str
    score: float
    box: list[float] | None


class NsfwImageClassifier:
    unsafe_label_hints = ("nsfw", "porn", "hentai", "sexy", "sexual", "explicit", "nude", "nudity", "adult")
    safe_label_hints = ("sfw", "safe", "normal", "neutral")

    def __init__(self, enabled: bool, model_name: str, device: int, download_on_request: bool) -> None:
        self.enabled = enabled
        self.model_name = model_name
        self.device = device
        self.download_on_request = download_on_request
        self._classifier: Any | None = None
        self._load_attempted = False
        self._last_load_attempt_at = 0.0
        self._load_error: str | None = None

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self._classifier is not None:
            return f"loaded:{self.model_name}"
        if self._load_error:
            return f"error:{self._load_error}"
        mode = "download_on_request" if self.download_on_request else "local_cache_only"
        return f"configured:{self.model_name}:{mode}"

    def predict(self, image: Image.Image) -> NsfwPrediction | None:
        if not self.enabled:
            return None
        classifier = self._load()
        if classifier is None:
            return None
        try:
            try:
                raw_outputs = classifier(image.convert("RGB"), top_k=None)
            except TypeError:
                raw_outputs = classifier(image.convert("RGB"), top_k=5)
        except Exception as exc:  # pragma: no cover - depends on optional model runtime
            self._load_error = f"predict_failed:{type(exc).__name__}"
            return None

        outputs = self._flatten_outputs(raw_outputs)
        if not outputs:
            return None

        unsafe_score = 0.0
        safe_score = 0.0
        top_label = ""
        top_score = 0.0
        evidence_parts: list[str] = []

        for item in outputs:
            label = str(item.get("label", "")).strip()
            score = float(item.get("score", 0.0))
            label_lower = label.lower()
            if score > top_score:
                top_label = label
                top_score = score
            if self._matches(label_lower, self.unsafe_label_hints):
                unsafe_score = max(unsafe_score, score)
                evidence_parts.append(f"{label}:{score:.3f}")
            elif self._matches(label_lower, self.safe_label_hints):
                safe_score = max(safe_score, score)

        if unsafe_score <= 0 and safe_score > 0:
            unsafe_score = max(0.0, 1.0 - safe_score)
        if not evidence_parts and top_label:
            evidence_parts.append(f"top={top_label}:{top_score:.3f}")

        return NsfwPrediction(
            score=max(0.0, min(1.0, unsafe_score)),
            label=top_label or "unknown",
            evidence=", ".join(evidence_parts),
        )

    def _load(self) -> Any | None:
        if self._classifier is not None:
            return self._classifier
        now = time.monotonic()
        if self._load_attempted and now - self._last_load_attempt_at < 60:
            return None
        self._load_attempted = True
        self._last_load_attempt_at = now
        try:
            from transformers import AutoImageProcessor, AutoModelForImageClassification, pipeline  # type: ignore

            local_files_only = not self.download_on_request
            image_processor = AutoImageProcessor.from_pretrained(
                self.model_name,
                local_files_only=local_files_only,
            )
            model = AutoModelForImageClassification.from_pretrained(
                self.model_name,
                local_files_only=local_files_only,
            )
            try:
                self._classifier = pipeline(
                    "image-classification",
                    model=model,
                    image_processor=image_processor,
                    device=self.device,
                )
            except TypeError:
                self._classifier = pipeline(
                    "image-classification",
                    model=model,
                    feature_extractor=image_processor,
                    device=self.device,
                )
            self._load_error = None
            return self._classifier
        except Exception as exc:  # pragma: no cover - depends on optional dependencies/network
            if not self.download_on_request:
                self._load_error = "model_not_cached"
            else:
                self._load_error = f"{type(exc).__name__}"
            return None

    @staticmethod
    def _flatten_outputs(raw_outputs: Any) -> list[dict[str, Any]]:
        if isinstance(raw_outputs, list) and raw_outputs and isinstance(raw_outputs[0], list):
            raw_outputs = raw_outputs[0]
        if not isinstance(raw_outputs, list):
            return []
        return [item for item in raw_outputs if isinstance(item, dict)]

    @staticmethod
    def _matches(label: str, hints: tuple[str, ...]) -> bool:
        return any(hint in label for hint in hints)


class NudeNetDetector:
    high_risk_classes = (
        "ANUS_EXPOSED",
        "BUTTOCKS_EXPOSED",
        "FEMALE_BREAST_EXPOSED",
        "FEMALE_GENITALIA_EXPOSED",
        "MALE_GENITALIA_EXPOSED",
    )
    review_classes = high_risk_classes + (
        "BELLY_EXPOSED",
        "ARMPITS_EXPOSED",
    )

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._detector: Any | None = None
        self._load_attempted = False
        self._load_error: str | None = None

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self._detector is not None:
            return "loaded:nudenet"
        if self._load_error:
            return f"error:{self._load_error}"
        return "configured:nudenet"

    def detect(self, image: Image.Image) -> list[NudeDetection]:
        if not self.enabled:
            return []
        detector = self._load()
        if detector is None:
            return []

        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
                temp_path = temp_file.name
            image.convert("RGB").save(temp_path, format="JPEG", quality=92)
            raw_detections = detector.detect(temp_path)
        except Exception as exc:  # pragma: no cover - depends on optional model runtime
            self._load_error = f"detect_failed:{type(exc).__name__}"
            return []
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

        if not isinstance(raw_detections, list):
            return []

        parsed: list[NudeDetection] = []
        for item in raw_detections:
            if not isinstance(item, dict):
                continue
            label = str(item.get("class", item.get("label", ""))).strip()
            if not label or label.upper() not in self.review_classes:
                continue
            score = float(item.get("score", 0.0))
            parsed.append(
                NudeDetection(
                    label=label,
                    score=max(0.0, min(1.0, score)),
                    box=self._parse_box(item.get("box")),
                )
            )
        return parsed

    def _load(self) -> Any | None:
        if self._detector is not None:
            return self._detector
        if self._load_attempted:
            return None
        self._load_attempted = True
        try:
            from nudenet import NudeDetector  # type: ignore

            self._detector = NudeDetector()
            self._load_error = None
            return self._detector
        except Exception as exc:  # pragma: no cover - depends on optional dependencies/network
            self._load_error = f"{type(exc).__name__}"
            return None

    @staticmethod
    def _parse_box(raw_box: Any) -> list[float] | None:
        if isinstance(raw_box, (list, tuple)) and len(raw_box) == 4:
            return [float(value) for value in raw_box]
        return None


class VisualAnalyzer:
    def __init__(
        self,
        thresholds_path: Path,
        enable_nsfw_model: bool,
        nsfw_model_name: str,
        nsfw_model_device: int,
        nsfw_download_on_request: bool,
        enable_nudenet: bool,
    ) -> None:
        thresholds = load_yaml(thresholds_path)
        image_thresholds = thresholds.get("image", {}) if isinstance(thresholds.get("image", {}), dict) else {}
        self.nsfw_block_score = float(image_thresholds.get("nsfw_block_score", 0.9))
        self.nsfw_review_score = float(image_thresholds.get("nsfw_review_score", 0.6))
        self.nudity_block_score = float(image_thresholds.get("nudity_block_score", 0.88))
        self.nudity_review_score = float(image_thresholds.get("nudity_review_score", 0.55))
        self.skin_review_score = float(image_thresholds.get("skin_review_score", 0.65))
        self.qr_review_score = float(image_thresholds.get("qr_review_score", 0.65))
        self.nsfw_classifier = NsfwImageClassifier(
            enable_nsfw_model,
            nsfw_model_name,
            nsfw_model_device,
            nsfw_download_on_request,
        )
        self.nudenet = NudeNetDetector(enable_nudenet)

    @property
    def status(self) -> str:
        return (
            "heuristic:enabled,"
            f"nsfw_model:{self.nsfw_classifier.status},"
            f"nudenet:{self.nudenet.status}"
        )

    def analyze(self, image: Image.Image, metadata: ImageMetadata) -> VisualResult:
        array = np.array(image)
        skin_score, skin_ratio = self._skin_exposure_score(array)
        qr_score, qr_evidence = self._qr_score(array)
        quality_score, quality_label = self._quality_score(metadata)
        nsfw_prediction = self.nsfw_classifier.predict(image)
        nude_detections = self.nudenet.detect(image)
        nsfw_score = nsfw_prediction.score if nsfw_prediction else 0.0
        nudity_score = max((detection.score for detection in nude_detections), default=0.0)

        scores = {
            "nsfw": round(nsfw_score, 4),
            "nudity": round(nudity_score, 4),
            "skin_exposure": round(skin_score, 4),
            "qr_code": round(qr_score, 4),
            "image_quality": round(quality_score, 4),
        }
        detections: list[DetectionPayload] = []

        if nsfw_prediction and nsfw_score >= self.nsfw_review_score:
            detections.append(
                DetectionPayload(
                    label="nsfw",
                    score=round(nsfw_score, 4),
                    source="falconsai_nsfw_image_detection",
                    action="block" if nsfw_score >= self.nsfw_block_score else "review",
                    risk_level="high" if nsfw_score >= self.nsfw_block_score else "medium",
                    evidence=nsfw_prediction.evidence or nsfw_prediction.label,
                )
            )

        for nude_detection in nude_detections:
            if nude_detection.score < self.nudity_review_score:
                continue
            detections.append(
                DetectionPayload(
                    label="nudity",
                    score=round(nude_detection.score, 4),
                    box=nude_detection.box,
                    source="nudenet",
                    action="block" if nude_detection.score >= self.nudity_block_score else "review",
                    risk_level="high" if nude_detection.score >= self.nudity_block_score else "medium",
                    evidence=nude_detection.label,
                )
            )

        if skin_score >= self.skin_review_score:
            detections.append(
                DetectionPayload(
                    label="skin_exposure_heuristic",
                    score=round(skin_score, 4),
                    source="heuristic",
                    action="review",
                    risk_level="medium",
                    evidence=f"skin_like_pixel_ratio={skin_ratio:.3f}",
                )
            )

        if qr_score >= self.qr_review_score:
            detections.append(
                DetectionPayload(
                    label="qr_code",
                    score=round(qr_score, 4),
                    source="opencv",
                    action="review",
                    risk_level="medium",
                    evidence=qr_evidence,
                )
            )

        if quality_score > 0:
            detections.append(
                DetectionPayload(
                    label=quality_label,
                    score=round(quality_score, 4),
                    source="metadata",
                    action="review",
                    risk_level="low",
                )
            )

        return VisualResult(scores=scores, detections=detections)

    @staticmethod
    def _skin_exposure_score(rgb: np.ndarray) -> tuple[float, float]:
        # This is a conservative heuristic for review routing, not a nudity model.
        ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
        lower = np.array([0, 133, 77], dtype=np.uint8)
        upper = np.array([255, 173, 127], dtype=np.uint8)
        skin_mask = cv2.inRange(ycrcb, lower, upper)

        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        skin_mask = np.where((skin_mask > 0) & (saturation > 25) & (value > 60), 255, 0).astype(np.uint8)

        ratio = float(np.count_nonzero(skin_mask)) / float(skin_mask.size)
        if ratio < 0.18:
            return 0.0, ratio
        score = min(0.88, 0.45 + ratio * 0.75)
        return score, ratio

    @staticmethod
    def _qr_score(rgb: np.ndarray) -> tuple[float, str | None]:
        detector = cv2.QRCodeDetector()
        data, points, _ = detector.detectAndDecode(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        if points is None:
            return 0.0, None
        if data:
            preview = data[:80] + ("..." if len(data) > 80 else "")
            return 0.82, preview
        return 0.68, "qr-like pattern detected"

    @staticmethod
    def _quality_score(metadata: ImageMetadata) -> tuple[float, str]:
        min_side = min(metadata.width, metadata.height)
        max_side = max(metadata.width, metadata.height)
        if min_side < 80:
            return 0.45, "image_too_small"
        if max_side / max(1, min_side) > 8:
            return 0.45, "image_extreme_aspect_ratio"
        return 0.0, "image_quality"
