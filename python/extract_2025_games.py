"""One-off driver: split the 2025 weekly raw library into per-game JSON files.

Reads data/raw/2025/{REG,POST}/wk*.json and writes one file per game to
nfl/raw/2025/{nflverse_game_id}.json (e.g. 2025_01_DAL_PHI.json). Postseason
weeks are continued past the regular season (Wild Card -> 19 ... Super Bowl -> 22).

Run from the repo root:
    .venv/Scripts/python.exe python/extract_2025_games.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.model_training.track6_nfl_ep_wp.fetcher import (  # noqa: E402
    extract_library_to_games,
)


def main() -> None:
    start = time.monotonic()
    paths = extract_library_to_games(
        season=2025,
        data_dir=Path("data/raw"),
        output_dir=Path("nfl/raw"),
        season_types=["REG", "POST"],
    )
    elapsed = time.monotonic() - start
    print(f"[extract_2025] wrote {len(paths)} per-game files in {elapsed:.1f}s")
    for p in paths[:3]:
        print(f"    first: {p.name}")
    for p in paths[-3:]:
        print(f"    last:  {p.name}")


if __name__ == "__main__":
    main()
