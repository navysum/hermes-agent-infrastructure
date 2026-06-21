#!/usr/bin/env python3
"""Quiet Strategy analyst cron wrapper.
Runs the agentic analyst in paper mode and prints only when a proposal is submitted.
Silence means no trade proposal. No live execution.
"""
from __future__ import annotations

import json
import subprocess
import sys

CMD = [
    sys.executable,
    "/root/fx-signal-bot/scripts/agentic_analyst_job.py",
    "--instrument",
    "USD_JPY",
    "--mode",
    "paper",
    "--allow-live-data",
    "--output",
    "/root/fx-signal-bot/state/latest_agentic_proposal.json",
    "--ledger",
    "/root/fx-signal-bot/state/agentic_discretionary.sqlite3",
]

proc = subprocess.run(CMD, cwd="/root/fx-signal-bot", capture_output=True, text=True, timeout=180)
if proc.returncode != 0:
    print("D'oh: Strategy analyst job failed")
    print(proc.stderr[-1000:] or proc.stdout[-1000:])
    raise SystemExit(proc.returncode)

try:
    result = json.loads(proc.stdout)
except json.JSONDecodeError:
    print("D'oh: Strategy analyst returned non-JSON output")
    print(proc.stdout[-1000:])
    raise SystemExit(1)

if result.get("status") == "PROPOSAL_SUBMITTED":
    proposal = result.get("proposal", {})
    exec_result = result.get("executor_result", {})
    decision = exec_result.get("decision", {})
    print("Strategy analyst proposal — paper mode only")
    print(f"- Instrument: {proposal.get('instrument')}")
    print(f"- Side: {proposal.get('side')}")
    print(f"- Entry: {proposal.get('entry_price')}")
    print(f"- Stop: {proposal.get('stop_loss')}")
    print(f"- Take profit: {proposal.get('take_profit')}")
    print(f"- Confidence: {proposal.get('confidence')}")
    print(f"- Risk fraction: {proposal.get('risk_fraction')}")
    print(f"- Gate decision: {decision.get('action')} — {decision.get('reason')}")
    print(f"- Proposal file: {result.get('proposal_path')}")
    print("No live order was placed. Patty and Selma are still blocking the live door.")
