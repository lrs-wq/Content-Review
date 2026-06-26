from __future__ import annotations

import csv
import json
import random
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "storage" / "samples" / "lexicons" / "raw"
MODEL_DIR = ROOT / "storage" / "models" / "text-classifier"
REPORT_DIR = ROOT / "storage" / "reports"


SOURCES = {
    "ad": (
        "fwwdn_ad.txt",
        "https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E5%B9%BF%E5%91%8A.txt",
    ),
    "adult": (
        "fwwdn_adult.txt",
        "https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E8%89%B2%E6%83%85%E7%B1%BB.txt",
    ),
    "weapon": (
        "fwwdn_weapon_explosive.txt",
        "https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E6%B6%89%E6%9E%AA%E6%B6%89%E7%88%86%E8%BF%9D%E6%B3%95%E4%BF%A1%E6%81%AF%E5%85%B3%E9%94%AE%E8%AF%8D.txt",
    ),
    "cold": (
        "COLDataset_test.csv",
        "https://raw.githubusercontent.com/thu-coai/COLDataset/main/COLDataset/test.csv",
    ),
}

TEMPLATES = {
    "ad": [
        "{term}",
        "加我了解{term}",
        "这里有{term}，私聊",
        "免费领取{term}",
        "扫码联系，{term}",
    ],
    "adult": [
        "{term}",
        "有人发{term}内容",
        "图片里出现{term}",
        "评论暗示{term}",
    ],
    "weapon": [
        "{term}",
        "有人发布{term}信息",
        "图片文字写着{term}",
        "私聊购买{term}",
    ],
}

SAFE_EXTRAS = [
    "今天天气很好，晚上去散步。",
    "这是一条普通社区评论。",
    "分享一个做饭的小技巧。",
    "周末准备去公园拍照。",
    "这篇文章是在讨论电影剧情。",
    "新闻引用不代表个人观点。",
    "医学科普内容需要理性讨论。",
    "反诈宣传提醒大家不要转账。",
]


def download(filename: str, url: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / filename
    if path.exists() and path.stat().st_size > 0:
        return path
    req = urllib.request.Request(url, headers={"User-Agent": "ContentReviewTrain/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        path.write_bytes(response.read())
    return path


def parse_terms(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    result: list[str] = []
    for line in text.splitlines():
        for part in re.split(r"[,，、\t ]+", line):
            term = part.strip()
            if len(term) >= 2:
                result.append(term)
    return dedupe(result)


def parse_cold(path: Path) -> tuple[list[str], list[str]]:
    safe: list[str] = []
    offensive: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            text = (row.get("TEXT") or "").strip()
            label = str(row.get("label", "")).strip()
            if not text:
                continue
            if label == "1":
                offensive.append(text)
            elif label == "0":
                safe.append(text)
    return dedupe(safe), dedupe(offensive)


def build_examples() -> tuple[list[str], list[str]]:
    texts: list[str] = []
    labels: list[str] = []

    for label in ("ad", "adult", "weapon"):
        filename, url = SOURCES[label]
        terms = parse_terms(download(filename, url))
        for term in terms:
            for template in TEMPLATES[label]:
                texts.append(template.format(term=term))
                labels.append(label)

    cold_filename, cold_url = SOURCES["cold"]
    safe, offensive = parse_cold(download(cold_filename, cold_url))
    for text in safe:
        texts.append(text)
        labels.append("safe")
    for text in offensive:
        texts.append(text)
        labels.append("offensive")
    for text in SAFE_EXTRAS:
        texts.append(text)
        labels.append("safe")

    return texts, labels


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def train() -> tuple[Path, Path]:
    random.seed(20260624)
    texts, labels = build_examples()
    counts = Counter(labels)

    train_x, test_x, train_y, test_y = train_test_split(
        texts,
        labels,
        test_size=0.2,
        random_state=20260624,
        stratify=labels,
    )

    pipeline = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char",
                    ngram_range=(2, 5),
                    min_df=1,
                    max_features=80000,
                    sublinear_tf=True,
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    solver="liblinear",
                ),
            ),
        ]
    )
    pipeline.fit(train_x, train_y)
    pred_y = pipeline.predict(test_x)
    report = classification_report(test_y, pred_y, output_dict=True, zero_division=0)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = MODEL_DIR / "text_classifier.joblib"
    report_path = REPORT_DIR / f"text_classifier_train_report_{stamp}.json"
    metadata = {
        "version": f"tfidf-char-logreg-{stamp}",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sources": SOURCES,
        "label_counts": dict(counts),
        "model": "TfidfVectorizer(char 2-5) + LogisticRegression",
    }
    joblib.dump({"model": pipeline, "metadata": metadata}, model_path)
    report_path.write_text(
        json.dumps(
            {
                "metadata": metadata,
                "classification_report": report,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (REPORT_DIR / "text_classifier_train_report_latest.json").write_text(
        report_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return model_path, report_path


def main() -> None:
    model_path, report_path = train()
    print(str(model_path))
    print(str(report_path))


if __name__ == "__main__":
    main()

