#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys

CMD = [
    sys.executable,
    "/root/fx-signal-bot/scripts/agentic_paper_profile.py",
    "--instrument",
    "USD_JPY",
    "--granularity",
    "H1",
    "--count",
    "250",
    "--allow-live-data",
    "--db",
    "/root/fx-signal-bot/state/strategy_agentic_paper.sqlite3",
    "--profile",
    "strategy-agentic-paper",
    "--starting-equity",
    "1000",
    "--min-confidence",
    "0.65",
    "--risk-fraction",
    "0.003",
]

proc = subprocess.run(CMD, cwd="/root/fx-signal-bot", capture_output=True, text=True, timeout=120)
if proc.returncode != 0:
    print("D'oh. Strategy paper profile run failed.")
    print(proc.stderr.strip() or proc.stdout.strip())
    raise SystemExit(proc.returncode)

try:
    result = json.loads(proc.stdout)
except json.JSONDecodeError:
    print("D'oh. Strategy paper profile returned non-JSON output.")
    print(proc.stdout.strip())
    raise SystemExit(1)

status = result.get("status")
summary = result.get("summary", {})
closed = int(result.get("closed_positions") or 0)

if status == "PAPER_POSITION_OPENED" or closed > 0:
    lines = [
        "Woo-hoo — Strategy paper profile updated.",
        f"Status: {status}",
        f"Closed positions this run: {closed}",
        f"Equity: {summary.get('equity')}",
        f"Realised P&L: {summary.get('realized_pnl')}",
        f"Unrealised P&L: {summary.get('unrealized_pnl')}",
        f"Open positions: {summary.get('open_positions')}",
        "Mode: isolated paper ledger only — no broker order path.",
    ]
    print("\n".join(lines))
