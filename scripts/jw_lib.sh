#!/bin/bash
# jw_lib.sh — Hermes job wrapper helper.
# run_dedup "<Job Name>" <script> [args...]
#   Runs the script (py via trading-venv, else bash), and echoes its output to
#   stdout ONLY when the output changed vs last run (digit-stripped md5), so a
#   persistent condition alerts once instead of every tick. Empty/unchanged =>
#   silent stdout => Hermes delivers nothing. Mirrors the old run_job.sh logic.
run_dedup() {
  local NAME="$1"; local SCRIPT="$2"; shift 2
  local OUT RC
  case "$SCRIPT" in
    *.py) OUT=$("/usr/local/lib/trading-venv/bin/python" "$SCRIPT" "$@" 2>&1); RC=$? ;;
    *)    OUT=$(bash "$SCRIPT" "$@" 2>&1); RC=$? ;;
  esac
  local SD=/root/.hermes/cron/jobstate
  local HF="$SD/$(echo "$NAME" | tr -c 'A-Za-z0-9' '_').hash"
  local NEW OLD
  NEW=$(echo "$OUT" | tr -d '0-9' | md5sum | cut -d' ' -f1)
  OLD=$(cat "$HF" 2>/dev/null)
  if [ -n "$OUT" ] && [ "$NEW" != "$OLD" ]; then
    echo "📋 $NAME"
    echo "$OUT" | head -c 3800
  fi
  echo "$NEW" > "$HF"
  return $RC
}
