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
.venv/Scripts/python.exe python/scrape_nfl_json.py -s 2024 -e 2024 --commit

# Default run: 1999 -> current season, REG+POST, 2s throttle, extract on
.venv/Scripts/python.exe python/scrape_nfl_json.py
.venv/Scripts/python.exe python/scrape_nfl_json.py -s 1999 -e 2025 --reverse --skip-existing
.venv/Scripts/python.exe python/scrape_nfl_json.py -s 1920 -e 1998 --no-extract   # schedule shells only

# Re-extract per-game files from the cached weekly library WITHOUT re-hitting the network
# (e.g. after changing game_id / relocation logic):
.venv/Scripts/python.exe python/extract_nfl_games.py -s 2024 -e 2024
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
  historical nflverse game_ids (`_nflverse_abbr_fixups` in `raw_fetcher.py`).
- **Throttle is `--delay` SECONDS (default 2.0), not a workers env var** — the pull
  is sequential. `--no-resume` re-fetches cached weeks; `resume=True` (default)
  skips on-disk files and doesn't sleep on skips. `--skip-existing` skips a whole
  season that already has per-game output (resume a backfill).
- `--commit` requires extraction (errors with `--no-extract`).

## Reference

- Scripts: `python/scrape_nfl_json.py` (fetch+extract+commit CLI),
  `python/extract_nfl_games.py` (re-extract from cache), `python/raw_fetcher.py`
  (`build_raw_library` / `extract_library_to_games` / `nflverse_game_id`).
- `HANDOFF.md`, `docs/raw-to-data-migration-playbook.md` (SP3 split context),
  `dev/nflfastr-port-map.md` (gitignored notes).
