#!/usr/bin/env python3
"""Side-by-side comparison of the two live OANDA bots (fx-live-bot vs quantumfx).

Attribution: quantumfx tags every order (clientExtensions.tag='quantumfx');
anything untagged on this account is fx-live-bot (or pre-June legacy residue).
Output is plain text, Telegram-friendly (no markdown tables).

Usage: compare_bots.py [--closed N]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/root/quantumfx-bot")
from quantumfx.oanda import OandaClient  # noqa: E402

QFX_STATE = Path("/root/quantumfx-bot/state")
FB_ANALYST = Path("/root/fx-live-bot/analyst_report.json")

# walk-forward validated expectations (research/STRATEGY_RESEARCH.md §5)
QFX_VALIDATION = "backtest 2022-26 OOS: +10.6%/yr, Sharpe 0.80, maxDD -16%"


def tag_of(t: dict) -> str:
    return (t.get("clientExtensions") or {}).get("tag", "")


def owner(t: dict) -> str:
    return "quantumfx" if tag_of(t) == "quantumfx" else "fx-live-bot"


def stats(trades: list[dict]) -> dict:
    pls = [float(t.get("realizedPL", 0)) for t in trades]
    wins = [p for p in pls if p > 0]
    losses = [p for p in pls if p <= 0]
    gross_w, gross_l = sum(wins), -sum(losses)
    return {
        "n": len(pls),
        "net": sum(pls),
        "wr": 100 * len(wins) / len(pls) if pls else 0.0,
        "pf": (gross_w / gross_l) if gross_l > 0 else float("inf") if gross_w else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
    }


def fmt_side(name: str, s: dict, extra: list[str]) -> list[str]:
    out = [f"— {name} —"]
    if s["n"]:
        out += [
            f"closed trades: {s['n']}",
            f"net P/L: £{s['net']:+.2f}",
            f"win rate: {s['wr']:.0f}%",
            f"profit factor: {s['pf']:.2f}" if s["pf"] != float("inf") else "profit factor: inf (no losses yet)",
            f"avg win £{s['avg_win']:+.2f} / avg loss £{s['avg_loss']:+.2f}",
        ]
    else:
        out += ["closed trades: 0 (no completed trades yet)"]
    out += extra
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--closed", type=int, default=50)
    args = ap.parse_args()

    c = OandaClient()
    acct = c.summary()
    nav = float(acct["NAV"])
    margin_used = float(acct.get("marginUsed", 0))

    r = c._get(f"/v3/accounts/{c.account_id}/trades", state="CLOSED", count=args.closed)
    closed = r.get("trades", [])
    open_tr = c.open_trades()

    by = {"fx-live-bot": [], "quantumfx": []}
    for t in closed:
        by[owner(t)].append(t)
    open_by = {"fx-live-bot": [], "quantumfx": []}
    for t in open_tr:
        open_by[owner(t)].append(t)

    fb_extra = [f"open now: {len(open_by['fx-live-bot'])}"]
    try:
        rep = json.loads(FB_ANALYST.read_text())
        fb_extra.append(f"analyst verdict: {rep.get('verdict', '?')}")
    except Exception:
        pass
    fb_extra += [
        "live since: ~2026-06-10",
        f"account growth since start: {100 * (nav / 15.46 - 1):+.1f}%",
        "strategy: EMA pullback + breakout (H1, 07-17 UTC)",
    ]

    qfx_extra = [f"open now: {len(open_by['quantumfx'])}"]
    try:
        hb = json.loads((QFX_STATE / "heartbeat.json").read_text())
        age = (datetime.now(timezone.utc).timestamp() - hb["ts"]) / 60
        qfx_extra.append(f"heartbeat: {hb['status']} ({age:.0f}m ago)")
    except Exception:
        qfx_extra.append("heartbeat: MISSING")
    kill = Path("/root/quantumfx-bot/KILL").exists()
    qfx_extra += [
        f"entries: {'FROZEN (KILL file)' if kill else 'armed'}",
        "live since: 2026-07-01",
        "strategy: OU mean-reversion (H4, 24/5, 12 pairs)",
        QFX_VALIDATION,
    ]

    lines = [
        f"ACCOUNT £{nav:.2f} NAV, margin used £{margin_used:.2f}",
        f"(last {len(closed)} closed trades attributed by order tag)",
        "",
        *fmt_side("ForexBot", stats(by["fx-live-bot"]), fb_extra),
        "",
        *fmt_side("QuantumFX", stats(by["quantumfx"]), qfx_extra),
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
