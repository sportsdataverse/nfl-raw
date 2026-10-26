#!/usr/bin/env bash
# Droplet step after /mnt/sdv_repos/bin/alt_daily.sh parses a season into nfl-alt-data:
# rebuild nfl/espn/crosswalk/players_{cbs,fox,yahoo}.json for the seasons given
# (python/nfl_espn_03_alt_players.py, offline; it refuses to shrink a season), then
# commit + push only what changed.
#
#   bash scripts/cron_alt_fill.sh -s YYYY [-e YYYY] [-n]    # -n = build, compare, restore the files; no lock, no commit
#
# Runs on the sdv-py main checkout's venv: this repo's lock pins an sdv-py without
# sportsdataverse._crosswalk_alt. A provider without a parsed season is skipped by the builder.
set -uo pipefail
cd "$(dirname "$0")/.."
echo "=== cron_alt_fill $(date -u +%FT%TZ)"
START="" END="" DRY=0
SDV_PY=${XWALK_SDV_PY:-/mnt/sdv_repos/sdv-py}
while getopts s:e:n flag; do
  case "$flag" in s) START=$OPTARG;; e) END=$OPTARG;; n) DRY=1;; *) echo "usage: $0 -s YYYY [-e YYYY] [-n]" >&2; exit 2;; esac
done
[ -n "$START" ] || { echo "usage: $0 -s YYYY [-e YYYY] [-n]" >&2; exit 2; }
END=${END:-$START}
fail() { echo "::error ::$*"; echo "EXIT=1"; exit 1; }

XW=nfl/espn/crosswalk
if [ "$DRY" = 1 ]; then   # keep the current files aside and put them back after the build
  keep=$(mktemp -d); cp -p "$XW"/players_*.json "$keep"/ 2>/dev/null
else
  # The git_pull sweep would autostash our outputs; 9>&- keeps git helpers off the lock.
  exec 9>/tmp/git_pull_sdv.lock
  flock -w 3600 9 || fail "git_pull sweep held its lock for 1h"
  branch=$(git rev-parse --abbrev-ref HEAD)
  if [ "$branch" != main ] || [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    git status --short --untracked-files=no | head -20
    fail "checkout is on '$branch' or has tracked changes; refusing to fill"
  fi
  git pull -q --rebase --autostash origin main 9>&- || fail "git pull failed"
fi

paths=()
for provider in cbs fox yahoo; do
  PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONPATH="$SDV_PY:$PWD" "$SDV_PY/.venv/bin/python" \
    python/nfl_espn_03_alt_players.py --provider "$provider" -s "$START" -e "$END" 9>&- \
    || fail "$provider players $START-$END failed"
  f=$XW/players_$provider.json
  [ -f "$f" ] || continue
  if [ "$DRY" = 1 ]; then
    cmp -s "$f" "$keep/${f##*/}" && echo "$provider: unchanged" || echo "$provider: WOULD CHANGE"
    continue
  fi
  { ! git diff --quiet -- "$f" || [ -z "$(git ls-files -- "$f")" ]; } && paths+=("$f")
done
if [ "$DRY" = 1 ]; then
  rm -f "$XW"/players_*.json; cp -p "$keep"/players_*.json "$XW"/ 2>/dev/null; rm -rf "$keep"
  echo "dry run: files restored, no commit"; echo "EXIT=0"; exit 0
fi
[ ${#paths[@]} -gt 0 ] || { echo "players crosswalks unchanged"; echo "EXIT=0"; exit 0; }
git diff --stat -- "${paths[@]}"

git add -- "${paths[@]}"
git commit -q -m "NFL ESPN crosswalk: alt players (Start: $START End: $END)" 9>&- || fail "commit failed"
for attempt in 1 2 3; do
  git push -q origin HEAD:main 9>&- && { echo "pushed NFL alt players $START-$END"; echo "EXIT=0"; exit 0; }
  git pull -q --rebase --autostash origin main 9>&- || fail "cannot rebase onto origin/main"
done
fail "push rejected 3 times"
