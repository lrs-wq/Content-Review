from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import shutil
import sys
import threading
import time
from urllib.parse import quote

import requests


MODEL_ID = "google/shieldgemma-2-4b-it"
FILES: dict[str, int] = {
    "added_tokens.json": 35,
    "chat_template.json": 1325,
    "config.json": 1570,
    "model-00001-of-00002.safetensors": 4_961_255_536,
    "model-00002-of-00002.safetensors": 3_639_027_648,
    "model.safetensors.index.json": 95_856,
    "preprocessor_config.json": 576,
    "processor_config.json": 806,
    "special_tokens_map.json": 662,
    "tokenizer.json": 33_384_570,
    "tokenizer.model": 4_689_074,
    "tokenizer_config.json": 1_156_717,
}


class Progress:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.bytes_done = 0
        self.last_print = time.monotonic()
        self.started = self.last_print

    def add(self, amount: int, label: str, total: int) -> None:
        with self.lock:
            self.bytes_done += amount
            now = time.monotonic()
            if now - self.last_print >= 30:
                elapsed = max(0.001, now - self.started)
                mb = self.bytes_done / 1024 / 1024
                speed = mb / elapsed
                print(f"{label}: downloaded_delta={mb:.1f} MiB speed={speed:.2f} MiB/s total={total / 1024 / 1024:.1f} MiB", flush=True)
                self.last_print = now


def read_token(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"HF token file not found: {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not token.startswith("hf_"):
        raise ValueError("HF token file does not look like a Hugging Face token")
    return token


def model_url(filename: str) -> str:
    encoded = "/".join(quote(part) for part in filename.split("/"))
    return f"https://huggingface.co/{MODEL_ID}/resolve/main/{encoded}"


def request_headers(token: str, start: int | None = None, end: int | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "content-review-model-downloader/1.0"}
    if start is not None and end is not None:
        headers["Range"] = f"bytes={start}-{end}"
    return headers


def download_small_file(filename: str, expected_size: int, target: Path, token: str, proxies: dict[str, str] | None) -> None:
    if target.exists() and target.stat().st_size == expected_size:
        print(f"skip {filename} size={expected_size}", flush=True)
        return
    response = requests.get(
        model_url(filename),
        headers=request_headers(token),
        proxies=proxies,
        timeout=(30, 180),
        allow_redirects=True,
    )
    response.raise_for_status()
    target.write_bytes(response.content)
    actual = target.stat().st_size
    if actual != expected_size:
        raise RuntimeError(f"{filename} size mismatch: expected={expected_size} actual={actual}")
    print(f"done {filename} size={actual}", flush=True)


def download_part(
    filename: str,
    part_index: int,
    start: int,
    end: int,
    part_path: Path,
    token: str,
    proxies: dict[str, str] | None,
    progress: Progress,
) -> None:
    expected = end - start + 1
    current = part_path.stat().st_size if part_path.exists() else 0
    if current == expected:
        return
    if current > expected:
        part_path.unlink()
        current = 0

    for attempt in range(1, 9):
        resume_start = start + current
        try:
            with requests.get(
                model_url(filename),
                headers=request_headers(token, resume_start, end),
                proxies=proxies,
                timeout=(30, 180),
                stream=True,
                allow_redirects=True,
            ) as response:
                if response.status_code != 206:
                    raise RuntimeError(f"expected HTTP 206 for range, got {response.status_code}")
                with part_path.open("ab") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        stream.write(chunk)
                        current += len(chunk)
                        progress.add(len(chunk), filename, end + 1)
                if part_path.stat().st_size == expected:
                    return
                raise RuntimeError(f"partial size mismatch part={part_index} expected={expected} actual={part_path.stat().st_size}")
        except Exception as exc:
            if attempt == 8:
                raise
            print(f"retry {filename} part={part_index} attempt={attempt} reason={type(exc).__name__}", flush=True)
            time.sleep(min(30, attempt * 3))


def assemble_parts(filename: str, expected_size: int, target: Path, parts_dir: Path, part_count: int) -> None:
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    with tmp_path.open("wb") as output:
        for index in range(part_count):
            part_path = parts_dir / f"{index:05d}.part"
            if not part_path.exists():
                raise FileNotFoundError(f"missing part {part_path}")
            with part_path.open("rb") as part:
                shutil.copyfileobj(part, output, length=16 * 1024 * 1024)
    actual = tmp_path.stat().st_size
    if actual != expected_size:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"{filename} assembled size mismatch expected={expected_size} actual={actual}")
    tmp_path.replace(target)
    shutil.rmtree(parts_dir, ignore_errors=True)
    print(f"done {filename} size={expected_size}", flush=True)


def download_large_file(
    filename: str,
    expected_size: int,
    target: Path,
    token: str,
    proxies: dict[str, str] | None,
    workers: int,
    chunk_size: int,
) -> None:
    if target.exists() and target.stat().st_size == expected_size:
        print(f"skip {filename} size={expected_size}", flush=True)
        return
    if target.exists() and target.stat().st_size != expected_size:
        print(f"remove incomplete final {filename} size={target.stat().st_size}", flush=True)
        target.unlink()

    parts_dir = target.with_suffix(target.suffix + ".parts")
    parts_dir.mkdir(parents=True, exist_ok=True)
    ranges: list[tuple[int, int, int, Path]] = []
    index = 0
    for start in range(0, expected_size, chunk_size):
        end = min(expected_size - 1, start + chunk_size - 1)
        ranges.append((index, start, end, parts_dir / f"{index:05d}.part"))
        index += 1

    progress = Progress()
    print(f"start {filename} size={expected_size} parts={len(ranges)} workers={workers}", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(download_part, filename, part_index, start, end, part_path, token, proxies, progress)
            for part_index, start, end, part_path in ranges
        ]
        for future in as_completed(futures):
            future.result()
    assemble_parts(filename, expected_size, target, parts_dir, len(ranges))


def main() -> int:
    parser = argparse.ArgumentParser(description="Download ShieldGemma 2 required files with resumable range requests.")
    parser.add_argument("--token-file", default="apikey.txt")
    parser.add_argument("--output-dir", default="storage/models/shieldgemma-2-4b-it")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk-mib", type=int, default=64)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    args = parser.parse_args()

    root = Path.cwd()
    token = read_token((root / args.token_file).resolve())
    output_dir = (root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None
    chunk_size = args.chunk_mib * 1024 * 1024

    total_size = sum(FILES.values())
    print(f"target={output_dir}", flush=True)
    print(f"files={len(FILES)} total={total_size / 1024 / 1024 / 1024:.2f} GiB", flush=True)

    for filename, expected_size in FILES.items():
        target = output_dir / filename
        if expected_size < 64 * 1024 * 1024:
            download_small_file(filename, expected_size, target, token, proxies)
        else:
            download_large_file(filename, expected_size, target, token, proxies, args.workers, chunk_size)

    print("shieldgemma2 download complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
