"""Frame sampling helper for video moderation."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.core.config import Settings
from app.core.errors import VideoAuditError


@dataclass(frozen=True)
class SampledFrame:
    """A frame image extracted from the source video and its approximate timestamp."""

    index: int
    timestamp_seconds: float
    path: Path
    source: str = "fixed"


class FrameSampler:
    """Extracts review frames using fixed FFmpeg sampling plus optional scene detection."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def sample(self, video_path: Path, output_dir: Path, duration_seconds: float) -> list[SampledFrame]:
        """Sample frames and return bounded, timestamp-ordered evidence frames."""

        output_dir.mkdir(parents=True, exist_ok=True)
        fps = max(0.1, self.settings.frame_sample_fps)
        max_frames = max(1, self.settings.max_sampled_frames)
        fixed_frames = self._sample_fixed_frames(video_path, output_dir, duration_seconds, fps, max_frames)
        scene_frames = self._sample_scene_frames(video_path, output_dir, duration_seconds)
        frames = self._merge_frames(fixed_frames, scene_frames, max_frames)
        if not frames:
            raise VideoAuditError(status_code=400, error="no_sampled_frames", detail="ffmpeg produced no sampled frames")
        return [
            SampledFrame(
                index=index,
                timestamp_seconds=frame.timestamp_seconds,
                path=frame.path,
                source=frame.source,
            )
            for index, frame in enumerate(frames, 1)
        ]

    def _sample_fixed_frames(
        self,
        video_path: Path,
        output_dir: Path,
        duration_seconds: float,
        fps: float,
        max_frames: int,
    ) -> list[SampledFrame]:
        """Sample deterministic fixed-interval frames with FFmpeg."""

        output_pattern = output_dir / "fixed_%05d.jpg"

        # The fps filter keeps a predictable baseline across all videos. Scene-detected frames are
        # added later only as replacements for nearby fixed frames so the total budget stays bound.
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

        paths = sorted(output_dir.glob("fixed_*.jpg"))
        if not paths:
            raise VideoAuditError(status_code=400, error="no_sampled_frames", detail="ffmpeg produced no sampled frames")

        frames: list[SampledFrame] = []
        for offset, path in enumerate(paths):
            # Timestamps are approximate because ffmpeg writes numbered images without exposing
            # per-frame timestamps in this command path. They are precise enough for evidence.
            timestamp = min(duration_seconds, offset / fps)
            frames.append(
                SampledFrame(
                    index=offset + 1,
                    timestamp_seconds=round(timestamp, 3),
                    path=path,
                    source="fixed",
                )
            )
        return frames

    def _sample_scene_frames(self, video_path: Path, output_dir: Path, duration_seconds: float) -> list[SampledFrame]:
        """Use PySceneDetect to extract scene-cut frames, falling back silently on failure."""

        if not self.settings.scene_detect_enabled or self.settings.scene_detect_max_scene_frames <= 0:
            return []
        timestamps = self._detect_scene_timestamps(video_path, duration_seconds)
        frames: list[SampledFrame] = []
        for offset, timestamp in enumerate(timestamps[: self.settings.scene_detect_max_scene_frames], 1):
            target = output_dir / f"scene_{offset:05d}.jpg"
            if self._extract_timestamp_frame(video_path, target, timestamp):
                frames.append(
                    SampledFrame(
                        index=offset,
                        timestamp_seconds=round(timestamp, 3),
                        path=target,
                        source="scene_detect",
                    )
                )
        return frames

    def _detect_scene_timestamps(self, video_path: Path, duration_seconds: float) -> list[float]:
        """Return scene-start timestamps from PySceneDetect, excluding the first frame."""

        try:
            from scenedetect import ContentDetector, SceneManager, open_video  # type: ignore

            video = open_video(str(video_path))
            scene_manager = SceneManager()
            scene_manager.add_detector(
                ContentDetector(
                    threshold=self.settings.scene_detect_threshold,
                    min_scene_len=max(1, self.settings.scene_detect_min_scene_len),
                )
            )
            scene_manager.detect_scenes(video=video, show_progress=False)
            scene_list = scene_manager.get_scene_list()
        except Exception:
            return []

        timestamps: list[float] = []
        for start_time, _ in scene_list:
            timestamp = float(start_time.get_seconds())
            if timestamp <= 0.05 or timestamp >= duration_seconds:
                continue
            timestamps.append(min(duration_seconds, timestamp))
        return self._dedupe_timestamps(timestamps)

    def _extract_timestamp_frame(self, video_path: Path, target: Path, timestamp: float) -> bool:
        """Extract one accurate frame at a timestamp; return False if FFmpeg cannot seek it."""

        command = [
            self.settings.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-ss",
            f"{max(0.0, timestamp):.3f}",
            "-an",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(target),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
            return target.exists() and target.stat().st_size > 0
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False

    def _merge_frames(
        self,
        fixed_frames: list[SampledFrame],
        scene_frames: list[SampledFrame],
        max_frames: int,
    ) -> list[SampledFrame]:
        """Merge scene frames by replacing nearby fixed frames while preserving the total cap."""

        if not scene_frames:
            return fixed_frames[:max_frames]

        deduped_scene_frames = self._dedupe_frames(scene_frames)
        scene_timestamps = [frame.timestamp_seconds for frame in deduped_scene_frames]
        selected_fixed = [
            frame
            for frame in fixed_frames
            if self._nearest_distance(frame.timestamp_seconds, scene_timestamps)
            >= self.settings.scene_detect_dedupe_seconds
        ]

        # If fixed sampling already consumed the whole frame budget, remove fixed frames closest to
        # scene-cut frames. This gives scene boundaries priority without increasing downstream
        # image-audit calls.
        while len(selected_fixed) + len(deduped_scene_frames) > max_frames and selected_fixed:
            remove_index = min(
                range(len(selected_fixed)),
                key=lambda index: self._nearest_distance(selected_fixed[index].timestamp_seconds, scene_timestamps),
            )
            selected_fixed.pop(remove_index)

        merged = [*selected_fixed, *deduped_scene_frames]
        return sorted(merged, key=lambda frame: (frame.timestamp_seconds, 0 if frame.source == "scene_detect" else 1))[
            :max_frames
        ]

    def _dedupe_frames(self, frames: Iterable[SampledFrame]) -> list[SampledFrame]:
        """Remove scene frames that are too close to an already selected scene frame."""

        result: list[SampledFrame] = []
        for frame in sorted(frames, key=lambda item: item.timestamp_seconds):
            if any(
                abs(frame.timestamp_seconds - selected.timestamp_seconds) < self.settings.scene_detect_dedupe_seconds
                for selected in result
            ):
                continue
            result.append(frame)
        return result

    def _dedupe_timestamps(self, timestamps: Iterable[float]) -> list[float]:
        """Remove scene timestamps closer than the configured dedupe window."""

        result: list[float] = []
        for timestamp in sorted(timestamps):
            if any(abs(timestamp - selected) < self.settings.scene_detect_dedupe_seconds for selected in result):
                continue
            result.append(timestamp)
        return result

    @staticmethod
    def _nearest_distance(timestamp: float, candidates: list[float]) -> float:
        """Return distance from timestamp to the nearest candidate timestamp."""

        if not candidates:
            return float("inf")
        return min(abs(timestamp - candidate) for candidate in candidates)
