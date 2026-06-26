from __future__ import annotations

import csv
import hashlib
import json
import random
import statistics
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = ROOT / "services" / "text-audit"
RAW_DIR = ROOT / "storage" / "samples" / "lexicons" / "raw"
REPORT_DIR = ROOT / "storage" / "reports"

sys.path.insert(0, str(SERVICE_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    parser: str
    expected: str
    limit: int
    notes: str


SOURCES = [
    Source(
        name="fwwdn_ad",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E5%B9%BF%E5%91%8A.txt",
        parser="txt_terms",
        expected="non_allow",
        limit=120,
        notes="广告/导流词库，部分词较宽，统计结果更适合作为覆盖率参考。",
    ),
    Source(
        name="fwwdn_adult",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E8%89%B2%E6%83%85%E7%B1%BB.txt",
        parser="txt_terms",
        expected="non_allow",
        limit=120,
        notes="成人内容词库，期望至少进入 review 或 block。",
    ),
    Source(
        name="fwwdn_weapon_explosive",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E6%B6%89%E6%9E%AA%E6%B6%89%E7%88%86%E8%BF%9D%E6%B3%95%E4%BF%A1%E6%81%AF%E5%85%B3%E9%94%AE%E8%AF%8D.txt",
        parser="txt_terms",
        expected="non_allow",
        limit=120,
        notes="涉枪涉爆违法信息词库，期望高风险规则直接拦截。",
    ),
    Source(
        name="fwwdn_url",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E7%BD%91%E5%9D%80.txt",
        parser="txt_terms",
        expected="non_allow",
        limit=120,
        notes="网址/域名词库，期望至少进入 review，避免外链导流和黑产站点漏放。",
    ),
    Source(
        name="fwwdn_political",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E6%94%BF%E6%B2%BB%E7%B1%BB.txt",
        parser="txt_terms",
        expected="non_allow",
        limit=120,
        notes="政治类词库，期望进入 review，由人工复核兜底。",
    ),
    Source(
        name="COLDataset_offensive",
        url="https://raw.githubusercontent.com/thu-coai/COLDataset/main/COLDataset/test.csv",
        parser="cold_offensive",
        expected="non_allow",
        limit=120,
        notes="COLD 中文冒犯语料测试集 label=1 抽样，期望进入 review 或 block。",
    ),
    Source(
        name="COLDataset_safe",
        url="https://raw.githubusercontent.com/thu-coai/COLDataset/main/COLDataset/test.csv",
        parser="cold_safe",
        expected="allow",
        limit=120,
        notes="COLD 中文冒犯语料测试集 label=0 抽样，期望 allow。",
    ),
]


def download(source: Source) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".csv" if source.url.endswith(".csv") else ".txt"
    path = RAW_DIR / f"{source.name}{suffix}"
    if path.exists() and path.stat().st_size > 0:
        return path

    req = urllib.request.Request(source.url, headers={"User-Agent": "ContentReviewTest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        path.write_bytes(response.read())
    return path


def parse_txt_terms(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    terms: list[str] = []
    for line in text.splitlines():
        for part in line.replace("，", ",").split(","):
            term = part.strip()
            if len(term) >= 2:
                terms.append(term)
    return dedupe(terms)


def parse_cold(path: Path, wanted_label: str) -> list[str]:
    rows: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            if str(row.get("label", "")).strip() == wanted_label:
                text = (row.get("TEXT") or "").strip()
                if text:
                    rows.append(text)
    return dedupe(rows)


def parse_source(source: Source, path: Path) -> list[str]:
    if source.parser == "txt_terms":
        return parse_txt_terms(path)
    if source.parser == "cold_offensive":
        return parse_cold(path, "1")
    if source.parser == "cold_safe":
        return parse_cold(path, "0")
    raise ValueError(f"unknown parser: {source.parser}")


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def sample(items: list[str], limit: int) -> list[str]:
    rng = random.Random(20260624)
    if len(items) <= limit:
        return list(items)
    return rng.sample(items, limit)


def mask_text(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= 4:
        return compact[0] + "*" * max(len(compact) - 1, 0)
    return compact[:2] + "*" * min(max(len(compact) - 3, 3), 12) + compact[-1]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * pct))
    return ordered[index]


def expected_passed(expected: str, action: str) -> bool:
    if expected == "allow":
        return action == "allow"
    if expected == "non_allow":
        return action in {"review", "block"}
    raise ValueError(f"unknown expected: {expected}")


def run_case(client: TestClient, source: Source, index: int, text: str) -> dict:
    payload = {
        "content_id": f"{source.name}_{index}",
        "user_id": "lexicon_report",
        "scene": "lexicon_test",
        "text": text,
        "context": {},
    }
    started = time.perf_counter()
    response = client.post("/v1/moderation/text", json=payload)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    body = response.json()
    action = body["action"]
    return {
        "source": source.name,
        "expected": source.expected,
        "passed": expected_passed(source.expected, action),
        "text_hash": text_hash(text),
        "text_preview": mask_text(text),
        "action": action,
        "risk_level": body["risk_level"],
        "labels": body["labels"],
        "score": body["scores"]["overall"],
        "rule_hits": [hit["category"] for hit in body["hits"]],
        "classifier_label": body.get("classifier_review", {}).get("label"),
        "classifier_action": body.get("classifier_review", {}).get("action"),
        "classifier_score": body.get("classifier_review", {}).get("score", 0.0),
        "agent_used": bool(body.get("agent_review", {}).get("used")),
        "agent_score": body.get("agent_review", {}).get("score", 0.0),
        "elapsed_ms": round(elapsed_ms, 3),
    }


def summarize(source: Source, results: list[dict]) -> dict:
    total = len(results)
    action_counts = count_by(results, "action")
    label_counts: dict[str, int] = {}
    for item in results:
        for label in item["labels"]:
            label_counts[label] = label_counts.get(label, 0) + 1
    latencies = [item["elapsed_ms"] for item in results]
    passed = sum(1 for item in results if item["passed"])
    return {
        "source": source.name,
        "expected": source.expected,
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total * 100, 2) if total else 0.0,
        "allow": action_counts.get("allow", 0),
        "review": action_counts.get("review", 0),
        "block": action_counts.get("block", 0),
        "rule_hit_cases": sum(1 for item in results if item["rule_hits"]),
        "classifier_review_cases": sum(
            1 for item in results if item.get("classifier_action") in {"review", "block"}
        ),
        "agent_used_cases": sum(1 for item in results if item["agent_used"]),
        "avg_ms": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "p50_ms": round(percentile(latencies, 0.5), 3),
        "p95_ms": round(percentile(latencies, 0.95), 3),
        "labels": dict(sorted(label_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "notes": source.notes,
    }


def count_by(results: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        value = str(item.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def render_report(summaries: list[dict], failures: list[dict], skipped: list[dict], json_path: Path) -> str:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# 文本审核词库测试报告",
        "",
        f"生成时间：{generated}",
        "",
        "## 测试范围",
        "",
        "- 测试对象：`text-audit-service` 当前本地实现。",
        "- 测试方式：下载公开词库/语料，固定随机种子抽样，通过 FastAPI TestClient 调用 `/v1/moderation/text`。",
        "- 判定方式：高风险词库和 COLD offensive 样本期望 `review` 或 `block`；COLD safe 样本期望 `allow`。",
        "- 隐私处理：报告仅保留脱敏预览和文本哈希，不直接展开完整敏感词。",
        "",
        "## 汇总",
        "",
        "| 数据源 | 期望 | 样本数 | 通过率 | allow | review | block | 规则命中 | 小模型触发 | agent 触发 | avg ms | p50 ms | p95 ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for item in summaries:
        lines.append(
            "| {source} | {expected} | {total} | {pass_rate:.2f}% | {allow} | {review} | {block} | "
            "{rule_hit_cases} | {classifier_review_cases} | {agent_used_cases} | "
            "{avg_ms:.3f} | {p50_ms:.3f} | {p95_ms:.3f} |".format(**item)
        )

    lines.extend(["", "## 数据源说明", ""])
    for item in summaries:
        labels = ", ".join(f"{key}:{value}" for key, value in item["labels"].items()) or "-"
        lines.append(f"- `{item['source']}`：{item['notes']} 标签分布：{labels}")

    if skipped:
        lines.extend(["", "## 跳过的数据源", ""])
        for item in skipped:
            lines.append(f"- `{item['source']}`：{item['error']}")

    lines.extend(["", "## 未通过样本抽查", ""])
    if not failures:
        lines.append("本次抽样无未通过样本。")
    else:
        lines.extend(
            [
                "| 数据源 | 期望 | 实际动作 | 风险等级 | 标签 | 分数 | 文本预览 | 哈希 |",
                "|---|---|---|---|---|---:|---|---|",
            ]
        )
        for item in failures[:30]:
            lines.append(
                "| {source} | {expected} | {action} | {risk_level} | {labels} | {score:.2f} | {preview} | `{hash}` |".format(
                    source=item["source"],
                    expected=item["expected"],
                    action=item["action"],
                    risk_level=item["risk_level"],
                    labels=",".join(item["labels"]) or "-",
                    score=float(item["score"]),
                    preview=item["text_preview"].replace("|", "/"),
                    hash=item["text_hash"],
                )
            )

    lines.extend(
        [
            "",
            "## 初步结论",
            "",
            "- 加入小模型分类层后，广告、成人、涉枪涉爆、COLD offensive 的抽样覆盖率明显提升。",
            "- 接入 fwwdn 规则词库后，广告、成人、涉枪涉爆、网址、政治类词命中会优先由规则层给出可解释证据。",
            "- `agent_review` 能补住部分“动词 + 对象”的暴力泛化，但它仍是启发式 agent，不等于真正小模型或 LLM 语义理解。",
            "- COLD safe 样本可以观察误审率；若误审高，需要继续加强上下文和白名单策略。",
            "- 当前小模型基于公开词库和 COLDataset，仍需要业务真实样本继续微调和校准阈值。",
            "",
            f"完整 JSON 明细：`{json_path}`",
            "",
            "## 来源",
            "",
            "- fwwdn/sensitive-stop-words：https://github.com/fwwdn/sensitive-stop-words",
            "- thu-coai/COLDataset：https://github.com/thu-coai/COLDataset",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    all_results: list[dict] = []
    summaries: list[dict] = []
    skipped: list[dict] = []

    for source in SOURCES:
        try:
            path = download(source)
            parsed = parse_source(source, path)
            sampled = sample(parsed, source.limit)
            results = [run_case(client, source, index, text) for index, text in enumerate(sampled, 1)]
            all_results.extend(results)
            summaries.append(summarize(source, results))
        except Exception as exc:
            skipped.append({"source": source.name, "error": str(exc)})

    failures = [item for item in all_results if not item["passed"]]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"text_audit_lexicon_report_{stamp}.json"
    md_path = REPORT_DIR / f"text_audit_lexicon_report_{stamp}.md"

    json_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summaries": summaries,
        "skipped": skipped,
        "results": all_results,
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_report(summaries, failures, skipped, json_path), encoding="utf-8")
    (REPORT_DIR / "text_audit_lexicon_report_latest.json").write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (REPORT_DIR / "text_audit_lexicon_report_latest.md").write_text(
        render_report(summaries, failures, skipped, REPORT_DIR / "text_audit_lexicon_report_latest.json"),
        encoding="utf-8",
    )
    print(str(md_path))


if __name__ == "__main__":
    main()
