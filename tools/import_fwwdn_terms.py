from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs"
RAW_DIR = ROOT / "storage" / "samples" / "lexicons" / "raw"
REPORT_DIR = ROOT / "storage" / "reports"
TARGET_PATH = CONFIG_DIR / "fwwdn_terms.csv"
BASE_TERM_PATHS = (
    CONFIG_DIR / "sensitive_terms.csv",
    CONFIG_DIR / "political_terms.csv",
)

TERM_SPLIT_RE = re.compile(r"[,，、\t ]+")


@dataclass(frozen=True)
class Source:
    name: str
    filename: str
    url: str
    category: str
    risk_level: str
    action: str
    notes: str


SOURCES = (
    Source(
        name="fwwdn_ad",
        filename="fwwdn_ad.txt",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E5%B9%BF%E5%91%8A.txt",
        category="ad",
        risk_level="medium",
        action="review",
        notes="source:fwwdn/sensitive-stop-words:ad",
    ),
    Source(
        name="fwwdn_adult",
        filename="fwwdn_adult.txt",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E8%89%B2%E6%83%85%E7%B1%BB.txt",
        category="adult",
        risk_level="high",
        action="block",
        notes="source:fwwdn/sensitive-stop-words:adult",
    ),
    Source(
        name="fwwdn_weapon_explosive",
        filename="fwwdn_weapon_explosive.txt",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E6%B6%89%E6%9E%AA%E6%B6%89%E7%88%86%E8%BF%9D%E6%B3%95%E4%BF%A1%E6%81%AF%E5%85%B3%E9%94%AE%E8%AF%8D.txt",
        category="weapon",
        risk_level="high",
        action="block",
        notes="source:fwwdn/sensitive-stop-words:weapon_explosive",
    ),
    Source(
        name="fwwdn_url",
        filename="fwwdn_url.txt",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E7%BD%91%E5%9D%80.txt",
        category="url",
        risk_level="medium",
        action="review",
        notes="source:fwwdn/sensitive-stop-words:url",
    ),
    Source(
        name="fwwdn_political",
        filename="fwwdn_political.txt",
        url="https://raw.githubusercontent.com/fwwdn/sensitive-stop-words/master/%E6%94%BF%E6%B2%BB%E7%B1%BB.txt",
        category="political",
        risk_level="high",
        action="review",
        notes="source:fwwdn/sensitive-stop-words:political",
    ),
)


def term_key(term: str) -> str:
    normalized = unicodedata.normalize("NFKC", term or "").strip().lower()
    return "".join(char for char in normalized if char.isalnum())


def download(source: Source, refresh: bool) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / source.filename
    if path.exists() and path.stat().st_size > 0 and not refresh:
        return path

    req = urllib.request.Request(source.url, headers={"User-Agent": "ContentReviewImport/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        path.write_bytes(response.read())
    return path


def parse_terms(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    terms: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for part in TERM_SPLIT_RE.split(stripped):
            term = part.strip().strip("\"'`")
            key = term_key(term)
            if len(term) < 2 or not key or key in seen:
                continue
            seen.add(key)
            terms.append(term)
    return terms


def load_existing_terms(paths: tuple[Path, ...]) -> set[str]:
    terms: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                key = term_key(row.get("term") or "")
                if key:
                    terms.add(key)
    return terms


def build_rows(refresh: bool) -> tuple[list[dict[str, str]], list[dict[str, int | str]]]:
    seen = load_existing_terms(BASE_TERM_PATHS)
    rows: list[dict[str, str]] = []
    summary: list[dict[str, int | str]] = []

    for source in SOURCES:
        path = download(source, refresh)
        parsed_terms = parse_terms(path)
        added = 0
        skipped_duplicate = 0

        for term in parsed_terms:
            key = term_key(term)
            if key in seen:
                skipped_duplicate += 1
                continue
            seen.add(key)
            added += 1
            rows.append(
                {
                    "term": term,
                    "category": source.category,
                    "risk_level": source.risk_level,
                    "match_type": "compact",
                    "action": source.action,
                    "enabled": "true",
                    "notes": source.notes,
                }
            )

        summary.append(
            {
                "source": source.name,
                "category": source.category,
                "parsed": len(parsed_terms),
                "added": added,
                "skipped_duplicate": skipped_duplicate,
            }
        )

    return rows, summary


def write_terms(rows: list[dict[str, str]]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = ["term", "category", "risk_level", "match_type", "action", "enabled", "notes"]
    with TARGET_PATH.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(summary: list[dict[str, int | str]], total: int) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target": str(TARGET_PATH),
        "total_terms": total,
        "sources": [asdict(source) for source in SOURCES],
        "summary": summary,
    }
    report_path = REPORT_DIR / f"fwwdn_terms_import_{stamp}.json"
    latest_path = REPORT_DIR / "fwwdn_terms_import_latest.json"
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    report_path.write_text(data, encoding="utf-8")
    latest_path.write_text(data, encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Import fwwdn/sensitive-stop-words into CSV rules.")
    parser.add_argument("--refresh", action="store_true", help="Download sources even if cached files exist.")
    args = parser.parse_args()

    rows, summary = build_rows(refresh=args.refresh)
    write_terms(rows)
    report_path = write_report(summary, len(rows))

    print(f"wrote {TARGET_PATH}")
    print(f"terms {len(rows)}")
    for item in summary:
        print(
            "{source}: parsed={parsed} added={added} skipped_duplicate={skipped_duplicate}".format(
                **item
            )
        )
    print(f"report {report_path}")


if __name__ == "__main__":
    main()
