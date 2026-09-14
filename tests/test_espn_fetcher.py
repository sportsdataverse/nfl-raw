"""Offline tests for the ESPN NFL capture + crosswalk (monkeypatched network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from python.nfl_espn_scrape import espn_fetcher as ef


def _fake_download(payloads):
    class _Resp:
        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    def download(url, **kwargs):
        for key, body in payloads.items():
            if key in url:
                return _Resp(body)
        raise AssertionError(f"unexpected url {url}")

    return download


def test_capture_event_strips_media_and_pages_plays(tmp_path, monkeypatch):
    monkeypatch.setenv("ESPN_RATE_SLEEP", "0")
    summary = {
        "header": {
            "season": {"year": 2026},
            "competitions": [
                {"date": "2026-09-10T00:20Z", "status": {"type": {"completed": True}}}
            ],
        },
        "drives": {},
        "videos": [1],
        "news": {"x": 1},
        "article": {},
        "boxscore": {},
    }
    plays_p1 = {
        "pageCount": 2,
        "items": [
            {
                "id": "1",
                "text": "drop me",
                "participants": [
                    {
                        "athlete": {"$ref": "http://x/athletes/7"},
                        "position": {"$ref": "http://x/positions/8"},
                        "type": "passer",
                        "order": 1,
                        "statistics": {"$ref": "drop"},
                    }
                ],
            }
        ],
    }
    plays_p2 = {"pageCount": 2, "items": [{"id": "2", "participants": []}]}
    monkeypatch.setattr(
        ef,
        "download",
        _fake_download(
            {
                "summary?event=401": summary,
                "plays?limit=1000&page=1": plays_p1,
                "plays?limit=1000&page=2": plays_p2,
            }
        ),
    )
    r = ef.capture_event(tmp_path, 2026, 401)
    assert r == {"summary": "written", "plays": "written"}
    assert ef.summary_path(tmp_path, 2026, 401).name.endswith(".json.gz")
    s = ef.read_json(ef.summary_path(tmp_path, 2026, 401))
    assert (
        "videos" not in s and "news" not in s and "article" not in s and "boxscore" in s
    )
    p = ef.read_json(ef.plays_path(tmp_path, 2026, 401))
    assert [i["id"] for i in p["items"]] == ["1", "2"]
    assert p["items"][0]["participants"] == [
        {
            "athlete": {"$ref": "http://x/athletes/7"},
            "position": {"$ref": "http://x/positions/8"},
            "type": "passer",
            "order": 1,
        }
    ]
    assert "text" not in p["items"][0]
    # resumable: a second capture touches nothing
    monkeypatch.setattr(ef, "download", _fake_download({}))
    assert ef.capture_event(tmp_path, 2026, 401) == {
        "summary": "exists",
        "plays": "exists",
    }


def test_list_season_events_reads_ids_from_refs(monkeypatch):
    monkeypatch.setenv("ESPN_RATE_SLEEP", "0")
    listing = {
        "pageCount": 1,
        "items": [
            {"$ref": "http://x/events/401872922?lang=en"},
            {"$ref": "http://x/events/401872931"},
        ],
    }
    monkeypatch.setattr(
        ef,
        "download",
        _fake_download(
            {"types/2/events": listing, "types/3/events": {"pageCount": 1, "items": []}}
        ),
    )
    assert ef.list_season_events(2026) == [(401872922, 2), (401872931, 2)]


def test_crosswalk_matches_on_kickoff_and_home_name(tmp_path, monkeypatch):
    from python import nfl_espn_02_crosswalk as xw

    monkeypatch.setattr(xw, "ROOT", tmp_path)
    espn_dir = tmp_path / "nfl" / "espn" / "raw" / "2025"
    shield_dir = tmp_path / "nfl" / "raw" / "2025"
    espn_dir.mkdir(parents=True)
    shield_dir.mkdir(parents=True)
    espn_dir.joinpath("401772510.json").write_text(
        json.dumps(
            {
                "header": {
                    "season": {"year": 2025, "type": 2},
                    "week": 1,
                    "competitions": [
                        {
                            "date": "2025-09-07T17:00Z",
                            "neutralSite": False,
                            "status": {"type": {"name": "STATUS_FINAL"}},
                            "competitors": [
                                {
                                    "homeAway": "home",
                                    "team": {
                                        "id": "18",
                                        "abbreviation": "NO",
                                        "displayName": "New Orleans Saints",
                                    },
                                },
                                {
                                    "homeAway": "away",
                                    "team": {
                                        "id": "22",
                                        "abbreviation": "ARI",
                                        "displayName": "Arizona Cardinals",
                                    },
                                },
                            ],
                        }
                    ],
                }
            }
        )
    )
    espn_dir.joinpath("401999999.json").write_text(
        json.dumps(
            {
                "header": {
                    "season": {"year": 2025, "type": 3},
                    "week": 5,
                    "competitions": [
                        {
                            "date": "2026-02-01T20:00Z",
                            "competitors": [
                                {
                                    "homeAway": "home",
                                    "team": {
                                        "id": "1",
                                        "abbreviation": "AFC",
                                        "displayName": "AFC",
                                    },
                                },
                                {
                                    "homeAway": "away",
                                    "team": {
                                        "id": "2",
                                        "abbreviation": "NFC",
                                        "displayName": "NFC",
                                    },
                                },
                            ],
                        }
                    ],
                }
            }
        )
    )
    shield_dir.joinpath("2025_01_ARI_NO.json").write_text(
        json.dumps(
            {
                "id": "f591a18c",
                "date": "2025-09-07",
                "time": "2025-09-07T17:00:00Z",
                "homeTeam": {"id": "uuid-no", "fullName": "New Orleans Saints"},
                "awayTeam": {"id": "uuid-ari", "fullName": "Arizona Cardinals"},
            }
        )
    )
    games, teams, stats = xw.build([2025])
    assert stats == {"espn": 2, "matched_time": 1, "matched_date": 0, "unmatched": 1}
    g = {r["espn_event_id"]: r for r in games}
    assert (
        g[401772510]["game_id"] == "2025_01_ARI_NO"
        and g[401772510]["shield_game_id"] == "f591a18c"
    )
    assert (
        g[401772510]["home_nflverse"] == "NO" and g[401772510]["away_nflverse"] == "ARI"
    )
    assert g[401999999]["match"] == "unmatched" and g[401999999]["game_id"] is None
    by_abbr = {t["espn_abbr"]: t for t in teams}
    assert (
        by_abbr["NO"]["shield_team_id"] == "uuid-no"
        and by_abbr["NO"]["nflverse_abbr"] == "NO"
        and by_abbr["NO"]["seasons"] == [2025]
    )


def _summary(completed: bool, date: str) -> dict:
    return {
        "header": {
            "competitions": [
                {"date": date, "status": {"type": {"completed": completed}}}
            ]
        }
    }


def test_capture_event_refreshes_unfinished_games_only(tmp_path, monkeypatch):
    # A routine run keeps skip_existing on; only a game that has kicked off but
    # is not final (in progress, or captured before the final was posted) is
    # re-fetched -- and its plays with it. Finals and future shells are left.
    monkeypatch.setenv("ESPN_RATE_SLEEP", "0")
    for eid, done, date in (
        (1, True, "2025-09-07T17:00Z"),
        (2, False, "2025-09-07T17:00Z"),
        (3, False, "2099-01-01T00:00Z"),
    ):
        ef._write_json(ef.summary_path(tmp_path, 2025, eid), _summary(done, date))
        ef._write_json(ef.plays_path(tmp_path, 2025, eid), {"items": []})
    monkeypatch.setattr(
        ef,
        "download",
        _fake_download(
            {
                "summary?event=2": _summary(True, "2025-09-07T17:00Z"),
                "events/2/competitions/2/plays": {
                    "pageCount": 1,
                    "items": [{"id": "9", "participants": []}],
                },
            }
        ),
    )
    assert ef.capture_event(tmp_path, 2025, 1) == {"summary": "exists", "plays": "exists"}
    assert ef.capture_event(tmp_path, 2025, 3) == {"summary": "exists", "plays": "exists"}
    assert ef.capture_event(tmp_path, 2025, 2) == {"summary": "written", "plays": "written"}
    assert ef.is_final(ef.read_json(ef.summary_path(tmp_path, 2025, 2)))
    assert ef.read_json(ef.plays_path(tmp_path, 2025, 2))["items"][0]["id"] == "9"
    # now final: a third pass touches nothing
    monkeypatch.setattr(ef, "download", _fake_download({}))
    assert ef.capture_event(tmp_path, 2025, 2) == {"summary": "exists", "plays": "exists"}
