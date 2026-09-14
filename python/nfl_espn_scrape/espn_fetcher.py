"""Fetch ESPN's NFL game payloads into the committed ``nfl/espn/`` library.

Two ESPN endpoints per event:

* ``site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={id}`` --
  the game summary ``NFLPlayProcess`` consumes (drives, plays, boxscore,
  header, pickcenter, win probability). Stored gzipped at
  ``nfl/espn/raw/{season}/{event_id}.json.gz`` with the media-only keys
  (``videos`` / ``news`` / ``article``) dropped; everything the processor or
  a box-score consumer reads is kept verbatim (~80 KB a game compressed).
* ``sports.core.api.espn.com/v2/.../events/{id}/competitions/{id}/plays`` --
  the per-play ``participants[]`` (athlete / position refs and the
  participant type) the processor's participants join reads. Stored gzipped at
  ``nfl/espn/plays/{season}/{event_id}.json.gz`` as ``{"items": [...]}`` after
  following ``pageCount``, slimmed to each play's ``id`` / ``sequenceNumber``
  and its participants -- the play text, clock and probabilities already live
  in the summary.

Gzip keeps a 25-season capture near 0.6 GB instead of 6 GB; readers open the
files with :func:`read_json`.

Event ids come from the core season listing
(``.../seasons/{season}/types/{type}/events?limit=1000``): type 2 is the
regular season, 3 the postseason (the Pro Bowl rides along and stays
unmatched in the crosswalk), 1 the preseason.

Throttle / retry are environment-tunable so a running backfill can be re-paced
without a code change: ``ESPN_RATE_SLEEP`` (seconds between requests per
worker, default 0.25) and ``ESPN_RATE_RETRIES`` (default 3).
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sportsdataverse.dl_utils import download

log = logging.getLogger("nfl_espn_scrape")

SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"
PLAYS_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
    "events/{event_id}/competitions/{event_id}/plays?limit=1000&page={page}"
)
EVENTS_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
    "seasons/{season}/types/{season_type}/events?limit=1000&page={page}"
)
#: keys of the summary payload that carry media, not game data
MEDIA_KEYS = ("videos", "news", "article")
#: ESPN play-by-play for the NFL is reliable from the 2002 realignment on
ESPN_NFL_DETAIL_START = 2002
_EVENT_ID_RE = re.compile(r"/events/(\d+)")


def _sleep() -> None:
    time.sleep(float(os.environ.get("ESPN_RATE_SLEEP", "0.25")))


def _get_json(url: str, **kwargs: Any) -> dict:
    """GET ``url`` with sdv-py's retrying downloader plus a paced retry of our own."""
    retries = int(os.environ.get("ESPN_RATE_RETRIES", "3"))
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = download(url=url, **kwargs)
            body = resp.json()
            _sleep()
            return body
        except Exception as exc:  # noqa: BLE001 -- network / decode; retry then surface
            last = exc
            time.sleep(min(30.0, 2.0 * (attempt + 1)))
    raise RuntimeError(
        f"ESPN request failed after {retries + 1} attempts: {url}: {last}"
    )


def list_season_events(
    season: int, season_types: Iterable[int] = (2, 3), **kwargs: Any
) -> list[tuple[int, int]]:
    """``[(event_id, season_type), ...]`` for a season from the core listing, following ``pageCount``."""
    out: list[tuple[int, int]] = []
    for season_type in season_types:
        page = 1
        while True:
            body = _get_json(
                EVENTS_URL.format(season=season, season_type=season_type, page=page),
                **kwargs,
            )
            for item in body.get("items") or []:
                m = _EVENT_ID_RE.search(str(item.get("$ref", "")))
                if m:
                    out.append((int(m.group(1)), int(season_type)))
            if page >= int(body.get("pageCount") or 1):
                break
            page += 1
    return out


def fetch_summary(event_id: int, **kwargs: Any) -> dict:
    """The game summary with the media keys dropped."""
    body = _get_json(SUMMARY_URL.format(event_id=event_id), **kwargs)
    for k in MEDIA_KEYS:
        body.pop(k, None)
    return body


def _slim_play(play: dict) -> dict:
    """Keep the identity and the participants; the rest is in the summary."""
    parts = []
    for k in play.get("participants") or []:
        if not isinstance(k, dict):
            continue
        parts.append(
            {
                "athlete": {"$ref": (k.get("athlete") or {}).get("$ref")},
                "position": {"$ref": (k.get("position") or {}).get("$ref")},
                "type": k.get("type"),
                "order": k.get("order"),
            }
        )
    return {
        "id": play.get("id"),
        "sequenceNumber": play.get("sequenceNumber"),
        "participants": parts,
    }


def fetch_plays(event_id: int, **kwargs: Any) -> dict:
    """``{"items": [...]}`` -- every core play's id and ``participants[]``, all pages."""
    items: list[dict] = []
    page = 1
    while True:
        body = _get_json(PLAYS_URL.format(event_id=event_id, page=page), **kwargs)
        items.extend(
            _slim_play(i) for i in (body.get("items") or []) if isinstance(i, dict)
        )
        if page >= int(body.get("pageCount") or 1) or not body.get("items"):
            break
        page += 1
    return {"items": items}


def summary_path(root: Path, season: int, event_id: int) -> Path:
    return root / "nfl" / "espn" / "raw" / str(season) / f"{event_id}.json.gz"


def plays_path(root: Path, season: int, event_id: int) -> Path:
    return root / "nfl" / "espn" / "plays" / str(season) / f"{event_id}.json.gz"


def read_json(path: Path) -> dict:
    """Read a committed ``.json.gz`` (or a plain ``.json``) payload."""
    if str(path).endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(Path(path).read_text())


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if path.name.endswith(".gz"):
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
            fh.write(data)
    else:
        tmp.write_text(data)
    tmp.replace(path)


def is_final(summary: dict) -> bool:
    """True when the stored summary's competition status says the game completed."""
    try:
        comp = summary["header"]["competitions"][0]
        return bool(comp["status"]["type"]["completed"])
    except (KeyError, IndexError, TypeError):
        return False


def has_kicked_off(summary: dict, now: Optional[float] = None) -> bool:
    """True when the competition date is in the past (or unreadable)."""
    try:
        raw = summary["header"]["competitions"][0]["date"]
        kickoff = (
            datetime.strptime(raw, "%Y-%m-%dT%H:%MZ")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return True
    return kickoff <= (now if now is not None else time.time())


def needs_refresh(path: Path) -> bool:
    """A captured summary is stale when the game is not final but has started.

    Routine (daily) runs re-capture with ``skip_existing=True``; this is what
    keeps an in-progress or just-finished game from freezing at the state it
    was first seen in, while a future game's pregame shell and every final are
    left alone.
    """
    try:
        summary = read_json(path)
    except (OSError, ValueError):
        return True
    return not is_final(summary) and has_kicked_off(summary)


def capture_event(
    root: Path,
    season: int,
    event_id: int,
    *,
    with_plays: bool = True,
    skip_existing: bool = True,
    **kwargs: Any,
) -> dict[str, str]:
    """Write the summary (and plays) for one event. Returns what happened per file.

    With ``skip_existing`` a final game already on disk is untouched; a stored
    game that has kicked off but is not final is refreshed (summary and plays).
    """
    result: dict[str, str] = {}
    sp = summary_path(root, season, event_id)
    if skip_existing and sp.exists() and not needs_refresh(sp):
        result["summary"] = "exists"
    else:
        _write_json(sp, fetch_summary(event_id, **kwargs))
        result["summary"] = "written"
    if with_plays:
        pp = plays_path(root, season, event_id)
        if skip_existing and pp.exists() and result["summary"] == "exists":
            result["plays"] = "exists"
        else:
            _write_json(pp, fetch_plays(event_id, **kwargs))
            result["plays"] = "written"
    return result
