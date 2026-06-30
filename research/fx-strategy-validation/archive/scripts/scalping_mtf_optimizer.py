#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/quantum-forex-bot/src")
from quantum_forex_bot.oanda_data import fetch_oanda_candles  # noqa: E402
from quantum_forex_bot.execution import entry_price, hit_stop_or_target, open_exit_price  # noqa: E402

PAIRS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "EUR_JPY", "GBP_JPY", "USD_CAD", "NZD_USD", "EUR_GBP"]
CACHE_DIR = Path("/root/bots/forexbot/shadow/cache")


def pip_size(instrument: str) -> float:
    return 0.01 if "JPY" in instrument else 0.0001


def fetch_history_robust(instrument: str, count: int, use_cache: bool = True) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{instrument}_M5_MBA_{count}.pkl"
    if use_cache and cache.exists():
        return pd.read_pickle(cache)
    remaining = int(count)
    to = None
    chunks = []
    while remaining > 0:
        n = min(5000, remaining)
        df = fetch_oanda_candles(instrument, "M5", n, allow_live_data=True, price="MBA", to=to)
        if df.empty:
            break
        chunks.append(df)
        remaining -= len(df)
        oldest = pd.to_datetime(df["time"], utc=True).min()
        next_to = (oldest - pd.Timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        if to == next_to or len(df) < 100:
            break
        to = next_to
    if not chunks:
        return pd.DataFrame()
    out = pd.concat(chunks, ignore_index=True).sort_values("time").drop_duplicates("time")
    out = out.tail(int(count)).reset_index(drop=True)
    out.to_pickle(cache)
    return out


def add_indicators(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    out = df.copy()
    c = out["close"].astype(float)
    h = out["high"].astype(float)
    l = out["low"].astype(float)
    for span in [20, 50, 100, 200]:
        out[f"{prefix}ema{span}"] = c.ewm(span=span, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    out[f"{prefix}rsi14"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    out[f"{prefix}atr14"] = atr
    up = h.diff()
    down = -l.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_di = 100 * pd.Series(plus_dm, index=out.index).ewm(alpha=1 / 14, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=out.index).ewm(alpha=1 / 14, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    out[f"{prefix}adx14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    out[f"{prefix}don_hi20"] = h.rolling(20).max().shift(1)
    out[f"{prefix}don_lo20"] = l.rolling(20).min().shift(1)
    out[f"{prefix}bb_mid20"] = c.rolling(20).mean()
    out[f"{prefix}bb_std20"] = c.rolling(20).std()
    out[f"{prefix}bb_upper20"] = out[f"{prefix}bb_mid20"] + 2 * out[f"{prefix}bb_std20"]
    out[f"{prefix}bb_lower20"] = out[f"{prefix}bb_mid20"] - 2 * out[f"{prefix}bb_std20"]
    return out


def prep(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    for col in ["bid_open", "ask_open"]:
        if col in df.columns: agg[col] = "first"
    for col in ["bid_high", "ask_high"]:
        if col in df.columns: agg[col] = "max"
    for col in ["bid_low", "ask_low"]:
        if col in df.columns: agg[col] = "min"
    for col in ["bid_close", "ask_close"]:
        if col in df.columns: agg[col] = "last"

    frames = {"m5": add_indicators(df, "m5_")}
    for rule, name in [("15min", "m15"), ("30min", "m30"), ("1h", "h1")]:
        res = df.resample(rule, label="right", closed="right").agg(agg).dropna(subset=["open", "high", "low", "close"])
        frames[name] = add_indicators(res, f"{name}_")
    base = frames["m5"].copy()
    for name in ["m15", "m30", "h1"]:
        cols = [c for c in frames[name].columns if c.startswith(f"{name}_") or c in ["close"]]
        renamed = frames[name][cols].rename(columns={"close": f"{name}_close"})
        base = pd.concat([base, renamed.reindex(base.index, method="ffill")], axis=1)
    return base.dropna()


@dataclass(frozen=True)
class Params:
    family: str
    signal_tf: str
    trend_tf: str
    trend_ema: int
    entry_rsi_long: int
    entry_rsi_short: int
    adx_min: float
    adx_max: float
    sl_atr: float
    tp_atr: float
    max_hold_bars: int
    session_start: int
    session_end: int
    block_hours: tuple[int, ...]
    max_spread_pips: float
    atr_tf: str
    long_enabled: bool = True
    short_enabled: bool = True


def spread_pips(row: pd.Series, instrument: str) -> float:
    ask, bid = row.get("ask_open"), row.get("bid_open")
    if pd.isna(ask) or pd.isna(bid):
        return 0.0
    return float((ask - bid) / pip_size(instrument))


def trend_ok(row: pd.Series, side: int, p: Params) -> bool:
    close = row[f"{p.trend_tf}_close"]
    ema = row[f"{p.trend_tf}_ema{p.trend_ema}"]
    ema50 = row[f"{p.trend_tf}_ema50"]
    ema200 = row[f"{p.trend_tf}_ema200"]
    if side == 1:
        return close > ema and ema50 > ema200
    return close < ema and ema50 < ema200


def signal_side(df: pd.DataFrame, i: int, p: Params) -> int:
    row = df.iloc[i]
    prev = df.iloc[i - 1]
    tf = p.signal_tf
    close = row["close"] if tf == "m5" else row[f"{tf}_close"]
    prev_close = prev["close"] if tf == "m5" else prev[f"{tf}_close"]
    rsi = row[f"{tf}_rsi14"]
    prev_rsi = prev[f"{tf}_rsi14"]
    adx = row[f"{tf}_adx14"]
    if p.adx_min and adx < p.adx_min:
        return 0
    if p.adx_max and adx > p.adx_max:
        return 0

    side = 0
    if p.family == "trend_rsi_resume":
        # Buy dip resumes: RSI crosses up from a pullback level inside a higher-TF trend.
        if p.long_enabled and trend_ok(row, 1, p) and prev_rsi <= p.entry_rsi_long < rsi and close > row[f"{tf}_ema20"]:
            side = 1
        elif p.short_enabled and trend_ok(row, -1, p) and prev_rsi >= p.entry_rsi_short > rsi and close < row[f"{tf}_ema20"]:
            side = -1
    elif p.family == "donchian_breakout":
        if p.long_enabled and trend_ok(row, 1, p) and close > row[f"{tf}_don_hi20"] and prev_close <= prev[f"{tf}_don_hi20"]:
            side = 1
        elif p.short_enabled and trend_ok(row, -1, p) and close < row[f"{tf}_don_lo20"] and prev_close >= prev[f"{tf}_don_lo20"]:
            side = -1
    elif p.family == "bb_range_revert":
        # Range only: fade bands when ADX is capped. Exit still through ATR bracket/time.
        if p.long_enabled and close < row[f"{tf}_bb_lower20"] and rsi < p.entry_rsi_long:
            side = 1
        elif p.short_enabled and close > row[f"{tf}_bb_upper20"] and rsi > p.entry_rsi_short:
            side = -1
    return side


def run_backtest(df: pd.DataFrame, instrument: str, p: Params) -> list[dict]:
    trades = []
    pos = None
    idx = list(df.index)
    warmup = 260
    last_entry_bar_by_tf = {"m5": None, "m15": None, "m30": None, "h1": None}
    for i in range(warmup, len(df) - 1):
        t = idx[i]
        row = df.iloc[i]
        nxt = df.iloc[i + 1]
        if pos is not None:
            reason, px = hit_stop_or_target(row, pos["side"], pos["sl"], pos["tp"])
            held = i - pos["entry_i"]
            if reason is None and held >= p.max_hold_bars:
                reason = "time"
                px = open_exit_price(nxt, pos["side"], float(nxt["open"]))
            if reason is not None:
                risk = abs(pos["entry"] - pos["sl"])
                r = ((px - pos["entry"]) * pos["side"]) / risk if risk > 0 else 0.0
                trades.append({
                    "instrument": instrument, "family": p.family,
                    "side": "long" if pos["side"] == 1 else "short",
                    "entry_time": str(pos["entry_time"]), "exit_time": str(t),
                    "entry": float(pos["entry"]), "exit": float(px), "sl": float(pos["sl"]), "tp": float(pos["tp"]),
                    "r": float(r), "reason": reason, "held_bars": int(held),
                    "spread_pips": float(pos["spread_pips"]), "atr_pips": float(pos["atr"] / pip_size(instrument)),
                })
                pos = None
            continue

        if not (p.session_start <= t.hour < p.session_end) or t.hour in p.block_hours:
            continue
        if spread_pips(nxt, instrument) > p.max_spread_pips:
            continue
        # Only evaluate higher timeframe signals once per new higher-TF close to avoid duplicated M5 entries.
        if p.signal_tf != "m5":
            sig_bar = row[f"{p.signal_tf}_close"]
            key = (p.signal_tf, sig_bar, row.name.floor({"m15":"15min","m30":"30min","h1":"1h"}[p.signal_tf]))
            if last_entry_bar_by_tf[p.signal_tf] == key:
                continue
        atr = row[f"{p.atr_tf}_atr14"]
        if pd.isna(atr) or atr <= 0:
            continue
        side = signal_side(df, i, p)
        if side == 0:
            continue
        if p.signal_tf != "m5":
            last_entry_bar_by_tf[p.signal_tf] = key
        ent = entry_price(nxt, side, float(nxt["open"]))
        sl = ent - side * p.sl_atr * float(atr)
        tp = ent + side * p.tp_atr * float(atr)
        pos = {"side": side, "entry": ent, "sl": sl, "tp": tp, "atr": float(atr), "entry_i": i + 1, "entry_time": idx[i + 1], "spread_pips": spread_pips(nxt, instrument)}
    return trades


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0, "win_rate_pct": 0, "profit_factor": 0, "net_r": 0, "expectancy_r": 0, "max_drawdown_r": 0}
    rs = np.array([t["r"] for t in trades], dtype=float)
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    equity = np.cumsum(rs)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    return {
        "trades": int(len(rs)),
        "wins": int((rs > 0).sum()),
        "losses": int((rs <= 0).sum()),
        "win_rate_pct": round(float((rs > 0).mean() * 100), 2),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3) if abs(losses.sum()) > 1e-12 else None,
        "net_r": round(float(rs.sum()), 3),
        "expectancy_r": round(float(rs.mean()), 4),
        "median_r": round(float(np.median(rs)), 4),
        "max_drawdown_r": round(float(dd.max()), 3),
        "avg_hold_bars": round(float(np.mean([t["held_bars"] for t in trades])), 2),
        "tp_exits": int(sum(t["reason"] == "tp" for t in trades)),
        "sl_exits": int(sum(t["reason"] == "sl" for t in trades)),
        "time_exits": int(sum(t["reason"] == "time" for t in trades)),
    }


def split_by_time(trades: list[dict]) -> tuple[list[dict], list[dict]]:
    if not trades:
        return [], []
    ts = pd.to_datetime([t["entry_time"] for t in trades], utc=True)
    cut_time = ts.min() + (ts.max() - ts.min()) * 0.70
    train, test = [], []
    for t, dt in zip(trades, ts):
        (train if dt <= cut_time else test).append(t)
    return train, test


def make_grid() -> list[Params]:
    grid = []
    # Fast targeted second pass: structural changes only, not parameter soup.
    # 1) Slow signal from M5 to M15, H1 trend filter.
    for rb, rs, adx_min, sl, tp in [(45, 55, 18, 1.0, 1.5), (50, 50, 18, 1.0, 2.0), (55, 45, 24, 1.2, 2.4)]:
        grid.append(Params("trend_rsi_resume", "m15", "h1", 100, rb, rs, adx_min, 0, sl, tp, 48, 7, 17, (10, 11), 1.6, "m15"))
    # 2) Breakout alternative on M15/M30; if the market trends, stop fading noise and buy strength/sell weakness.
    for signal_tf in ["m15", "m30"]:
        for adx_min, sl, tp in [(18, 1.0, 2.0), (24, 1.2, 2.4), (24, 1.5, 3.0)]:
            grid.append(Params("donchian_breakout", signal_tf, "h1", 100, 0, 100, adx_min, 0, sl, tp, 48 if signal_tf == "m15" else 72, 7, 17, (10, 11), 1.6, signal_tf))
    # 3) Low-ADX range strategy: only fade Bollinger extremes when Springfield's power grid is not trending.
    for signal_tf in ["m15", "m30"]:
        for rb, rs, adx_max, sl, tp in [(30, 70, 18, 1.0, 1.0), (35, 65, 18, 1.0, 1.3)]:
            grid.append(Params("bb_range_revert", signal_tf, "h1", 200, rb, rs, 0, adx_max, sl, tp, 36 if signal_tf == "m15" else 72, 7, 17, (10, 11), 1.6, signal_tf))
    return grid


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=",".join(PAIRS))
    ap.add_argument("--count", type=int, default=20000)
    ap.add_argument("--outdir", default="/root/bots/forexbot/shadow/results")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    grid = make_grid()
    data_info, errors, all_results = {}, {}, []
    for pair in [p.strip() for p in args.pairs.split(",") if p.strip()]:
        try:
            raw = fetch_history_robust(pair, args.count, use_cache=not args.no_cache)
            feat = prep(raw)
            data_info[pair] = {"m5_candles": len(raw), "usable_rows": len(feat), "from": str(feat.index.min()), "to": str(feat.index.max())}
            for params in grid:
                trades = run_backtest(feat, pair, params)
                train, oos = split_by_time(trades)
                all_results.append({"pair": pair, "params": asdict(params), "overall": summarize(trades), "train_70pct": summarize(train), "oos_30pct": summarize(oos), "trades": trades})
        except Exception as e:
            errors[pair] = repr(e)

    pair_ranked = sorted(
        [r for r in all_results if r["overall"]["trades"] >= 12 and r["oos_30pct"]["trades"] >= 4],
        key=lambda r: (r["oos_30pct"]["expectancy_r"], r["oos_30pct"]["profit_factor"] or 0, r["oos_30pct"]["trades"]), reverse=True)

    combo = {}
    for r in all_results:
        key = json.dumps(r["params"], sort_keys=True)
        combo.setdefault(key, {"params": r["params"], "trades": []})["trades"].extend(r["trades"])
    combo_ranked = []
    for v in combo.values():
        train, oos = split_by_time(sorted(v["trades"], key=lambda x: x["entry_time"]))
        combo_ranked.append({"params": v["params"], "overall": summarize(v["trades"]), "train_70pct": summarize(train), "oos_30pct": summarize(oos)})
    combo_ranked = sorted(
        [r for r in combo_ranked if r["overall"]["trades"] >= 50 and r["oos_30pct"]["trades"] >= 12],
        key=lambda r: (r["oos_30pct"]["expectancy_r"], r["oos_30pct"]["profit_factor"] or 0, r["oos_30pct"]["trades"]), reverse=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at_utc": ts,
        "purpose": "Improve rejected M5/M15/M30 RSI scalp by testing slower signals, stricter trend/regime filters, Donchian breakout, and low-ADX Bollinger range reversion.",
        "safety": "Read-only shadow backtest. No live trading path touched.",
        "data": data_info, "errors": errors, "grid_size": len(grid),
        "top_combined_variants": combo_ranked[:30],
        "top_pair_variants": [{k: v for k, v in r.items() if k != "trades"} for r in pair_ranked[:50]],
    }
    summary_path = outdir / f"scalping_mtf_optimizer_summary_{ts}.json"
    trades_path = outdir / f"scalping_mtf_optimizer_trades_{ts}.csv"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    flat = []
    for rank, r in enumerate(pair_ranked[:100], start=1):
        for t in r["trades"]:
            flat.append({"rank": rank, **r["params"], **t})
    pd.DataFrame(flat).to_csv(trades_path, index=False)
    print(json.dumps({"summary_path": str(summary_path), "trades_path": str(trades_path), "data": data_info, "errors": errors, "grid_size": len(grid), "top_combined": combo_ranked[:8], "top_pair": [{k: v for k, v in r.items() if k != "trades"} for r in pair_ranked[:8]]}, indent=2))


if __name__ == "__main__":
    main()
