"""Import dablelv/dirty-cnwords curse words into project CSV rules."""

from __future__ import annotations

import argparse
import csv
import json
import unicodedata
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs"
RAW_DIR = ROOT / "storage" / "samples" / "lexicons" / "raw"
REPORT_DIR = ROOT / "storage" / "reports"
TARGET_PATH = CONFIG_DIR / "dirty_cnwords_curse_terms.csv"
SOURCE_URL = "https://raw.githubusercontent.com/dablelv/dirty-cnwords/master/curse/all.txt"


@dataclass(frozen=True)
class Source:
    """Metadata kept in import reports for auditability."""

    name: str
    url: str
    category: str
    risk_level: str
    action: str
    notes: str


SOURCE = Source(
    name="dablelv_dirty_cnwords_curse",
    url=SOURCE_URL,
    category="offensive",
    risk_level="high",
    action="review",
    notes="source:dablelv/dirty-cnwords:curse/all.txt",
)


def term_key(term: str) -> str:
    """Build a stable duplicate key while preserving symbol-only vulgar terms."""

    normalized = unicodedata.normalize("NFKC", term or "").strip().lower()
    compact = "".join(char for char in normalized if char.isalnum())
    return compact or normalized


def download(refresh: bool) -> Path:
    """Download the upstream curse list unless a cached copy can be reused."""

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / "dirty_cnwords_curse_all.txt"
    if path.exists() and path.stat().st_size > 0 and not refresh:
        return path

    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "ContentReviewImport/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())
    return path


def parse_terms(path: Path) -> list[str]:
    """Read one term per line and drop duplicates while preserving source order."""

    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    terms: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        term = line.strip().strip("\"'`")
        key = term_key(term)
        if not term or not key or key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms


def load_existing_terms(paths: tuple[Path, ...]) -> set[str]:
    """Load existing project terms so the import file only contains new entries."""

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


def build_rows(refresh: bool) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Convert upstream curse terms into the moderation CSV schema."""

    existing = load_existing_terms(
        (
            CONFIG_DIR / "sensitive_terms.csv",
            CONFIG_DIR / "political_terms.csv",
            CONFIG_DIR / "fwwdn_terms.csv",
            CONFIG_DIR / "oral_vulgar_terms.csv",
        )
    )
    parsed_terms = parse_terms(download(refresh))
    rows: list[dict[str, str]] = []
    skipped_duplicate = 0

    for term in parsed_terms:
        key = term_key(term)
        if key in existing:
            skipped_duplicate += 1
            continue
        existing.add(key)
        rows.append(
            {
                "term": term,
                "category": SOURCE.category,
                "risk_level": SOURCE.risk_level,
                "match_type": "compact",
                "action": SOURCE.action,
                "enabled": "true",
                "notes": SOURCE.notes,
            }
        )

    return rows, {
        "parsed": len(parsed_terms),
        "added": len(rows),
        "skipped_duplicate": skipped_duplicate,
    }


def write_terms(rows: list[dict[str, str]]) -> None:
    """Write imported terms in the same CSV schema used by the rule engine."""

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = ["term", "category", "risk_level", "match_type", "action", "enabled", "notes"]
    with TARGET_PATH.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(summary: dict[str, int], total: int) -> Path:
    """Persist a reproducible import report."""

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target": str(TARGET_PATH),
        "total_terms": total,
        "source": asdict(SOURCE),
        "summary": summary,
        "license_note": "No LICENSE file was found at the fetched repository root; verify reuse rights before redistribution.",
    }
    report_path = REPORT_DIR / f"dirty_cnwords_curse_terms_import_{stamp}.json"
    latest_path = REPORT_DIR / "dirty_cnwords_curse_terms_import_latest.json"
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    report_path.write_text(data, encoding="utf-8")
    latest_path.write_text(data, encoding="utf-8")
    return report_path


def main() -> None:
    """CLI entrypoint for refreshing the dirty-cnwords curse import."""

    parser = argparse.ArgumentParser(description="Import dablelv/dirty-cnwords curse list into CSV rules.")
    parser.add_argument("--refresh", action="store_true", help="Download the source even if a cached file exists.")
    args = parser.parse_args()

    rows, summary = build_rows(refresh=args.refresh)
    write_terms(rows)
    report_path = write_report(summary, len(rows))

    print(f"wrote {TARGET_PATH}")
    print(f"terms {len(rows)}")
    print(
        "parsed={parsed} added={added} skipped_duplicate={skipped_duplicate}".format(
            **summary
        )
    )
    print(f"report {report_path}")


if __name__ == "__main__":
    main()
