"""Vendor the minimal commercial-stack packages ArvisX's LLM layer needs into
`arvisx/vendor/`, so the pilot Docker image (build context = arvisx/) can COPY
them. Run this BEFORE `docker compose build` whenever you want the LLM layer
(ARVIS_X_LLM=1) in the image.

Footprint is tiny: a live import trace shows `agent_unified.llm.UnifiedLLM`
touches only `agent_home` + `agent_unified` (and pydantic, installed via pip).
We copy those two packages, excluding logs/caches/pyc so the image stays lean
(agent_home is ~0MB of code; its 34MB `logs/` dir is excluded).

Usage:  python arvisx/scripts/vendor_commercial.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PACKAGES = ("agent_home", "agent_unified")
EXCLUDE_DIRS = {"logs", "__pycache__", "tests", ".pytest_cache"}
EXCLUDE_SUFFIX = (".pyc", ".log", ".db", ".sqlite")

REPO_ROOT = Path(__file__).resolve().parents[2]   # arvisx/scripts/ -> arvisx/ -> repo
VENDOR = Path(__file__).resolve().parents[1] / "vendor"


def _ignore(_dir, names):
    drop = set()
    for n in names:
        if n in EXCLUDE_DIRS or n.endswith(EXCLUDE_SUFFIX):
            drop.add(n)
    return drop


def main() -> int:
    if VENDOR.exists():
        shutil.rmtree(VENDOR)
    VENDOR.mkdir(parents=True)
    (VENDOR / ".gitignore").write_text("*\n")   # never commit vendored code
    for pkg in PACKAGES:
        src = REPO_ROOT / pkg
        if not src.is_dir():
            print(f"ERROR: {src} not found — run from the repo that has the commercial stack.")
            return 1
        shutil.copytree(src, VENDOR / pkg, ignore=_ignore)
        print(f"vendored {pkg}")
    # agent_home writes runtime logs here; ensure the dir exists in the image.
    (VENDOR / "agent_home" / "logs").mkdir(parents=True, exist_ok=True)
    print(f"OK -> {VENDOR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
