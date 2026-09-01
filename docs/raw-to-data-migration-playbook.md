# `-raw` → `-data` Migration Playbook (CFB reference → NFL target)

Distilled from the **cfbfastR-cfb-raw → cfbfastR-cfb-data** modeling migration (June 2026), as
the template for the equivalent **nfl-raw → nfl-data** split.

## 1. The pattern

The SportsDataverse two-repo convention separates two responsibilities that had grown tangled in
a single repo:

| Repo | Single responsibility |
|---|---|
| **`-raw`** | Scrape provider JSON → commit raw + enriched per-game files to git. Nothing else. |
| **`-data`** | Read the raw repo's enriched JSON **by URL**, reshape → compiled parquet/rds/csv datasets, train models, render reports, publish artifacts to GitHub Releases. |

The load-bearing idea: the `-data` repo is a *consumer* of the `-raw` repo's committed output (read
by raw `raw.githubusercontent.com` URL referenced from the schedule master), so the scraper repo
stays lean and the modeling/dataset churn lives elsewhere.

## 2. How CFB was migrated (3 sub-projects + hardening)

**SP1 — lift-and-shift + ingest seam** (cfb-data PR #3)
- `git mv` the modeling packages (`model_training`, `cpoe`, `pregame_wp`, `rb_eval`) and the
  compiled-PBP builder out of cfb-raw into cfb-data.
- New `cfb_data_ingest/` — reads raw `final.json` **by URL** from the raw repo's schedule master
  (`RAW_BASE` constant), with a local cache.
- New `cfb_model_pbp/` — builds the compiled model-PBP parquet (schema frozen; EP/WP carried from
  `final.json`, net-new CPOE).
- `pytest` `integration` marker keeps the default suite hermetic (`addopts='-m "not integration"'`);
  network/whole-corpus tests are opt-in.

**SP2 — reports + publish** (cfb-data PR #4)
- `cfb_model_reports/` — pure Markdown renderer; discovers models by globbing `*.json` cards,
  reads `model_type` (rb_eval has none → `.pkl` fallback). Output committed under `docs/models/`.
- `cfb_model_publish/` — `gh release upload` artifact uploader.
- One thin R script (`espn_cfb_16_model_pbp.R`) feeds the Python model-PBP parquet through the
  existing `write_dataset`/`publish_dataset` for parquet/rds/csv parity.
- **Division of labor:** Python owns modeling/reports/artifacts; R owns dataset-parity publishing.

**SP3 — decommission** (cfb-raw PR #5)
- `git rm` the modeling packages + their tests/fixtures from cfb-raw; relocate any scraper-owned
  test that was misfiled under the modeling tree.
- Drop modeling-only deps (`scikit-learn`, `xgboost`, `joblib` direct + `figures`/`gam`/`pregame-wp`
  groups). `xgboost` stays *transitively* via `sportsdataverse` (enrichment needs it) — that's fine;
  the repo simply no longer declares modeling deps directly.
- Boundary gate: `git grep` proves no surviving scraper/test imports a deleted package; the scraping
  suite stays green.

**Publish target + release tags**
- Both model releases publish to the **central `sportsdataverse/sportsdataverse-data`** repo (the
  CLI default `--repo`, the R `PUBLISH_REPOS`, and where the sdv-py loaders read) — *not* the
  per-sport `-data` repo. Tags: `espn_cfb_model_pbp` (dataset), `espn_cfb_model_artifacts`
  (`.ubj`/`.pkl` + cards). Registered idempotently in `R/releases_init.R`.

**Hardening found while testing the publish path** (cfb-data PRs #6, #7, and a fix)
- `library(arrow)` exports its own `write_dataset()` → an `if (!exists("write_dataset")) source(...)`
  guard silently shadowed the custom writer. Guard data-utils sourcing on a name unique to the utils
  file (`publish_dataset`), never `write_dataset`.
- Make publish self-sufficient: create the release if missing. `gh` resolves tags directly (no race);
  piggyback's `pb_upload` resolves via the **separately memoised `pb_info`** *and* GitHub's
  list-releases endpoint lags create by up to ~70s — so the R path must bust both caches and
  **poll until the tag is visible** before uploading (pay the wait once on the first asset).

## 3. Model tracks (CFB Modeling Suite)

T1 EP/WP/QBR (shipped), T2 4th-down, T3 RB-eval (xREPA GAM — trained full-history 2026-06-17,
weighted R² 0.70), T4 pregame-WP (CFBD-gated), T5 CPOE (StatsBomb re-base infeasible; 8-feat
game-state already shipped), **T6 NFL EP/WP — built in nfl-raw, the subject of this migration.**

## 4. NFL target state (what differs from CFB)

`nfl-raw` today mirrors cfb-raw's *pre-migration* state — scraping + modeling + dataset-building
all in one repo:

| nfl-raw today | CFB analog | Migrates to nfl-data? |
|---|---|---|
| `python/nfl_raw_01_scrape.py`, `nfl_raw_02_extract.py` | cfb-raw scrapers | **No — stays in nfl-raw** |
| `nfl/raw/` (3.1 GB committed JSON) | cfb-raw `cfb/json/` | **No — stays in nfl-raw** |
| `python/model_training/track6_nfl_ep_wp/` (EP/WP/CP trainer + reporting suite + model cards) | `model_training` | **Yes → nfl-data** |
| `python/native_pbp/` (build/features/labels/parity/parse — compiled PBP w/ nflfastR parity) | `cfb_model_pbp` | **Yes → nfl-data** |
| `models/` (trained `.ubj`) | published artifacts | **Yes (publish from nfl-data)** |

Key differences from the CFB migration:
1. **nfl-data must be stood up** — the dir exists but is **not a git repo** (CFB's data repo already
   existed). Need: repo home decision (GitHub org/name), `git init` + remote, project scaffold.
2. **NFL modeling is real and substantially built** (Track 6), not greenfield — so SP1 is a genuine
   move of working code, and SP2 reporting largely exists already (the track has a report CLI + cards).
3. **nflfastR parity** is a first-class gate (`native_pbp/parity.py`) — the NFL dataset's correctness
   bar is "matches nflverse," analogous to but stricter than CFB.
4. **sdv-py handoff fixes a known bug:** the trained NFL EP/WP/WP-naive `.ubj` replace sdv-py's
   *placeholder CFB-shape* models (`nfl/models/*.ubj` are currently 8/13-feat CFB copies; real NFL is
   18 EP / 12 WP-spread / 11 WP-naive). See `nfl-raw/HANDOFF.md`.
5. **Publish target + tags** — decide: `sportsdataverse-data` (sdv convention) vs `nflverse-data`
   (NFL ecosystem convention). The native_pbp parity to nflfastR suggests an nflverse audience.

## 5. NFL migration shape (proposed, mirrors CFB)

- **SP0 — stand up nfl-data**: repo home + `git init`/remote + uv scaffold + hermetic test marker.
- **SP1 — lift-and-shift**: move `track6_nfl_ep_wp` + `native_pbp` → nfl-data; add URL-ingest from
  nfl-raw's committed `nfl/raw/{season}/{game_id}.json`; build the compiled PBP dataset.
- **SP2 — reports + publish**: wire the existing track-6 report CLI + a dataset-publish path to the
  chosen release repo/tags.
- **SP3 — decommission**: `git rm` modeling/native_pbp from nfl-raw; drop modeling-only deps;
  scraping-only boundary gate.
- **SP4 (parallel/after) — sdv-py handoff**: replace placeholder NFL models + wire `wp_naive`,
  behind the parity gate in HANDOFF.md.
