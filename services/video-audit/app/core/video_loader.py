"""Remote video loading helpers for URL-based moderation requests."""

from __future__ import annotations

import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core.config import Settings
from app.core.errors import VideoAuditError


@dataclass(frozen=True)
class LoadedVideoFile:
    """Downloaded video file metadata passed into the existing audit pipeline."""

    path: Path
    filename: str
    mime_type: str
    bytes: int


class RemoteVideoLoader:
    """Download a remote video while preserving upload limits and local ffmpeg compatibility."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def download(self, video_url: str) -> LoadedVideoFile:
        """Fetch one http/https video URL into a temporary file for ffprobe/ffmpeg."""

        url = str(video_url or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise VideoAuditError(400, "invalid_video_url", "video_url must be an http or https URL")

        filename = self._filename_from_url(parsed.path)
        suffix = Path(filename).suffix or ".mp4"
        request = urllib.request.Request(url, headers={"User-Agent": "ContentReviewVideoAudit/1.0"})
        temp_path = ""
        total_bytes = 0
        try:
            with urllib.request.urlopen(request, timeout=self.settings.video_download_timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.settings.max_video_bytes:
                    raise VideoAuditError(
                        413,
                        "video_file_too_large",
                        f"remote video is too large: {content_length}>{self.settings.max_video_bytes}",
                    )

                mime_type = (response.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0]
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                    temp_path = temp_file.name
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                        if total_bytes > self.settings.max_video_bytes:
                            raise VideoAuditError(
                                413,
                                "video_file_too_large",
                                f"remote video is too large: {total_bytes}>{self.settings.max_video_bytes}",
                            )
                        temp_file.write(chunk)

            if total_bytes <= 0:
                raise VideoAuditError(400, "empty_video", "remote video is empty")
            return LoadedVideoFile(
                path=Path(temp_path),
                filename=filename,
                mime_type=mime_type or "application/octet-stream",
                bytes=total_bytes,
            )
        except VideoAuditError:
            self._cleanup(temp_path)
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._cleanup(temp_path)
            raise VideoAuditError(400, "video_download_failed", f"failed to download video_url: {exc}") from exc

    @staticmethod
    def _filename_from_url(path: str) -> str:
        """Infer a stable filename from the URL path, defaulting to mp4 when absent."""

        raw_name = Path(unquote(path or "")).name.strip()
        filename = raw_name or "remote_video.mp4"
        if not Path(filename).suffix:
            filename = f"{filename}.mp4"
        return filename.replace("\\", "_").replace("/", "_")

    @staticmethod
    def _cleanup(temp_path: str) -> None:
        """Remove partially downloaded files after validation or network failures."""

        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
