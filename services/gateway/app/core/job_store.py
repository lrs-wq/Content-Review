"""File-backed async moderation job storage shared by 8040 submit and 8041 query."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings


TERMINAL_STATUSES = {"completed", "failed"}


class JobStore:
    """Persist async moderation status and results as small JSON documents."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.jobs_dir = root / "jobs"
        self.files_dir = root / "files"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def create(self, content_id: str, content_type: str, brief: bool) -> dict[str, Any]:
        """Create or replace the initial queued job record for a content id."""

        now = utc_now()
        record = {
            "content_id": content_id,
            "status": "queued",
            "content_type": content_type,
            "brief": brief,
            "created_at": now,
            "updated_at": now,
            "http_status": None,
            "result": None,
            "error": None,
            "detail": None,
        }
        self.write(record)
        return record

    def mark_processing(self, content_id: str) -> None:
        """Mark a job as actively processing."""

        self.update(content_id, status="processing", error=None, detail=None)

    def mark_completed(self, content_id: str, http_status: int, result: Any) -> None:
        """Store a successful downstream moderation response."""

        status = "completed" if 200 <= int(http_status) < 300 else "failed"
        self.update(content_id, status=status, http_status=http_status, result=result)

    def mark_failed(self, content_id: str, error: str, detail: str, http_status: int = 500) -> None:
        """Store a terminal failure that occurred before a downstream result was available."""

        self.update(content_id, status="failed", http_status=http_status, error=error, detail=detail)

    def get(self, content_id: str) -> dict[str, Any] | None:
        """Read one job by content id, returning None when it is unknown."""

        path = self._job_path(content_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def update(self, content_id: str, **changes: Any) -> dict[str, Any]:
        """Merge changes into one job record and persist it atomically."""

        record = self.get(content_id) or {
            "content_id": content_id,
            "created_at": utc_now(),
        }
        record.update(changes)
        record["updated_at"] = utc_now()
        self.write(record)
        return record

    def write(self, record: dict[str, Any]) -> None:
        """Atomically write one JSON job record."""

        path = self._job_path(str(record["content_id"]))
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)

    def save_upload(self, content_id: str, filename: str, data: bytes) -> Path:
        """Persist uploaded media so the background task can read it after the response returns."""

        safe_name = safe_filename(filename or "upload.bin")
        path = self.files_dir / f"{content_id}_{safe_name}"
        path.write_bytes(data)
        return path

    def remove_upload(self, path: str | None) -> None:
        """Best-effort cleanup for stored upload bytes after a job reaches a terminal state."""

        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass

    def _job_path(self, content_id: str) -> Path:
        return self.jobs_dir / f"{safe_content_id(content_id)}.json"


def get_job_store() -> JobStore:
    """Build a job store rooted under the configured project storage directory."""

    settings = get_settings()
    root = Path(settings.async_job_dir)
    if not root.is_absolute():
        # Source checkout layout is <repo>/services/gateway/app/core/job_store.py, while the
        # Docker image layout is /app/app/core/job_store.py. Choose the repo root when available
        # and fall back to /app inside the container.
        parents = Path(__file__).resolve().parents
        project_root = parents[4] if len(parents) > 4 else parents[2]
        root = project_root / root
    return JobStore(root)


def generate_content_id(prefix: str = "cr") -> str:
    """Generate a stable content id when clients omit one."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:10]}"


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp for job records."""

    return datetime.now(timezone.utc).isoformat()


def safe_content_id(content_id: str) -> str:
    """Keep content id usable as a filename while preserving readability."""

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(content_id))[:160] or generate_content_id()


def safe_filename(filename: str) -> str:
    """Return a conservative upload filename for local storage."""

    name = Path(filename).name
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:120] or "upload.bin"
