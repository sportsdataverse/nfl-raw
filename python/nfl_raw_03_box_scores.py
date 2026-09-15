"""Bank per-game team + player box scores for FINAL games from api.nfl.com.

Reads the committed ``nfl/raw/{season}/`` game library (stage 01/02 output) and
writes ``nfl/box_scores/{season}/{game_id}.json``. Resumable: a valid banked file
is skipped unless ``--rescrape``.

Usage::

    .venv/bin/python python/nfl_raw_03_box_scores.py -s 2026 -e 2026 --commit
    .venv/bin/python python/nfl_raw_03_box_scores.py -s 1999 -e 2025 --delay 0.5 --commit
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.nfl_raw_scrape.box_scores import scrape_season


def _commit(out_dir: str, season: int, n: int) -> None:
    path = f"{out_dir}/{season}"
    if not Path(path).exists():
        return
    subprocess.run(["git", "add", "--", path], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet", "--", path], check=False).returncode == 0:
        print(f"[box_scores] {season}: nothing new to commit")
        return
    subprocess.run(["git", "commit", "-q", "-m", f"NFL Raw: {season} box scores ({n} games)"], check=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nfl_raw_03_box_scores")
    ap.add_argument("-s", "--start", type=int, required=True)
    ap.add_argument("-e", "--end", type=int)
    ap.add_argument("--raw-dir", default="nfl/raw")
    ap.add_argument("--out-dir", default="nfl/box_scores")
    ap.add_argument("--delay", type=float, default=float(os.environ.get("NFL_BOX_SCORE_DELAY", "0.5")),
                    help="seconds after each request (env NFL_BOX_SCORE_DELAY; default 0.5)")
    ap.add_argument("--rescrape", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="cap new games per season (smoke tests)")
    ap.add_argument("--commit", action="store_true", help="git commit each season's box scores")
    a = ap.parse_args(argv)
    rc = 0
    for season in range(a.start, (a.end or a.start) + 1):
        st = scrape_season(season, raw_dir=Path(a.raw_dir), out_dir=Path(a.out_dir),
                           delay=a.delay, rescrape=a.rescrape, limit=a.limit)
        print(f"nfl_raw_03_box_scores {json.dumps(st)}", flush=True)
        if st["failed"]:
            rc = 1
        if a.commit:
            _commit(a.out_dir, season, st["final"])
    return rc


if __name__ == "__main__":
    sys.exit(main())
