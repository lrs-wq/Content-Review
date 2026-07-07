"""Smoke tests for image-audit-service using synthetic local images."""

from __future__ import annotations

import base64
import json
import sys
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = ROOT / "services" / "image-audit"
sys.path.insert(0, str(SERVICE_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def encode_image(image: Image.Image) -> str:
    """Encode a generated PIL image into API-compatible base64."""

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def plain_image() -> Image.Image:
    """Create a benign synthetic image for allow-path checks."""

    image = Image.new("RGB", (320, 180), "#f4f6f8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 300, 160), outline="#90a4ae", width=3)
    draw.text((40, 75), "safe sample", fill="#263238")
    return image


def skin_like_image() -> Image.Image:
    """Create a skin-tone synthetic image to exercise heuristic/vision-safety routing."""

    image = Image.new("RGB", (320, 180), "#e1a078")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 35, 280, 145), outline="#8d6e63", width=4)
    return image


def run_case(client: TestClient, name: str, image: Image.Image, provided_ocr_text: str | None = None) -> dict:
    """Submit one synthetic image and return compact result fields."""

    payload = {
        "content_id": name,
        "user_id": "image_smoke",
        "scene": "image_smoke",
        "image_base64": encode_image(image),
        "provided_ocr_text": provided_ocr_text,
        "context": {},
    }
    started = time.perf_counter()
    response = client.post("/v1/moderation/image", params={"brief": "false"}, json=payload)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    body = response.json()
    return {
        "case": name,
        "action": body["action"],
        "risk_level": body["risk_level"],
        "labels": body["labels"],
        "scores": body["scores"],
        "ocr_status": body["ocr"]["status"],
        "text_review": body["text_review"]["status"],
        "elapsed_ms": round(elapsed_ms, 3),
    }


def main() -> None:
    """Run local TestClient checks without starting image-audit-service over HTTP."""

    client = TestClient(app)
    results = [
        run_case(client, "safe_image", plain_image()),
        run_case(client, "skin_like_review", skin_like_image()),
        run_case(client, "ocr_ad_review", plain_image(), "加微信免费领取，日赚500不是梦"),
        run_case(client, "ocr_political_review", plain_image(), "习近平"),
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
