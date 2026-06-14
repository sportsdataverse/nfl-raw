"""Raw NFL API JSON file library builder.

Fetches per-week game detail payloads from ``api.nfl.com`` and stores them as
JSON files on disk, one file per week per season/type combination.

Storage layout::

    {output_dir}/{season}/{season_type}/wk{week:02d}.json

Each file contains the raw list (or dict) returned by the
``/football/v2/experience/weekly-game-details`` endpoint, exactly as received
from the NFL Shield API.  Downstream tools can read these files via
:func:`load_weekly_raw` without re-hitting the network.

Usage::

    from pathlib import Path
    from python.model_training.track6_nfl_ep_wp.fetcher import build_raw_library

    paths = build_raw_library(
        seasons=list(range(2012, 2025)),
        output_dir=Path("data/raw"),
        season_types=["REG", "POST"],
        resume=True,
    )
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Union


# ---------------------------------------------------------------------------
# Thin network wrappers — monkeypatched in tests
# ---------------------------------------------------------------------------

def _list_weeks(season: int, season_type: str, headers: dict | None = None) -> dict:
    """Return raw JSON from ``nfl_weeks`` (the NFL Shield week calendar)."""
    from sportsdataverse.nfl.nfl_api import nfl_weeks
    return nfl_weeks(season=season, season_type=season_type, return_parsed=False, headers=headers)


def _fetch_weekly_details(
    season: int,
    season_type: str,
    week: int,
    headers: dict | None = None,
) -> Union[list, dict]:
    """Return raw JSON from ``nfl_weekly_game_details`` (bare list or dict)."""
    from sportsdataverse.nfl.nfl_api import nfl_weekly_game_details
    return nfl_weekly_game_details(
        season=season,
        season_type=season_type,
        week=week,
        include_drive_chart=True,
        return_parsed=False,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_season_weeks(
    season: int,
    season_type: str = "REG",
    headers: dict | None = None,
) -> list[int]:
    """Return sorted week numbers for a season / type via the NFL API.

    Args:
        season: NFL season year (e.g. ``2024``).
        season_type: ``"REG"`` (regular season) or ``"POST"`` (postseason).
        headers: Pre-minted auth headers from ``nfl_headers_gen()``.
            A fresh token is minted automatically when ``None``.

    Returns:
        Sorted list of integer week numbers (e.g. ``[1, 2, ..., 18]``).
    """
    raw = _list_weeks(season, season_type, headers=headers)
    weeks_list = raw.get("weeks", []) or []
    week_nums: list[int] = []
    for wk in weeks_list:
        val = wk.get("week")
        if val is not None:
            try:
                week_nums.append(int(val))
            except (TypeError, ValueError):
                pass
    return sorted(week_nums)


def extract_game_ids_from_weekly(payload: Union[list, dict]) -> list[str]:
    """Extract game ID strings from a ``nfl_weekly_game_details`` raw payload.

    The endpoint returns either a bare ``list`` of game objects or a dict with a
    ``games``/``data`` key.  Each game object is checked for an ``id``,
    ``nflId``, or ``gameId`` field (in that priority order).

    Args:
        payload: Raw return value from ``nfl_weekly_game_details``.

    Returns:
        List of game ID strings; objects with no identifiable ID are skipped.
    """
    if isinstance(payload, list):
        games = payload
    else:
        games = payload.get("games", []) or payload.get("data", []) or []

    ids: list[str] = []
    for game in games:
        for field in ("id", "nflId", "gameId"):
            val = game.get(field)
            if val is not None:
                ids.append(str(val))
                break
    return ids


def build_raw_library(
    seasons: List[int],
    output_dir: Path = Path("data/raw"),
    *,
    season_types: List[str] = ("REG", "POST"),
    resume: bool = True,
    headers: dict | None = None,
    delay_s: float = 0.0,
) -> list[Path]:
    """Download and store weekly NFL game details JSON for the given seasons.

    For each (season, season_type, week) tuple, fetches the raw payload from
    ``api.nfl.com/football/v2/experience/weekly-game-details`` and writes it to
    ``{output_dir}/{season}/{season_type}/wk{week:02d}.json``.  When
    ``resume=True`` (default) an existing file is left untouched.

    Args:
        seasons: List of NFL season years to fetch (e.g. ``list(range(2012, 2025))``).
        output_dir: Root directory for the raw JSON library.
        season_types: Season type codes to fetch for each year.
            Defaults to ``("REG", "POST")``.
        resume: Skip weeks whose JSON file already exists on disk when ``True``.
        headers: Pre-minted auth headers to reuse across all requests.
            A fresh anonymous ``WEB_DESKTOP`` token is minted when ``None``.
        delay_s: Seconds to sleep after each network request (both the
            week-calendar lookup and each weekly-details fetch). Use a small
            positive value (e.g. ``2.0``) to throttle a sequential pull and stay
            polite to ``api.nfl.com``. A skipped (already-on-disk) week does not
            trigger a sleep, so resumed runs aren't penalized. Defaults to ``0.0``
            (no throttle).

    Returns:
        List of :class:`pathlib.Path` objects for each file written this run
        (already-present files skipped under ``resume=True`` are excluded).

    Example:
        Quick start (all regular-season weeks, 2020–2024)::

            from pathlib import Path
            from python.model_training.track6_nfl_ep_wp.fetcher import build_raw_library

            paths = build_raw_library(
                seasons=list(range(2020, 2025)),
                output_dir=Path("data/raw"),
                season_types=["REG"],
            )
            print(f"Wrote {len(paths)} weekly files")

        Throttled sequential pull (2s between requests)::

            paths = build_raw_library(
                seasons=[2025],
                output_dir=Path("data/raw"),
                delay_s=2.0,
            )
    """
    output_dir = Path(output_dir)
    written: list[Path] = []

    for season in seasons:
        for stype in list(season_types):
            week_nums = list_season_weeks(season, stype, headers=headers)
            if delay_s > 0:
                time.sleep(delay_s)
            if not week_nums:
                continue
            season_dir = output_dir / str(season) / stype
            season_dir.mkdir(parents=True, exist_ok=True)

            for week in week_nums:
                out = season_dir / f"wk{week:02d}.json"
                if resume and out.exists():
                    continue
                payload = _fetch_weekly_details(season, stype, week, headers=headers)
                out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                print(f"[fetcher] {season}/{stype} wk{week:02d} -> {out}")
                written.append(out)
                if delay_s > 0:
                    time.sleep(delay_s)

    return written


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------

def load_weekly_raw(path: Path) -> Union[list, dict]:
    """Load a stored weekly JSON file from disk.

    Args:
        path: Path to a ``wk{NN}.json`` file written by :func:`build_raw_library`.

    Returns:
        The parsed JSON value (bare list or dict, matching what the API returned).

    Raises:
        FileNotFoundError: When ``path`` does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Weekly raw file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_library_files(
    season: int,
    season_type: str,
    data_dir: Path = Path("data/raw"),
) -> list[Path]:
    """List all stored weekly JSON files for a season/type, sorted by week.

    Args:
        season: NFL season year.
        season_type: ``"REG"`` or ``"POST"``.
        data_dir: Root directory of the raw JSON library.

    Returns:
        Sorted list of :class:`pathlib.Path` objects for each ``wk*.json`` file
        found.  Returns an empty list when the directory does not exist or
        contains no matching files.
    """
    week_dir = Path(data_dir) / str(season) / season_type
    if not week_dir.is_dir():
        return []
    return sorted(week_dir.glob("wk*.json"))
