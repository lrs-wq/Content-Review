"""Smoke tests for the unified gateway request routing layer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = ROOT / "services" / "gateway"
sys.path.insert(0, str(SERVICE_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.routes import get_gateway_client  # noqa: E402
from app.core.client import ForwardedResponse  # noqa: E402
from app.main import app  # noqa: E402


class FakeGatewayClient:
    """Fake downstream client that records routing decisions without network calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post_json(self, url: str, payload: dict[str, Any], brief: bool) -> ForwardedResponse:
        self.calls.append({"kind": "json", "url": url, "payload": payload, "brief": brief})
        return ForwardedResponse(
            status_code=200,
            body={
                "content_id": payload["content_id"],
                "result": "allow",
                "reason": "fake downstream",
            },
        )

    async def post_multipart(
        self,
        url: str,
        fields: dict[str, str],
        file_bytes: bytes,
        filename: str,
        content_type: str,
        brief: bool,
    ) -> ForwardedResponse:
        self.calls.append(
            {
                "kind": "multipart",
                "url": url,
                "fields": fields,
                "filename": filename,
                "content_type": content_type,
                "bytes": len(file_bytes),
                "brief": brief,
            }
        )
        return ForwardedResponse(
            status_code=200,
            body={
                "content_id": fields["content_id"],
                "result": "review",
                "reason": "fake upload downstream",
            },
        )

    async def health(self) -> dict[str, Any]:
        return {"fake": {"ok": True}}


def main() -> None:
    """Run gateway routing checks with FastAPI TestClient."""

    fake = FakeGatewayClient()
    app.dependency_overrides[get_gateway_client] = lambda: fake
    client = TestClient(app)

    text_response = client.post(
        "/v1/moderation",
        json={
            "content_type": "text",
            "content_id": "text_case",
            "user_id": "u1",
            "scene": "comment",
            "text": "\u8fd9\u662f\u4e00\u6761\u6b63\u5e38\u6587\u672c",
            "context": {},
        },
    )
    text_response.raise_for_status()

    image_response = client.post(
        "/v1/moderation?brief=false",
        data={
            "content_id": "image_case",
            "user_id": "u1",
            "skip_ocr": "true",
            "context": "{}",
        },
        files={"file": ("sample.jpg", b"fake-image", "image/jpeg")},
    )
    image_response.raise_for_status()

    video_response = client.post(
        "/v1/moderation",
        data={
            "content_type": "video",
            "content_id": "video_case",
            "user_id": "u1",
            "skip_ocr": "true",
            "context": "{}",
        },
        files={"file": ("sample.mp4", b"fake-video", "video/mp4")},
    )
    video_response.raise_for_status()

    summary = {
        "responses": [text_response.json(), image_response.json(), video_response.json()],
        "calls": fake.calls,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if fake.calls[0]["kind"] != "json" or fake.calls[0]["brief"] is not True:
        raise SystemExit("text request did not route as default brief JSON")
    if fake.calls[1]["kind"] != "multipart" or fake.calls[1]["brief"] is not False:
        raise SystemExit("image upload did not honor brief=false")
    if fake.calls[2]["content_type"] != "video/mp4":
        raise SystemExit("video upload did not route as video multipart")


if __name__ == "__main__":
    main()
