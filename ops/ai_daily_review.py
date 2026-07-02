#!/usr/bin/env python3
"""End-of-day review + self-heal for the shared OANDA account (QuantumFX + fx-live-bot).

Runs Mon-Fri at 21:06 UTC (daily-review.timer) — inside the ~1h market break
after the New York close — and:

  1. Pulls the UTC day's transactions from OANDA and reconstructs every trade.
  2. Attributes each order via client-extension tags (quantumfx / fx-live-bot);
     UNTAGGED orders are an alarm — no bot on this box places untagged orders.
  3. Grades each trade on PROCESS (stop attached, risk within budget, leverage
     sane) separately from OUTCOME (win/loss). A losing trade with good process
     is fine; a winning trade with bad process is still flagged.
  4. Self-heals in two layers. Deterministic floor: restart dead services,
     restart on stale heartbeat. Smart layer: hands the full health evidence
     (services, heartbeat, risk-governor state, stale GLOBAL_RISK_BLOCK, log
     tails) to the AI model the Hermes agent is CURRENTLY running (read live
     from /root/.hermes/config.yaml — Codex today, whatever the operator switches to
     tomorrow) and executes only whitelist-validated actions it proposes.
     Never touches strategy parameters directly.
  5. Asks the same current model (headless, fail-soft; falls back to the
     claude CLI) for lessons + bounded parameter candidates; candidates go to
     state/evolution_queue.json where ONLY the weekend research gate
     (evolution.py) can promote them after beating the incumbent
     out-of-sample. This script never edits live config.
  6. Journals to state/daily_review.sqlite3, writes reports/daily_review_<date>.md,
     and sends a plain-text Telegram summary.

Flags: --date YYYY-MM-DD  --no-notify  --no-llm  --no-heal
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/root/working-on/bot-control-centre")
REPORTS = ROOT / "reports"
STATE = ROOT / "state"
QUEUE = STATE / "evolution_queue.json"
JOURNAL_DB = STATE / "daily_review.sqlite3"
FOREXBOT_ENV = Path("/root/working-on/fx-live-bot/.env")
HERMES_ENV = Path("/root/.hermes/.env")
QFX_LOG = Path("/root/working-on/quantumfx/logs/bot.log")
QFX_DB = Path("/root/working-on/quantumfx/state/quantumfx.sqlite3")
QFX_HEARTBEAT = Path("/root/working-on/quantumfx/state/heartbeat.json")

SERVICES = ["quantumfx.service", "fx-live-bot.service"]
HERMES_CONFIG = Path("/root/.hermes/config.yaml")
RISK_BLOCK = STATE / "GLOBAL_RISK_BLOCK"

# Per-tag risk budget: worst acceptable single-trade loss as % of NAV.
# Margin-utilization sizing (2026-07-02): quantumfx takes ~45% of available
# margin per entry (~10% NAV at a 3-ATR stop), fx-live-bot ~8x equity notional
# (~5% NAV at typical stops); anything beyond 2x budget is a hard process
# failure. Legacy vol-sized budgets were 1.5 / 0.5.
RISK_BUDGET_PCT = {"quantumfx": 10.0, "fx-live-bot": 5.0}
LEVERAGE_WARN, LEVERAGE_BAD = 15.0, 28.0

# Bounded self-tuning surface. The z_in floor of 2.0 is deliberate: the
# frequency-frontier study (research/reports/freq_frontier.md) showed every
# higher-frequency variant destroys the edge after spreads.
WHITELIST = {
    "z_in": (2.0, 2.5),
    "z_out": (0.10, 0.50),
    "hl_max": (40.0, 80.0),
    "vr_max": (0.90, 1.00),
    "d1_veto_x": (0.015, 0.04),
}


def read_env(path: Path) -> dict:
    env = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


class Oanda:
    def __init__(self, env: dict):
        self.token = (env.get("OANDA_API_KEY") or env.get("OANDA_TOKEN")
                      or env.get("OANDA_ACCESS_TOKEN"))
        self.account = env.get("OANDA_ACCOUNT_ID", "000-000-0000000-000")  # set in .env
        host = "api-fxtrade.oanda.com"
        if (env.get("OANDA_ENVIRONMENT") or "live").lower() in ("practice", "demo"):
            host = "api-fxpractice.oanda.com"
        self.base = f"https://{host}"

    def get(self, path: str) -> dict:
        req = urllib.request.Request(
            self.base + path, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def window_transactions(self, frm: str, to: str) -> list[dict]:
        q = urllib.parse.urlencode({"from": frm, "to": to, "pageSize": 1000})
        idx = self.get(f"/v3/accounts/{self.account}/transactions?{q}")
        txns = []
        for page in idx.get("pages", []):
            parsed = urllib.parse.urlparse(page)
            txns += self.get(parsed.path + "?" + parsed.query).get("transactions", [])
        return txns

    def summary(self) -> dict:
        return self.get(f"/v3/accounts/{self.account}/summary")["account"]


def tag_of(txn: dict) -> str | None:
    for key in ("tradeClientExtensions", "clientExtensions"):
        tag = (txn.get(key) or {}).get("tag")
        if tag:
            return tag
    # Only ForexBot sets a clientExtensions.id (e.g. "EMA _EUR_USD_...",
    # "OUMe_EUR_AUD_..."); QuantumFX sets tag+comment, manual trades set
    # nothing. An id without a tag therefore means an older ForexBot build.
    if (txn.get("clientExtensions") or {}).get("id"):
        return "fx-live-bot"
    return None


def reconstruct(txns: list[dict]) -> tuple[list[dict], float]:
    """Rebuild the day's trades (opens + closes) from raw transactions."""
    orders = {t["id"]: t for t in txns if t["type"] in ("MARKET_ORDER", "LIMIT_ORDER")}
    sl_orders = [t for t in txns if t["type"] == "STOP_LOSS_ORDER"]
    trades: dict[str, dict] = {}
    financing = 0.0

    for t in txns:
        if t["type"] == "DAILY_FINANCING":
            financing += float(t.get("financing", 0))
        if t["type"] != "ORDER_FILL":
            continue
        order = orders.get(t.get("orderID"), {})
        opened = t.get("tradeOpened")
        if opened:
            tid = opened["tradeID"]
            if tid in trades:  # never let a later fill erase close data
                continue
            trades[tid] = {
                "trade_id": tid,
                "instrument": t["instrument"],
                "units": float(opened["units"]),
                "entry_price": float(t["price"]),
                "opened_at": t["time"],
                "tag": tag_of(order) or tag_of(t),
                "sl_on_fill": "stopLossOnFill" in order,
                "loss_conv": float(t.get("lossQuoteHomeConversionFactor", 1.0)),
                "closed_at": None, "exit_price": None, "pl": None,
                "close_reason": None, "sl_price": None,
            }
        for closed in (t.get("tradesClosed") or []) + ([t["tradeReduced"]] if t.get("tradeReduced") else []):
            tid = closed["tradeID"]
            rec = trades.setdefault(tid, {
                "trade_id": tid, "instrument": t["instrument"],
                "units": -float(closed["units"]), "entry_price": None,
                "opened_at": "(before today)", "tag": None, "sl_on_fill": None,
                "loss_conv": 1.0, "sl_price": None,
            })
            # trades opened before this window: recover the bot tag from the
            # closing fill/order so multi-day holds aren't flagged as manual
            rec["tag"] = rec.get("tag") or tag_of(t) or tag_of(order)
            rec["closed_at"] = t["time"]
            rec["exit_price"] = float(t["price"])
            rec["pl"] = float(closed.get("realizedPL", 0)) + rec.get("pl_prev", 0.0)
            rec["pl_prev"] = rec["pl"]
            rec["close_reason"] = t.get("reason", "")

    for sl in sl_orders:  # SL added after fill still counts, and gives distance
        rec = trades.get(sl.get("tradeID", ""))
        if rec is not None:
            rec["sl_price"] = float(sl.get("price", 0)) or rec.get("sl_price")
            opened_at = rec.get("opened_at")
            if opened_at and opened_at != "(before today)" and sl["time"] <= _plus_seconds(opened_at, 180):
                rec["sl_on_fill"] = True if rec["sl_on_fill"] is None else rec["sl_on_fill"] or True

    for rec in trades.values():
        rec.pop("pl_prev", None)
    return list(trades.values()), financing


def _plus_seconds(iso: str, secs: int) -> str:
    clean = re.sub(r"\.\d+", "", iso).replace("Z", "+00:00")
    if "+" not in clean:
        clean += "+00:00"
    ts = datetime.fromisoformat(clean)
    return (ts + timedelta(seconds=secs)).isoformat().replace("+00:00", "Z")


def grade(trade: dict, nav: float) -> dict:
    """Process grade, independent of outcome."""
    issues, notes = [], []
    tag = trade.get("tag")
    if not tag:
        issues.append("UNTAGGED order — no bot on this VPS places untagged orders "
                      "(manual trade or unknown client)")
    if trade.get("sl_on_fill") is False:
        issues.append("no stop-loss within 3 min of entry")

    entry, sl_price = trade.get("entry_price"), trade.get("sl_price")
    units = abs(trade.get("units") or 0)
    if entry and units and nav:
        notional_home = units * entry * trade.get("loss_conv", 1.0)
        lev = notional_home / nav
        if lev > LEVERAGE_BAD:
            issues.append(f"leverage {lev:.0f}x > {LEVERAGE_BAD:.0f}x")
        elif lev > LEVERAGE_WARN:
            notes.append(f"leverage {lev:.0f}x")
        if sl_price:
            risk_pct = abs(entry - sl_price) * units * trade.get("loss_conv", 1.0) / nav * 100
            budget = RISK_BUDGET_PCT.get(tag or "", 0.5)
            trade["risk_at_sl_pct"] = round(risk_pct, 2)
            if risk_pct > 2 * budget:
                issues.append(f"risk at stop {risk_pct:.1f}% NAV > 2x the "
                              f"{budget}% budget for tag '{tag or 'untagged'}'")
    pl = trade.get("pl")
    if pl is not None and nav:
        trade["pl_pct"] = round(pl / nav * 100, 2)
    if trade.get("opened_at") not in (None, "(before today)") and trade.get("closed_at"):
        try:
            o = datetime.fromisoformat(re.sub(r"\.\d+", "", trade["opened_at"]).replace("Z", "+00:00"))
            c = datetime.fromisoformat(re.sub(r"\.\d+", "", trade["closed_at"]).replace("Z", "+00:00"))
            mins = (c - o).total_seconds() / 60
            trade["held_minutes"] = round(mins)
            if mins < 30 and (pl or 0) < 0 and trade.get("close_reason") == "STOP_LOSS_ORDER":
                notes.append("stopped out within 30 min — stop likely inside noise range")
        except ValueError:
            pass
    trade["process"] = "bad" if issues else "good"
    trade["issues"] = issues
    trade["notes"] = notes
    return trade


def bot_context(day: str) -> dict:
    ctx = {"halts": 0, "qfx_bars_seen": 0, "qfx_trades_today": 0, "services": {}, "heartbeat_age_min": None}
    try:
        for line in QFX_LOG.read_text(errors="replace").splitlines():
            if not line.startswith(day):
                continue
            if "DAILY HALT" in line:
                ctx["halts"] += 1
            if " bar " in line:
                ctx["qfx_bars_seen"] += 1
    except OSError:
        pass
    try:
        con = sqlite3.connect(f"file:{QFX_DB}?mode=ro", uri=True)
        ctx["qfx_trades_today"] = con.execute(
            "SELECT count(*) FROM trades WHERE ts LIKE ?", (day + "%",)).fetchone()[0]
        con.close()
    except sqlite3.Error:
        pass
    try:
        hb = json.loads(QFX_HEARTBEAT.read_text())
        ctx["heartbeat_age_min"] = round(
            (datetime.now(timezone.utc).timestamp() - hb["ts"]) / 60, 1)
        ctx["halted"] = hb.get("halted")
    except (OSError, ValueError, KeyError):
        pass
    for svc in SERVICES:
        state = subprocess.run(["systemctl", "is-active", svc],
                               capture_output=True, text=True).stdout.strip()
        ctx["services"][svc] = state
    return ctx


def self_heal(ctx: dict, enabled: bool) -> list[str]:
    actions = []
    for svc, state in ctx["services"].items():
        if state != "active":
            if enabled:
                subprocess.run(["systemctl", "restart", svc], capture_output=True)
                after = subprocess.run(["systemctl", "is-active", svc],
                                       capture_output=True, text=True).stdout.strip()
                actions.append(f"restarted {svc} (was {state}, now {after})")
            else:
                actions.append(f"WOULD restart {svc} (was {state}) [--no-heal]")
    hb = ctx.get("heartbeat_age_min")
    if hb is not None and hb > 15 and ctx["services"].get("quantumfx.service") == "active":
        if enabled:
            subprocess.run(["systemctl", "restart", "quantumfx.service"], capture_output=True)
            actions.append(f"quantumfx heartbeat stale ({hb} min) — restarted service")
        else:
            actions.append(f"quantumfx heartbeat stale ({hb} min) [--no-heal]")
    return actions


def current_model() -> str:
    """Provider/model the Hermes agent is currently on. The operator switches this
    over time (openai-codex/gpt-5.5 as of 2026-07-02); everything here routes
    through it dynamically, so the review is model-agnostic by construction."""
    try:
        import yaml
        m = (yaml.safe_load(HERMES_CONFIG.read_text()) or {}).get("model") or {}
        return f"{m.get('provider', '?')}/{m.get('default', '?')}"
    except Exception:
        return "unknown"


def ask_model(prompt: str, timeout: int = 300) -> str:
    """One-shot prompt through the Hermes agent, which answers with whatever
    model it is currently configured to run. Falls back to the claude CLI
    (claude.ai login on this box), then returns "" — callers must fail soft."""
    env = {"PATH": "/root/.local/bin:/usr/local/bin:/usr/bin:/bin", "HOME": "/root"}
    try:
        proc = subprocess.run(["hermes", "-z", prompt], capture_output=True,
                              text=True, timeout=timeout, env=env)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    except Exception:
        pass
    try:
        # No ANTHROPIC_API_KEY on purpose: the key in trading-secrets.env is
        # stale and would shadow the working claude.ai login on this box.
        proc = subprocess.run(["claude", "-p", prompt, "--model", "sonnet"],
                              capture_output=True, text=True, timeout=timeout, env=env)
        return proc.stdout
    except Exception:
        return ""


def _model_json(prompt: str) -> dict:
    out = ask_model(prompt)
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {}


def governor_severity() -> tuple[str, list]:
    """Fresh risk-governor evaluation (ok/warn/block) + issues, fail-closed."""
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "risk_governor.py")],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT))
        result = json.loads(proc.stdout)
        return result.get("severity", "block"), result.get("issues", [])
    except Exception:
        return "block", []


# Smart-heal action whitelist: the model proposes, this code decides. Every
# action is validated against live facts before it runs — the model can never
# invent a target or clear a block that is still justified.
HEAL_ACTIONS = ("restart_service", "clear_stale_risk_block", "none")


def smart_heal(ctx: dict, trades: list[dict], anomalies: list[str],
               enabled: bool, use_llm: bool) -> list[str]:
    """LLM-driven diagnosis on top of the deterministic self_heal floor."""
    actions = self_heal(ctx, enabled)
    severity, issues = governor_severity()
    block_info = None
    if RISK_BLOCK.exists():
        try:
            block_info = json.loads(RISK_BLOCK.read_text())
        except ValueError:
            block_info = {"raw": RISK_BLOCK.read_text()[:500]}
    if not use_llm:
        return actions

    logs = {}
    for name, path in (("quantumfx", QFX_LOG),
                       ("fx-live-bot", Path("/root/working-on/fx-live-bot/bot.log"))):
        try:
            logs[name] = path.read_text(errors="replace").splitlines()[-40:]
        except OSError:
            logs[name] = []
    evidence = {
        "services": ctx["services"],
        "heartbeat_age_min": ctx.get("heartbeat_age_min"),
        "halts_today": ctx.get("halts"),
        "risk_governor": {"severity": severity, "issues": issues},
        "risk_block_file": block_info,
        "deterministic_actions_already_taken": actions,
        "todays_anomalies": anomalies,
        "n_trades_today": len(trades),
        "log_tails": logs,
    }
    diag = _model_json(
        "You are the self-heal brain for a live FX trading VPS (OANDA, two "
        "bots: quantumfx + fx-live-bot, shared account). Diagnose the system "
        "from the evidence and propose remedial actions. Reply with ONLY a "
        "JSON object: {\"diagnosis\": [\"...\"], \"actions\": [{\"action\": "
        f"one of {list(HEAL_ACTIONS)}, \"target\": \"service name if "
        "restart\", \"reason\": \"...\"}]}. Rules: propose "
        "clear_stale_risk_block ONLY if the block file's cause is visibly "
        "resolved in the evidence; propose restarts ONLY for services that "
        "are failing or wedged right now, not as hygiene; prefer no actions "
        "when the system is healthy. Keep diagnosis bullets under 25 words."
        "\n\nEVIDENCE:\n" + json.dumps(evidence, default=str))

    for d in (diag.get("diagnosis") or [])[:6]:
        actions.append(f"diagnosis: {d}")
    for a in diag.get("actions") or []:
        kind, target = a.get("action"), a.get("target", "")
        reason = str(a.get("reason", ""))[:140]
        if kind not in HEAL_ACTIONS or kind == "none":
            continue
        if kind == "restart_service":
            # validate: known service AND currently not healthy
            if target not in SERVICES or ctx["services"].get(target) == "active":
                actions.append(f"REJECTED model restart of '{target}' (healthy/unknown)")
                continue
            if enabled:
                subprocess.run(["systemctl", "restart", target], capture_output=True)
                actions.append(f"model-directed restart of {target}: {reason}")
            else:
                actions.append(f"WOULD restart {target} ({reason}) [--no-heal]")
        elif kind == "clear_stale_risk_block":
            # validate: file exists AND a fresh governor run no longer blocks
            if not RISK_BLOCK.exists() or severity == "block":
                actions.append("REJECTED clear_stale_risk_block (still justified or absent)")
                continue
            if enabled:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                RISK_BLOCK.rename(STATE / f"GLOBAL_RISK_BLOCK.cleared-{stamp}")
                actions.append(f"cleared stale GLOBAL_RISK_BLOCK (governor now "
                               f"'{severity}'; archived .cleared-{stamp}): {reason}")
            else:
                actions.append(f"WOULD clear stale GLOBAL_RISK_BLOCK ({reason}) [--no-heal]")
    return actions


def llm_lessons(day: str, payload: dict) -> dict:
    """Daily review by the current Hermes model. Fail-soft: returns {}."""
    bounds = {k: list(v) for k, v in WHITELIST.items()}
    prompt = (
        "You are the nightly reviewer for a live OU mean-reversion FX system "
        "(OANDA, tiny account). Below is today's structured trading day. "
        "Reply with ONLY a JSON object: {\"good\": [..], \"bad\": [..], "
        "\"lessons\": [..], \"candidates\": [{\"param\":.., \"value\":.., "
        "\"rationale\":..}]}. Rules: candidates may ONLY use params/bounds "
        f"{json.dumps(bounds)}; propose a candidate ONLY if today's evidence "
        "genuinely suggests it (usually propose none — one day is noise); "
        "never suggest loosening z_in below 2.0; keep each bullet under 25 "
        "words; judge PROCESS separately from OUTCOME.\n\nDAY:\n"
        + json.dumps(payload, default=str)
    )
    return _model_json(prompt)


def queue_candidates(day: str, candidates: list[dict]) -> list[dict]:
    accepted = []
    try:
        queue = json.loads(QUEUE.read_text()) if QUEUE.exists() else []
        if not isinstance(queue, list):
            raise ValueError("queue is not a list")
    except ValueError:
        # preserve the corrupt file for forensics instead of silently wiping it
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        QUEUE.rename(QUEUE.with_suffix(f".corrupt-{stamp}"))
        queue = []
    for c in candidates or []:
        p, v = c.get("param"), c.get("value")
        if p not in WHITELIST:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        lo, hi = WHITELIST[p]
        if not lo <= v <= hi:
            continue
        if any(q["param"] == p and q["value"] == v and q["status"] == "queued" for q in queue):
            continue
        entry = {"param": p, "value": v, "rationale": c.get("rationale", ""),
                 "source_date": day, "status": "queued"}
        queue.append(entry)
        accepted.append(entry)
    QUEUE.write_text(json.dumps(queue, indent=2))
    return accepted


def journal(day: str, summary: dict, trades: list[dict]) -> None:
    con = sqlite3.connect(JOURNAL_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS days(
        date TEXT PRIMARY KEY, nav REAL, realized_pl REAL, financing REAL,
        n_trades INTEGER, n_bad_process INTEGER, anomalies TEXT,
        heal_actions TEXT, lessons TEXT, created_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS trades(
        date TEXT, trade_id TEXT, instrument TEXT, tag TEXT, units REAL,
        entry REAL, exit REAL, pl REAL, pl_pct REAL, risk_at_sl_pct REAL,
        held_minutes INTEGER, process TEXT, issues TEXT, close_reason TEXT,
        PRIMARY KEY(date, trade_id))""")
    con.execute("INSERT OR REPLACE INTO days VALUES(?,?,?,?,?,?,?,?,?,?)", (
        day, summary["nav"], summary["realized_pl"], summary["financing"],
        len(trades), sum(1 for t in trades if t["process"] == "bad"),
        json.dumps(summary["anomalies"]), json.dumps(summary["heal_actions"]),
        json.dumps(summary.get("lessons", {})), datetime.now(timezone.utc).isoformat()))
    for t in trades:
        con.execute("INSERT OR REPLACE INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            day, t["trade_id"], t["instrument"], t.get("tag"), t.get("units"),
            t.get("entry_price"), t.get("exit_price"), t.get("pl"),
            t.get("pl_pct"), t.get("risk_at_sl_pct"), t.get("held_minutes"),
            t["process"], json.dumps(t["issues"] + t["notes"]), t.get("close_reason")))
    con.commit()
    con.close()


def write_report(day: str, summary: dict, trades: list[dict], ctx: dict) -> Path:
    L = [f"# Daily review — {day}", "",
         f"Reviewed by: {summary.get('model', 'unknown')} (Hermes current model)", "",
         f"NAV £{summary['nav']:.2f} | realized P/L £{summary['realized_pl']:+.2f} "
         f"| financing £{summary['financing']:+.4f} | trades touched: {len(trades)} "
         f"| halts today: {ctx['halts']}", ""]
    if summary["anomalies"]:
        L += ["## Anomalies"] + [f"- {a}" for a in summary["anomalies"]] + [""]
    if summary["heal_actions"]:
        L += ["## Self-heal actions"] + [f"- {a}" for a in summary["heal_actions"]] + [""]
    if trades:
        L += ["## Trades", "",
              "| id | pair | tag | units | P/L £ | P/L % | risk@SL % | held | process | reason |",
              "|---|---|---|---:|---:|---:|---:|---:|---|---|"]
        for t in sorted(trades, key=lambda x: x.get("pl") or 0):
            L.append(f"| {t['trade_id']} | {t['instrument']} | {t.get('tag') or 'UNTAGGED'} "
                     f"| {t.get('units') or '?'} | {t.get('pl') if t.get('pl') is not None else 'open'} "
                     f"| {t.get('pl_pct', '')} | {t.get('risk_at_sl_pct', '')} "
                     f"| {str(t['held_minutes']) + 'm' if t.get('held_minutes') is not None else '?'} | {t['process']} "
                     f"| {'; '.join(t['issues'] + t['notes']) or 'clean'} |")
        L.append("")
    lessons = summary.get("lessons") or {}
    for section in ("good", "bad", "lessons"):
        if lessons.get(section):
            L += [f"## {section.title()}"] + [f"- {x}" for x in lessons[section]] + [""]
    if summary.get("queued"):
        L += ["## Evolution candidates queued (weekend research gate decides)"]
        L += [f"- {c['param']} -> {c['value']} ({c['rationale']})" for c in summary["queued"]]
        L.append("")
    L += [f"Bot context: {json.dumps(ctx)}", ""]
    path = REPORTS / f"daily_review_{day}.md"
    path.write_text("\n".join(L))
    (REPORTS / "daily_review_latest.md").write_text("\n".join(L))
    return path


def telegram(text: str) -> bool:
    env = read_env(HERMES_ENV)
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_HOME_CHANNEL")
    if not token or not chat:
        (REPORTS / "pending_alert.txt").write_text(text)
        return False
    data = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None,
                    help="review this calendar day (UTC); default: rolling "
                         "24h window ending now, so nothing between runs is missed")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-heal", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    if args.date:
        day = args.date
        frm, to = f"{day}T00:00:00Z", f"{day}T23:59:59Z"
    else:
        day = now.strftime("%Y-%m-%d")
        frm = (now - timedelta(hours=24, minutes=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
        to = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    oanda = Oanda(read_env(FOREXBOT_ENV))
    acct = oanda.summary()
    nav = float(acct["NAV"])
    if args.date:
        # backdated run: grade against that day's NAV, not today's
        try:
            con = sqlite3.connect(f"file:{QFX_DB}?mode=ro", uri=True)
            row = con.execute("SELECT nav FROM equity WHERE ts LIKE ? "
                              "ORDER BY ts DESC LIMIT 1", (day + "%",)).fetchone()
            con.close()
            if row:
                nav = float(row[0])
        except sqlite3.Error:
            pass
    txns = oanda.window_transactions(frm, to)
    trades, financing = reconstruct(txns)
    trades = [grade(t, nav) for t in trades]
    realized = sum(t["pl"] or 0 for t in trades)

    ctx = bot_context(day)
    anomalies = []
    for t in trades:
        for issue in t["issues"]:
            anomalies.append(f"{t['instrument']} #{t['trade_id']}: {issue}")
    for t in txns:
        if "MARGIN_CALL" in t.get("type", ""):
            anomalies.append(f"OANDA {t['type']} at {t['time'][:19]} — "
                             "account entered/changed margin-call state")
    cancels = sum(1 for t in txns if t.get("type") == "ORDER_CANCEL"
                  and t.get("reason") not in ("CLIENT_REQUEST", "LINKED_TRADE_CLOSED"))
    if cancels:
        anomalies.append(f"{cancels} order(s) cancelled by OANDA (not client-requested)")
    if ctx["halts"]:
        anomalies.append(f"daily-loss halt fired ({ctx['halts']} log hits)")
    heal_actions = smart_heal(ctx, trades, anomalies,
                              enabled=not args.no_heal, use_llm=not args.no_llm)

    summary = {"nav": nav, "realized_pl": realized, "financing": financing,
               "anomalies": anomalies, "heal_actions": heal_actions,
               "model": current_model()}

    if not args.no_llm:
        summary["lessons"] = llm_lessons(day, {
            "date": day, "nav": nav, "realized_pl": realized,
            "trades": trades, "context": ctx, "anomalies": anomalies})
        summary["queued"] = queue_candidates(day, summary["lessons"].get("candidates", []))

    journal(day, summary, trades)
    report = write_report(day, summary, trades, ctx)

    closed = [t for t in trades if t.get("pl") is not None]
    wins = sum(1 for t in closed if t["pl"] > 0)
    bad = sum(1 for t in trades if t["process"] == "bad")
    lines = [f"🩺 Daily review {day} (model: {summary.get('model', '?')})",
             f"NAV £{nav:.2f}, realized £{realized:+.2f}, "
             f"{len(closed)} closed ({wins} wins), {bad} with process issues"]
    lines += [f"⚠️ {a}" for a in anomalies[:5]]
    lines += [f"🔧 {a}" for a in heal_actions]
    for x in (summary.get("lessons") or {}).get("lessons", [])[:3]:
        lines.append(f"💡 {x}")
    for c in summary.get("queued", []):
        lines.append(f"🧬 queued {c['param']}={c['value']} for weekend research gate")
    if not args.no_notify:
        telegram("\n".join(lines))
    print(report)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
