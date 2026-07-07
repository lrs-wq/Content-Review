"""Smoke tests for video-audit-service upload validation and moderation flow."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx


def create_sample_video(path: Path, duration: float, size: str = "320x180") -> None:
    """Generate a deterministic synthetic video with ffmpeg for end-to-end API checks."""

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=white:s={size}:d={duration}",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(command, check=True)


def post_video(api_url: str, video_path: Path, timeout: float = 180.0) -> tuple[int, dict[str, Any]]:
    """Upload one video to the running video-audit-service."""

    data = {
        # Provide empty text fields so the smoke test exercises real no-audio/empty-text behavior.
        "content_id": video_path.stem,
        "user_id": "video_smoke",
        "scene": "video_smoke",
        "related_text": "",
        "provided_asr_text": "",
        "skip_ocr": "true",
        "context": "{}",
    }
    with video_path.open("rb") as stream:
        files = {"file": (video_path.name, stream, "video/mp4")}
        response = httpx.post(api_url, params={"brief": "false"}, data=data, files=files, timeout=timeout)
    return response.status_code, response.json()


def run_valid_case(api_url: str, video_path: Path) -> dict[str, Any]:
    """Verify that a short valid video reaches the moderation pipeline successfully."""

    status_code, body = post_video(api_url, video_path)
    if status_code != 200:
        raise SystemExit(f"valid video expected HTTP 200, got {status_code}: {body}")
    if body["action"] not in {"allow", "review", "block"}:
        raise SystemExit(f"unexpected action: {body['action']}")
    if body["video"]["duration_seconds"] > 60:
        raise SystemExit(f"valid video duration exceeds limit: {body['video']['duration_seconds']}")
    return {
        "case": "valid_video",
        "http_status": status_code,
        "action": body["action"],
        "risk_level": body["risk_level"],
        "labels": body["labels"],
        "sampled_frames": body["sampled_frames"],
        "audited_frames": body["audited_frames"],
        "duration_seconds": body["video"]["duration_seconds"],
        "elapsed_ms": body["elapsed_ms"],
    }


def run_too_long_case(api_url: str, video_path: Path) -> dict[str, Any]:
    """Verify that videos longer than the 60-second API contract are rejected early."""

    status_code, body = post_video(api_url, video_path, timeout=90)
    if status_code != 400 or body.get("error") != "video_too_long":
        raise SystemExit(f"too-long video expected video_too_long, got HTTP {status_code}: {body}")
    return {
        "case": "too_long_video",
        "http_status": status_code,
        "error": body.get("error"),
        "detail": body.get("detail"),
    }


def main() -> None:
    """Run smoke checks against a live video-audit-service instance."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8030/v1/moderation/video/upload")
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--skip-too-long", action="store_true")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        valid_video_path = temp_path / "video_smoke_valid.mp4"
        create_sample_video(valid_video_path, args.duration)
        results = [run_valid_case(args.api_url, valid_video_path)]

        if not args.skip_too_long:
            too_long_video_path = temp_path / "video_smoke_too_long.mp4"
            create_sample_video(too_long_video_path, 61.0, size="160x90")
            results.append(run_too_long_case(args.api_url, too_long_video_path))

        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
