"""Run a localhost-only, rule/heuristic documentation demo using the real text service."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18010)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    thresholds = yaml.safe_load((root / "configs/thresholds.yaml").read_text())
    for component in ("semantic", "classifier", "agent"):
        thresholds["text"][component]["enabled"] = False
    with tempfile.TemporaryDirectory(prefix="content-review-demo-") as temporary:
        config = Path(temporary) / "thresholds.yaml"
        config.write_text(yaml.safe_dump(thresholds, allow_unicode=True), encoding="utf-8")
        env = os.environ.copy()
        env.update(PROJECT_ROOT=str(root), CONFIG_DIR=str(root / "configs"),
                   THRESHOLDS_PATH=str(config), TEXT_AUDIT_ENABLE_MODEL="false")
        print("Documentation demo: text rules and built-in heuristics; no model or production API.", flush=True)
        try:
            return subprocess.call(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
                cwd=root / "services/text-audit", env=env,
            )
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
