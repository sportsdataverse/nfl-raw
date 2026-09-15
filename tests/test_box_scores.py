"""Stage 03 box scores -- offline; every fetch is injected."""

import json
from pathlib import Path

from python.nfl_raw_scrape import box_scores as bs

TEAM = {"gameId": "g", "offset": 1, "homeTeam": {"teamId": "h", "passingYards": 200}, "awayTeam": {"teamId": "a"}}
PLAYER = {"gameId": "g", "homeTeam": {"teamId": "h", "players": [{"gsisPlayerId": "00-1"}]}, "awayTeam": {"teamId": "a", "players": []}}


def _game(tmp: Path, season: int, gid: str, phase):
    p = tmp / "raw" / str(season) / f"{gid}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"id": f"uuid-{gid}", "status": "SCHEDULED", "summary": {"phase": phase} if phase else None}))


class Api:
    def __init__(self, team=TEAM, player=PLAYER, fail=()):
        self.team, self.player, self.fail, self.calls = team, player, set(fail), []

    def __call__(self, url, headers):
        self.calls.append(url)
        if any(f in url for f in self.fail):
            raise RuntimeError("HTTP 500")
        return self.team if "team-statistics" in url else self.player


def _run(tmp, api, **kw):
    return bs.scrape_season(2025, raw_dir=tmp / "raw", out_dir=tmp / "out", delay=0, fetch=api, mint=lambda: {"Authorization": "x"}, **kw)


def test_only_final_games_by_summary_phase_not_status(tmp_path: Path):
    _game(tmp_path, 2025, "2025_01_A_B", "FINAL")
    _game(tmp_path, 2025, "2025_01_C_D", "FINAL_OVERTIME")
    _game(tmp_path, 2025, "2025_18_E_F", None)  # not played yet; status says SCHEDULED for all
    api = Api()
    st = _run(tmp_path, api)
    assert st["final"] == 2 and st["not_final"] == 1 and st["wrote"] == 2
    assert not any("E_F" in u or "uuid-2025_18_E_F" in u for u in api.calls)
    banked = json.loads((tmp_path / "out" / "2025" / "2025_01_A_B.json").read_text())
    assert banked["shield_game_id"] == "uuid-2025_01_A_B"
    assert banked["team_statistics"] == TEAM and banked["player_statistics"] == PLAYER


def test_valid_banked_file_is_skipped_then_rescraped_on_demand(tmp_path: Path):
    _game(tmp_path, 2025, "2025_01_A_B", "FINAL")
    api = Api()
    _run(tmp_path, api)
    n = len(api.calls)
    assert _run(tmp_path, api)["skipped"] == 1 and len(api.calls) == n
    assert _run(tmp_path, api, rescrape=True)["wrote"] == 1 and len(api.calls) == n + 2


def test_invalid_payload_is_failure_and_never_written(tmp_path: Path):
    _game(tmp_path, 2025, "2025_01_A_B", "FINAL")
    empty_players = {"homeTeam": {"players": []}, "awayTeam": {"players": []}}
    st = _run(tmp_path, Api(player=empty_players))
    assert st["failed"] == 1 and st["wrote"] == 0
    assert not (tmp_path / "out" / "2025" / "2025_01_A_B.json").exists()


def test_corrupt_banked_file_is_refetched(tmp_path: Path):
    _game(tmp_path, 2025, "2025_01_A_B", "FINAL")
    out = tmp_path / "out" / "2025" / "2025_01_A_B.json"
    out.parent.mkdir(parents=True)
    out.write_text('{"team_statistics": {')
    assert _run(tmp_path, Api())["wrote"] == 1 and bs.is_valid_file(out)


def test_transport_failure_counts_and_continues(tmp_path: Path):
    _game(tmp_path, 2025, "2025_01_A_B", "FINAL")
    _game(tmp_path, 2025, "2025_01_C_D", "FINAL")
    st = _run(tmp_path, Api(fail={"uuid-2025_01_A_B"}))
    assert st["failed"] == 1 and st["wrote"] == 1
