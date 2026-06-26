from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile
import time

from PIL import Image


def resolve_model_name(model_name: str) -> str:
    path = Path(model_name)
    if path.is_absolute() or path.exists():
        return str(path.resolve())
    repo_path = Path(__file__).resolve().parents[1] / path
    if repo_path.exists():
        return str(repo_path.resolve())
    return model_name


def prewarm_nsfw_model(model_name: str, device: int) -> None:
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")

    from transformers import AutoImageProcessor, AutoModelForImageClassification, pipeline  # type: ignore

    started = time.perf_counter()
    resolved_model_name = resolve_model_name(model_name)
    image_processor = AutoImageProcessor.from_pretrained(resolved_model_name, local_files_only=False)
    model = AutoModelForImageClassification.from_pretrained(resolved_model_name, local_files_only=False)
    try:
        classifier = pipeline(
            "image-classification",
            model=model,
            image_processor=image_processor,
            device=device,
        )
    except TypeError:
        classifier = pipeline(
            "image-classification",
            model=model,
            feature_extractor=image_processor,
            device=device,
        )
    probe_image = Image.new("RGB", (224, 224), (245, 247, 250))
    outputs = classifier(probe_image, top_k=None)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    print(f"nsfw_model=ok model={resolved_model_name} elapsed_ms={elapsed_ms} outputs={outputs}")


def prewarm_nudenet() -> None:
    from nudenet import NudeDetector  # type: ignore

    started = time.perf_counter()
    detector = NudeDetector()
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            temp_path = temp_file.name
        Image.new("RGB", (320, 240), (245, 247, 250)).save(temp_path, format="JPEG")
        outputs = detector.detect(temp_path)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    print(f"nudenet=ok elapsed_ms={elapsed_ms} detections={len(outputs) if isinstance(outputs, list) else 0}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and initialize image audit models.")
    parser.add_argument("--model-name", default="storage/models/falconsai-nsfw")
    parser.add_argument("--device", type=int, default=-1, help="-1 means CPU for transformers pipeline")
    parser.add_argument("--skip-nsfw", action="store_true")
    parser.add_argument("--skip-nudenet", action="store_true")
    args = parser.parse_args()

    if not args.skip_nsfw:
        prewarm_nsfw_model(args.model_name, args.device)
    if not args.skip_nudenet:
        prewarm_nudenet()


if __name__ == "__main__":
    main()
