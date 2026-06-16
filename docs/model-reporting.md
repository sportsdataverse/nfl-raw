# NFL Track 6 — model reporting, figures & metrics

This brings the NFL EP/WP/CP model training (`python/model_training/track6_nfl_ep_wp/`)
to the cfbfastR model-suite house style, and reproduces nflfastR's two signature
model figures. It is the reporting layer on top of the training pipeline.

## What's produced

Run it with the CLI:

```sh
# LOSO calibration report: tables + figures + metrics, off the native nfl/raw library
uv run python -m python.model_training.track6_nfl_ep_wp report \
    --seasons 1999 2024 --source native --out-dir reports/native

# quick pass (fewer per-fold rounds), nflverse source, tables only
uv run python -m python.model_training.track6_nfl_ep_wp report \
    --seasons 2016 2024 --source nflverse --nrounds 100 --no-figures
```

Output (`--out-dir`):

| File | Contents |
|---|---|
| `ep_calibration.{png,csv,parquet}` | EP reliability: predicted EP vs realized next-score points (LOSO) |
| `wp_calibration.{png,csv,parquet}` | WP reliability: predicted vs observed win rate (LOSO) |
| `cp_calibration.{png,csv,parquet}` | CP reliability, faceted by air-yards bucket (Short/Intermediate/Deep) |
| `ep_by_yardline.{png,csv}` | **nflfastR signature**: Expected Points by yardline × down |
| `cp_by_air_yards.{png,csv}` | **nflfastR signature**: completion % by air yards × pass direction |
| `metrics.json` | weighted calibration error + Brier per model |
| `report.md` | human-readable summary table + figure embeds |

Figures use the bespoke cfbfastR garnet styling (`#500f1b`, grey panels, Gill Sans
MT) via plotnine, emitting PNG + CSV + Parquet sidecars — identical to the CFB
suite's `write_calibration`. The loess smoother falls back to `lm` if `scikit-misc`
is absent or a facet is degenerate.

## Module layout

| Module | Role |
|---|---|
| `metrics.py` | `calibration_table` (generic binned, optional facet), `weighted_cal_error`, `brier_score`, `pearson_correlation`, `ep_expected_points` |
| `loso.py` | leave-one-season-out CV → long-form (pred, outcome[, facet]) frames for EP/WP/CP |
| `figures.py` | `write_calibration` + `plot_ep_by_yardline` + `plot_cp_by_air_yards` (lazy plotnine, loess→lm fallback) |
| `model_card.py` | `write_model_card` → `model_card.json` sidecar per `.ubj` |
| `report.py` | orchestrates LOSO → tables → figures → `metrics.json` + `report.md` |
| `validate.py` | the existing nflfastR-reference **parity gate** (EP corr ≥ 0.98, WP Brier ≤ 0.20) |

Model cards are written automatically by `run_full_pipeline` (one `<model>.json`
beside each `.ubj`): features, label, training seasons, row count, hyperparameters,
data source (`native`/`nflverse`), and train date.

## Dependency

Figures need the `figures` group: `uv sync --group figures` (plotnine + scikit-misc).
The package imports cleanly without it; `report --no-figures` writes tables + metrics only.

## Standard comparison

| Dimension | nflfastR (in-repo) | cfbfastR suite | **Track 6 (now)** |
|---|---|---|---|
| Calibration tables + weighted cal error | — | ✓ | ✓ |
| Calibration plots (garnet, PNG+CSV+Parquet) | — | ✓ | ✓ |
| LOSO cross-validation | WP only | T3/T5 | ✓ EP/WP/CP |
| EP-by-yardline + CP-by-air-yards curves | ✓ | — | ✓ |
| model_card.json | — | T3 only | ✓ all models |
| `report` / parity-gate CLI | — | per-track | ✓ |

Track 6 now meets or exceeds both reference standards.
