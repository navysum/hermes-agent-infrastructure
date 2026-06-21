#!/usr/bin/env python3
"""OANDA NAV + manual signal alerts for the operator.

Safe/read-only: fetches account/signal data and prints alerts only when there is
something worth delivering. Intended for Hermes cron with no_agent=True so stdout
is sent to the operator; empty stdout stays silent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path('/root/.hermes/state/oanda_signal_alerts.json')
BB_DIR = Path('/root/signal-bot')
QFX_DIR = Path('/root/fx-signal-bot')
NAV_LOW_THRESHOLD = 10.0
NAV_ALERT_COOLDOWN_SECONDS = 6 * 60 * 60


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(STATE_PATH)


def load_env(path: Path) -> dict:
    vals = {}
    if not path.exists():
        return vals
    for raw in path.read_text(errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def fetch_oanda_summary() -> dict | None:
    env = load_env(BB_DIR / '.env')
    token = env.get('OANDA_API_KEY')
    account = env.get('OANDA_ACCOUNT_ID')
    oanda_env = env.get('OANDA_ENV', 'live').lower()
    if not token or not account:
        return None
    base = 'https://api-fxpractice.oanda.com' if oanda_env == 'practice' else 'https://api-fxtrade.oanda.com'
    req = urllib.request.Request(
        f'{base}/v3/accounts/{account}/summary',
        headers={'Authorization': f'Bearer {token}'},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    a = data.get('account', {})
    return {
        'env': oanda_env,
        'currency': a.get('currency', 'GBP'),
        'balance': float(a.get('balance', 0)),
        'nav': float(a.get('NAV', a.get('balance', 0))),
        'unrealizedPL': float(a.get('unrealizedPL', 0)),
        'openTradeCount': int(a.get('openTradeCount', 0)),
        'openPositionCount': int(a.get('openPositionCount', 0)),
        'pl': float(a.get('pl', 0)),
        'financing': float(a.get('financing', 0)),
    }


def nav_alert(state: dict) -> list[str]:
    alerts = []
    try:
        summary = fetch_oanda_summary()
    except Exception as e:
        return [f"⚠️ OANDA NAV alert check failed: {type(e).__name__}: {e}"]
    if not summary:
        return ["⚠️ OANDA NAV alert check failed: credentials not found server-side."]
    now = time.time()
    nav = summary['nav']
    ccy = summary['currency']
    was_low = bool(state.get('nav_was_low'))
    last_sent = float(state.get('nav_low_last_sent', 0))
    if nav < NAV_LOW_THRESHOLD and now - last_sent >= NAV_ALERT_COOLDOWN_SECONDS:
        needed = NAV_LOW_THRESHOLD - nav
        alerts.append(
            f"🚨 OANDA NAV low: {ccy} {nav:.2f} (< {ccy} {NAV_LOW_THRESHOLD:.2f}). "
            f"Deposit at least {ccy} {needed:.2f} to clear the dashboard warning; {ccy} 5.00 gives a tiny buffer. "
            f"Open trades: {summary['openTradeCount']} | Unrealized P/L: {summary['unrealizedPL']:.2f}."
        )
        state['nav_low_last_sent'] = now
    if nav >= NAV_LOW_THRESHOLD and was_low:
        alerts.append(f"✅ OANDA NAV recovered: {ccy} {nav:.2f} — low-NAV warning should be clear.")
    state['nav_was_low'] = nav < NAV_LOW_THRESHOLD
    state['last_nav'] = nav
    return alerts


def bb_rsi_alerts(state: dict) -> list[str]:
    alerts = []
    old_cwd = os.getcwd()
    try:
        os.chdir(BB_DIR)
        sys.path.insert(0, str(BB_DIR))
        import production_bot as bot  # type: ignore
        client = bot.OandaClient(slack=None)
        account = client.get_account()
        balance = float(account['balance'])
        currency = account.get('currency', 'GBP')
        now = datetime.now(timezone.utc)
        news_events = bot.load_news_events()
        for pair in bot.PAIRS:
            cfg = bot.PAIR_CONFIGS[pair]
            df = bot.calc_indicators(client.get_candles(pair, count=bot.CANDLES_NEEDED), cfg)
            if df.empty:
                continue
            sig = bot.get_signal(df, cfg)
            if sig is None:
                continue
            direction = 'BUY' if sig['direction'] == 1 else 'SELL'
            last_time = str(df.index[-1])
            key = f"bb:{pair}:{direction}:{last_time}:{sig['entry']:.5f}"
            if state.get('last_bb_signal_key') == key:
                continue
            pat_ok = bot.passes_pattern_filter(df, sig['direction'])
            sess_ok = bot.in_trading_session(now)
            news_block = bot.near_news_event(news_events, now)
            try:
                spread = client.get_spread_pips(pair)
            except Exception:
                spread = None
            spread_limit = bot.SPREAD_LIMIT_PIPS.get(pair, 2.5)
            spread_ok = spread is not None and spread <= spread_limit
            est_units = bot.calc_units_from_allocation(pair, balance * bot.CAPITAL_ALLOC_PCT, sig['entry'], currency, client)
            auto_ready = pat_ok and sess_ok and not news_block and spread_ok
            alerts.append(
                f"📣 BB+RSI manual signal: {direction} {pair} @ {sig['entry']:.5f}\n"
                f"SL {sig['sl']:.5f} | TP {sig['tp']:.5f} | RSI {sig['rsi']:.1f} | ATR {sig['atr']:.5f}\n"
                f"Est units {est_units} using {bot.CAPITAL_ALLOC_PCT:.0%} allocation of {currency} {balance:.2f}.\n"
                f"Auto-trade filters: {'READY' if auto_ready else 'BLOCKED'} "
                f"(session={sess_ok}, news={'clear' if not news_block else news_block}, spread={spread if spread is not None else 'unknown'}p/{spread_limit}p).\n"
                f"Manual note: check OANDA open trades first so you don't double-enter alongside Homer’s automatic Strategy bot."
            )
            state['last_bb_signal_key'] = key
    except Exception as e:
        alerts.append(f"⚠️ BB+RSI manual signal alert check failed: {type(e).__name__}: {e}")
    finally:
        os.chdir(old_cwd)
        try:
            sys.path.remove(str(BB_DIR))
        except ValueError:
            pass
    return alerts


def fx_signal_alerts(state: dict) -> list[str]:
    if not QFX_DIR.exists():
        return []
    try:
        env = os.environ.copy()
        env['PYTHONPATH'] = 'src'
        proc = subprocess.run(
            [sys.executable, 'scripts/current_signal.py', '--instrument', 'USD_JPY', '--threshold', '0.30', '--model', 'fx_signal', '--target-mode', 'next_close', '--allow-live-data'],
            cwd=str(QFX_DIR), env=env, capture_output=True, text=True, timeout=45,
        )
        if proc.returncode != 0:
            return [f"⚠️ FX signal alert check failed: {proc.stderr.strip()[-300:]}"]
        sig = json.loads(proc.stdout)
        signal = sig.get('signal', 'FLAT')
        if signal == 'FLAT':
            return []
        key = f"qfx:{signal}:{sig.get('latest_time')}:{sig.get('score')}"
        if state.get('last_qfx_signal_key') == key:
            return []
        state['last_qfx_signal_key'] = key
        return [
            f"📣 FX manual signal: {signal} USD_JPY @ {sig.get('latest_close')}\n"
            f"Score {sig.get('score')} vs threshold {sig.get('threshold')} | regime {sig.get('regime')} | model {sig.get('model_key')}/{sig.get('target_mode')}.\n"
            f"Automatic timer is live-capable too; check OANDA open trades before manual entry."
        ]
    except Exception as e:
        return [f"⚠️ FX signal alert check failed: {type(e).__name__}: {e}"]


def main() -> int:
    state = load_state()
    messages = []
    messages.extend(nav_alert(state))
    messages.extend(bb_rsi_alerts(state))
    messages.extend(fx_signal_alerts(state))
    state['last_checked_utc'] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    if messages:
        print('\n\n'.join(messages))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
