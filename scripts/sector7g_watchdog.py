#!/usr/bin/env python3
"""the operator Sector 7-G trading watchdog.
Prints ONLY when something needs the operator's attention; silence means all normal.
No order placement. No config mutation. No secrets printed.
"""
import os, re, sqlite3, subprocess, json
from datetime import datetime, timezone

SERVICES = [
    "forexbot.service",
    "crypto-bot.service",
    "crypto-bot-lab.service",
    "quantum-fx-usdjpy-execution.timer",
]
OPTIONAL_ONESHOT = "quantum-fx-usdjpy-execution.service"
MIN_OANDA_NAV_GBP = 14.00
MAX_OPEN_OANDA_TRADES = 1


def env(path):
    d = {}
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return d


def run(args, timeout=12):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception as e:
        return f"ERR:{e}"


def service_active(s):
    return run(["systemctl", "is-active", s], 5)


def journal_tail(s, n="20"):
    txt = run(["journalctl", "-u", s, "-n", n, "--no-pager"], 15)
    txt = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]+", r"\1[REDACTED]", txt)
    txt = re.sub(r"(Authorization[:=]\s*)[^\s]+", r"\1[REDACTED]", txt, flags=re.I)
    return txt


def check_oanda(alerts):
    e = env("/root/bots/forexbot/.env")
    token = e.get("OANDA_API_KEY") or e.get("OANDA_ACCESS_TOKEN")
    acct = e.get("OANDA_ACCOUNT_ID")
    if not token or not acct:
        alerts.append("D'oh: OANDA env missing token/account id for watchdog read.")
        return
    oanda_env = (e.get("OANDA_ENV") or e.get("OANDA_ENVIRONMENT") or "").lower()
    api = e.get("OANDA_API_URL") or ("https://api-fxtrade.oanda.com" if oanda_env == "live" else "https://api-fxpractice.oanda.com")
    try:
        import requests
        h = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{api}/v3/accounts/{acct}/summary", headers=h, timeout=15)
        if not r.ok:
            alerts.append(f"D'oh: OANDA summary read failed HTTP {r.status_code}.")
            return
        a = r.json().get("account", {})
        nav = float(a.get("NAV", 0))
        open_trades = int(a.get("openTradeCount", 0))
        margin_used = float(a.get("marginUsed", 0))
        if nav < MIN_OANDA_NAV_GBP:
            alerts.append(f"D'oh: OANDA NAV low: £{nav:.2f} < £{MIN_OANDA_NAV_GBP:.2f}.")
        if open_trades > MAX_OPEN_OANDA_TRADES:
            alerts.append(f"D'oh: OANDA open trades high: {open_trades} > {MAX_OPEN_OANDA_TRADES}.")
        if margin_used > 0 and nav > 0 and margin_used / nav > 0.25:
            alerts.append(f"D'oh: OANDA margin used {margin_used:.2f} is >25% of NAV £{nav:.2f}.")
    except Exception as ex:
        alerts.append(f"D'oh: OANDA watchdog exception: {ex}")


def check_quantum(alerts):
    db = "/root/quantum-forex-bot/state/live_execution.sqlite3"
    if not os.path.exists(db):
        alerts.append("D'oh: Quantum FX live_execution.sqlite3 missing.")
        return
    try:
        con = sqlite3.connect(db)
        row = con.execute("SELECT created_at_utc, mode, action, detail_json FROM run_events ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            alerts.append("D'oh: Quantum FX has no run_events.")
            return
        created, mode, action, detail = row
        # Alert only for real live-risk actions/errors, not normal flat/open-trade skips
        # or paper/dry-run evidence collection. Paper INTENT_RECORDED is healthy
        # forward-test evidence, not an emergency.
        normal_actions = {
            "SKIP_FLAT",
            "SKIP_OPEN_TRADE_EXISTS",
            "INTENT_RECORDED",
            "PAPER_INTENT_RECORDED",
            "DRY_RUN_READY",
        }
        if action not in normal_actions:
            alerts.append(f"Quantum FX action: {action} mode={mode} at {created}. Detail: {detail[:300]}")
    except Exception as ex:
        alerts.append(f"D'oh: Quantum FX DB check failed: {ex}")


def check_crypto_ledgers(alerts):
    for label, db, min_bal in [
        ("crypto main", "/root/crypto-bot/state.sqlite3", 990.0),
        ("crypto lab", "/root/crypto-bot-lab/state.sqlite3", 490.0),
    ]:
        if not os.path.exists(db):
            alerts.append(f"D'oh: {label} ledger missing: {db}")
            continue
        try:
            con = sqlite3.connect(db)
            bal_row = con.execute("SELECT balance, updated_at FROM account_state ORDER BY id DESC LIMIT 1").fetchone()
            open_count = con.execute("SELECT COUNT(*) FROM trades WHERE status='open'").fetchone()[0]
            if bal_row and float(bal_row[0]) < min_bal:
                alerts.append(f"D'oh: {label} paper balance low: {float(bal_row[0]):.2f} < {min_bal:.2f}.")
            if open_count > 1:
                alerts.append(f"D'oh: {label} has {open_count} open paper trades.")
        except Exception as ex:
            alerts.append(f"D'oh: {label} ledger check failed: {ex}")


def main():
    alerts = []
    for s in SERVICES:
        st = service_active(s)
        if st != "active":
            alerts.append(f"D'oh: {s} is {st}, expected active.")
    # oneshot service is normally inactive; alert only failed
    if service_active(OPTIONAL_ONESHOT) == "failed":
        alerts.append(f"D'oh: {OPTIONAL_ONESHOT} failed.")

    for s in ["crypto-bot.service", "crypto-bot-lab.service", "quantum-fx-usdjpy-execution.service"]:
        tail = journal_tail(s)
        bad = [ln for ln in tail.splitlines() if re.search(r"\b(ERROR|CRITICAL|Traceback|Exception|failed|rejected)\b", ln, re.I)]
        if bad:
            alerts.append(f"{s} suspicious log lines:\n" + "\n".join(bad[-4:]))

    check_oanda(alerts)
    check_quantum(alerts)
    check_crypto_ledgers(alerts)

    if alerts:
        print("Sector 7-G trading watchdog alert — " + datetime.now(timezone.utc).isoformat(timespec="seconds"))
        print("\n".join(f"- {a}" for a in alerts))
        print("No autonomous trades placed; this is monitor/guardrail output only.")

if __name__ == "__main__":
    main()
