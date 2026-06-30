#!/usr/bin/env python3
"""Read-only Bot Control Centre for a personal trading/automation VPS.

This is a sanitized, single-file version of the live Sector 7-G control panel.
It inspects an inventory of bots/services, evaluates global risk, exposes a tiny
local dashboard, and provides a pre-trade guard that trading bots can import or
call before opening new exposure.

Security model:
- no credentials are stored here;
- all paths are configurable by environment variables;
- generated reports/state live outside git by default;
- the guard blocks new live exposure on BLOCK conditions but should not be used
  to prevent exits/closures that reduce risk.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

ROOT = Path(os.environ.get("BOT_CONTROL_CENTRE_ROOT", "/root/working-on/bot-control-centre"))
INVENTORY_PATH = Path(os.environ.get("BOT_CONTROL_INVENTORY", ROOT / "inventory.json"))
POLICY_PATH = Path(os.environ.get("GLOBAL_RISK_POLICY", ROOT / "config/global_risk_policy.json"))
STATE_DIR = Path(os.environ.get("BOT_CONTROL_STATE_DIR", ROOT / "state"))
REPORTS_DIR = Path(os.environ.get("BOT_CONTROL_REPORTS_DIR", ROOT / "reports"))
BACKUPS_DIR = Path(os.environ.get("BOT_CONTROL_BACKUPS_DIR", "/root/backups/bot-control-centre"))
LATEST_RISK_PATH = Path(os.environ.get("GLOBAL_RISK_REPORT", REPORTS_DIR / "latest_risk.json"))
GUARD_EVENT_LOG = Path(os.environ.get("GLOBAL_RISK_GUARD_LOG", REPORTS_DIR / "trade_guard_events.jsonl"))
TRUTHY = {"1", "true", "yes", "y", "on"}

DEFAULT_POLICY: dict[str, Any] = {
    "version": 1,
    "mode": "enforced_for_new_trades",
    "description": "Global guardrail policy. Executors must not increase exposure during BLOCK conditions.",
    "limits": {
        "max_live_trading_bots": 2,
        "max_stale_data_minutes_live": 30,
        "max_stale_data_minutes_paper": 180,
        "min_free_disk_gb": 10,
        "max_swap_used_pct_warn": 70,
        "max_swap_used_pct_block": 90,
    },
    "actions": {
        "warn": "Alert operator and mark dashboard yellow.",
        "block": "Alert operator, write kill-switch file, and require manual review before new exposure.",
        "kill_switch_file": str(STATE_DIR / "GLOBAL_RISK_BLOCK"),
    },
    "manual_override": {
        "file": str(STATE_DIR / "MANUAL_OVERRIDE"),
        "required_text": "OPERATOR ACCEPTS TEMPORARY OVERRIDE RISK",
    },
}

DEFAULT_INVENTORY: dict[str, Any] = {
    "version": 1,
    "generated_by": "bot_control_centre.py example inventory",
    "bots": [
        {
            "id": "forexbot-oanda-live",
            "name": "ForexBot OANDA Live",
            "type": "live_trading",
            "risk_tier": "critical",
            "canonical_path": "/root/working-on/forexbot-oanda-live",
            "legacy_paths": ["/root/bots/forexbot"],
            "services": ["forexbot.service", "forexbot-enhanced-dashboard.service"],
            "timers": ["forexbot-analyst.timer"],
            "ports": [9127],
            "broker_access": True,
            "mode": "live",
            "data_sources": ["metrics.sqlite3", "logs/bot.log", "analyst_report.json"],
            "notes": "Primary FX bot. Highest safety tier.",
        },
        {
            "id": "crypto-bot-main-live",
            "name": "Crypto Bot Main",
            "type": "live_trading",
            "risk_tier": "critical",
            "canonical_path": "/root/working-on/crypto-bot-main-live",
            "legacy_paths": ["/root/crypto-bot"],
            "services": ["crypto-bot.service"],
            "timers": [],
            "ports": [],
            "broker_access": True,
            "mode": "live_or_exchange_configured",
            "data_sources": ["state.sqlite3"],
            "notes": "Verify exchange mode before scaling.",
        },
        {
            "id": "crypto-bot-lab-state",
            "name": "Crypto Bot Lab",
            "type": "paper_trading",
            "risk_tier": "medium",
            "canonical_path": "/root/working-on/crypto-bot-lab-state",
            "legacy_paths": ["/root/crypto-bot-lab"],
            "services": ["crypto-bot-lab.service"],
            "timers": [],
            "ports": [],
            "broker_access": False,
            "mode": "paper_or_lab",
            "data_sources": ["state.sqlite3"],
            "notes": "Lab/paper state directory.",
        },
        {
            "id": "quantum-forex-bot-paper-forward",
            "name": "Quantum FX USDJPY Paper Forward",
            "type": "paper_trading",
            "risk_tier": "high",
            "canonical_path": "/root/working-on/quantum-forex-bot-paper-forward",
            "legacy_paths": ["/root/quantum-forex-bot"],
            "services": ["quantum-fx-usdjpy-execution.service"],
            "timers": ["quantum-fx-usdjpy-execution.timer"],
            "ports": [],
            "broker_access": False,
            "mode": "paper",
            "data_sources": ["state/USD_JPY.sqlite3"],
            "notes": "Paper-forward timer; readiness gate required before live use.",
        },
        {
            "id": "bots-pl-dashboard-live",
            "name": "Bot P/L Dashboard",
            "type": "dashboard",
            "risk_tier": "low",
            "canonical_path": "/root/working-on/bots-pl-dashboard-live",
            "legacy_paths": ["/root/bots-dashboard"],
            "services": ["bots-dashboard.service"],
            "timers": [],
            "ports": [9125],
            "broker_access": False,
            "mode": "dashboard",
            "data_sources": [],
            "notes": "Dashboard only; must not trade.",
        },
    ],
    "archived": [],
}


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    severity: str
    reason: str
    bot_id: str
    instrument: str | None = None
    mode: str | None = None
    source: str | None = None
    override: bool = False


class GlobalRiskBlocked(RuntimeError):
    """Raised when a bot tries to open new exposure during a global risk block."""

    def __init__(self, decision: GuardDecision):
        self.decision = decision
        super().__init__(decision.reason)


@dataclass
class NormalizedTrade:
    bot: str
    source: str
    source_id: str
    instrument: str
    opened_at: str | None
    closed_at: str | None
    side: str | None
    entry: float | None
    exit: float | None
    size: float | None
    stop_loss: float | None
    take_profit: float | None
    fees_spread: float | None
    realized_pnl: float | None
    r_multiple: float | None
    status: str
    strategy: str | None = None
    reason: str | None = None
    signal: str | None = None
    regime: str | None = None
    mode: str | None = None
    notes: str | None = None


@dataclass
class SourceHealth:
    bot: str
    path: str
    exists: bool
    records: int
    usable_closed_trades: int
    notes: str


def ensure_dirs() -> None:
    for path in (STATE_DIR, REPORTS_DIR, BACKUPS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + "\nTIMEOUT"
    except Exception as exc:  # pragma: no cover - defensive boundary around host tools
        return 1, f"{type(exc).__name__}: {exc}"


def load_json_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return default


def load_inventory() -> dict[str, Any]:
    return load_json_or_default(INVENTORY_PATH, DEFAULT_INVENTORY)


def load_policy() -> dict[str, Any]:
    return load_json_or_default(POLICY_PATH, DEFAULT_POLICY)


def write_examples() -> None:
    ensure_dirs()
    INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not INVENTORY_PATH.exists():
        INVENTORY_PATH.write_text(json.dumps(DEFAULT_INVENTORY, indent=2) + "\n")
    if not POLICY_PATH.exists():
        POLICY_PATH.write_text(json.dumps(DEFAULT_POLICY, indent=2) + "\n")
    print(f"Wrote examples if missing:\n- {INVENTORY_PATH}\n- {POLICY_PATH}")


def systemctl_state(unit: str, kind: str) -> dict[str, Any]:
    code, active = run(["systemctl", "is-active", unit])
    _, enabled = run(["systemctl", "is-enabled", unit])
    show_props = ["NRestarts", "ActiveEnterTimestamp", "ExecMainPID", "MemoryCurrent"]
    if kind == "timer":
        show_props = ["NextElapseUSecRealtime", "LastTriggerUSec"]
    show_cmd = ["systemctl", "show", unit, *(f"-p{x}" for x in show_props), "--no-pager"]
    _, show = run(show_cmd)
    info: dict[str, Any] = {"unit": unit, "active": active, "enabled": enabled, "exists": code in (0, 3)}
    for line in show.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key] = value
    return info


def path_age_minutes(path: Path) -> float | None:
    try:
        if not path.exists():
            return None
        return max(0.0, (time.time() - path.stat().st_mtime) / 60.0)
    except Exception:
        return None


def latest_data_age(bot: dict[str, Any]) -> tuple[str | None, float | None]:
    base = Path(bot["canonical_path"])
    candidates: list[Path] = []
    for rel in bot.get("data_sources", []):
        path = base / rel
        if path.exists():
            candidates.append(path)
    if not candidates and base.exists():
        for pattern in ("*.sqlite*", "*.db", "*.json"):
            candidates.extend([p for p in base.rglob(pattern) if ".venv" not in p.parts and "node_modules" not in p.parts][:10])
    if not candidates:
        return None, None
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    return str(newest), path_age_minutes(newest)


def port_state(port: int) -> str:
    _, out = run(["bash", "-lc", f"ss -tlnp | grep -E ':{int(port)}\\b' || true"])
    return "listening" if out.strip() else "closed"


def bot_status(bot: dict[str, Any]) -> dict[str, Any]:
    path = Path(bot["canonical_path"])
    data_path, age = latest_data_age(bot)
    services = [systemctl_state(unit, "service") for unit in bot.get("services", [])]
    timers = [systemctl_state(unit, "timer") for unit in bot.get("timers", [])]
    ports = {str(port): port_state(int(port)) for port in bot.get("ports", [])}
    expected_active = bot["type"] in {"live_trading", "dashboard"}
    service_problem = any(s["active"] not in {"active", "inactive"} for s in services)
    if expected_active:
        service_problem = service_problem or any(s["active"] != "active" for s in services if not s["unit"].endswith("-execution.service"))
    return {
        "id": bot["id"],
        "name": bot["name"],
        "type": bot["type"],
        "risk_tier": bot["risk_tier"],
        "mode": bot.get("mode"),
        "broker_access": bot.get("broker_access", False),
        "path": str(path),
        "path_exists": path.exists(),
        "services": services,
        "timers": timers,
        "ports": ports,
        "latest_data_path": data_path,
        "latest_data_age_minutes": age,
        "service_problem": service_problem,
        "notes": bot.get("notes", ""),
    }


def all_status() -> dict[str, Any]:
    inventory = load_inventory()
    return {"generated_at": utc_now(), "bots": [bot_status(bot) for bot in inventory.get("bots", [])], "archived": inventory.get("archived", [])}


def system_snapshot() -> dict[str, Any]:
    _, disk = run(["df", "-BG", "/"])
    _, memory = run(["free", "-m"])
    _, uptime = run(["uptime"])
    return {"disk": disk, "memory": memory, "uptime": uptime}


def extract_swap_pct(memory_text: str) -> float:
    for line in memory_text.splitlines():
        if line.startswith("Swap:"):
            parts = line.split()
            total = float(parts[1])
            used = float(parts[2])
            return (used / total * 100.0) if total else 0.0
    return 0.0


def evaluate_risk(status: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_dirs()
    status = status or all_status()
    policy = load_policy()
    limits = policy.get("limits", {})
    issues: list[dict[str, Any]] = []
    sys_snap = system_snapshot()
    swap_pct = extract_swap_pct(sys_snap["memory"])
    if swap_pct >= float(limits.get("max_swap_used_pct_block", 90)):
        issues.append({"severity": "block", "code": "swap_high_block", "message": f"Swap usage {swap_pct:.1f}% >= block threshold"})
    elif swap_pct >= float(limits.get("max_swap_used_pct_warn", 70)):
        issues.append({"severity": "warn", "code": "swap_high_warn", "message": f"Swap usage {swap_pct:.1f}% >= warn threshold"})
    try:
        line = sys_snap["disk"].splitlines()[1]
        avail = float(line.split()[3].rstrip("G"))
        if avail < float(limits.get("min_free_disk_gb", 10)):
            issues.append({"severity": "block", "code": "disk_low", "message": f"Free disk {avail}G below minimum"})
    except Exception:
        issues.append({"severity": "warn", "code": "disk_parse_failed", "message": "Could not parse df output"})
    live_count = sum(1 for bot in status["bots"] if bot["type"] == "live_trading" and any(s["active"] == "active" for s in bot["services"]))
    if live_count > int(limits.get("max_live_trading_bots", 2)):
        issues.append({"severity": "warn", "code": "too_many_live_bots", "message": f"{live_count} live trading bots active"})
    for bot in status["bots"]:
        stale_limit = float(limits.get("max_stale_data_minutes_live", 30) if bot["type"] == "live_trading" else limits.get("max_stale_data_minutes_paper", 180))
        age = bot.get("latest_data_age_minutes")
        if bot["type"] in {"live_trading", "paper_trading"} and age is not None and age > stale_limit:
            issues.append({"severity": "warn", "code": "stale_data", "bot": bot["id"], "message": f"{bot['id']} latest data age {age:.1f} min > {stale_limit}"})
        if bot.get("service_problem"):
            severity = "block" if bot["type"] == "live_trading" else "warn"
            issues.append({"severity": severity, "code": "service_problem", "bot": bot["id"], "message": f"{bot['id']} service problem detected"})
    severity = "block" if any(i["severity"] == "block" for i in issues) else ("warn" if issues else "ok")
    kill_switch = Path((policy.get("actions") or {}).get("kill_switch_file") or STATE_DIR / "GLOBAL_RISK_BLOCK")
    if severity == "block":
        kill_switch.parent.mkdir(parents=True, exist_ok=True)
        kill_switch.write_text(json.dumps({"created_at": utc_now(), "issues": issues}, indent=2) + "\n")
    result = {"generated_at": utc_now(), "severity": severity, "issues": issues, "system": sys_snap, "swap_used_pct": swap_pct, "policy_mode": policy.get("mode")}
    LATEST_RISK_PATH.write_text(json.dumps(result, indent=2) + "\n")
    return result


def markdown_status(status: dict[str, Any], risk: dict[str, Any] | None = None) -> str:
    risk = risk or evaluate_risk(status)
    lines = ["# Bot Control Centre Status", "", f"Generated: `{status['generated_at']}`", "", f"Global risk: **{risk['severity'].upper()}** (`{risk.get('policy_mode')}`)", ""]
    if risk["issues"]:
        lines += ["## Risk issues", ""]
        for issue in risk["issues"]:
            lines.append(f"- **{issue['severity'].upper()}** `{issue['code']}`: {issue['message']}")
        lines.append("")
    lines += ["## Bots", "", "| Bot | Type | Mode | Services | Timers | Ports | Data age | Path |", "|---|---|---|---|---|---|---:|---|"]
    for bot in status["bots"]:
        services = ", ".join(f"{s['unit']}={s['active']}/{s['enabled']}" for s in bot["services"]) or "-"
        timers = ", ".join(f"{t['unit']}={t['active']}/{t['enabled']}" for t in bot["timers"]) or "-"
        ports = ", ".join(f"{p}:{v}" for p, v in bot["ports"].items()) or "-"
        age = "-" if bot["latest_data_age_minutes"] is None else f"{bot['latest_data_age_minutes']:.1f}m"
        lines.append(f"| `{bot['id']}` | {bot['type']} | {bot['mode']} | {services} | {timers} | {ports} | {age} | `{bot['path']}` |")
    return "\n".join(lines) + "\n"


def status_command(fmt: str) -> int:
    ensure_dirs()
    status = all_status()
    risk = evaluate_risk(status)
    (REPORTS_DIR / "latest_status.json").write_text(json.dumps(status, indent=2) + "\n")
    (REPORTS_DIR / "latest_status.md").write_text(markdown_status(status, risk))
    if fmt == "json":
        print(json.dumps({"status": status, "risk": risk}, indent=2))
    elif fmt == "markdown":
        print(markdown_status(status, risk))
    else:
        print(f"Global risk: {risk['severity'].upper()} | generated {status['generated_at']}")
        print(f"{'BOT':36} {'TYPE':14} {'MODE':20} {'SERVICE':18} {'DATA AGE'}")
        for bot in status["bots"]:
            svc = ",".join(s["active"] for s in bot["services"]) or "-"
            age = "-" if bot["latest_data_age_minutes"] is None else f"{bot['latest_data_age_minutes']:.1f}m"
            print(f"{bot['id'][:36]:36} {bot['type'][:14]:14} {str(bot['mode'])[:20]:20} {svc[:18]:18} {age}")
        if risk["issues"]:
            print("\nIssues:")
            for issue in risk["issues"]:
                print(f"- {issue['severity'].upper()} {issue['code']}: {issue['message']}")
    return 2 if risk["severity"] == "block" else 1 if risk["severity"] == "warn" else 0


def alert_once() -> int:
    ensure_dirs()
    status = all_status()
    risk = evaluate_risk(status)
    md = markdown_status(status, risk)
    if risk["severity"] in {"warn", "block"}:
        payload = "\n".join([risk["severity"], json.dumps(risk["issues"], sort_keys=True)])
        digest = hashlib.sha256(payload.encode()).hexdigest()
        alert_state = STATE_DIR / "last_alert_hash"
        if not alert_state.exists() or alert_state.read_text().strip() != digest:
            alert_state.write_text(digest)
            text = "Sector 7-G Bot Control Centre alert: " + risk["severity"].upper() + "\n\n" + "\n".join(f"- {i['code']}: {i['message']}" for i in risk["issues"])
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat = os.environ.get("TELEGRAM_CHAT_ID")
            if token and chat:
                data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20).read()
            else:
                (REPORTS_DIR / "pending_alert.txt").write_text(text)
                print("Telegram env not set; wrote reports/pending_alert.txt")
        else:
            print("No new alert state")
    print(md)
    return 2 if risk["severity"] == "block" else 1 if risk["severity"] == "warn" else 0


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) or math.isinf(out) else out


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone() is not None


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _json_loads(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _crypto_r_multiple(row: sqlite3.Row) -> float | None:
    pnl = _safe_float(row["pnl"])
    size = _safe_float(row["size"])
    entry = _safe_float(row["entry"])
    stop = _safe_float(row["sl"])
    if pnl is None or not size or not entry or stop is None:
        return None
    risk = abs(size * ((entry - stop) / entry))
    return None if risk <= 0 else pnl / risk


def load_crypto_trades(bot: dict[str, Any]) -> tuple[list[NormalizedTrade], SourceHealth]:
    path = Path(bot["canonical_path"]) / "state.sqlite3"
    trades: list[NormalizedTrade] = []
    if not path.exists():
        return trades, SourceHealth(bot["id"], str(path), False, 0, 0, "missing SQLite ledger")
    with _connect(path) as con:
        if not _table_exists(con, "trades"):
            return trades, SourceHealth(bot["id"], str(path), True, 0, 0, "no trades table")
        rows = con.execute("select * from trades order by id").fetchall()
    for row in rows:
        status = str(row["status"] or "unknown")
        trade_status = "closed" if status == "closed" else "open"
        result = row["result"] if "result" in row.keys() else None
        trades.append(NormalizedTrade(bot=bot["id"], source="crypto_state_sqlite", source_id=str(row["id"]), instrument=str(row["pair"]), opened_at=row["opened_at"], closed_at=row["closed_at"], side=row["signal"], entry=_safe_float(row["entry"]), exit=_safe_float(row["exit"]), size=_safe_float(row["size"]), stop_loss=_safe_float(row["sl"]), take_profit=_safe_float(row["tp"]), fees_spread=None, realized_pnl=_safe_float(row["pnl"]), r_multiple=_crypto_r_multiple(row), status=trade_status, strategy=row["strategy"], reason=row["reason"] or result, signal=row["signal"], regime=row["regime"], mode=str(bot.get("mode"))))
    closed = sum(1 for t in trades if t.status == "closed" and t.realized_pnl is not None)
    return trades, SourceHealth(bot["id"], str(path), True, len(trades), closed, "trade-level ledger")


def load_forexbot_daily_metrics(bot: dict[str, Any]) -> tuple[list[NormalizedTrade], SourceHealth]:
    path = Path(bot["canonical_path"]) / "metrics.sqlite3"
    trades: list[NormalizedTrade] = []
    if not path.exists():
        return trades, SourceHealth(bot["id"], str(path), False, 0, 0, "missing metrics DB")
    with _connect(path) as con:
        if not _table_exists(con, "daily_metrics"):
            return trades, SourceHealth(bot["id"], str(path), True, 0, 0, "no daily_metrics table")
        rows = con.execute("select * from daily_metrics order by date, id").fetchall()
    for row in rows:
        trades.append(NormalizedTrade(bot=bot["id"], source="forexbot_daily_metrics_aggregate", source_id=str(row["id"]), instrument="ALL", opened_at=row["date"], closed_at=row["date"], side=None, entry=None, exit=None, size=None, stop_loss=None, take_profit=None, fees_spread=None, realized_pnl=_safe_float(row["net_pnl_usd"]), r_multiple=None, status="aggregate_day", strategy="daily_metrics", reason="aggregate_only", mode=str(bot.get("mode")), notes=f"daily aggregate; total_trades={row['total_trades']}"))
    return trades, SourceHealth(bot["id"], str(path), True, len(rows), 0, "daily summary only; no trade-level fills available locally")


def load_quantum_trade_intents(bot: dict[str, Any]) -> tuple[list[NormalizedTrade], SourceHealth]:
    base = Path(bot["canonical_path"])
    candidates = [base / "state/live_execution.sqlite3", base / "state/USD_JPY.sqlite3"]
    path = next((p for p in candidates if p.exists()), candidates[0])
    trades: list[NormalizedTrade] = []
    if not path.exists():
        return trades, SourceHealth(bot["id"], str(path), False, 0, 0, "missing quantum execution DB")
    with _connect(path) as con:
        if not _table_exists(con, "trade_intents"):
            return trades, SourceHealth(bot["id"], str(path), True, 0, 0, "no trade_intents table")
        rows = con.execute("select * from trade_intents order by id").fetchall()
    for row in rows:
        response = _json_loads(row["response_json"] if "response_json" in row.keys() else None)
        fill = response.get("orderFillTransaction") or {}
        opened = fill.get("tradeOpened") or {}
        status = str(row["status"])
        trade_status = "open_or_intent" if status in {"ORDER_FILLED", "INTENT_RECORDED", "DRY_RUN_READY"} else status.lower()
        trades.append(NormalizedTrade(bot=bot["id"], source="quantum_trade_intents", source_id=str(opened.get("tradeID") or row["id"]), instrument=row["instrument"], opened_at=row["created_at_utc"], closed_at=None, side=row["side"], entry=_safe_float(fill.get("price")) or _safe_float(row["entry_price"]), exit=None, size=abs(_safe_float(row["units"]) or 0.0), stop_loss=_safe_float(row["stop_loss"]), take_profit=_safe_float(row["take_profit"]), fees_spread=_safe_float(fill.get("halfSpreadCost")), realized_pnl=_safe_float(fill.get("pl")), r_multiple=None, status=trade_status, strategy="quantum_fx_usdjpy", reason=status, signal=str(row["signal_score"]) if "signal_score" in row.keys() and row["signal_score"] is not None else None, mode=row["mode"], notes="intent/fill ledger; closure P&L not available in this table"))
    return trades, SourceHealth(bot["id"], str(path), True, len(trades), 0, "trade intents/fills only; not closed trade lifecycle")


def load_all_trades() -> tuple[list[NormalizedTrade], list[SourceHealth]]:
    trades: list[NormalizedTrade] = []
    health: list[SourceHealth] = []
    for bot in load_inventory().get("bots", []):
        bot_id = bot["id"]
        if bot_id.startswith("crypto"):
            out, src = load_crypto_trades(bot)
        elif "forexbot" in bot_id:
            out, src = load_forexbot_daily_metrics(bot)
        elif "quantum" in bot_id:
            out, src = load_quantum_trade_intents(bot)
        else:
            continue
        trades.extend(out)
        health.append(src)
    return trades, health


def _closed_realized(trades: Iterable[NormalizedTrade]) -> list[NormalizedTrade]:
    return [t for t in trades if t.status == "closed" and t.realized_pnl is not None]


def _max_drawdown(pnls: list[float]) -> float:
    equity = peak = max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def summarize_group(name: str, trades: list[NormalizedTrade]) -> dict[str, Any]:
    closed = _closed_realized(trades)
    pnls = [float(t.realized_pnl) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    r_values = [float(t.r_multiple) for t in closed if t.r_multiple is not None]
    return {
        "name": name,
        "records": len(trades),
        "closed_trades": len(closed),
        "open_or_intent": sum(1 for t in trades if t.status in {"open", "open_or_intent"}),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (len(wins) / len(closed) * 100.0) if closed else None,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": sum(pnls),
        "expectancy": mean(pnls) if pnls else None,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else (None if gross_profit == 0 else math.inf),
        "avg_r": mean(r_values) if r_values else None,
        "max_drawdown_abs": _max_drawdown(pnls),
    }


def gate_recommendation(summary: dict[str, Any], source_quality: str = "trade_level") -> dict[str, Any]:
    closed = int(summary["closed_trades"])
    pf = summary["profit_factor"]
    expectancy = summary["expectancy"]
    issues: list[str] = []
    if source_quality != "trade_level":
        issues.append("not trade-level closed-fill evidence")
    if closed < 30:
        issues.append(f"sample too small ({closed}/30 closed trades)")
    if pf is None or pf < 1.2:
        issues.append(f"profit factor below gate ({pf})")
    if expectancy is None or expectancy <= 0:
        issues.append(f"expectancy not positive ({expectancy})")
    if not issues and closed >= 100 and pf is not None and pf >= 1.5:
        stage = "candidate_for_tiny_live_or_scale_review"
    elif not issues:
        stage = "continue_paper_forward"
    elif closed >= 10 and expectancy is not None and expectancy > 0:
        stage = "watchlist_improve_evidence"
    else:
        stage = "do_not_promote"
    return {"stage": stage, "issues": issues, "manual_review_required": True}


def build_trade_report() -> dict[str, Any]:
    trades, health = load_all_trades()
    by_bot: dict[str, list[NormalizedTrade]] = defaultdict(list)
    by_bot_instrument: dict[str, list[NormalizedTrade]] = defaultdict(list)
    for trade in trades:
        by_bot[trade.bot].append(trade)
        by_bot_instrument[f"{trade.bot}:{trade.instrument}"].append(trade)
    health_by_bot = {h.bot: h for h in health}
    bot_summaries = []
    for bot in sorted(set(by_bot) | set(health_by_bot)):
        summary = summarize_group(bot, by_bot.get(bot, []))
        src = health_by_bot.get(bot)
        quality = "trade_level" if src and src.usable_closed_trades > 0 and src.notes.startswith("trade-level") else "aggregate_or_intent"
        summary["source_quality"] = quality
        summary["gate"] = gate_recommendation(summary, quality)
        bot_summaries.append(summary)
    return {
        "generated_at": utc_now(),
        "schema_version": 1,
        "sources": [asdict(h) for h in health],
        "totals": summarize_group("all", trades),
        "bot_leaderboard": sorted(bot_summaries, key=lambda x: (x["expectancy"] is not None, x["net_pnl"]), reverse=True),
        "bot_instrument_leaderboard": [summarize_group(k, v) for k, v in sorted(by_bot_instrument.items())],
        "closed_trade_count": len(_closed_realized(trades)),
        "normalized_trade_count": len(trades),
        "promotion_policy": {"min_closed_trades": 30, "preferred_closed_trades_for_live_scale": 100, "min_profit_factor": 1.2, "preferred_profit_factor": 1.5, "expectancy_required": "positive after available costs", "manual_review_required": True},
    }


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    if value == math.inf:
        return "∞"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def markdown_trade_report(report: dict[str, Any]) -> str:
    lines = ["# Unified Trade Analytics + Promotion Gates", "", f"Generated: `{report['generated_at']}`", "", "## Source health", "", "| Bot | Records | Usable closed trades | Evidence | Notes |", "|---|---:|---:|---|---|"]
    for src in report["sources"]:
        lines.append(f"| `{src['bot']}` | {src['records']} | {src['usable_closed_trades']} | {'ok' if src['exists'] else 'missing'} | {src['notes']} |")
    lines += ["", "## Bot leaderboard", "", "| Bot | Closed | Open/intent | Net P&L | Expectancy | PF | Win % | Gate |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for bot in report["bot_leaderboard"]:
        lines.append(f"| `{bot['name']}` | {bot['closed_trades']} | {bot['open_or_intent']} | {_fmt(bot['net_pnl'])} | {_fmt(bot['expectancy'])} | {_fmt(bot['profit_factor'])} | {_fmt(bot['win_rate_pct'], 2)} | {bot['gate']['stage']} |")
    lines += ["", "## Promotion blockers", ""]
    for bot in report["bot_leaderboard"]:
        issues = bot["gate"]["issues"]
        lines.append(f"- `{bot['name']}`: " + ("; ".join(issues) if issues else "no automated blockers; manual review still required"))
    lines += ["", "## Interpretation", "", "- Promotion requires trade-level closed-fill evidence, positive expectancy, PF >= 1.2, and manual review.", "- Aggregate-only or intent-only sources are visible but cannot promote a bot. That avoids Homer writing fake numbers on Mr Burns' clipboard."]
    return "\n".join(lines) + "\n"


def analytics_command(fmt: str, write: bool) -> int:
    ensure_dirs()
    report = build_trade_report()
    if write:
        trades, _ = load_all_trades()
        (REPORTS_DIR / "trade_analytics_latest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        (REPORTS_DIR / "trade_analytics_latest.md").write_text(markdown_trade_report(report))
        with (REPORTS_DIR / "normalized_trades_latest.csv").open("w", newline="") as fh:
            fields = list(asdict(trades[0]).keys()) if trades else ["bot"]
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for trade in trades:
                writer.writerow(asdict(trade))
    if fmt == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif fmt == "markdown":
        print(markdown_trade_report(report))
    else:
        print(f"Generated {report['generated_at']} | normalized records: {report['normalized_trade_count']} | closed trades: {report['closed_trade_count']}")
        print(f"{'BOT':38} {'CLOSED':>6} {'NET':>10} {'EXP':>10} {'PF':>8} {'GATE'}")
        for bot in report["bot_leaderboard"]:
            print(f"{bot['name'][:38]:38} {bot['closed_trades']:6d} {_fmt(bot['net_pnl']):>10} {_fmt(bot['expectancy']):>10} {_fmt(bot['profit_factor']):>8} {bot['gate']['stage']}")
    return 0


def manual_override_active(policy: dict[str, Any]) -> bool:
    config = policy.get("manual_override") or {}
    override_file = Path(config.get("file") or STATE_DIR / "MANUAL_OVERRIDE")
    required = str(config.get("required_text") or "").strip()
    try:
        actual = override_file.read_text().strip()
    except FileNotFoundError:
        return False
    return bool(required and actual == required)


def assess_trade_allowed(bot_id: str, *, instrument: str | None = None, mode: str | None = None, log_event: bool = True) -> GuardDecision:
    if str(os.environ.get("BOT_RISK_GUARD_DISABLED", "")).lower() in TRUTHY:
        decision = GuardDecision(True, "disabled", "BOT_RISK_GUARD_DISABLED is set", bot_id, instrument, mode, "env", True)
        if log_event:
            record_guard_event(decision)
        return decision
    try:
        policy = load_policy()
    except Exception as exc:
        liveish = str(mode or "").lower() in {"live", "live_or_exchange_configured"}
        decision = GuardDecision(not liveish, "unknown", f"Global risk policy unavailable: {type(exc).__name__}: {exc}", bot_id, instrument, mode, str(POLICY_PATH), False)
        if log_event:
            record_guard_event(decision)
        return decision
    override = manual_override_active(policy)
    kill_switch = Path((policy.get("actions") or {}).get("kill_switch_file") or STATE_DIR / "GLOBAL_RISK_BLOCK")
    if kill_switch.exists() and not override:
        try:
            detail = "; ".join(str(i.get("code", "block")) for i in json.loads(kill_switch.read_text()).get("issues", [])[:5])
        except Exception:
            detail = "kill-switch file present"
        decision = GuardDecision(False, "block", f"Global risk block active: {detail}", bot_id, instrument, mode, str(kill_switch), False)
        if log_event:
            record_guard_event(decision)
        return decision
    risk: dict[str, Any] = {}
    if LATEST_RISK_PATH.exists():
        try:
            risk = json.loads(LATEST_RISK_PATH.read_text())
        except Exception as exc:
            risk = {"severity": "unknown", "issues": [{"code": "risk_report_parse_failed", "message": str(exc)}]}
    severity = str(risk.get("severity") or "unknown").lower()
    if severity == "block" and not override:
        issues = risk.get("issues") or []
        detail = "; ".join(str(i.get("code", "block")) for i in issues[:5]) or "latest risk report severity=block"
        decision = GuardDecision(False, "block", f"Global risk report blocks new trades: {detail}", bot_id, instrument, mode, str(LATEST_RISK_PATH), False)
        if log_event:
            record_guard_event(decision)
        return decision
    decision = GuardDecision(True, severity or "unknown", "Manual override active" if override else f"Global risk severity {severity or 'unknown'} permits new trades", bot_id, instrument, mode, str(LATEST_RISK_PATH), override)
    if log_event:
        record_guard_event(decision)
    return decision


def assert_trade_allowed(bot_id: str, *, instrument: str | None = None, mode: str | None = None) -> GuardDecision:
    decision = assess_trade_allowed(bot_id, instrument=instrument, mode=mode)
    if not decision.allowed:
        raise GlobalRiskBlocked(decision)
    return decision


def record_guard_event(decision: GuardDecision) -> None:
    try:
        ensure_dirs()
        payload = {"checked_at": utc_now(), **asdict(decision)}
        with GUARD_EVENT_LOG.open("a") as fh:
            fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:
        pass


def guard_command(args: argparse.Namespace) -> int:
    decision = assess_trade_allowed(args.bot_id, instrument=args.instrument, mode=args.mode)
    if args.json:
        print(json.dumps(asdict(decision), indent=2))
    else:
        print(f"{'ALLOW' if decision.allowed else 'BLOCK'} {decision.bot_id}: {decision.reason}")
    return 0 if decision.allowed else 2


def backup_once() -> int:
    ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = BACKUPS_DIR / f"bot_state_snapshot_{ts}.tar.gz"
    inventory = load_inventory()
    exclude_dirs = {".venv", "venv", "node_modules", "__pycache__", ".git"}
    include_suffixes = (".sqlite", ".sqlite3", ".db", ".json", ".env.example", ".md", ".service", ".timer", ".toml", ".yaml", ".yml")

    def should_include(path: Path) -> bool:
        return not any(part in exclude_dirs for part in path.parts) and (path.suffix in include_suffixes or "/state/" in str(path) or "/data/" in str(path))

    with tarfile.open(dest, "w:gz") as tar:
        if INVENTORY_PATH.exists():
            tar.add(INVENTORY_PATH, arcname="bot-control-centre/inventory.json")
        if POLICY_PATH.exists():
            tar.add(POLICY_PATH, arcname="bot-control-centre/global_risk_policy.json")
        for bot in inventory.get("bots", []):
            base = Path(bot["canonical_path"])
            if not base.exists():
                continue
            manifest = base / "BOT_MANIFEST.json"
            if manifest.exists():
                tar.add(manifest, arcname=f"{bot['id']}/BOT_MANIFEST.json")
            for path in base.rglob("*"):
                if path.is_file() and should_include(path):
                    try:
                        tar.add(path, arcname=f"{bot['id']}/{path.relative_to(base)}")
                    except Exception:
                        pass
    latest = BACKUPS_DIR / "latest.tar.gz"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(dest)
    snaps = sorted(BACKUPS_DIR.glob("bot_state_snapshot_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in snaps[14:]:
        old.unlink(missing_ok=True)
    (REPORTS_DIR / "latest_backup.txt").write_text(str(dest) + "\n")
    print(dest)
    return 0


def dashboard_command(host: str, port: int) -> int:
    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/analytics/json"):
                report = build_trade_report()
                body = json.dumps(report, indent=2).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if self.path.startswith("/analytics"):
                md = markdown_trade_report(build_trade_report())
                body = ("<!doctype html><title>Trade Analytics</title><style>body{font-family:system-ui;margin:2rem;background:#111;color:#eee}pre{white-space:pre-wrap;background:#181818;border:1px solid #444;padding:1rem;border-radius:.5rem}a{color:#90caf9}</style><h1>Unified Trade Analytics + Promotion Gates</h1><p><a href='/'>Bot Control Centre</a> · <a href='/analytics/json'>JSON</a></p>" + f"<pre>{html.escape(md)}</pre>").encode()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            status = all_status(); risk = evaluate_risk(status)
            if self.path.startswith("/json"):
                body = json.dumps({"status": status, "risk": risk}, indent=2).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            color = {"ok": "#2e7d32", "warn": "#f9a825", "block": "#c62828"}[risk["severity"]]
            row_parts = []
            for b in status["bots"]:
                service_text = ", ".join(s["unit"] + ":" + s["active"] for s in b["services"])
                age_value = b["latest_data_age_minutes"]
                age_text = "-" if age_value is None else f"{age_value:.1f}m"
                row_parts.append(
                    "<tr>"
                    f"<td>{html.escape(str(b['id']))}</td>"
                    f"<td>{html.escape(str(b['type']))}</td>"
                    f"<td>{html.escape(str(b['mode']))}</td>"
                    f"<td>{html.escape(service_text)}</td>"
                    f"<td>{html.escape(age_text)}</td>"
                    "</tr>"
                )
            rows = "".join(row_parts)
            issues = "".join(f"<li><b>{i['severity'].upper()}</b> {html.escape(i['code'])}: {html.escape(i['message'])}</li>" for i in risk["issues"]) or "<li>No current issues</li>"
            body = f"<!doctype html><title>Bot Control Centre</title><style>body{{font-family:system-ui;margin:2rem;background:#111;color:#eee}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #444;padding:.5rem}}.risk{{color:white;background:{color};padding:.5rem 1rem;border-radius:.5rem;display:inline-block}}a{{color:#90caf9}}</style><h1>Sector 7-G Bot Control Centre</h1><p>Generated {status['generated_at']}</p><h2>Global Risk <span class='risk'>{risk['severity'].upper()}</span></h2><ul>{issues}</ul><h2>Bots</h2><table><tr><th>Bot</th><th>Type</th><th>Mode</th><th>Services</th><th>Data age</th></tr>{rows}</table><p><a href='/json'>Status JSON</a> · <a href='/analytics'>Trade Analytics + Promotion Gates</a> · <a href='/analytics/json'>Analytics JSON</a></p>".encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    HTTPServer((host, port), Handler).serve_forever()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bot Control Centre: status, risk, analytics, guard, backup and dashboard")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-examples", help="write example inventory/policy files if missing")
    status_p = sub.add_parser("status", help="inspect services/data freshness and evaluate risk")
    status_p.add_argument("--format", choices=["json", "markdown", "table"], default="table")
    sub.add_parser("risk", help="print latest risk governor result")
    sub.add_parser("monitor-once", help="status + de-duplicated alert write/send")
    analytics_p = sub.add_parser("analytics", help="normalize trade ledgers and apply promotion gates")
    analytics_p.add_argument("--format", choices=["json", "markdown", "table"], default="table")
    analytics_p.add_argument("--write", action="store_true", help="write JSON/Markdown/CSV reports under reports/")
    guard_p = sub.add_parser("guard", help="check whether a bot may open/increase exposure")
    guard_p.add_argument("--bot-id", required=True)
    guard_p.add_argument("--instrument")
    guard_p.add_argument("--mode")
    guard_p.add_argument("--json", action="store_true")
    sub.add_parser("backup", help="snapshot selected state/metadata files to a local tarball")
    dash_p = sub.add_parser("dashboard", help="serve local HTML dashboard")
    dash_p.add_argument("--host", default="127.0.0.1")
    dash_p.add_argument("--port", type=int, default=9124)
    args = parser.parse_args(argv)
    if args.command == "init-examples":
        write_examples(); return 0
    if args.command == "status":
        return status_command(args.format)
    if args.command == "risk":
        print(json.dumps(evaluate_risk(all_status()), indent=2)); return 0
    if args.command == "monitor-once":
        return alert_once()
    if args.command == "analytics":
        return analytics_command(args.format, args.write)
    if args.command == "guard":
        return guard_command(args)
    if args.command == "backup":
        return backup_once()
    if args.command == "dashboard":
        return dashboard_command(args.host, args.port)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
