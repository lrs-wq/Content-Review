"""Domain exceptions mapped to structured video API errors."""

from __future__ import annotations


class VideoAuditError(Exception):
    """Expected validation/probe/sampling error raised by video core components."""

    def __init__(self, status_code: int, error: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error = error
        self.detail = detail
