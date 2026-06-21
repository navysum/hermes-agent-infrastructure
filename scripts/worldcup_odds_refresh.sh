#!/usr/bin/env bash
set -euo pipefail

REPO="/root/worldcup-prediction-bot"
LOCK="/tmp/worldcup_odds_refresh.lock"
LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

exec 9>"$LOCK"
if ! flock -n 9; then
  exit 0
fi

cd "$REPO"

run() {
  printf '\n## %s\n' "$*" >>"$LOG"
  "$@" >>"$LOG" 2>&1
}

if ! {
  run .venv/bin/python -m app.cli ingest-live-odds --provider odds-api-io --limit 16 --league international-fifa-world-cup --bookmakers Bet365,Unibet
  run .venv/bin/python -m app.cli generate-snapshots --limit 16 --max-age-hours 24
  run .venv/bin/python -m app.cli health-gate --required
}; then
  echo "D'oh — World Cup odds refresh failed."
  tail -120 "$LOG"
  exit 1
fi

# Silent success: cron no_agent jobs only notify the operator on non-empty stdout.
exit 0
