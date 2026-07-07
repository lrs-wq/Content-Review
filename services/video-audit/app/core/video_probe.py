"""ffprobe-based video validation and metadata extraction."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.core.errors import VideoAuditError
from app.schemas.moderation import VideoMetadata


@dataclass(frozen=True)
class ProbeResult:
    """Parsed video metadata plus the raw ffprobe JSON for future debugging."""

    metadata: VideoMetadata
    raw: dict


class VideoProbe:
    """Validates uploaded videos and extracts metadata with ffprobe."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def status(self) -> str:
        ffmpeg = shutil.which(self.settings.ffmpeg_path) or self.settings.ffmpeg_path
        ffprobe = shutil.which(self.settings.ffprobe_path) or self.settings.ffprobe_path
        return f"ffmpeg:{ffmpeg},ffprobe:{ffprobe}"

    def probe(self, video_path: Path, filename: str, mime_type: str, bytes_size: int) -> ProbeResult:
        """Reject invalid or oversized videos before frame extraction starts."""

        extension = Path(filename).suffix.lower().lstrip(".")

        # Extension checking is only a first-line filter. ffprobe below is the authoritative
        # validation because clients can spoof MIME types and filenames.
        if extension and extension not in self.settings.allowed_extensions:
            raise VideoAuditError(
                status_code=400,
                error="unsupported_video_type",
                detail=f"unsupported video extension: {extension}",
            )
        if bytes_size <= 0:
            raise VideoAuditError(status_code=400, error="empty_video", detail="video file is empty")
        if bytes_size > self.settings.max_video_bytes:
            raise VideoAuditError(status_code=413, error="video_file_too_large", detail="video file is too large")

        raw = self._ffprobe(video_path)
        streams = raw.get("streams", []) if isinstance(raw.get("streams"), list) else []
        video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
        if not isinstance(video_stream, dict):
            raise VideoAuditError(status_code=400, error="missing_video_stream", detail="no video stream found")

        # The service currently accepts videos up to 60 seconds. Rejecting here avoids extracting
        # frames or calling models for content we know the API contract does not allow.
        audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        format_info = raw.get("format", {}) if isinstance(raw.get("format"), dict) else {}
        duration = self._duration_seconds(format_info, video_stream)
        if duration <= 0:
            raise VideoAuditError(status_code=400, error="invalid_video_duration", detail="video duration is invalid")
        if duration > self.settings.max_duration_seconds + 0.05:
            raise VideoAuditError(
                status_code=400,
                error="video_too_long",
                detail=f"video duration {duration:.3f}s exceeds {self.settings.max_duration_seconds:.3f}s",
            )

        metadata = VideoMetadata(
            filename=filename,
            mime_type=mime_type,
            bytes=bytes_size,
            sha256=self._sha256(video_path),
            duration_seconds=round(duration, 3),
            width=int(video_stream.get("width") or 0),
            height=int(video_stream.get("height") or 0),
            format_name=str(format_info.get("format_name", "")),
            video_codec=str(video_stream.get("codec_name", "")),
            audio_codec=str(audio_stream.get("codec_name")) if isinstance(audio_stream, dict) else None,
        )
        return ProbeResult(metadata=metadata, raw=raw)

    def _ffprobe(self, video_path: Path) -> dict:
        """Run ffprobe and return parsed JSON, mapping failures to API errors."""

        command = [
            self.settings.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
        try:
            completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
            data = json.loads(completed.stdout or "{}")
        except FileNotFoundError as exc:
            raise VideoAuditError(status_code=500, error="ffprobe_not_found", detail=str(exc)) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise VideoAuditError(status_code=400, error="ffprobe_failed", detail=detail) from exc
        except json.JSONDecodeError as exc:
            raise VideoAuditError(status_code=400, error="ffprobe_invalid_json", detail=str(exc)) from exc
        if not isinstance(data, dict):
            raise VideoAuditError(status_code=400, error="ffprobe_invalid_json", detail="ffprobe returned non-object JSON")
        return data

    @staticmethod
    def _duration_seconds(format_info: dict, video_stream: dict) -> float:
        """Prefer container duration, falling back to video-stream duration."""

        for source in (format_info, video_stream):
            raw = source.get("duration")
            if raw not in (None, "N/A"):
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    pass
        return 0.0

    @staticmethod
    def _sha256(video_path: Path) -> str:
        """Hash the raw upload for audit logs and duplicate detection."""

        digest = hashlib.sha256()
        with video_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
