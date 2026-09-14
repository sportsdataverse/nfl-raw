# CLAUDE.md — nfl-raw

`nfl-raw-pipeline`: scrapes NFL Shield-API (`api.nfl.com`) weekly game-detail JSON
into a committed per-game raw library under `nfl/raw/`. Pure scraper. Its sibling
**`nfl-data`** owns all modeling/reshaping/publishing (modeling was removed from
this repo in the SP3 decommission — `xgboost`/`numpy`/`plotnine` are gone).
Depends on **sportsdataverse** (`sdv-py`, the `.nfl` submodule) for the
authenticated Shield wrappers. uv-packaged.

## Commands

```sh
uv sync                                    # creates .venv, installs deps + dev group
uv run pytest                              # tests/test_fetcher.py (monkeypatched, offline)

# Scrape + extract + commit one season (network). Scripts live under python/.
.venv/Scripts/python.exe python/nfl_raw_01_scrape.py -s 2024 -e 2024 --commit

# Default run: 1999 -> current season, REG+POST, 2s throttle, extract on
.venv/Scripts/python.exe python/nfl_raw_01_scrape.py
.venv/Scripts/python.exe python/nfl_raw_01_scrape.py -s 1999 -e 2025 --reverse --skip-existing
.venv/Scripts/python.exe python/nfl_raw_01_scrape.py -s 1920 -e 1998 --no-extract   # schedule shells only

# Re-extract per-game files from the cached weekly library WITHOUT re-hitting the network
# (e.g. after changing game_id / relocation logic):
.venv/Scripts/python.exe python/nfl_raw_02_extract.py -s 2024 -e 2024
```

There is **no `[project.scripts]` console entry**, no Makefile, and **no
`.github/` workflows** — run the scripts by path. `requires-python >=3.9`.

## Conventions

- **Commit raw per-game JSON directly to git** — this is the intentional SDV
  `-raw` pattern. Do NOT warn about repo size or propose a cloud store.
- Per-season commit message is `NFL Raw: {season} ({n_games} games)` (via
  `--commit`). Nothing keys off this format — `nfl-data` is not auto-triggered
  from here.
- Conventional Commits for code changes (`feat(native_pbp):`, `fix:`, `refactor:`).
- **Never add AI co-author trailers** (`Co-Authored-By`, Claude/Copilot/etc.) to
  commits or PRs.
- Pin **`sportsdataverse>=0.0.59`** — the floor that ships the NFL Shield API
  wrappers (`nfl_games.nfl_headers_gen`, `nfl_api`, `utils_date`). Don't add
  sdv-py as a `[tool.uv.sources]` path source — it'd break clean PyPI installs;
  for local co-dev run `uv pip install -e ../../sdv-py` after `uv sync`.

## Inputs / Outputs

- Source: `api.nfl.com/football/v2/experience/weekly-game-details`, fetched with
  an anonymous `WEB_DESKTOP` token re-minted per season (long backfills ride the
  token's auto-renewal — a once-minted dict would freeze an expiring token).
- `data/raw/{season}/{REG,POST}/wk{NN}.json` — weekly cache, **gitignored**
  (`data/` is in `.gitignore`).
- `nfl/raw/{season}/{game_id}.json` — committed per-game library. `game_id` is the
  nflverse id `{season}_{week:02d}_{away}_{home}` (POST week offset auto-detected).

## Gotchas

- **Season floors:** play-by-play detail (`summary`/`driveChart`) reliable from
  **1999** (default `-s`); schedule shells (no detail) reach back to **1920**.
  1998-and-earlier and 1997 are shells/spotty — use `--no-extract` for those.
- **Arizona abbr fixup:** the Shield API renders Arizona as `AZ`; nflverse spells
  it `ARI`. Relocated franchises also need season-aware abbr fixups to match
  historical nflverse game_ids (`_nflverse_abbr_fixups` in `nfl_raw_scrape/raw_fetcher.py`).
- **Throttle is `--delay` SECONDS (default 2.0), not a workers env var** — the pull
  is sequential. `--no-resume` re-fetches cached weeks; `resume=True` (default)
  skips on-disk files and doesn't sleep on skips. `--skip-existing` skips a whole
  season that already has per-game output (resume a backfill).
- `--commit` requires extraction (errors with `--no-extract`).

## Reference

- Scripts: `python/nfl_raw_01_scrape.py` (fetch+extract+commit CLI),
  `python/nfl_raw_02_extract.py` (re-extract from cache), `python/nfl_raw_scrape/raw_fetcher.py`
  (`build_raw_library` / `extract_library_to_games` / `nflverse_game_id`).
- `HANDOFF.md`, `docs/raw-to-data-migration-playbook.md` (SP3 split context),
  `dev/nflfastr-port-map.md` (gitignored notes).

## ESPN game library (`nfl/espn/`)

A second feed alongside the Shield library: ESPN's per-event game summary and
core play participants, the inputs `sportsdataverse.nfl.NFLPlayProcess` (and so
Game on Paper and the `espn_nfl_*` processed-game releases) read.

```sh
# one season, both feeds, commit
.venv/bin/python python/nfl_espn_01_summary_scrape.py -s 2025 -e 2025 --commit
# the ESPN play-by-play era (2002 ->), newest first, resumable, one commit per season
bash scripts/espn_nfl_backfill.sh -s 2002            # tail -f logs/espn_nfl_backfill_$(date -u +%Y%m%d).log
# rebuild the crosswalk from the two libraries
.venv/bin/python python/nfl_espn_02_crosswalk.py --commit
```

- `nfl/espn/raw/{season}/{event_id}.json.gz` -- the summary
  (`site.api.espn.com/.../summary?event=`) with the media keys
  (`videos` / `news` / `article`) dropped; everything else verbatim.
- `nfl/espn/plays/{season}/{event_id}.json.gz` -- `{"items": [...]}` of the
  core plays slimmed to `id` / `sequenceNumber` / `participants[]`
  (athlete + position `$ref`, `type`, `order`).
- `nfl/espn/crosswalk/games.json` / `teams.json` -- ESPN event id <->
  nflverse `game_id` / Shield game uuid, and ESPN team id <-> Shield team uuid /
  nflverse code with the seasons each pairing held. Matched on (season,
  kickoff UTC, home team name), then on kickoff date; the Pro Bowl stays
  unmatched. JSON because the repo ignores csv/parquet.
- Read with `python.nfl_espn_scrape.espn_fetcher.read_json`. Gzipped so the
  25-season capture stays near 0.6 GB.
- **Routine runs:** `scripts/daily_nfl_scraper.sh` (cron / the
  `scrape_nfl_raw.yml` workflow, Aug-Feb) captures BOTH feeds for the current
  season with the same `-t "PRE REG POST"` (ESPN types 1 2 3), so playoffs and
  the Super Bowl land in January/February runs. A captured game is skipped
  only once its summary is final; a stored game that has kicked off but is
  not final is re-captured (summary + plays) every run
  (`espn_fetcher.needs_refresh`). `ESPN_WORKERS` (default 3) paces the step.
- Per-season commit message is `NFL ESPN Raw: {season} ({n_games} games)`;
  nothing keys off it. Pace is env-tunable: `ESPN_RATE_SLEEP` (default 0.25 s
  per request per worker), `ESPN_RATE_RETRIES` (3); keep `--workers` at 3 or
  below (ESPN 403s aggressive rates).
- Season floor 2002 (`ESPN_NFL_DETAIL_START`): ESPN NFL play-by-play is
  reliable from the realignment on.
