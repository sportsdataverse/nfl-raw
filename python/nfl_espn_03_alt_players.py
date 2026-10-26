"""ESPN athlete <-> Fox / Yahoo / CBS player crosswalk, from the parsed nfl-alt-data seasons.

For each season with a parsed provider season under ``--alt-root`` (the private
``nfl-alt-data`` checkout, written by its ``scripts/parse_alt.sh``), matches the provider's
games and players to ESPN through sdv-py's ``sportsdataverse._crosswalk_alt.match_season``:

* ESPN games come from ``nfl/espn/crosswalk/games.json`` (kickoff -> US-Eastern date) and
  ESPN athletes from the box scores of the captured summaries under ``nfl/espn/raw/``.
* Provider teams pair to ESPN teams by (date, home/away side) co-occurrence; games join on
  (Eastern date, team pair); players match inside each (game, team) on normalized name with
  a jersey tie-break and are voted across the season (a tie stays unmatched).

Writes ``nfl/espn/crosswalk/players_{provider}.json``: one row per (season, ESPN team, ESPN
athlete) with the provider's player id. Seasons not rebuilt keep their rows, and a rebuilt
season that would hold fewer provider ids than the file already has is refused (never drop a
leg). JSON because the repo ignores csv/parquet.

Usage::

    .venv/bin/python python/nfl_espn_03_alt_players.py --provider cbs -s 2016 -e 2026 [--commit]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sportsdataverse._common_crosswalk_basketball import to_eastern
from sportsdataverse._common_espn_parsers import parse_summary_boxscore_player
from sportsdataverse._crosswalk_alt import (
    ESPN_GAMES_SCHEMA,
    ESPN_ROSTERS_SCHEMA,
    match_season,
    read_season,
)

from python.nfl_espn_scrape.espn_fetcher import read_json

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "nfl" / "espn" / "crosswalk"
log = logging.getLogger("nfl_espn_alt_players")


def espn_side(season: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    """ESPN games (games.json) and box-score athletes (captured summaries) for one season."""
    games = [
        g
        for g in json.loads((OUT_DIR / "games.json").read_text())
        if g["season"] == season
    ]
    espn_games = pl.DataFrame(
        [
            {
                "espn_game_id": str(g["espn_event_id"]),
                "game_date": to_eastern(g["kickoff_utc"]),
                "home_espn_team_id": int(g["home_espn_team_id"]),
                "away_espn_team_id": int(g["away_espn_team_id"]),
            }
            for g in games
        ],
        schema=ESPN_GAMES_SCHEMA,
    )
    frames = []
    for g in games:
        path = next(
            iter(
                (ROOT / "nfl" / "espn" / "raw" / str(season)).glob(
                    f"{g['espn_event_id']}.json*"
                )
            ),
            None,
        )
        if path is None:
            continue
        box = parse_summary_boxscore_player(read_json(path))
        if box.height:
            frames.append(
                box.select(
                    pl.lit(str(g["espn_event_id"])).alias("espn_game_id"),
                    pl.col("team_id").cast(pl.Int32).alias("espn_team_id"),
                    pl.col("athlete_id").cast(pl.Utf8).alias("espn_athlete_id"),
                    pl.col("athlete_display_name")
                    .cast(pl.Utf8)
                    .alias("espn_full_name"),
                    pl.col("athlete_jersey").cast(pl.Utf8).alias("espn_jersey"),
                ).unique(["espn_team_id", "espn_athlete_id"])
            )
    rosters = pl.concat(frames) if frames else pl.DataFrame(schema=ESPN_ROSTERS_SCHEMA)
    return espn_games, rosters.select(list(ESPN_ROSTERS_SCHEMA))


def season_rows(
    provider: str, season: int, alt_root: Path
) -> tuple[list[dict], dict] | None:
    alt = read_season(alt_root, provider, "nfl", season)
    if alt is None:
        return None
    games, rosters = espn_side(season)
    m = match_season(games, rosters, alt)
    names = (
        rosters.sort("espn_game_id")
        .unique(["espn_team_id", "espn_athlete_id"], keep="last")
        .select("espn_team_id", "espn_athlete_id", "espn_full_name", "espn_jersey")
    )
    out = m["players"].join(names, on=["espn_team_id", "espn_athlete_id"], how="left")
    team_ids = m["teams"].select(
        "espn_team_id", pl.col("team_id").alias(f"{provider}_team_id")
    )
    out = out.join(team_ids, on="espn_team_id", how="left").sort(
        ["espn_team_id", "espn_full_name"]
    )
    rows = [
        {
            "season": season,
            "espn_team_id": str(r["espn_team_id"]),
            "espn_athlete_id": r["espn_athlete_id"],
            "espn_full_name": r["espn_full_name"],
            "espn_jersey": r["espn_jersey"],
            f"{provider}_team_id": r[f"{provider}_team_id"],
            f"{provider}_player_id": r["player_id"],
            f"{provider}_player_name": r["player_name"],
            f"{provider}_jersey": r["jersey"],
            "match_method": r["match_method"],
            "match_confidence": round(r["match_confidence"], 4),
        }
        for r in out.iter_rows(named=True)
    ]
    return rows, m["stats"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build players_{provider}.json from nfl-alt-data."
    )
    ap.add_argument("--provider", required=True, choices=("cbs", "fox", "yahoo"))
    ap.add_argument("-s", "--start", type=int, required=True)
    ap.add_argument("-e", "--end", type=int, required=True)
    ap.add_argument("--alt-root", default=str(ROOT.parent / "nfl-alt-data"))
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    path = OUT_DIR / f"players_{args.provider}.json"
    id_col = f"{args.provider}_player_id"
    existing = json.loads(path.read_text()) if path.exists() else []
    kept = {}
    for r in existing:
        kept.setdefault(r["season"], []).append(r)
    built = []
    for season in range(args.start, args.end + 1):
        res = season_rows(args.provider, season, Path(args.alt_root))
        if res is None:
            log.info(
                "%s %s: no parsed season under %s; skipped",
                args.provider,
                season,
                args.alt_root,
            )
            continue
        rows, stats = res
        old_n = sum(1 for r in kept.get(season, []) if r.get(id_col))
        if len(rows) < old_n:
            log.error(
                "%s %s: %d ids < %d already stored; refusing to shrink the season",
                args.provider,
                season,
                len(rows),
                old_n,
            )
            return 1
        kept[season] = rows
        built.append(season)
        log.info(
            "%s %s: games %d/%d matched (ESPN %d), players %d/%d ESPN athletes (%.1f%%), %d->%d ids",
            args.provider,
            season,
            stats["games_matched"],
            stats["alt_games"],
            stats["espn_games"],
            stats["players_matched"],
            stats["espn_athletes"],
            100 * stats["players_matched"] / max(stats["espn_athletes"], 1),
            old_n,
            len(rows),
        )
    if not built:
        return 0
    path.write_text(
        json.dumps(
            [r for s in sorted(kept) for r in kept[s]], indent=0, ensure_ascii=False
        )
    )
    log.info("wrote %s (%d seasons rebuilt)", path, len(built))
    if args.commit:
        subprocess.run(
            ["git", "add", "--", str(path.relative_to(ROOT))], cwd=ROOT, check=True
        )
        msg = f"NFL ESPN crosswalk: {args.provider} players {built[0]}-{built[-1]}"
        r = subprocess.run(
            ["git", "commit", "-q", "-m", msg],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        log.info(
            "commit -> %s",
            "ok" if r.returncode == 0 else (r.stdout + r.stderr).strip()[:120],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
