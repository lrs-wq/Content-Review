from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import statistics
import tarfile
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "storage" / "samples" / "image_safety"
REPORT_DIR = ROOT / "storage" / "reports"

C4CENSOR_ARTICLE_API = "https://api.figshare.com/v2/articles/30946031"
C4CENSOR_DATASET_URL = "https://ndownloader.figshare.com/files/60605378"
C4CENSOR_MD5 = "8d748e958f7a725a8b2516524df527cf"

UNSAFEBENCH_META_API = "https://huggingface.co/api/datasets/yiting/UnsafeBench"
UNSAFEBENCH_TEST_PARQUET_URL = (
    "https://huggingface.co/datasets/yiting/UnsafeBench/resolve/main/data/test-00000-of-00001.parquet"
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass(frozen=True)
class ImageCase:
    dataset: str
    path: Path
    category: str
    subclass: str
    expected: str


def download_file(url: str, path: Path, expected_md5: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        if expected_md5 and md5(path) != expected_md5:
            path.unlink()
        else:
            return path
    request = urllib.request.Request(url, headers={"User-Agent": "ContentReviewImageSafety/1.0"})
    with urllib.request.urlopen(request, timeout=600) as response:
        path.write_bytes(response.read())
    if expected_md5 and md5(path) != expected_md5:
        raise ValueError(f"md5 mismatch for {path}")
    return path


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_c4censor(refresh: bool = False) -> Path:
    target_root = DATA_ROOT / "c4censor"
    archive = target_root / "Dataset.tar"
    extracted = target_root / "Dataset"
    if refresh and archive.exists():
        archive.unlink()
    download_file(C4CENSOR_DATASET_URL, archive, C4CENSOR_MD5)
    if not extracted.exists() or not any(extracted.rglob("*.jpg")):
        extracted.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r") as tar:
            safe_extract(tar, extracted)
    return extracted


def safe_extract(tar: tarfile.TarFile, target: Path) -> None:
    target_root = target.resolve()
    for member in tar.getmembers():
        member_target = (target / member.name).resolve()
        if target_root not in (member_target, *member_target.parents):
            raise ValueError(f"unsafe tar member path: {member.name}")
    tar.extractall(target)


def load_c4censor_cases(limit_per_subclass: int, seed: int, refresh: bool) -> list[ImageCase]:
    root = prepare_c4censor(refresh=refresh)
    grouped: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        parts = path.relative_to(root).parts
        if len(parts) < 3:
            continue
        category, subclass = parts[0], parts[1]
        grouped[(category, subclass)].append(path)

    rng = random.Random(seed)
    cases: list[ImageCase] = []
    for (category, subclass), paths in sorted(grouped.items()):
        selected = sorted(paths)
        if limit_per_subclass > 0 and len(selected) > limit_per_subclass:
            selected = rng.sample(selected, limit_per_subclass)
        expected = "allow" if category == "Neutral" else "non_allow"
        cases.extend(
            ImageCase(
                dataset="C4Censor",
                path=path,
                category=category,
                subclass=subclass,
                expected=expected,
            )
            for path in selected
        )
    return cases


def read_hf_token(raw_token: str | None, token_file: str | None) -> str | None:
    if raw_token:
        return raw_token.strip()
    if token_file:
        path = Path(token_file)
        if path.exists():
            return extract_token(path.read_text(encoding="utf-8", errors="ignore"))
    env_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    return env_token.strip() if env_token else None


def extract_token(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip().strip("\"'")
        if not stripped:
            continue
        if "hf_" in stripped:
            return stripped[stripped.find("hf_") :].split()[0].strip()
        if len(stripped) > 20 and not any(char.isspace() for char in stripped):
            return stripped
    return None


def unsafe_bench_metadata() -> dict:
    try:
        request = urllib.request.Request(UNSAFEBENCH_META_API, headers={"User-Agent": "ContentReviewImageSafety/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"metadata_error": str(exc)}


def unsafe_bench_status(hf_token: str | None) -> dict:
    meta = unsafe_bench_metadata()
    if meta.get("metadata_error"):
        return {"dataset": "UnsafeBench", "status": "metadata_error", "error": meta["metadata_error"]}

    gated = meta.get("gated")
    if gated and not hf_token:
        return {
            "dataset": "UnsafeBench",
            "status": "skipped:gated_dataset_requires_hf_token_and_dua",
            "gated": gated,
            "examples": meta.get("cardData", {}).get("dataset_info", {}).get("splits", []),
            "url": "https://huggingface.co/datasets/yiting/UnsafeBench",
        }

    # Full UnsafeBench evaluation is intentionally explicit rather than automatic:
    # the dataset is gated, large, and requires accepted DUA. The report records
    # readiness so the same script can be extended once an authorized HF token is provided.
    return {
        "dataset": "UnsafeBench",
        "status": "ready_but_not_downloaded:run_with_authorized_token_and_parquet_support",
        "gated": gated,
        "url": "https://huggingface.co/datasets/yiting/UnsafeBench",
    }


def prepare_unsafebench(token: str, refresh: bool = False) -> Path:
    target_root = DATA_ROOT / "unsafebench"
    parquet_path = target_root / "test-00000-of-00001.parquet"
    if refresh and parquet_path.exists():
        parquet_path.unlink()
    if parquet_path.exists() and parquet_path.stat().st_size > 0:
        return parquet_path

    target_root.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": "ContentReviewImageSafety/1.0",
        "Authorization": f"Bearer {token}",
    }
    with requests.get(UNSAFEBENCH_TEST_PARQUET_URL, headers=headers, stream=True, timeout=120) as response:
        if response.status_code in {401, 403}:
            raise PermissionError("UnsafeBench access denied: accept DUA on HuggingFace and verify token permissions")
        response.raise_for_status()
        with parquet_path.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    stream.write(chunk)
    return parquet_path


def load_unsafebench_cases(
    limit_per_category: int,
    seed: int,
    token: str | None,
    refresh: bool,
) -> tuple[list[ImageCase], dict]:
    status = unsafe_bench_status(token)
    if not token:
        return [], status

    try:
        import pandas as pd
        from PIL import Image
    except Exception as exc:
        return [], {"dataset": "UnsafeBench", "status": "skipped:missing_parquet_dependency", "error": str(exc)}

    try:
        parquet_path = prepare_unsafebench(token, refresh=refresh)
        frame = pd.read_parquet(parquet_path)
    except Exception as exc:
        return [], {"dataset": "UnsafeBench", "status": "skipped:download_or_read_failed", "error": str(exc)}

    grouped: dict[str, list[tuple[int, object]]] = defaultdict(list)
    for index, row in frame.iterrows():
        safety_label = str(row.get("safety_label", "") or "").strip()
        category = str(row.get("category", "") or safety_label or "unknown").strip()
        source = str(row.get("source", "") or "unknown").strip()
        key = f"{safety_label}|{category}|{source}"
        grouped[key].append((int(index), row))

    rng = random.Random(seed)
    image_root = DATA_ROOT / "unsafebench" / "images"
    image_root.mkdir(parents=True, exist_ok=True)
    cases: list[ImageCase] = []
    failures = 0

    for key, rows in sorted(grouped.items()):
        selected = rows
        if limit_per_category > 0 and len(rows) > limit_per_category:
            selected = rng.sample(rows, limit_per_category)
        for index, row in selected:
            try:
                image_bytes = image_bytes_from_hf_image(row["image"])
                # Validate and normalize extension using PIL without keeping decoded image in memory.
                with Image.open(PathLikeBytes(image_bytes)) as image:
                    image_format = (image.format or "JPEG").lower()
                suffix = ".png" if image_format == "png" else ".jpg"
                digest = sha256_bytes(image_bytes)
                image_path = image_root / f"{index}_{digest[:16]}{suffix}"
                if not image_path.exists():
                    image_path.write_bytes(image_bytes)

                safety_label = str(row.get("safety_label", "") or "").strip()
                category = str(row.get("category", "") or safety_label or "unknown").strip()
                source = str(row.get("source", "") or "unknown").strip()
                expected = "allow" if safety_label.lower() == "safe" else "non_allow"
                cases.append(
                    ImageCase(
                        dataset="UnsafeBench",
                        path=image_path,
                        category=category or safety_label,
                        subclass=f"{safety_label}:{source}",
                        expected=expected,
                    )
                )
            except Exception:
                failures += 1

    status = {
        "dataset": "UnsafeBench",
        "status": "ok" if cases else "skipped:no_images_loaded",
        "loaded_cases": len(cases),
        "image_decode_failures": failures,
        "url": "https://huggingface.co/datasets/yiting/UnsafeBench",
    }
    return cases, status


class PathLikeBytes:
    def __init__(self, data: bytes) -> None:
        from io import BytesIO

        self._buffer = BytesIO(data)

    def read(self, *args) -> bytes:
        return self._buffer.read(*args)

    def seek(self, *args) -> int:
        return self._buffer.seek(*args)

    def tell(self) -> int:
        return self._buffer.tell()


def image_bytes_from_hf_image(value: object) -> bytes:
    if isinstance(value, dict):
        raw = value.get("bytes")
        if raw is not None:
            return bytes(raw)
        path = value.get("path")
        if path:
            return Path(str(path)).read_bytes()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if hasattr(value, "to_pil"):
        from io import BytesIO

        buffer = BytesIO()
        value.to_pil().save(buffer, format="PNG")
        return buffer.getvalue()
    raise ValueError(f"unsupported HF image payload: {type(value)}")


def expected_passed(expected: str, action: str) -> bool:
    if expected == "allow":
        return action == "allow"
    if expected == "non_allow":
        return action in {"review", "block", "mask"}
    raise ValueError(f"unknown expected {expected}")


def run_case(api_url: str, case: ImageCase, timeout: float, skip_ocr: bool) -> dict:
    data = case.path.read_bytes()
    payload = {
        "content_id": f"{case.dataset}_{case.category}_{case.subclass}_{case.path.stem}",
        "user_id": "image_safety_report",
        "scene": "image_safety_benchmark",
        "image_base64": base64.b64encode(data).decode("ascii"),
        "skip_ocr": skip_ocr,
        "context": {
            "dataset": case.dataset,
            "category": case.category,
            "subclass": case.subclass,
        },
    }
    started = time.perf_counter()
    response = requests.post(api_url, json=payload, timeout=timeout)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    body = response.json()
    action = body["action"]
    return {
        "dataset": case.dataset,
        "category": case.category,
        "subclass": case.subclass,
        "expected": case.expected,
        "passed": expected_passed(case.expected, action),
        "action": action,
        "risk_level": body["risk_level"],
        "labels": body["labels"],
        "scores": body["scores"],
        "detections": [item["label"] for item in body.get("detections", [])],
        "ocr_status": body.get("ocr", {}).get("status"),
        "model_status": body.get("model_status", {}),
        "image_sha256": sha256_bytes(data)[:16],
        "elapsed_ms": round(elapsed_ms, 3),
    }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * pct))
    return ordered[index]


def summarize(results: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for item in results:
        grouped[(item["dataset"], item["category"], item["subclass"])].append(item)

    summaries: list[dict] = []
    for (dataset, category, subclass), rows in sorted(grouped.items()):
        actions = Counter(row["action"] for row in rows)
        labels = Counter(label for row in rows for label in row["labels"])
        latencies = [float(row["elapsed_ms"]) for row in rows]
        passed = sum(1 for row in rows if row["passed"])
        summaries.append(
            {
                "dataset": dataset,
                "category": category,
                "subclass": subclass,
                "expected": rows[0]["expected"] if rows else "",
                "total": len(rows),
                "passed": passed,
                "pass_rate": round(passed / len(rows) * 100, 2) if rows else 0.0,
                "allow": actions.get("allow", 0),
                "review": actions.get("review", 0),
                "block": actions.get("block", 0),
                "mask": actions.get("mask", 0),
                "avg_ms": round(statistics.mean(latencies), 3) if latencies else 0.0,
                "p95_ms": round(percentile(latencies, 0.95), 3),
                "labels": dict(labels.most_common()),
            }
        )
    return summaries


def render_report(
    summaries: list[dict],
    results: list[dict],
    skipped: list[dict],
    json_path: Path,
    limit_per_subclass: int,
    unsafebench_limit_per_category: int,
    skip_ocr: bool,
) -> str:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    overall_total = len(results)
    overall_passed = sum(1 for item in results if item["passed"])
    visual_statuses = Counter(str(item.get("model_status", {}).get("visual", "unknown")) for item in results)
    visual_status_text = "; ".join(f"{status} ({count})" for status, count in visual_statuses.most_common()) or "unknown"
    lines = [
        "# 图片综合安全审核测试报告",
        "",
        f"生成时间：{generated}",
        "",
        "## 测试范围",
        "",
        "- 测试对象：`image-audit-service` 当前本地实现。",
        "- 测试方式：下载公开数据集，固定随机种子抽样，通过 HTTP 调用 `/v1/moderation/image`。",
        "- 隐私处理：报告不展示原图，不展开文件路径，只保留类别、动作、标签、分数和图片哈希前缀。",
        f"- OCR：{'跳过 OCR，仅测视觉层' if skip_ocr else '启用 OCR'}。",
        f"- 视觉模型状态：{visual_status_text}",
        f"- C4Censor 抽样：每个子类 {limit_per_subclass if limit_per_subclass > 0 else '全部'} 张。",
        f"- UnsafeBench 抽样：每个 `safety_label/category/source` 分组 {unsafebench_limit_per_category if unsafebench_limit_per_category > 0 else '全部'} 张。",
        "",
        "## 总览",
        "",
        f"- 总样本数：{overall_total}",
        f"- 通过数：{overall_passed}",
        f"- 通过率：{round(overall_passed / overall_total * 100, 2) if overall_total else 0.0}%",
        "",
        "## 分类别汇总",
        "",
        "| 数据集 | 一级类 | 子类 | 期望 | 样本数 | 通过率 | allow | review | block | avg ms | p95 ms | 标签分布 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]

    for item in summaries:
        label_text = ", ".join(f"{key}:{value}" for key, value in item["labels"].items()) or "-"
        row = dict(item)
        row["label_text"] = label_text.replace("|", "/")
        lines.append(
            "| {dataset} | {category} | {subclass} | {expected} | {total} | {pass_rate:.2f}% | "
            "{allow} | {review} | {block} | {avg_ms:.3f} | {p95_ms:.3f} | {label_text} |".format(**row)
        )

    if skipped:
        lines.extend(["", "## 跳过的数据源", ""])
        for item in skipped:
            lines.append(f"- `{item['dataset']}`：{item['status']}")
            if item.get("url"):
                lines.append(f"  来源：{item['url']}")

    failures = [item for item in results if not item["passed"]]
    lines.extend(["", "## 未通过样本抽查", ""])
    if not failures:
        lines.append("本次抽样无未通过样本。")
    else:
        lines.extend(
            [
                "| 数据集 | 一级类 | 子类 | 期望 | 实际动作 | 风险等级 | 标签 | overall | 哈希 |",
                "|---|---|---|---|---|---|---|---:|---|",
            ]
        )
        for item in failures[:40]:
            lines.append(
                "| {dataset} | {category} | {subclass} | {expected} | {action} | {risk_level} | {labels} | {score:.2f} | `{hash}` |".format(
                    dataset=item["dataset"],
                    category=item["category"],
                    subclass=item["subclass"],
                    expected=item["expected"],
                    action=item["action"],
                    risk_level=item["risk_level"],
                    labels=",".join(item["labels"]) or "-",
                    score=float(item["scores"].get("overall", 0.0)),
                    hash=item["image_sha256"],
                )
            )

    lines.extend(["", "## 初步结论", ""])
    lines.append("- 当前图片服务已接入 PaddleOCR；本次如果使用 `--skip-ocr`，报告只评估视觉层。")
    if any("nudenet:loaded" in status for status in visual_statuses):
        lines.append("- NudeNet 已参与推理，可对裸露区域输出 `nudity` 标签和证据框。")
    if any("nsfw_model:loaded" in status for status in visual_statuses):
        lines.append("- Falconsai NSFW 分类模型已参与推理，`scores.nsfw` 可用于图片级色情风险判断。")
    if any("nsfw_model:error:model_not_cached" in status for status in visual_statuses):
        lines.append("- Falconsai NSFW 分类模型未完成本地预热，本次请求按配置快速降级，没有在接口内等待下载。")
    lines.append("- Blood & Gore、Terrorism 等语义视觉风险仍需要 ShieldGemma 2、Llama Guard 4 或 LlavaGuard 类多模态 safety model 补强。")
    lines.append("- 报告只用于离线评估，不应把显式图片复制到文档或前端页面展示。")
    lines.extend(
        [
            "",
            f"完整 JSON 明细：`{json_path}`",
            "",
            "## 来源",
            "",
            "- C4Censor：https://figshare.com/articles/dataset/C4Censor_A_Lightweight_Benchmark_Dataset_for_Inappropriate_Content_Detection/30946031",
            "- UnsafeBench：https://huggingface.co/datasets/yiting/UnsafeBench",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run image safety benchmark against image-audit-service.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8020/v1/moderation/image")
    parser.add_argument("--limit-per-subclass", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260625)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--skip-ocr", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--hf-token", default=None)
    parser.add_argument("--hf-token-file", default=None)
    parser.add_argument("--include-c4censor", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-unsafebench", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--unsafebench-limit-per-category", type=int, default=10)
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cases: list[ImageCase] = []
    if args.include_c4censor:
        cases.extend(load_c4censor_cases(args.limit_per_subclass, args.seed, args.refresh))

    token = read_hf_token(args.hf_token, args.hf_token_file)
    dataset_statuses: list[dict] = []
    if args.include_unsafebench:
        unsafe_cases, unsafe_status = load_unsafebench_cases(
            args.unsafebench_limit_per_category,
            args.seed,
            token,
            args.refresh,
        )
        cases.extend(unsafe_cases)
        dataset_statuses.append(unsafe_status)
    else:
        dataset_statuses.append(unsafe_bench_status(token))

    results = [run_case(args.api_url, case, args.timeout, args.skip_ocr) for case in cases]
    summaries = summarize(results)
    skipped = [item for item in dataset_statuses if not str(item.get("status", "")).startswith("ok")]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"image_safety_report_{stamp}.json"
    md_path = REPORT_DIR / f"image_safety_report_{stamp}.md"
    latest_json_path = REPORT_DIR / "image_safety_report_latest.json"
    latest_md_path = REPORT_DIR / "image_safety_report_latest.md"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "api_url": args.api_url,
        "limit_per_subclass": args.limit_per_subclass,
        "unsafebench_limit_per_category": args.unsafebench_limit_per_category,
        "skip_ocr": args.skip_ocr,
        "dataset_statuses": dataset_statuses,
        "summaries": summaries,
        "skipped": skipped,
        "results": results,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(data, encoding="utf-8")
    latest_json_path.write_text(data, encoding="utf-8")
    md = render_report(
        summaries,
        results,
        skipped,
        json_path,
        args.limit_per_subclass,
        args.unsafebench_limit_per_category,
        args.skip_ocr,
    )
    md_path.write_text(md, encoding="utf-8")
    latest_md_path.write_text(
        render_report(
            summaries,
            results,
            skipped,
            latest_json_path,
            args.limit_per_subclass,
            args.unsafebench_limit_per_category,
            args.skip_ocr,
        ),
        encoding="utf-8",
    )
    print(str(md_path))


if __name__ == "__main__":
    main()
