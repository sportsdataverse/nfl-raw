"""Extract per-game JSON from the cached weekly NFL library over a season range.

Reads ``{--data-dir}/{season}/{REG,POST}/wk*.json`` and writes one file per game
to ``{--output-dir}/{season}/{nflverse_game_id}.json``. Use this to (re)build the
committed per-game library from an already-fetched weekly cache without touching
the network (e.g. after changing the game_id / relocation logic).

Usage::

    # Re-extract a single cached season
    .venv/Scripts/python.exe python/extract_nfl_games.py -s 2024 -e 2024

    # Re-extract the whole detail era
    .venv/Scripts/python.exe python/extract_nfl_games.py -s 1999 -e 2025
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.model_training.track6_nfl_ep_wp.fetcher import (  # noqa: E402
    NFL_JSON_DETAIL_START,
    extract_library_to_games,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="extract_nfl_games",
        description="Split cached weekly NFL payloads into per-game nflverse-named files.",
    )
    ap.add_argument("-s", "--start", type=int, default=NFL_JSON_DETAIL_START,
                    help=f"First season to extract (default {NFL_JSON_DETAIL_START}).")
    ap.add_argument("-e", "--end", type=int, required=True,
                    help="Last season to extract (inclusive).")
    ap.add_argument("--season-types", nargs="+", default=["REG", "POST"],
                    metavar="TYPE", help="Season types to extract (default: REG POST).")
    ap.add_argument("--data-dir", default="data/raw",
                    help="Weekly raw cache dir to read. Default data/raw.")
    ap.add_argument("--output-dir", default="nfl/raw",
                    help="Per-game library dir to write. Default nfl/raw.")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.end < args.start:
        raise SystemExit(f"--end ({args.end}) is before --start ({args.start}).")

    total = 0
    start = time.monotonic()
    for season in range(args.start, args.end + 1):
        paths = extract_library_to_games(
            season=season,
            data_dir=Path(args.data_dir),
            output_dir=Path(args.output_dir),
            season_types=list(args.season_types),
        )
        total += len(paths)
        print(f"[extract] {season}: {len(paths)} game file(s)")

    print(f"[extract] done: {total} game file(s) across "
          f"{args.start}..{args.end} in {time.monotonic() - start:.1f}s")


if __name__ == "__main__":
    main()
