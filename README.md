# nfl-raw

Committed per-game raw library of NFL Shield-API (`api.nfl.com`) game-detail
JSON, 1999–2026 (28 seasons, 7,277 games).

This repo is a **pure scraper**. Its sibling [`nfl-data`](https://github.com/sportsdataverse/nfl-data)
owns all reshaping, modeling and publishing — modeling was removed here in the
SP3 decommission.

```mermaid
  graph LR;
    A[api.nfl.com Shield]-->B[nfl-raw];
    B-->C[nfl-data];
    C-->D1[nfl_model_pbp];
    C-->D2[nfl_model_artifacts];
    C-->D3[nfl_4th_down_models];
```

## nflverse workflow diagram

```mermaid
flowchart TB;
    subgraph A[nfl-raw];
        direction TB;
        A1[scrape_nfl_json.py driver]-->A2[raw_fetcher.build_raw_library];
        A2-->A3[weekly cache season/TYPE/wkNN.json];
        A3-->A4[raw_fetcher.extract_library_to_games];
        A4-->A5[nfl/raw/season/nflverse_game_id.json];
        A6[extract_nfl_games.py offline re-extract]-.->A4;
    end;

    subgraph B[nfl-data];
        direction TB;
        B1[nfl_data_ingest]-->B2[native_pbp];
        B2-->B3[model_training];
        B3-->B4[nfl_model_publish];
    end;

    subgraph C[sportsdataverse Releases];
        direction TB;
        C1[nfl_model_pbp];
        C2[nfl_model_artifacts];
        C3[nfl_4th_down_models];
    end;

    A-->B;
    B-->C1;
    B-->C2;
    B-->C3;
```

## Layout

| path | contents |
|---|---|
| `nfl/raw/{season}/{nflverse_game_id}.json` | one Shield game-detail payload per game (the committed library) |
| `python/scrape_nfl_json.py` | the scrape driver — fetches the weekly cache, then explodes it per game |
| `python/raw_fetcher.py` | `build_raw_library` (weekly fetch) + `extract_library_to_games` (per-game write) + `nflverse_game_id` |
| `python/extract_nfl_games.py` | **offline** re-extract: rebuilds the per-game library from an already-cached weekly library, no network |

**Two stages, not one.** `build_raw_library` writes a weekly cache at
`{season}/{REG,POST}/wk{NN}.json`; `extract_library_to_games` then explodes that
into the committed per-game files. `extract_nfl_games.py` re-runs only the second
stage, which is what you want after changing game-id or relocation logic.

Filenames are **nflverse `game_id`s** — `{season}_{week:02d}_{away}_{home}`, e.g.
`1999_01_ARI_PHI.json` — produced by `raw_fetcher.nflverse_game_id()`. Two details
a consumer must not re-derive naively: postseason weeks continue past the regular
season (19-22 for 2021+, 18-21 for 1999-2020), and team abbreviations carry
season-aware relocation fixups (`LA` -> `STL` for the pre-2016 Rams). Resolve ids
from the schedule or that helper rather than formatting them by hand.

## How consumers should read this repo

**Fetch individual game JSON over HTTP. Do not clone or check this repo out on
CI.** It is 229 MB today and grows every week; a runner that clones it is a
timeout waiting to happen.

```text
https://raw.githubusercontent.com/sportsdataverse/nfl-raw/main/nfl/raw/{season}/{nflverse_game_id}.json
```

Use a read-through cache keyed by filename so re-runs refetch nothing, validate
cached JSON before trusting it (a half-written entry from an interrupted run is
otherwise indistinguishable from a good one), and fail soft per game so one
missing file never aborts a season.
`cfbfastR-cfb-data`'s `cfb_data_ingest/fetch.py::fetch_final` is the reference
implementation of that shape.

## Setup

```sh
uv sync                # creates .venv, installs deps + dev group
uv run pytest          # tests/test_fetcher.py — monkeypatched, offline
```

Depends on [`sportsdataverse`](https://github.com/sportsdataverse/sportsdataverse-py)
(`sdv-py`, the `.nfl` submodule) for the authenticated Shield wrappers.

## Automation & status

| workflow | schedule | purpose |
|---|---|---|
| [`tests.yml`](.github/workflows/tests.yml) | on push / PR | offline unit tests |

Scrapes currently run **manually / locally**, not on a schedule in this repo —
there is no cron workflow here. `nfl-data` drives its own build cadence.

This repo publishes **no releases of its own** — the raw library is the committed
tree. Downstream release tags, produced by `nfl-data` on `sportsdataverse-data`:

| release tag | assets | last published |
|---|---:|---|
| [`nfl_model_pbp`](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/nfl_model_pbp) | 27 | 2026-06-18 |
| [`nfl_model_artifacts`](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/nfl_model_artifacts) | 11 | 2026-06-17 |
| [`nfl_4th_down_models`](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/nfl_4th_down_models) | 2 | 2026-06-23 |

Counts as of 2026-08-28. This table is live data and should be generated between
markers once the shared README renderer exists — hand-maintained, it goes stale
silently.

## Related repositories

- [nfl-data](https://github.com/sportsdataverse/nfl-data) — reshaping, modeling, publishing (source: this repo)
- [nflfastR](https://github.com/nflverse/nflfastR) — the R lineage this pipeline parallels
- [sportsdataverse-py](https://github.com/sportsdataverse/sportsdataverse-py) — the `nfl` submodule and Shield wrappers

Part of the [SportsDataverse](https://sportsdataverse.org/).
