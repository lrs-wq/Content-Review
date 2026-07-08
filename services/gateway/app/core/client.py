"""HTTP client used by the gateway to call specialized moderation services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import GatewayError


@dataclass(frozen=True)
class ForwardedResponse:
    """Normalized downstream response returned to the gateway route."""

    status_code: int
    body: Any


class GatewayClient:
    """Small async wrapper around httpx for JSON and multipart forwarding."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def post_json(self, url: str, payload: dict[str, Any], brief: bool) -> ForwardedResponse:
        """Forward a JSON moderation request and return the parsed JSON response."""

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds, trust_env=False) as client:
                response = await client.post(url, params={"brief": str(brief).lower()}, json=payload)
        except httpx.RequestError as exc:
            raise GatewayError(502, "downstream_unavailable", f"{url}: {exc}") from exc
        return self._parse_response(url, response)

    async def post_multipart(
        self,
        url: str,
        fields: dict[str, str],
        file_bytes: bytes,
        filename: str,
        content_type: str,
        brief: bool,
    ) -> ForwardedResponse:
        """Forward an uploaded image or video file as multipart/form-data."""

        files = {"file": (filename, file_bytes, content_type)}
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds, trust_env=False) as client:
                response = await client.post(
                    url,
                    params={"brief": str(brief).lower()},
                    data=fields,
                    files=files,
                )
        except httpx.RequestError as exc:
            raise GatewayError(502, "downstream_unavailable", f"{url}: {exc}") from exc
        return self._parse_response(url, response)

    async def health(self) -> dict[str, Any]:
        """Check all downstream services with short timeouts for the gateway health endpoint."""

        services = {
            "text": self.settings.text_audit_url,
            "image": self.settings.image_audit_upload_url,
            "video": self.settings.video_audit_upload_url,
        }
        results: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=self.settings.health_timeout_seconds, trust_env=False) as client:
            for name, url in services.items():
                health_url = self._health_url(url)
                try:
                    response = await client.get(health_url)
                    results[name] = {
                        "url": health_url,
                        "status_code": response.status_code,
                        "ok": 200 <= response.status_code < 300,
                    }
                except httpx.RequestError as exc:
                    results[name] = {
                        "url": health_url,
                        "ok": False,
                        "error": str(exc),
                    }
        return results

    @staticmethod
    def _parse_response(url: str, response: httpx.Response) -> ForwardedResponse:
        """Parse downstream JSON and preserve the downstream HTTP status code."""

        try:
            body = response.json()
        except ValueError as exc:
            raise GatewayError(
                502,
                "downstream_invalid_json",
                f"{url} returned non-JSON response: {response.text[:500]}",
            ) from exc
        return ForwardedResponse(status_code=response.status_code, body=body)

    @staticmethod
    def _health_url(url: str) -> str:
        """Convert a configured endpoint URL into its service-level /health URL."""

        parsed = httpx.URL(url)
        return str(parsed.copy_with(path="/health", query=None, fragment=None))
