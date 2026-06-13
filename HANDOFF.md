# NFL Model Handoff Protocol

Trained models from this repo are **manually** copied into `sportsdataverse/nfl/models/`
in `sdv-py`. There is no automated deployment.

## Prerequisites

Stage-2 full-season training must complete successfully before handoff:
- EP model trained on 2012–2024 nflverse PBP (`cal_data` equivalent, ~10 seasons)
- WP-spread + WP-naive trained on same corpus, filtered `qtr <= 4`
- Parity gate passes (see Phase 5 in plan)

## Parity gate

Before copying `.ubj` files, run:

```bash
uv run python -m python.model_training.track6_nfl_ep_wp.validate \
    --ep-model models/ep_model.ubj \
    --wp-model models/wp_spread.ubj \
    --sample-seasons 2022 2023
```

Gate criteria:
- EP predictions: correlation ≥ 0.98 with nflfastR reference values for sample games
- WP predictions: Brier score ≤ 0.20 on held-out 2023 games
- Feature names in saved model == `EP_FEATURES` / `WP_SPREAD_FEATURES` (checked by loader)

## Copy procedure

```bash
# From nfl-raw/
cp models/ep_model.ubj   /path/to/sdv-py/sportsdataverse/nfl/models/ep_model.ubj
cp models/wp_spread.ubj  /path/to/sdv-py/sportsdataverse/nfl/models/wp_spread.ubj
cp models/wp_naive.ubj   /path/to/sdv-py/sportsdataverse/nfl/models/wp_naive.ubj
```

`wp_naive.ubj` is **new** — `sdv-py/sportsdataverse/nfl/models/` does not currently
ship it. The sdv-py PR must add it and wire it into `nfl_pbp.py`.

## sdv-py PR checklist

After copying `.ubj` files, open a PR in sdv-py with these changes:

- [ ] `sportsdataverse/nfl/model_vars.py` — replace CFB-shape `ep_final_names` (8 feat) +
  `wp_final_names` (13 feat) with NFL-shape (18 EP / 12 WP-spread / 11 WP-naive)
- [ ] `nfl/model_vars.py` — add `ep_start_columns`, `ep_end_columns`,
  `ep_start_touchback_columns` selecting the correct PBP columns in the new NFL order
- [ ] `nfl/model_vars.py` — add `wp_start_columns`, `wp_end_columns`,
  `wp_start_touchback_columns` for the 12-feat WP-spread contract
- [ ] `nfl/nfl_pbp.py` — add feature-engineering block (era/roof/down one-hots,
  `elapsed_share`, `spread_time`, `Diff_Time_Ratio`, `receive_2h_ko`) before the
  EP/WP inference section
- [ ] `nfl/nfl_pbp.py` — add `wp_naive_model` Booster (load `wp_naive.ubj`) alongside
  `wp_model` (spread); wire into WP inference as a fallback when `spread_line` is NaN
- [ ] `pyproject.toml` — add `wp_naive.ubj` to `[tool.setuptools.package-data]`
  under `"nfl/models/*"`
- [ ] `tests/nfl/test_nfl_pbp_models.py` — offline regression test: load a VCR-cassette
  game, run inference, assert EP/WP columns present and in [−10, 10] / [0, 1] range

## Feature engineering reference

See `python/model_training/track6_nfl_ep_wp/features.py` for the authoritative Python
translation of `nflfastR/R/helper_add_ep_wp.R → make_model_mutations() + prepare_wp_data()`.

Key derived columns and their nflverse-pbp sources:

| Derived column | Source columns | Formula |
|---|---|---|
| `home` | `posteam`, `home_team` | `posteam == home_team` |
| `retractable` | `roof` | `roof == "retractable"` |
| `dome` | `roof` | `roof in ("dome", "closed")` |
| `outdoors` | `roof` | all other values |
| `era0..era4` | `season` | see `_ERA_BOUNDS` in `features.py` |
| `down1..down4` | `down` | one-hot of integer down |
| `elapsed_share` | `game_seconds_remaining` | `(3600 - gsr) / 3600` |
| `posteam_spread` | `spread_line`, `home` | `spread_line if home else -spread_line` |
| `spread_time` | `posteam_spread`, `elapsed_share` | `ps * exp(-4 * es)` |
| `Diff_Time_Ratio` | `score_differential`, `elapsed_share` | `sd / exp(-4 * es)` |
| `receive_2h_ko` | `qtr`, `posteam`, `defteam`, `game_id` | see `_add_receive_2h_ko()` |
