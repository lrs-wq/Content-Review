from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.core.errors import VideoAuditError


@dataclass(frozen=True)
class SampledFrame:
    """A frame image extracted from the source video and its approximate timestamp."""

    index: int
    timestamp_seconds: float
    path: Path


class FrameSampler:
    """Extracts review frames from a video using ffmpeg."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def sample(self, video_path: Path, output_dir: Path, duration_seconds: float) -> list[SampledFrame]:
        """Sample frames at the configured fps and return their paths and timestamps."""

        output_dir.mkdir(parents=True, exist_ok=True)
        fps = max(0.1, self.settings.frame_sample_fps)
        max_frames = max(1, self.settings.max_sampled_frames)
        output_pattern = output_dir / "frame_%05d.jpg"

        # The fps filter keeps sampling deterministic and cheap. Scene-change extraction can be
        # added later, but fixed sampling is easier to reason about for the first implementation.
        command = [
            self.settings.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-an",
            "-vf",
            f"fps={fps:g}",
            "-frames:v",
            str(max_frames),
            "-q:v",
            "3",
            str(output_pattern),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
        except FileNotFoundError as exc:
            raise VideoAuditError(status_code=500, error="ffmpeg_not_found", detail=str(exc)) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise VideoAuditError(status_code=400, error="frame_sampling_failed", detail=detail) from exc

        paths = sorted(output_dir.glob("frame_*.jpg"))
        if not paths:
            raise VideoAuditError(status_code=400, error="no_sampled_frames", detail="ffmpeg produced no sampled frames")

        frames: list[SampledFrame] = []
        for offset, path in enumerate(paths):
            # Timestamps are approximate because ffmpeg writes numbered images without exposing
            # per-frame timestamps in this command path. They are precise enough for evidence.
            timestamp = min(duration_seconds, offset / fps)
            frames.append(SampledFrame(index=offset + 1, timestamp_seconds=round(timestamp, 3), path=path))
        return frames
