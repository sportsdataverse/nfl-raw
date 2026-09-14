"""Capture ESPN's NFL game summaries (and per-play participants) over a season range.

For each season in ``[--start, --end]`` this lists the season's events from
ESPN's core API (regular season + postseason by default), fetches each event's
summary into ``nfl/espn/raw/{season}/{event_id}.json`` and its core plays
(participants) into ``nfl/espn/plays/{season}/{event_id}.json``. Resumable:
an event whose files exist is skipped, so a killed run just restarts.

The Shield-API library under ``nfl/raw/`` is a different feed keyed by the
nflverse game id; ``python/nfl_espn_02_crosswalk.py`` ties the two together.

Usage::

    # one season, both feeds, commit when done
    .venv/bin/python python/nfl_espn_01_summary_scrape.py -s 2025 -e 2025 --commit

    # the whole ESPN play-by-play era, newest first, 3 workers
    .venv/bin/python python/nfl_espn_01_summary_scrape.py -s 2002 -e 2026 --reverse --workers 3 --commit

    # summaries only (no participants), preseason too
    .venv/bin/python python/nfl_espn_01_summary_scrape.py -s 2026 -e 2026 --no-plays --types 1 2 3

Pace is environment-tunable: ``ESPN_RATE_SLEEP`` (seconds between requests per
worker, default 0.25) and ``ESPN_RATE_RETRIES`` (default 3).
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.nfl_espn_scrape.espn_fetcher import (
    ESPN_NFL_DETAIL_START,
    capture_event,
    list_season_events,
)

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("nfl_espn_scrape")


def _current_season() -> int:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return now.year if now.month >= 3 else now.year - 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Capture ESPN NFL game summaries + participants into nfl/espn/."
    )
    ap.add_argument("-s", "--start", type=int, default=ESPN_NFL_DETAIL_START)
    ap.add_argument("-e", "--end", type=int, default=_current_season())
    ap.add_argument(
        "--types",
        type=int,
        nargs="+",
        default=[2, 3],
        help="ESPN season types: 1 PRE, 2 REG, 3 POST",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=3,
        help="concurrent events (keep low; ESPN 403s aggressive rates)",
    )
    ap.add_argument("--reverse", action="store_true", help="newest season first")
    ap.add_argument(
        "--no-plays",
        action="store_true",
        help="skip the core plays / participants feed",
    )
    ap.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="re-fetch events whose files exist",
    )
    ap.add_argument(
        "--commit", action="store_true", help="git commit nfl/espn per season"
    )
    return ap


def _commit_season(season: int, n_games: int) -> None:
    subprocess.run(
        ["git", "add", f"nfl/espn/raw/{season}", f"nfl/espn/plays/{season}"],
        cwd=ROOT,
        check=False,
    )
    msg = f"NFL ESPN Raw: {season} ({n_games} games)"
    r = subprocess.run(
        ["git", "commit", "-q", "-m", msg],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    log.info(
        "commit %s -> %s",
        msg,
        "ok" if r.returncode == 0 else (r.stdout + r.stderr).strip()[:120],
    )


def run_season(season: int, args: argparse.Namespace) -> int:
    t0 = time.time()
    events = list_season_events(season, args.types)
    log.info("season %s: %d events listed (types %s)", season, len(events), args.types)
    written = skipped = failed = 0

    def work(ev: tuple[int, int]) -> str:
        event_id, _ = ev
        try:
            r = capture_event(
                ROOT,
                season,
                event_id,
                with_plays=not args.no_plays,
                skip_existing=not args.no_skip_existing,
            )
            return "written" if "written" in r.values() else "exists"
        except Exception as exc:  # noqa: BLE001
            log.error("season %s event %s FAILED: %s", season, event_id, exc)
            return "failed"

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(work, ev) for ev in events]
        for i, fut in enumerate(as_completed(futures), 1):
            out = fut.result()
            written += out == "written"
            skipped += out == "exists"
            failed += out == "failed"
            if i % 25 == 0 or i == len(events):
                log.info(
                    "season %s: %d/%d (written %d, existing %d, failed %d)",
                    season,
                    i,
                    len(events),
                    written,
                    skipped,
                    failed,
                )
    log.info(
        "season %s done in %.0fs: written %d existing %d failed %d",
        season,
        time.time() - t0,
        written,
        skipped,
        failed,
    )
    if args.commit and written:
        _commit_season(season, len(events) - failed)
    return failed


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    seasons = list(range(args.start, args.end + 1))
    if args.reverse:
        seasons.reverse()
    total_failed = 0
    for season in seasons:
        total_failed += run_season(season, args)
    log.info(
        "COMPLETED seasons %s-%s, failed events: %d", args.start, args.end, total_failed
    )
    sys.exit(1 if total_failed else 0)


if __name__ == "__main__":
    main()
