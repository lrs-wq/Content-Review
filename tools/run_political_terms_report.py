from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = ROOT / "services" / "text-audit"
REPORT_DIR = ROOT / "storage" / "reports"
POLITICAL_TERMS_PATH = ROOT / "configs" / "political_terms.csv"

sys.path.insert(0, str(SERVICE_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def load_terms() -> list[dict[str, str]]:
    with POLITICAL_TERMS_PATH.open("r", encoding="utf-8-sig", newline="") as stream:
        return [row for row in csv.DictReader(stream) if (row.get("enabled") or "").lower() == "true"]


def run_case(client: TestClient, row: dict[str, str]) -> dict:
    term = row["term"]
    payload = {
        "content_id": f"political_{term}",
        "user_id": "political_report",
        "scene": "political_terms_test",
        "text": term,
        "context": {},
    }
    started = time.perf_counter()
    response = client.post("/v1/moderation/text", json=payload)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    body = response.json()
    hit_terms = [hit["term"] for hit in body["hits"]]
    return {
        "term": term,
        "expected_category": row["category"],
        "expected_action": row["action"],
        "expected_risk_level": row["risk_level"],
        "actual_action": body["action"],
        "actual_risk_level": body["risk_level"],
        "labels": body["labels"],
        "hit_terms": hit_terms,
        "passed": term in hit_terms and row["category"] in body["labels"] and body["action"] == row["action"],
        "elapsed_ms": round(elapsed_ms, 3),
    }


def render(results: list[dict]) -> str:
    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    high = sum(1 for item in results if item["expected_risk_level"] == "high")
    medium = sum(1 for item in results if item["expected_risk_level"] == "medium")
    lines = [
        "# 政治敏感词库回归测试报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 汇总",
        "",
        f"- 词条总数：{total}",
        f"- high：{high}",
        f"- medium：{medium}",
        f"- 通过数：{passed}",
        f"- 通过率：{round(passed / total * 100, 2) if total else 0.0}%",
        "",
        "## 未通过词条",
        "",
    ]
    failures = [item for item in results if not item["passed"]]
    if not failures:
        lines.append("全部通过。")
    else:
        lines.extend(
            [
                "| term | expected | actual | labels | hits |",
                "|---|---|---|---|---|",
            ]
        )
        for item in failures:
            lines.append(
                "| {term} | {expected_risk_level}/{expected_action} | {actual_risk_level}/{actual_action} | {labels} | {hits} |".format(
                    term=item["term"].replace("|", "/"),
                    expected_risk_level=item["expected_risk_level"],
                    expected_action=item["expected_action"],
                    actual_risk_level=item["actual_risk_level"],
                    actual_action=item["actual_action"],
                    labels=",".join(item["labels"]) or "-",
                    hits=",".join(item["hit_terms"]) or "-",
                )
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    rows = load_terms()
    results = [run_case(client, row) for row in rows]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"political_terms_report_{stamp}.json"
    md_path = REPORT_DIR / f"political_terms_report_{stamp}.md"
    latest_json_path = REPORT_DIR / "political_terms_report_latest.json"
    latest_md_path = REPORT_DIR / "political_terms_report_latest.md"
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "results": results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render(results), encoding="utf-8")
    latest_md_path.write_text(render(results), encoding="utf-8")
    print(str(md_path))


if __name__ == "__main__":
    main()

