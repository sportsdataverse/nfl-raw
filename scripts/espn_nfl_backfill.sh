#!/usr/bin/env bash
# Capture ESPN NFL game summaries + participants into nfl/espn/ and rebuild the
# crosswalk. Resumable (existing events are skipped), one commit per season.
#
# Usage:  bash scripts/espn_nfl_backfill.sh [-s YYYY] [-e YYYY] [-w WORKERS]
# Watch:  tail -f logs/espn_nfl_backfill_$(date -u +%Y%m%d).log
# Pace:   ESPN_RATE_SLEEP (s per request per worker, default 0.25), ESPN_RATE_RETRIES (3)
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
START_YEAR=2002; END_YEAR=""; WORKERS=3
while getopts s:e:w: flag; do
  case "${flag}" in
    s) START_YEAR=${OPTARG};;
    e) END_YEAR=${OPTARG};;
    w) WORKERS=${OPTARG};;
    *) echo "usage: $0 [-s YYYY] [-e YYYY] [-w WORKERS]" >&2; exit 2;;
  esac
done
mkdir -p logs
LOG="logs/espn_nfl_backfill_$(date -u +%Y%m%d).log"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="$REPO/.venv/Scripts/python.exe"
export PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
{
  echo "[$(date -u '+%F %T')Z] espn nfl backfill start: ${START_YEAR}-${END_YEAR:-current} workers=${WORKERS}"
  "$PY" python/nfl_espn_01_summary_scrape.py -s "$START_YEAR" ${END_YEAR:+-e "$END_YEAR"} --reverse --workers "$WORKERS" --commit
  echo "SCRAPE_EXIT=$?"
  "$PY" python/nfl_espn_02_crosswalk.py --commit
  echo "CROSSWALK_EXIT=$?"
  echo "[$(date -u '+%F %T')Z] espn nfl backfill done"
} >> "$LOG" 2>&1
echo "EXIT=$?"
