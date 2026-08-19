#!/usr/bin/env bash
# Scrape the current NFL season's raw Shield-API game JSON and commit it.
#
# The sibling -raw repos (cfbfastR-cfb-raw, hoopR-*-raw, wehoop-*-raw) all have
# a driver like this; nfl-raw had only the bare python entry point, no driver,
# no schedule, and no automation of any kind -- which is why nfl/raw/ stopped at
# season 2025 while 2026 was already in preseason.
#
# Usage: bash scripts/daily_nfl_scraper.sh [-s YYYY] [-e YYYY] [-t "PRE REG POST"]
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

# NFL seasons are labelled by the calendar year they START in, and run into
# February. So Jan/Feb still belong to the previous season -- rolling over on
# 1 January would scrape an empty new season while the playoffs were live.
default_season() {
  local m y
  m=$(date -u +%m); y=$(date -u +%Y)
  if [ "$((10#$m))" -ge 3 ]; then echo "$y"; else echo "$((y - 1))"; fi
}

START_YEAR=""; END_YEAR=""; SEASON_TYPES="PRE REG POST"
while getopts s:e:t: flag; do
  case "${flag}" in
    s) START_YEAR=${OPTARG};;
    e) END_YEAR=${OPTARG};;
    t) SEASON_TYPES=${OPTARG};;
    *) echo "usage: $0 [-s YYYY] [-e YYYY] [-t \"PRE REG POST\"]" >&2; exit 2;;
  esac
done
START_YEAR=${START_YEAR:-$(default_season)}
END_YEAR=${END_YEAR:-$START_YEAR}

mkdir -p logs
LOG="logs/daily_nfl_$(date -u +%Y%m%d).log"

{
  echo "[$(date -u '+%F %T')Z] nfl raw scrape start: seasons ${START_YEAR}-${END_YEAR} types='${SEASON_TYPES}'"

  # Resolve the interpreter INSIDE the logging block: a resolver FATAL above it
  # would leave an empty logs/ that reads as "the job never ran".
  # shellcheck source=scripts/_venv.sh
  . "$REPO/scripts/_venv.sh"
  PY="$SDV_PY"
  echo "[$(date -u '+%F %T')Z] interpreter: $PY"
  sdv_preflight sportsdataverse.nfl

  git config --local user.email "action@github.com"
  git config --local user.name "Github Action"

  # Sync before scraping, not at push time -- a moved-ahead remote should cost
  # zero Shield requests. `rebase --merge`, never `pull --rebase`: the default am
  # backend base64-encodes every blob it replays, which crawls on a raw repo.
  git fetch --quiet origin main || echo "WARN: fetch failed; push may be rejected"
  if [ -n "$(git status --porcelain)" ]; then
    echo "[$(date -u '+%F %T')Z] WARN: working tree dirty; skipped sync with origin"
  elif ! git rebase --merge origin/main; then
    git rebase --abort 2>/dev/null
    echo "[$(date -u '+%F %T')Z] rebase onto origin/main failed; not scraping"
    exit 1
  fi

  # --no-resume is REQUIRED for a daily current-season run: without it the
  # weekly cache file for an in-progress week is reused verbatim, so results
  # that landed since the last run are never picked up. --skip-existing is
  # deliberately NOT passed either -- it skips a whole season once its output
  # dir is non-empty, which is exactly the current season every day after the
  # first. Both are the right flags for a backfill and wrong for a refresh.
  # shellcheck disable=SC2086
  "$PY" python/scrape_nfl_json.py \
      -s "$START_YEAR" -e "$END_YEAR" \
      --season-types $SEASON_TYPES \
      --no-resume --commit
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "[$(date -u '+%F %T')Z] scrape FAILED (rc=$rc)"
    exit "$rc"
  fi

  git push origin main
  push_rc=$?
  echo "[$(date -u '+%F %T')Z] nfl raw scrape done (scrape=$rc push=$push_rc)"
  exit "$push_rc"
} 2>&1 | tee -a "$LOG"
RC="${PIPESTATUS[0]}"

# The block has closed, so tee has flushed $LOG -- only now is it complete
# enough to commit. Run logs are tracked here (same as the cfb/hoopR/wehoop raw
# repos): the log IS the record of what a scheduled run did, and the whole point
# is that it survives somewhere readable rather than only on the box.
git add -- "$LOG"
if ! git diff --cached --quiet -- "$LOG"; then
  git commit -q -m "NFL Raw log update ($(date -u +%F))"
  git push -q origin main || echo "WARN: log push failed"
fi
exit "$RC"
