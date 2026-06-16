"""Game-state derivations: running score_differential + timeouts remaining.

Produces the base nflverse columns Track 6's labelers consume. The downstream
model-feature engineering (era / down one-hots / elapsed_share / spread_time /
Diff_Time_Ratio / receive_2h_ko) lives in Track 6's own ``features.py`` and is
derived from these base columns — so it is intentionally NOT done here.

``roof`` and ``spread_line`` are game-level and come from a schedules join
(nflverse schedules / Lee Sharpe games, the same source nflfastR uses); they are
passed in as scalars rather than parsed from the Shield feed, which omits them.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import polars as pl


def _scoring_events(df: pl.DataFrame, game: Dict[str, Any]) -> pl.DataFrame:
    """Build (key, home_running, away_running) score steps keyed just AFTER each
    scoring play's sequence, so an as-of backward join yields the PRE-snap score.
    """
    dc = game.get("driveChart") or {}
    summaries = dc.get("scoringSummaries") or []
    # Map scoringPlayId -> play_seq from the parsed frame.
    seq_by_pid = dict(zip(df["play_id"].to_list(), df["play_seq"].to_list()))
    rows = [{"key": -1.0, "home_running": 0, "away_running": 0}]
    for s in summaries:
        pid = s.get("scoringPlayId")
        seq = seq_by_pid.get(pid)
        if seq is None:
            continue
        rows.append({
            "key": float(seq) + 0.5,  # +0.5 makes the as-of backward join strict (< play_seq)
            "home_running": int(s.get("homeScore") or 0),
            "away_running": int(s.get("awayScore") or 0),
        })
    return pl.DataFrame(rows).sort("key")


def add_game_state(
    df: pl.DataFrame,
    game: Dict[str, Any],
    *,
    roof: Optional[str] = None,
    spread_line: Optional[float] = None,
) -> pl.DataFrame:
    """Add score_differential, posteam/defteam timeouts, roof, spread_line.

    Args:
        df: Base play frame (post parse, ideally post description) — must carry
            ``play_id``, ``play_seq``, ``game_half``, ``posteam``, ``home_team``,
            ``timeout``, ``timeout_team``.
        game: The raw Shield game payload (for scoringSummaries).
        roof: Game roof (``outdoors``/``dome``/``closed``/``open``/``retractable``)
            from a schedules join; ``None`` left as-is for downstream model_roof
            handling.
        spread_line: Closing spread (home-relative) from a schedules join.

    Returns:
        The frame with ``score_differential``, ``posteam_timeouts_remaining``,
        ``defteam_timeouts_remaining``, ``roof``, ``spread_line`` added.
    """
    if df.height == 0:
        return df

    df = df.sort("play_seq")

    # --- running score (pre-snap) via strict as-of backward join ---
    events = _scoring_events(df, game)
    df = df.join_asof(events, left_on="play_seq", right_on="key", strategy="backward")
    df = df.with_columns(
        home_running=pl.col("home_running").fill_null(0),
        away_running=pl.col("away_running").fill_null(0),
    )
    df = df.with_columns(
        posteam_score=pl.when(pl.col("posteam") == pl.col("home_team"))
        .then(pl.col("home_running")).otherwise(pl.col("away_running")),
        defteam_score=pl.when(pl.col("posteam") == pl.col("home_team"))
        .then(pl.col("away_running")).otherwise(pl.col("home_running")),
    ).with_columns(
        score_differential=(pl.col("posteam_score") - pl.col("defteam_score")),
    ).drop("key", "home_running", "away_running")

    # --- timeouts remaining (cumsum per half, capped at 3) ---
    df = df.with_columns(
        _home_to=((pl.col("timeout") == 1) & (pl.col("timeout_team") == pl.col("home_team"))).cast(pl.Int64),
        _away_to=((pl.col("timeout") == 1) & (pl.col("timeout_team") == pl.col("away_team"))).cast(pl.Int64),
    )
    df = df.with_columns(
        _home_used=pl.col("_home_to").cum_sum().over("game_half").clip(upper_bound=3),
        _away_used=pl.col("_away_to").cum_sum().over("game_half").clip(upper_bound=3),
    )
    df = df.with_columns(
        _home_rem=(3 - pl.col("_home_used")),
        _away_rem=(3 - pl.col("_away_used")),
    ).with_columns(
        posteam_timeouts_remaining=pl.when(pl.col("posteam") == pl.col("home_team"))
        .then(pl.col("_home_rem")).otherwise(pl.col("_away_rem")),
        defteam_timeouts_remaining=pl.when(pl.col("posteam") == pl.col("home_team"))
        .then(pl.col("_away_rem")).otherwise(pl.col("_home_rem")),
    ).drop("_home_to", "_away_to", "_home_used", "_away_used", "_home_rem", "_away_rem")

    # --- game-level joins (scalars) ---
    df = df.with_columns(
        roof=pl.lit(roof),
        spread_line=pl.lit(spread_line, dtype=pl.Float64),
    )
    return df
