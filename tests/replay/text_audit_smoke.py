"""Smoke tests for text-audit-service core moderation behavior."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = ROOT / "services" / "text-audit"
sys.path.insert(0, str(SERVICE_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def main() -> None:
    """Run local TestClient checks without starting an HTTP server."""

    client = TestClient(app)
    cases = [
        {
            "content_id": "safe_case",
            "user_id": "u1",
            "scene": "comment",
            "text": "\u8fd9\u662f\u4e00\u6761\u6b63\u5e38\u7684\u793e\u533a\u8bc4\u8bba",
            "expected_action": "allow",
        },
        {
            "content_id": "review_case",
            "user_id": "u2",
            "scene": "comment",
            "text": "\u8fd9\u91cc\u53ef\u4ee5\u52a0\u5fae\u4fe1\u79c1\u804a",
            "expected_action": "review",
        },
        {
            "content_id": "block_case",
            "user_id": "u3",
            "scene": "comment",
            "text": "\u7f51\u4e0a\u8d4c\u535a\u5e73\u53f0",
            "expected_action": "block",
        },
        {
            # These cases intentionally expect no rule hits. They protect the gray-zone agent path
            # that catches generalized violence such as "kill + animal/person" without enumerating
            # every possible target noun in the dictionary.
            "content_id": "agent_generalized_human_violence_case",
            "user_id": "u4",
            "scene": "comment",
            "text": "\u6740\u4eba\u507f\u547d juj...",
            "expected_action": "block",
            "expected_agent_used": True,
            "expected_hits": [],
        },
        {
            "content_id": "agent_generalized_dog_violence_case",
            "user_id": "u4",
            "scene": "comment",
            "text": "\u6740\u72d7\u507f\u547d juj...",
            "expected_action": "block",
            "expected_agent_used": True,
            "expected_hits": [],
        },
        {
            "content_id": "agent_generalized_cat_violence_case",
            "user_id": "u4",
            "scene": "comment",
            "text": "\u6740\u732b\u507f\u547d juj...",
            "expected_action": "block",
            "expected_agent_used": True,
            "expected_hits": [],
        },
        {
            "content_id": "agent_generalized_violence_case",
            "user_id": "u5",
            "scene": "comment",
            "text": "\u6740\u5154\u5b50\u507f\u547d juj...",
            "expected_action": "block",
            "expected_agent_used": True,
        },
        {
            "content_id": "political_sensitive_case",
            "user_id": "u6",
            "scene": "comment",
            "text": "\u8fd9\u662f\u4e00\u6761\u6d89\u653f\u654f\u611f\u5185\u5bb9",
            "expected_action": "review",
        },
    ]

    health = client.get("/health")
    health.raise_for_status()
    print(json.dumps(health.json(), ensure_ascii=False))

    for case in cases:
        expected = case.pop("expected_action")
        expected_agent_used = case.pop("expected_agent_used", None)
        expected_hits = case.pop("expected_hits", None)
        response = client.post("/v1/moderation/text", params={"brief": "false"}, json=case)
        response.raise_for_status()
        body = response.json()
        print(json.dumps(body, ensure_ascii=False))
        if body["action"] != expected:
            raise SystemExit(f"{case['content_id']} expected {expected}, got {body['action']}")
        if expected_agent_used is not None and body["agent_review"]["used"] is not expected_agent_used:
            raise SystemExit(
                f"{case['content_id']} expected agent_used={expected_agent_used}, "
                f"got {body['agent_review']['used']}"
            )
        if expected_hits is not None:
            actual_hits = [hit["term"] for hit in body["hits"]]
            if actual_hits != expected_hits:
                raise SystemExit(
                    f"{case['content_id']} expected hits={expected_hits}, got {actual_hits}"
                )


if __name__ == "__main__":
    main()
