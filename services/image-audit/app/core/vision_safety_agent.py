from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

from app.core.config import Settings
from app.core.visual_analyzer import VisualResult
from app.schemas.moderation import DetectionPayload, ImageModerationRequest


@dataclass(frozen=True)
class VisionSafetyResult:
    used: bool
    status: str
    scores: dict[str, float]
    detections: list[DetectionPayload]
    elapsed_ms: float


@dataclass(frozen=True)
class SafetyVerdict:
    label: str
    score: float
    action: str
    risk_level: str
    evidence: str


class ShieldGemma2LocalProvider:
    policies = (
        ("vision_sexual", "No sexually explicit or nude content."),
        ("vision_violence_gore", "No graphic violence, gore, blood, terrorism, war crimes, or severe injury."),
        ("vision_dangerous", "No dangerous content, weapons misuse, illegal activity, or instructions that enable harm."),
    )

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.vision_safety_model_name
        self.device = settings.vision_safety_device
        self.download_on_request = settings.vision_safety_download_on_request
        self.allow_cpu = settings.vision_safety_allow_cpu
        self.review_score = settings.vision_safety_review_score
        self.block_score = settings.vision_safety_block_score
        self._processor: Any | None = None
        self._model: Any | None = None
        self._load_attempted = False
        self._last_load_attempt_at = 0.0
        self._load_error: str | None = None

    @property
    def status(self) -> str:
        if self._model is not None:
            return f"loaded:{self.model_name}"
        if self._load_error:
            return f"error:{self._load_error}"
        mode = "download_on_request" if self.download_on_request else "local_cache_only"
        return f"configured:{self.model_name}:{mode}"

    def review(self, image: Image.Image, _: ImageModerationRequest, __: str) -> list[SafetyVerdict]:
        loaded = self._load()
        if not loaded:
            return []
        processor, model, torch = loaded
        verdicts: list[SafetyVerdict] = []
        for label, policy in self.policies:
            try:
                inputs = processor(images=image.convert("RGB"), text=policy, return_tensors="pt")
                if self.device != "auto":
                    device = next(model.parameters()).device
                    inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}
                with torch.no_grad():
                    outputs = model(**inputs)
                if hasattr(outputs, "probabilities"):
                    probabilities = outputs.probabilities
                else:
                    probabilities = torch.softmax(outputs.logits, dim=-1)
                # ShieldGemma2 returns [Yes, No]; Yes means the image violates the policy.
                score = float(probabilities.reshape(-1, probabilities.shape[-1])[0, 0].item())
            except Exception as exc:  # pragma: no cover - optional heavy model runtime
                self._load_error = f"predict_failed:{type(exc).__name__}"
                continue
            if score >= self.review_score:
                verdicts.append(self._to_verdict(label, score, policy))
        return verdicts

    def _load(self) -> tuple[Any, Any, Any] | None:
        if self._processor is not None and self._model is not None:
            import torch  # type: ignore

            return self._processor, self._model, torch
        now = time.monotonic()
        if self._load_attempted and now - self._last_load_attempt_at < 300:
            return None
        self._load_attempted = True
        self._last_load_attempt_at = now
        try:
            import torch  # type: ignore
            from transformers import AutoProcessor, ShieldGemma2ForImageClassification  # type: ignore

            cuda_available = torch.cuda.is_available()
            if self.device == "cuda" and not cuda_available:
                self._load_error = "cuda_not_available"
                return None
            if self.device in {"cpu", "auto"} and not cuda_available and not self.allow_cpu:
                self._load_error = "cpu_inference_disabled"
                return None

            local_files_only = not self.download_on_request
            self._processor = AutoProcessor.from_pretrained(self.model_name, local_files_only=local_files_only)
            kwargs: dict[str, Any] = {"local_files_only": local_files_only}
            if self.device == "auto":
                kwargs["device_map"] = "auto"
                kwargs["torch_dtype"] = torch.bfloat16 if torch.cuda.is_available() else torch.float32
            self._model = ShieldGemma2ForImageClassification.from_pretrained(self.model_name, **kwargs)
            if self.device != "auto":
                target = torch.device("cuda" if self.device == "cuda" and torch.cuda.is_available() else "cpu")
                self._model.to(target)
            self._model.eval()
            self._load_error = None
            return self._processor, self._model, torch
        except Exception as exc:  # pragma: no cover - optional heavy model runtime
            self._processor = None
            self._model = None
            if not self.download_on_request:
                self._load_error = "model_not_cached"
            else:
                self._load_error = f"{type(exc).__name__}"
            return None

    def _to_verdict(self, label: str, score: float, evidence: str) -> SafetyVerdict:
        return SafetyVerdict(
            label=label,
            score=max(0.0, min(1.0, score)),
            action="block" if score >= self.block_score else "review",
            risk_level="high" if score >= self.block_score else "medium",
            evidence=evidence,
        )


class OpenAICompatibleVisionProvider:
    def __init__(self, settings: Settings) -> None:
        self.provider = settings.vision_safety_provider
        self.model_name = settings.vision_safety_model_name
        self.endpoint_url = settings.vision_safety_endpoint_url.rstrip("/")
        self.api_key_env = settings.vision_safety_api_key_env
        self.timeout_seconds = settings.vision_safety_timeout_seconds
        self.max_new_tokens = settings.vision_safety_max_new_tokens
        self.review_score = settings.vision_safety_review_score
        self.block_score = settings.vision_safety_block_score
        self._last_error: str | None = None

    @property
    def status(self) -> str:
        if not self.endpoint_url:
            return "disabled:missing_endpoint"
        if self._last_error:
            return f"error:{self._last_error}"
        return f"configured:{self.provider}:{self.model_name}"

    def review(self, image: Image.Image, payload: ImageModerationRequest, ocr_text: str) -> list[SafetyVerdict]:
        if not self.endpoint_url:
            return []
        body = {
            "model": self.model_name,
            "temperature": 0,
            "max_tokens": self.max_new_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a strict multimodal content safety classifier. Return only valid JSON.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._prompt(payload, ocr_text)},
                        {"type": "image_url", "image_url": {"url": self._image_data_url(image)}},
                    ],
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        api_key = os.getenv(self.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = httpx.post(self.endpoint_url, headers=headers, json=body, timeout=self.timeout_seconds)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            verdict = self._parse_content(str(content))
            self._last_error = None
            return [verdict] if verdict else []
        except Exception as exc:  # pragma: no cover - depends on optional remote service
            self._last_error = f"{type(exc).__name__}"
            return []

    def _prompt(self, payload: ImageModerationRequest, ocr_text: str) -> str:
        context = {
            "scene": payload.scene,
            "related_text": payload.related_text or "",
            "ocr_text": ocr_text,
            "context": payload.context,
        }
        return (
            "Classify the image and attached context for community safety moderation. "
            "Focus on sexual content, nudity, violence/gore, terrorism, weapons, dangerous acts, "
            "hate, harassment, self-harm, illegal activity, deception/spam, and sensitive political/public-affairs risk. "
            "Return JSON with keys: action allow|review|block, risk_level none|low|medium|high, "
            "labels array, score number 0..1, reason short string. "
            f"Context: {json.dumps(context, ensure_ascii=False)}"
        )

    def _parse_content(self, content: str) -> SafetyVerdict | None:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            lowered = content.lower()
            if "unsafe" not in lowered and "block" not in lowered and "review" not in lowered:
                return None
            parsed = {"action": "review", "risk_level": "medium", "labels": ["vision_safety"], "score": 0.65, "reason": content[:200]}
        else:
            parsed = json.loads(match.group(0))
        action = str(parsed.get("action", "allow")).lower()
        score = float(parsed.get("score", 0.0))
        if action == "allow" and score < self.review_score:
            return None
        if action not in {"review", "block"}:
            action = "block" if score >= self.block_score else "review"
        labels = parsed.get("labels", ["vision_safety"])
        label = str(labels[0] if isinstance(labels, list) and labels else "vision_safety")
        return SafetyVerdict(
            label=label,
            score=max(0.0, min(1.0, score)),
            action="block" if action == "block" or score >= self.block_score else "review",
            risk_level=str(parsed.get("risk_level", "high" if score >= self.block_score else "medium")),
            evidence=str(parsed.get("reason", ""))[:240],
        )

    @staticmethod
    def _image_data_url(image: Image.Image) -> str:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=88)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"


class VisionSafetyAgent:
    endpoint_providers = {"openai_compatible", "llama_guard4_openai", "shieldgemma2_openai"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.enable_vision_safety
        self.provider_name = settings.vision_safety_provider
        self.trigger_mode = settings.vision_safety_trigger_mode
        self.gray_min_score = settings.vision_safety_gray_min_score
        self.gray_max_score = settings.vision_safety_gray_max_score
        self.review_score = settings.vision_safety_review_score
        self.review_on_unavailable = settings.vision_safety_review_on_unavailable
        if not self.enabled:
            self.provider: ShieldGemma2LocalProvider | OpenAICompatibleVisionProvider | None = None
        elif self.provider_name == "shieldgemma2_local":
            self.provider = ShieldGemma2LocalProvider(settings)
        elif self.provider_name in self.endpoint_providers:
            self.provider = OpenAICompatibleVisionProvider(settings)
        else:
            self.provider = None

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.provider is None:
            return f"error:unsupported_provider:{self.provider_name}"
        return self.provider.status

    def review(
        self,
        image: Image.Image,
        payload: ImageModerationRequest,
        visual_result: VisualResult,
        ocr_text: str,
    ) -> VisionSafetyResult:
        started = time.perf_counter()
        if not self.enabled:
            return self._empty("disabled", started)
        if self.provider is None:
            return self._empty(f"unsupported_provider:{self.provider_name}", started)
        should_review, reason = self._should_review(payload, visual_result)
        if not should_review:
            return self._empty(f"skipped:{reason}", started)
        verdicts = self.provider.review(image, payload, ocr_text)
        if not verdicts and self.review_on_unavailable and self._provider_unavailable():
            verdicts = [
                SafetyVerdict(
                    label="vision_safety_unavailable",
                    score=self.review_score,
                    action="review",
                    risk_level="medium",
                    evidence=f"gray image routed to vision safety but provider unavailable: {self.provider.status}",
                )
            ]
        detections = [
            DetectionPayload(
                label=verdict.label,
                score=round(verdict.score, 4),
                source=f"vision_safety:{self.provider_name}",
                action=verdict.action,  # type: ignore[arg-type]
                risk_level=verdict.risk_level,  # type: ignore[arg-type]
                evidence=verdict.evidence,
            )
            for verdict in verdicts
        ]
        scores = {"vision_safety": round(max((verdict.score for verdict in verdicts), default=0.0), 4)}
        return VisionSafetyResult(
            used=True,
            status="ok" if detections else f"no_risk:{self.provider.status}",
            scores=scores,
            detections=detections,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def _should_review(self, payload: ImageModerationRequest, visual_result: VisualResult) -> tuple[bool, str]:
        if payload.context.get("force_vision_safety") is True:
            return True, "forced_by_context"
        mode = self.trigger_mode.lower()
        if mode == "all":
            return True, "all"
        if mode in {"never", "disabled"}:
            return False, "trigger_disabled"
        score = max(visual_result.scores.values(), default=0.0)
        if mode == "gray":
            if self.gray_min_score <= score <= self.gray_max_score:
                return True, "gray_score"
            if any(detection.label in {"qr_code", "skin_exposure_heuristic"} for detection in visual_result.detections):
                return True, "gray_detection"
            return False, "not_gray"
        if mode == "risk":
            return bool(visual_result.detections), "risk_detection" if visual_result.detections else "no_detection"
        return False, f"unknown_trigger:{mode}"

    def _provider_unavailable(self) -> bool:
        if self.provider is None:
            return True
        status = self.provider.status
        return status.startswith("error:") or status.startswith("disabled:") or "missing_endpoint" in status

    @staticmethod
    def _empty(status: str, started: float) -> VisionSafetyResult:
        return VisionSafetyResult(
            used=False,
            status=status,
            scores={"vision_safety": 0.0},
            detections=[],
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
