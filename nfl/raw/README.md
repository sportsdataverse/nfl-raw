# nfl/raw — committed per-game NFL JSON library

One JSON file per game, fetched from `api.nfl.com`'s
`football/v2/experience/weekly-game-details` endpoint (the modern "Shield" API)
and split out of the weekly payloads.

## Layout

```
nfl/raw/{season}/{game_id}.json
```

`game_id` is the **nflverse** identifier `{season}_{week:02d}_{away}_{home}`,
e.g. `2025_01_DAL_PHI.json`. Each file is a single Shield game object carrying
schedule metadata plus (for 1999+) the full `summary` and `driveChart`
play-by-play detail.

### Week numbering

Regular-season games keep their week number. Postseason weeks continue past the
regular season, matching nflverse:

| Round | 1999–2020 (17 REG wks) | 2021+ (18 REG wks) |
|---|---|---|
| Wild Card | 18 | 19 |
| Divisional | 19 | 20 |
| Conference | 20 | 21 |
| Super Bowl | 21 | 22 |

### Team abbreviations

Abbreviations come from each club's `currentLogo` URL and are normalized to
nflverse: `AZ` → `ARI`, and season-aware relocation fixups so historical ids
match nflverse exactly:

| Franchise | Old abbr (through) | Modern abbr (from) |
|---|---|---|
| Rams | `STL` (2015) | `LA` (2016) |
| Chargers | `SD` (2016) | `LAC` (2017) |
| Raiders | `OAK` (2019) | `LV` (2020) |

## Data availability

| Floor | Coverage |
|---|---|
| **1999** | full play-by-play detail (`summary` + `driveChart`) — the default scrape start |
| **1920** | schedule/game shells only (teams, dates, scores; no per-play detail) |

1997 has spotty detail; 1998 and earlier are shells only.

## (Re)building this library

The fetch cache lives in the gitignored `data/raw/`; this committed library is
derived from it. Both stages are driven by `python/scrape_nfl_json.py`
(fetch + extract) and `python/extract_nfl_games.py` (extract only). Run from the
repo root with the project venv:

```sh
# Default: 1999 -> current season, REG + POST, 2s throttle, extract on
.venv/Scripts/python.exe python/scrape_nfl_json.py

# A single season
.venv/Scripts/python.exe python/scrape_nfl_json.py -s 2024 -e 2024

# Whole detail era, newest first (backfill)
.venv/Scripts/python.exe python/scrape_nfl_json.py -s 1999 -e 2025 --reverse

# Re-extract per-game files from the cache after a game_id / relocation change
.venv/Scripts/python.exe python/extract_nfl_games.py -s 1999 -e 2025
```

The reusable functions (`build_raw_library`, `extract_library_to_games`,
`nflverse_game_id`, the `NFL_JSON_DETAIL_START` / `NFL_JSON_SCHEDULE_START`
floors) live in
`python/model_training/track6_nfl_ep_wp/fetcher.py`.
