#!/usr/bin/env python3
"""Market watchdog — monitors the market data bot.
Prints only when something worth alerting on changes.
"""
from __future__ import annotations
import json, sqlite3, subprocess, time
from pathlib import Path
from datetime import datetime, timezone

BOT_DIR = Path('/root/market-bot')
DB = BOT_DIR / 'state.sqlite3'
STATE = Path('/root/.hermes/state/market_watchdog_state.json')
STATE.parent.mkdir(parents=True, exist_ok=True)

now = datetime.now(timezone.utc).isoformat(timespec='seconds')
alerts = []

def sh(cmd):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=20)

svc = sh('systemctl is-active market-bot.service 2>/dev/null || true').stdout.strip()
if svc != 'active':
    alerts.append(f'🚨 market-bot.service is {svc or "unknown"}')

# Recent service errors/warnings.
logs = sh("journalctl -u market-bot.service --since '35 minutes ago' --no-pager -o cat 2>/dev/null | tail -120").stdout.splitlines()
noisy = [l for l in logs if any(x in l.lower() for x in ['error', 'exception', 'traceback', 'failed', 'insufficient', 'blocked'])]
if noisy:
    alerts.append('⚠️ Recent bot warnings/errors:\n' + '\n'.join(noisy[-8:]))

snapshot = {'ts': now, 'service': svc, 'balance': None, 'open_trades': [], 'trade_count': None, 'latest_log': logs[-1] if logs else None}
try:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    row = con.execute('select balance, updated_at from account_state order by id desc limit 1').fetchone()
    if row:
        snapshot['balance'] = float(row['balance'])
        snapshot['balance_updated_at'] = row['updated_at']
    trades = con.execute("select id,pair,signal,entry,size,strategy,tp,sl,opened_at,exit from trades order by id").fetchall()
    snapshot['trade_count'] = len(trades)
    snapshot['open_trades'] = [dict(r) for r in trades if r['exit'] is None]
except Exception as e:
    alerts.append(f'🚨 Could not read state.sqlite3: {e}')

prev = None
if STATE.exists():
    try: prev = json.loads(STATE.read_text())
    except Exception: prev = None

if prev:
    if snapshot.get('balance') is not None and prev.get('balance') is not None:
        delta = snapshot['balance'] - prev['balance']
        if abs(delta) >= 10:
            alerts.append(f'💰 Paper balance moved by {delta:+.2f}: {prev["balance"]:.2f} → {snapshot["balance"]:.2f}')
    prev_open = {str(t.get('id')): t for t in prev.get('open_trades', [])}
    cur_open = {str(t.get('id')): t for t in snapshot.get('open_trades', [])}
    new_ids = sorted(set(cur_open) - set(prev_open), key=lambda x: int(x) if x.isdigit() else x)
    closed_ids = sorted(set(prev_open) - set(cur_open), key=lambda x: int(x) if x.isdigit() else x)
    for i in new_ids:
        t = cur_open[i]
        alerts.append(f'🟢 New paper trade opened: #{i} {t.get("pair")} {t.get("signal")} @ {t.get("entry")} ({t.get("strategy")})')
    for i in closed_ids:
        t = prev_open[i]
        alerts.append(f'🔴 Paper trade no longer open: #{i} {t.get("pair")} {t.get("signal")}')
else:
    # First run baseline: only alert if risk already noteworthy.
    if len(snapshot.get('open_trades', [])) >= 4:
        alerts.append(f'⚠️ Baseline risk: {len(snapshot["open_trades"])} open paper trades')

if len(snapshot.get('open_trades', [])) >= 4:
    alerts.append(f'⚠️ Open paper trades now {len(snapshot["open_trades"])} — getting a bit Weasley-car-in-the-sky.')

STATE.write_text(json.dumps(snapshot, indent=2, default=str))

if alerts:
    print('## Work-mode crypto watchdog — ' + datetime.now().strftime('%H:%M'))
    print('\n'.join(alerts))
    if snapshot.get('open_trades'):
        print('\nOpen tracked trades:')
        for t in snapshot['open_trades']:
            print(f'- #{t.get("id")} {t.get("pair")} {t.get("signal")} entry {t.get("entry")} TP {t.get("tp")} SL {t.get("sl")}')
