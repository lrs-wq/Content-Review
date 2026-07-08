"""Smoke tests for the unified gateway request routing layer."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = ROOT / "services" / "gateway"
sys.path.insert(0, str(SERVICE_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.routes import get_gateway_client  # noqa: E402
from app.core.client import ForwardedResponse  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402


class FakeGatewayClient:
    """Fake downstream client that records routing decisions without network calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post_json(self, url: str, payload: dict[str, Any], brief: bool) -> ForwardedResponse:
        self.calls.append({"kind": "json", "url": url, "payload": payload, "brief": brief})
        if payload["content_id"] == "aliyun_case":
            return ForwardedResponse(
                status_code=200,
                body={
                    "statusCode": 200,
                    "body": json.dumps(
                        {
                            "code": 200,
                            "data": {
                                "result": [
                                    {
                                        "confidence": 100,
                                        "description": "疑似低俗口头语内容",
                                        "label": "inappropriate_oral",
                                        "riskPositions": [
                                            {"endPos": 3, "riskWord": "八嘎", "startPos": 1},
                                        ],
                                        "riskWords": "八嘎",
                                    }
                                ],
                                "riskLevel": "high",
                            },
                            "message": "OK",
                            "requestId": "019F3BEB-6F42-5B03-B93D-7E1BA21EDD51",
                        },
                        ensure_ascii=False,
                    ),
                },
            )
        return ForwardedResponse(
            status_code=200,
            body=self._fake_json_body(payload),
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

    @staticmethod
    def _fake_json_body(payload: dict[str, Any]) -> dict[str, Any]:
        """Return a downstream-like body; one case omits content_id to test gateway fallback."""

        body = {
            "result": "allow",
            "reason": "fake downstream",
        }
        if payload.get("text") != "没有传 content_id 的文本":
            body["content_id"] = payload["content_id"]
        return body


def main() -> None:
    """Run gateway routing checks with FastAPI TestClient."""

    fake = FakeGatewayClient()
    app.dependency_overrides[get_gateway_client] = lambda: fake
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as job_dir:
        os.environ["GATEWAY_ASYNC_JOB_DIR"] = job_dir
        get_settings.cache_clear()

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

        auto_id_response = client.post(
            "/v1/moderation",
            json={
                "content_type": "text",
                "user_id": "u1",
                "scene": "comment",
                "text": "没有传 content_id 的文本",
                "context": {},
            },
        )
        auto_id_response.raise_for_status()

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

        aliyun_response = client.post(
            "/v1/moderation",
            json={
                "content_type": "text",
                "content_id": "aliyun_case",
                "user_id": "u1",
                "scene": "comment",
                "text": "八嘎",
                "context": {},
            },
        )
        aliyun_response.raise_for_status()

        async_response = client.post(
            "/v1/moderation/async",
            json={
                "content_type": "text",
                "user_id": "u1",
                "scene": "comment",
                "text": "异步审核文本",
                "context": {},
            },
        )
        async_response.raise_for_status()
        async_body = async_response.json()
        result_response = client.get(f"/v1/moderation/result/{async_body['content_id']}")
        result_response.raise_for_status()

    summary = {
        "responses": [
            text_response.json(),
            auto_id_response.json(),
            image_response.json(),
            video_response.json(),
            aliyun_response.json(),
            async_response.json(),
            result_response.json(),
        ],
        "calls": fake.calls,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if fake.calls[0]["kind"] != "json" or fake.calls[0]["brief"] is not True:
        raise SystemExit("text request did not route as default brief JSON")
    if not auto_id_response.json()["content_id"].startswith("cr_"):
        raise SystemExit(f"auto-generated content_id missing: {auto_id_response.json()}")
    if fake.calls[2]["kind"] != "multipart" or fake.calls[2]["brief"] is not False:
        raise SystemExit("image upload did not honor brief=false")
    if fake.calls[3]["content_type"] != "video/mp4":
        raise SystemExit("video upload did not route as video multipart")
    aliyun_body = aliyun_response.json()
    if aliyun_body["result"] != "block":
        raise SystemExit(f"aliyun high risk expected block, got {aliyun_body['result']}")
    for expected in ("原因 疑似低俗口头语内容", "命中词 八嘎", "标签 inappropriate_oral", "置信度 100"):
        if expected not in aliyun_body["reason"]:
            raise SystemExit(f"aliyun reason missing {expected}: {aliyun_body['reason']}")
    for removed in ("阿里云敏感词审核未通过", "风险等级 high"):
        if removed in aliyun_body["reason"]:
            raise SystemExit(f"aliyun reason should not include {removed}: {aliyun_body['reason']}")
    result_body = result_response.json()
    if result_body["status"] != "completed" or result_body["result"]["content_id"] != async_body["content_id"]:
        raise SystemExit(f"async polling result unexpected: {result_body}")
    if ":8041/" not in async_body["result_url"]:
        raise SystemExit(f"async result_url should use 8041: {async_body['result_url']}")


if __name__ == "__main__":
    main()
