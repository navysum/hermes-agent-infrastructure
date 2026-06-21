#!/usr/bin/env python3
"""Quiet FX paper-readiness watcher.

Prints only when paper evidence crosses a milestone or reaches 100.
Silence means no user-facing update needed.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path("/root/fx-signal-bot/state/live_execution.sqlite3")
STATE = Path("/root/.hermes/state/fx_paper_readiness_watch.json")
TARGET = 100
MILESTONE_STEP = 10


def load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")


def main() -> int:
    if not DB.exists():
        print(f"D'oh: FX paper-readiness ledger missing: {DB}")
        return 0

    con = sqlite3.connect(DB)
    try:
        count = int(con.execute("SELECT COUNT(*) FROM trade_intents WHERE mode='paper'").fetchone()[0])
        latest = con.execute(
            """
            SELECT id, created_at_utc, instrument, side, units, status, signal_score
            FROM trade_intents
            WHERE mode='paper'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        con.close()

    remaining = max(0, TARGET - count)
    state = load_state()
    last_reported = int(state.get("last_reported_count", 0) or 0)

    should_report = False
    if count >= TARGET and last_reported < TARGET:
        should_report = True
    elif count > last_reported and count % MILESTONE_STEP == 0:
        should_report = True

    if not should_report:
        return 0

    state["last_reported_count"] = count
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_state(state)

    lines = [
        f"FX paper-readiness progress — {count}/{TARGET} paper trades",
        f"Remaining: {remaining}",
    ]
    if latest:
        trade_id, created, instrument, side, units, status, score = latest
        lines.append(f"Latest: #{trade_id} {created} {instrument} {side} units={units} status={status} score={score}")
    if count >= TARGET:
        lines.append("Woo-hoo: paper evidence count target reached. Next step: run readiness validation/certificate checks before any live mode.")
    else:
        lines.append("Still paper-only. No live OANDA trade permission granted.")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
