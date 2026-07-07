"""Prewarm the configured multimodal vision-safety model."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import time

from PIL import Image


def resolve_model_name(model_name: str) -> str:
    """Prefer a local model path when it exists, otherwise keep the remote model id."""

    path = Path(model_name)
    if path.is_absolute() or path.exists():
        return str(path.resolve())
    repo_path = Path(__file__).resolve().parents[1] / path
    if repo_path.exists():
        return str(repo_path.resolve())
    return model_name


def prewarm_shieldgemma2(model_name: str, device: str, download: bool) -> None:
    """Load ShieldGemma2 and run a single blank-image policy probe."""

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")

    import torch  # type: ignore
    from transformers import AutoProcessor, ShieldGemma2ForImageClassification  # type: ignore

    resolved = resolve_model_name(model_name)
    started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(resolved, local_files_only=not download)
    kwargs = {"local_files_only": not download}
    # Use device_map=auto only when requested so explicit cpu/cuda runs remain predictable.
    if device == "auto":
        kwargs["device_map"] = "auto"
        kwargs["torch_dtype"] = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    model = ShieldGemma2ForImageClassification.from_pretrained(resolved, **kwargs)
    if device != "auto":
        target = torch.device("cuda" if device == "cuda" and torch.cuda.is_available() else "cpu")
        model.to(target)
    model.eval()

    image = Image.new("RGB", (224, 224), (245, 247, 250))
    inputs = processor(images=image, text="No graphic violence, gore, or dangerous content.", return_tensors="pt")
    if device != "auto":
        target = next(model.parameters()).device
        inputs = {key: value.to(target) if hasattr(value, "to") else value for key, value in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
    probabilities = outputs.probabilities if hasattr(outputs, "probabilities") else torch.softmax(outputs.logits, dim=-1)
    # ShieldGemma2 returns [Yes, No]; Yes means the image violates the policy.
    score = float(probabilities.reshape(-1, probabilities.shape[-1])[0, 0].item())
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    print(f"shieldgemma2=ok model={resolved} device={device} score={score:.4f} elapsed_ms={elapsed_ms}")


def main() -> None:
    """CLI entrypoint for local multimodal safety model prewarming."""

    parser = argparse.ArgumentParser(description="Prewarm optional multimodal vision safety models.")
    parser.add_argument("--provider", default="shieldgemma2_local", choices=["shieldgemma2_local"])
    parser.add_argument("--model-name", default="storage/models/shieldgemma-2-4b-it")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"])
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    if args.provider == "shieldgemma2_local":
        prewarm_shieldgemma2(args.model_name, args.device, args.download)


if __name__ == "__main__":
    main()
