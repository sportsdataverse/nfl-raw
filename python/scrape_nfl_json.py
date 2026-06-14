"""Scrape NFL weekly game-detail JSON from api.nfl.com over a season range.

For each season in ``[--start, --end]`` this fetches every weekly
game-details payload (throttled, resumable) into the local ``data/raw`` cache,
then extracts one file per game into the committed ``nfl/raw`` library, named
with the nflverse ``game_id`` (``{season}_{week:02d}_{away}_{home}``).

Data availability (api.nfl.com weekly-game-details):
  * Full play-by-play detail (summary + driveChart) is reliable from 1999 (the
    nflverse era) -- this is the default ``--start``.
  * Schedule/game shells (no per-play detail) reach back to 1920; pass
    ``--start 1920`` to scrape those too.

Usage::

    # Default: 1999 -> current season, REG + POST, 2s throttle, extract on
    .venv/Scripts/python.exe python/scrape_nfl_json.py

    # One season
    .venv/Scripts/python.exe python/scrape_nfl_json.py -s 2024 -e 2024

    # Full detail era, newest first
    .venv/Scripts/python.exe python/scrape_nfl_json.py -s 1999 -e 2025 --reverse

    # Schedule shells back to the league's founding (fetch only, no extract)
    .venv/Scripts/python.exe python/scrape_nfl_json.py -s 1920 -e 1998 --no-extract
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sportsdataverse.nfl.nfl_games import nfl_headers_gen  # noqa: E402
from python.model_training.track6_nfl_ep_wp.fetcher import (  # noqa: E402
    NFL_JSON_DETAIL_START,
    build_raw_library,
    extract_library_to_games,
)


def _current_season(default: int = 2025) -> int:
    """Best-effort current NFL season, falling back to ``default``."""
    try:
        from sportsdataverse.nfl.utils_date import get_current_nfl_season

        return int(get_current_nfl_season())
    except Exception:  # noqa: BLE001
        return default


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="scrape_nfl_json",
        description="Scrape + extract NFL weekly game-detail JSON over a season range.",
    )
    ap.add_argument(
        "-s", "--start", type=int, default=NFL_JSON_DETAIL_START,
        help=f"First season to scrape (default {NFL_JSON_DETAIL_START}, the play-detail floor).",
    )
    ap.add_argument(
        "-e", "--end", type=int, default=None,
        help="Last season to scrape (default: current NFL season).",
    )
    ap.add_argument(
        "--season-types", nargs="+", default=["REG", "POST"],
        metavar="TYPE", help="Season types to fetch (default: REG POST).",
    )
    ap.add_argument(
        "--delay", type=float, default=2.0,
        help="Seconds to rest between requests (default 2.0).",
    )
    ap.add_argument(
        "--data-dir", default="data/raw",
        help="Local weekly raw cache dir (gitignored). Default data/raw.",
    )
    ap.add_argument(
        "--output-dir", default="nfl/raw",
        help="Committed per-game library dir. Default nfl/raw.",
    )
    ap.add_argument(
        "--reverse", action="store_true",
        help="Iterate newest season first (handy for backfills).",
    )
    ap.add_argument(
        "--no-resume", action="store_true",
        help="Re-fetch weeks even if their cache file already exists.",
    )
    ap.add_argument(
        "--no-extract", action="store_true",
        help="Only fetch the weekly cache; skip per-game extraction.",
    )
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    end = args.end if args.end is not None else _current_season()
    if end < args.start:
        raise SystemExit(f"--end ({end}) is before --start ({args.start}).")

    seasons = list(range(args.start, end + 1))
    if args.reverse:
        seasons.reverse()

    headers = nfl_headers_gen()
    print(
        f"[scrape] seasons {seasons[0]}..{seasons[-1]} "
        f"({len(seasons)}) | types={args.season_types} | delay={args.delay}s "
        f"| extract={'off' if args.no_extract else 'on'}"
    )

    grand_start = time.monotonic()
    total_weeks = 0
    total_games = 0
    for season in seasons:
        s0 = time.monotonic()
        written = build_raw_library(
            seasons=[season],
            output_dir=Path(args.data_dir),
            season_types=list(args.season_types),
            resume=not args.no_resume,
            headers=headers,
            delay_s=args.delay,
        )
        total_weeks += len(written)
        msg = f"[scrape] {season}: fetched {len(written)} new weekly file(s)"

        if not args.no_extract:
            games = extract_library_to_games(
                season=season,
                data_dir=Path(args.data_dir),
                output_dir=Path(args.output_dir),
                season_types=list(args.season_types),
            )
            total_games += len(games)
            msg += f" -> extracted {len(games)} game file(s)"

        print(f"{msg} in {time.monotonic() - s0:.1f}s")

    elapsed = time.monotonic() - grand_start
    print(
        f"[scrape] done: {len(seasons)} season(s), {total_weeks} new weekly file(s), "
        f"{total_games} game file(s) in {elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
