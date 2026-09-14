"""Build the ESPN <-> Shield/nflverse crosswalk from the two committed libraries.

Reads every captured ESPN summary under ``nfl/espn/raw/{season}/`` and every
Shield game file under ``nfl/raw/{season}/`` (named with the nflverse game id
``{season}_{week:02d}_{away}_{home}``) and writes:

* ``nfl/espn/crosswalk/games.json`` -- one row per ESPN event: the ESPN event
  id, season / type / week, kickoff (UTC), home and away ESPN team ids and
  abbreviations, and -- when the Shield library has the game -- the nflverse
  ``game_id``, the Shield game uuid and the nflverse team codes. A game is
  matched on (season, kickoff UTC, home team name), then on (season, kickoff
  date, home team name); an unmatched ESPN event (Pro Bowl, a game the Shield
  feed lacks) keeps null Shield fields and a ``match`` reason.
* ``nfl/espn/crosswalk/teams.json`` -- one row per (ESPN team id, Shield team
  uuid, nflverse code) seen together, with the seasons it held; relocations
  and renames therefore appear as separate rows with disjoint season lists.

JSON rather than csv/parquet because the repo ignores those extensions.

Usage::

    .venv/bin/python python/nfl_espn_02_crosswalk.py            # every captured season
    .venv/bin/python python/nfl_espn_02_crosswalk.py -s 2025 -e 2026 --commit
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.nfl_espn_scrape.espn_fetcher import read_json

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("nfl_espn_scrape")
OUT_DIR = ROOT / "nfl" / "espn" / "crosswalk"


def _espn_rows(season: int) -> list[dict]:
    rows = []
    for f in sorted((ROOT / "nfl" / "espn" / "raw" / str(season)).glob("*.json*")):
        try:
            d = read_json(f)
            header = d["header"]
            comp = header["competitions"][0]
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: unreadable summary (%s)", f.name, exc)
            continue
        teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        home, away = teams.get("home", {}), teams.get("away", {})
        rows.append(
            {
                "espn_event_id": int(f.name.split(".")[0]),
                "season": int(header.get("season", {}).get("year") or season),
                "season_type": header.get("season", {}).get("type"),
                "week": header.get("week"),
                "kickoff_utc": comp.get("date"),
                "neutral_site": comp.get("neutralSite"),
                "status": ((comp.get("status") or {}).get("type") or {}).get("name"),
                "home_espn_team_id": (home.get("team") or {}).get("id"),
                "home_espn_abbr": (home.get("team") or {}).get("abbreviation"),
                "home_name": (home.get("team") or {}).get("displayName"),
                "away_espn_team_id": (away.get("team") or {}).get("id"),
                "away_espn_abbr": (away.get("team") or {}).get("abbreviation"),
                "away_name": (away.get("team") or {}).get("displayName"),
            }
        )
    return rows


def _shield_rows(season: int) -> list[dict]:
    rows = []
    for f in sorted((ROOT / "nfl" / "raw" / str(season)).glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: unreadable Shield file (%s)", f.name, exc)
            continue
        parts = f.stem.split("_")
        if len(parts) != 4:
            continue
        rows.append(
            {
                "game_id": f.stem,
                "shield_game_id": d.get("id"),
                "season": int(parts[0]),
                "week": int(parts[1]),
                "away_nflverse": parts[2],
                "home_nflverse": parts[3],
                "kickoff_utc": d.get("time"),
                "date": d.get("date"),
                "home_name": (d.get("homeTeam") or {}).get("fullName"),
                "away_name": (d.get("awayTeam") or {}).get("fullName"),
                "home_shield_team_id": (d.get("homeTeam") or {}).get("id"),
                "away_shield_team_id": (d.get("awayTeam") or {}).get("id"),
            }
        )
    return rows


def _norm_time(s: str | None) -> str | None:
    if not s:
        return None
    s = s.replace("Z", "").replace("+00:00", "")
    return s[:16]  # YYYY-MM-DDTHH:MM


def _prev_day(date: str) -> str:
    return (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()


def build(seasons: list[int]) -> tuple[list[dict], list[dict], dict]:
    """Match every ESPN event to its Shield game, in three passes.

    1. kickoff UTC minute + home name -- exact on modern seasons.
    2. franchise + date: the Shield ``time`` is a placeholder on older seasons
       and Shield names franchises by their CURRENT name (Chargers, Rams,
       Raiders, Commanders...), so the ESPN team id -> Shield team uuid pairing
       is LEARNED from pass 1 across all seasons and the rest are matched on
       (home franchise, Shield local date), accepting the ESPN UTC date or the
       day before (a night game crosses midnight UTC).
    3. home name + date, for a franchise pass 1 never saw.
    A Shield game is used at most once.
    """
    games: list[dict] = []
    team_seasons: dict[tuple, set] = defaultdict(set)
    stats = {"espn": 0, "matched_time": 0, "matched_date": 0, "unmatched": 0}
    espn_by = {season: _espn_rows(season) for season in seasons}
    shield_by = {season: _shield_rows(season) for season in seasons}
    matched: dict[int, tuple[dict, str]] = {}  # espn_event_id -> (shield row, how)
    used: set[str] = set()
    pair_votes: dict[tuple, int] = defaultdict(int)

    # pass 1 -- kickoff minute + home name
    for season in seasons:
        by_time = {
            (_norm_time(r["kickoff_utc"]), r["home_name"]): r for r in shield_by[season]
        }
        for e in espn_by[season]:
            m = by_time.get((_norm_time(e["kickoff_utc"]), e["home_name"]))
            if m is not None and m["game_id"] not in used:
                matched[e["espn_event_id"]] = (m, "time")
                used.add(m["game_id"])
                for side in ("home", "away"):
                    pair_votes[
                        (e[f"{side}_espn_team_id"], m[f"{side}_shield_team_id"])
                    ] += 1
    team_map: dict[str, str] = {}
    for (espn_id, shield_id), n in sorted(pair_votes.items(), key=lambda kv: -kv[1]):
        team_map.setdefault(espn_id, shield_id)

    # pass 2 -- learned franchise + local date (same UTC day or the day before)
    # pass 3 -- home name + date
    for season in seasons:
        by_franchise = {
            (r["home_shield_team_id"], (r["date"] or r["kickoff_utc"] or "")[:10]): r
            for r in shield_by[season]
        }
        by_name = {
            ((r["date"] or r["kickoff_utc"] or "")[:10], r["home_name"]): r
            for r in shield_by[season]
        }
        for e in espn_by[season]:
            if e["espn_event_id"] in matched:
                continue
            utc_date = (e["kickoff_utc"] or "")[:10]
            dates = [utc_date, _prev_day(utc_date)] if len(utc_date) == 10 else []
            home_shield = team_map.get(e["home_espn_team_id"])
            m = None
            for d in dates:
                m = by_franchise.get((home_shield, d)) if home_shield else None
                if m is None:
                    m = by_name.get((d, e["home_name"]))
                if m is not None and m["game_id"] in used:
                    m = None
                if m is not None:
                    break
            if m is not None:
                matched[e["espn_event_id"]] = (m, "date")
                used.add(m["game_id"])

    for season in seasons:
        for e in espn_by[season]:
            stats["espn"] += 1
            row = dict(e)
            hit = matched.get(e["espn_event_id"])
            if hit is None:
                stats["unmatched"] += 1
                row.update(
                    {
                        "game_id": None,
                        "shield_game_id": None,
                        "home_nflverse": None,
                        "away_nflverse": None,
                        "match": "unmatched",
                    }
                )
            else:
                m, how = hit
                stats["matched_time" if how == "time" else "matched_date"] += 1
                row.update(
                    {
                        "game_id": m["game_id"],
                        "shield_game_id": m["shield_game_id"],
                        "home_nflverse": m["home_nflverse"],
                        "away_nflverse": m["away_nflverse"],
                        "match": how,
                    }
                )
                for side in ("home", "away"):
                    key = (
                        e[f"{side}_espn_team_id"],
                        e[f"{side}_espn_abbr"],
                        e[f"{side}_name"],
                        m[f"{side}_shield_team_id"],
                        m[f"{side}_nflverse"],
                    )
                    team_seasons[key].add(season)
            games.append(row)
    teams = [
        {
            "espn_team_id": k[0],
            "espn_abbr": k[1],
            "name": k[2],
            "shield_team_id": k[3],
            "nflverse_abbr": k[4],
            "seasons": sorted(v),
        }
        for k, v in sorted(
            team_seasons.items(), key=lambda kv: (str(kv[0][0]), min(kv[1]))
        )
    ]
    return games, teams, stats


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Build the ESPN <-> Shield/nflverse crosswalk."
    )
    ap.add_argument("-s", "--start", type=int, default=None)
    ap.add_argument("-e", "--end", type=int, default=None)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    captured = sorted(
        int(p.name)
        for p in (ROOT / "nfl" / "espn" / "raw").glob("[0-9]*")
        if p.is_dir()
    )
    seasons = [
        s
        for s in captured
        if (args.start is None or s >= args.start)
        and (args.end is None or s <= args.end)
    ]
    games, teams, stats = build(seasons)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "games.json").write_text(json.dumps(games, indent=0, ensure_ascii=False))
    (OUT_DIR / "teams.json").write_text(json.dumps(teams, indent=1, ensure_ascii=False))
    log.info(
        "crosswalk: %d ESPN events over %d seasons -- matched by time %d, by date %d, unmatched %d; %d team rows",
        stats["espn"],
        len(seasons),
        stats["matched_time"],
        stats["matched_date"],
        stats["unmatched"],
        len(teams),
    )
    for g in games:
        if g["match"] == "unmatched":
            log.info(
                "  unmatched: %s %s wk%s %s @ %s (%s)",
                g["season"],
                g["season_type"],
                g["week"],
                g["away_espn_abbr"],
                g["home_espn_abbr"],
                g["espn_event_id"],
            )
    if args.commit:
        subprocess.run(["git", "add", "nfl/espn/crosswalk"], cwd=ROOT, check=False)
        r = subprocess.run(
            [
                "git",
                "commit",
                "-q",
                "-m",
                f"NFL ESPN crosswalk: {seasons[0]}-{seasons[-1]} ({stats['espn']} events)",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        log.info(
            "commit -> %s",
            "ok" if r.returncode == 0 else (r.stdout + r.stderr).strip()[:120],
        )


if __name__ == "__main__":
    main()
