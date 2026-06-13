"""Ingest nflverse play-by-play data for EP/WP/CP model training.

Usage:
    from python.model_training.track6_nfl_ep_wp.ingest import download_pbp
    download_pbp(seasons=list(range(2012, 2025)), output_dir=Path("data"))
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import polars as pl


# ---------------------------------------------------------------------------
# Required columns — superset of all EP/WP/CP source + label columns
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS: list[str] = [
    # identifiers / ordering
    "game_id",
    "play_id",
    "qtr",
    "game_half",
    # EP/WP feature sources
    "down",
    "yardline_100",
    "ydstogo",
    "half_seconds_remaining",
    "game_seconds_remaining",
    "posteam_timeouts_remaining",
    "defteam_timeouts_remaining",
    "posteam",
    "defteam",
    "home_team",
    "season",
    "roof",
    "spread_line",
    "score_differential",
    # EP label sources
    "sp",
    "touchdown",
    "td_team",
    "field_goal_result",
    "safety",
    # WP label sources
    "result",
    "home_score",
    "away_score",
    # CP feature sources
    "air_yards",
    "pass_location",
    "complete_pass",
    "incomplete_pass",
    "interception",
    "receiver_player_id",
    "receiver_player_name",
    "qb_hit",
]


def validate_pbp(df: pl.DataFrame) -> None:
    """Raise ValueError if the DataFrame is missing required columns or has no rows.

    Args:
        df: Raw nflverse PBP DataFrame.

    Raises:
        ValueError: On missing columns or empty frame.
    """
    if df.height == 0:
        raise ValueError("PBP frame is empty — likely a failed download or wrong season range.")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"PBP frame is missing required columns: {missing}. "
            "Ensure nflverse-compatible data is loaded."
        )


def _load_nfl_pbp(seasons: List[int], **kwargs) -> pl.DataFrame:
    """Thin wrapper around sportsdataverse so tests can monkeypatch it."""
    from sportsdataverse.nfl import load_nfl_pbp
    from sportsdataverse.nfl import update_config

    update_config(cache_mode="off")
    return load_nfl_pbp(seasons=seasons, **kwargs)


def download_pbp(
    seasons: List[int],
    *,
    output_dir: Path = Path("data"),
) -> list[Path]:
    """Download nflverse PBP for the given seasons and save as parquet files.

    Files are saved as ``{output_dir}/pbp_{season}.parquet``. Existing files are
    overwritten so re-running is idempotent.

    Args:
        seasons: List of NFL seasons (e.g. ``list(range(2012, 2025))``).
        output_dir: Directory for output parquet files. Created if absent.

    Returns:
        List of paths to written parquet files.

    Example:
        Quick start::

            from pathlib import Path
            from python.model_training.track6_nfl_ep_wp.ingest import download_pbp
            paths = download_pbp([2023, 2024], output_dir=Path("data"))
            print(paths)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for season in seasons:
        print(f"[ingest] downloading season {season}...")
        df = _load_nfl_pbp([season])
        validate_pbp(df)
        out = output_dir / f"pbp_{season}.parquet"
        df.write_parquet(str(out))
        print(f"[ingest] saved {out} ({df.height:,} rows, {df.width} cols)")
        written.append(out)

    return written


def load_local_pbp(seasons: List[int], data_dir: Path = Path("data")) -> pl.DataFrame:
    """Load previously-downloaded PBP parquets from disk.

    Args:
        seasons: Seasons to load.
        data_dir: Directory containing ``pbp_{season}.parquet`` files.

    Returns:
        Concatenated polars DataFrame.

    Raises:
        FileNotFoundError: If a season file is missing.
    """
    frames: list[pl.DataFrame] = []
    for season in seasons:
        path = Path(data_dir) / f"pbp_{season}.parquet"
        if not path.exists():
            raise FileNotFoundError(
                f"No local PBP found for season {season} at {path}. "
                "Run download_pbp() first."
            )
        frames.append(pl.read_parquet(str(path)))
    return pl.concat(frames, how="diagonal_relaxed")
