"""Domain errors raised by the gateway before or during forwarding."""

from __future__ import annotations


class GatewayError(Exception):
    """Structured error that can be returned directly as JSON."""

    def __init__(self, status_code: int, error: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.error = error
        self.detail = detail
