"""Per-game box scores from api.nfl.com's live statistics routes.

For every FINAL game in the committed ``nfl/raw/{season}/{game_id}.json``
library, fetch::

    /football/v2/stats/live/team-statistics/{shield_id}     both sides' team box score
    /football/v2/stats/live/player-statistics/{shield_id}   every player's box score

and bank both raw bodies in one file, ``nfl/box_scores/{season}/{game_id}.json``::

    {"game_id": ..., "shield_game_id": ..., "captured_at": ...,
     "team_statistics": {...}, "player_statistics": {...}}

Despite "live" in the route name these serve completed games too: verified back
to 2001 with the same 106-field team payload (2026-09-15).

Rules:

- **Finality comes from the game file**, ``summary.phase`` in ``FINAL`` /
  ``FINAL_OVERTIME``. Shield's top-level ``status`` says ``SCHEDULED`` for every
  game in the library, 2001 included, so it cannot be used.
- **Presence is not validity.** A banked file is trusted only when both halves
  carry a ``homeTeam`` object and the player half has player rows; otherwise it
  is refetched. A payload that fails that test is never written.
- Writes are atomic (tmp + rename).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

FINAL_PHASES = {"FINAL", "FINAL_OVERTIME", "FINAL OVERTIME"}
API = "https://api.nfl.com/football/v2/stats/live"
TOKEN_REFRESH_S = 15 * 60  # anonymous tokens live ~1h; re-mint well inside that

Fetch = Callable[[str, Optional[dict]], dict]


def _default_fetch(url: str, headers: Optional[dict]) -> dict:
    from sportsdataverse.nfl.nfl_api_runtime import _get

    return _get(url, headers=headers)


def _mint() -> dict:
    from sportsdataverse.nfl.nfl_games import nfl_headers_gen

    return nfl_headers_gen()


def is_final(game: dict) -> bool:
    return ((game.get("summary") or {}).get("phase") or "") in FINAL_PHASES


def valid_team(body: object) -> bool:
    return (
        isinstance(body, dict)
        and isinstance(body.get("homeTeam"), dict)
        and isinstance(body.get("awayTeam"), dict)
    )


def valid_player(body: object) -> bool:
    if not valid_team(body):
        return False
    return any((body[side].get("players") or []) for side in ("homeTeam", "awayTeam"))


def is_valid_file(path: Path) -> bool:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return valid_team(d.get("team_statistics")) and valid_player(
        d.get("player_statistics")
    )


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def scrape_season(
    season: int,
    *,
    raw_dir: Path = Path("nfl/raw"),
    out_dir: Path = Path("nfl/box_scores"),
    delay: float = 0.5,
    rescrape: bool = False,
    limit: int = 0,
    fetch: Optional[Fetch] = None,
    mint: Optional[Callable[[], dict]] = None,
) -> dict:
    """Bank box scores for every FINAL game of a season. Returns counters."""
    fetch = fetch or _default_fetch
    mint = mint or _mint
    counts = {
        "games": 0,
        "final": 0,
        "wrote": 0,
        "skipped": 0,
        "not_final": 0,
        "failed": 0,
    }
    files = sorted((raw_dir / str(season)).glob("*.json"))
    counts["games"] = len(files)
    headers, minted_at = None, 0.0
    done = 0
    for f in files:
        game_id = f.stem
        try:
            game = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            counts["failed"] += 1
            print(
                f"  box score {season} {game_id} FAILED: unreadable game file",
                flush=True,
            )
            continue
        if not is_final(game):
            counts["not_final"] += 1
            continue
        counts["final"] += 1
        out = out_dir / str(season) / f"{game_id}.json"
        if not rescrape and is_valid_file(out):
            counts["skipped"] += 1
            continue
        if limit and done >= limit:
            break
        shield_id = game.get("id")
        if headers is None or time.monotonic() - minted_at > TOKEN_REFRESH_S:
            headers, minted_at = mint(), time.monotonic()
        try:
            team = fetch(f"{API}/team-statistics/{shield_id}", headers)
            if delay:
                time.sleep(delay)
            player = fetch(f"{API}/player-statistics/{shield_id}", headers)
        except Exception as exc:  # noqa: BLE001 -- one game must not end the season; counted + rc
            counts["failed"] += 1
            print(
                f"  box score {season} {game_id} FAILED: {type(exc).__name__}: {str(exc)[:120]}",
                flush=True,
            )
            headers = None  # an expired/revoked token is the likeliest cause: re-mint next time
            continue
        finally:
            if delay:
                time.sleep(delay)
        if not (valid_team(team) and valid_player(player)):
            counts["failed"] += 1
            print(
                f"  box score {season} {game_id} FAILED: payload missing team or player rows",
                flush=True,
            )
            continue
        _write_atomic(
            out,
            {
                "game_id": game_id,
                "shield_game_id": shield_id,
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "team_statistics": team,
                "player_statistics": player,
            },
        )
        counts["wrote"] += 1
        done += 1
        if counts["wrote"] % 50 == 0:
            print(f"  box scores {season}: {counts}", flush=True)
    return {"season": season, **counts}
