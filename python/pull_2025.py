"""One-off driver: sequential 2025 raw JSON pull with a 2s inter-request throttle.

Mints a single WEB_DESKTOP bearer token and reuses it across all requests so a
fresh token isn't minted per call. Writes per-week files under data/raw/2025/.

Run from the repo root:
    .venv/Scripts/python.exe python/pull_2025.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Make `python.model_training...` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sportsdataverse.nfl.nfl_games import nfl_headers_gen  # noqa: E402
from python.model_training.track6_nfl_ep_wp.fetcher import build_raw_library  # noqa: E402


def main() -> None:
    start = time.monotonic()
    headers = nfl_headers_gen()
    print("[pull_2025] minted WEB_DESKTOP token; starting sequential pull (2s throttle)")

    written = build_raw_library(
        seasons=[2025],
        output_dir=Path("data/raw"),
        season_types=["REG", "POST"],
        resume=True,
        headers=headers,
        delay_s=2.0,
    )

    elapsed = time.monotonic() - start
    print(f"[pull_2025] wrote {len(written)} weekly files in {elapsed:.1f}s")
    for p in written:
        print(f"    {p}")


if __name__ == "__main__":
    main()
