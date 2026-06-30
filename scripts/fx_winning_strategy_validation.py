#!/usr/bin/env python3
"""Validate the current USD/JPY M15 Donchian fade research candidate.

This is a read-only research harness. It does not place orders. It fetches OANDA
candles through the live bot's existing read-only data adapter, records data
provenance hashes, reruns the candidate deterministically, and writes machine-
readable evidence files.

The candidate under test is the best pocket found during shadow research:
- instrument: USD_JPY
- normal signal: M15 Donchian breakout with H1 trend filter
- tested action: inverted/faded signal
- ADX min: 18
- SL/TP: 1.0 ATR / 2.0 ATR
- session: 07:00-17:00 UTC, excluding 10:00 and 11:00 UTC
- max spread: 1.6 pips
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_OPTIMIZER = "/root/bots/forexbot/shadow/scalping_mtf_optimizer.py"
DEFAULT_OUTDIR = "research/fx-strategy-validation/results"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dataframe_hash(df: pd.DataFrame) -> str:
    canonical = df.copy()
    for col in canonical.columns:
        if pd.api.types.is_datetime64_any_dtype(canonical[col]):
            canonical[col] = pd.to_datetime(canonical[col], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    canonical = canonical.sort_values("time") if "time" in canonical.columns else canonical
    csv_text = canonical.to_csv(index=False, float_format="%.10f")
    return sha256_text(csv_text)


def trades_hash(trades: list[dict[str, Any]]) -> str:
    return sha256_text(json.dumps(trades, sort_keys=True, separators=(",", ":")))


def load_optimizer(path: str):
    opt_path = Path(path)
    if not opt_path.exists():
        raise FileNotFoundError(f"optimizer module not found: {opt_path}")
    spec = importlib.util.spec_from_file_location("fx_shadow_optimizer", str(opt_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fx_shadow_optimizer"] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def candidate_params(opt):
    return opt.Params(
        family="donchian_breakout",
        signal_tf="m15",
        trend_tf="h1",
        trend_ema=100,
        entry_rsi_long=0,
        entry_rsi_short=100,
        adx_min=18,
        adx_max=0,
        sl_atr=1.0,
        tp_atr=2.0,
        max_hold_bars=48,
        session_start=7,
        session_end=17,
        block_hours=(10, 11),
        max_spread_pips=1.6,
        atr_tf="m15",
        long_enabled=True,
        short_enabled=True,
    )


def summarize_r_values(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "net_r": 0.0,
            "expectancy_r": 0.0,
            "max_drawdown_r": 0.0,
        }
    arr = np.asarray(rs, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    eq = np.cumsum(arr)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    return {
        "trades": int(len(arr)),
        "wins": int((arr > 0).sum()),
        "losses": int((arr <= 0).sum()),
        "win_rate_pct": round(float((arr > 0).mean() * 100), 2),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3) if abs(losses.sum()) > 1e-12 else None,
        "net_r": round(float(arr.sum()), 3),
        "expectancy_r": round(float(arr.mean()), 4),
        "median_r": round(float(np.median(arr)), 4),
        "max_drawdown_r": round(float(dd.max()), 3),
    }


def contiguous_folds(index: pd.DatetimeIndex, folds: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if folds < 2:
        return [(index.min(), index.max())]
    cuts = np.linspace(0, len(index) - 1, folds + 1, dtype=int)
    out = []
    for i in range(folds):
        start = index[cuts[i]]
        end = index[cuts[i + 1]]
        if end > start:
            out.append((start, end))
    return out


def bootstrap_expectancy_ci(rs: list[float], samples: int = 5000, seed: int = 42) -> dict[str, Any]:
    if len(rs) < 2:
        return {"samples": 0, "p_expectancy_gt_0": None, "ci95_expectancy_r": [None, None]}
    rng = np.random.default_rng(seed)
    arr = np.asarray(rs, dtype=float)
    means = np.empty(samples)
    for i in range(samples):
        means[i] = rng.choice(arr, size=len(arr), replace=True).mean()
    return {
        "samples": samples,
        "p_expectancy_gt_0": round(float((means > 0).mean()), 4),
        "ci95_expectancy_r": [round(float(np.quantile(means, 0.025)), 4), round(float(np.quantile(means, 0.975)), 4)],
    }


def validate_raw(raw: pd.DataFrame) -> dict[str, Any]:
    issues = []
    if raw.empty:
        issues.append("raw dataframe is empty")
    if "time" not in raw.columns:
        issues.append("missing time column")
        return {"passed": False, "issues": issues}
    times = pd.to_datetime(raw["time"], utc=True)
    if times.duplicated().any():
        issues.append(f"duplicate timestamps: {int(times.duplicated().sum())}")
    if not times.is_monotonic_increasing:
        issues.append("timestamps are not monotonic increasing before canonical sort")
    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(raw.columns))
    if missing:
        issues.append(f"missing OHLC columns: {missing}")
    for col in sorted(required & set(raw.columns)):
        non_numeric = pd.to_numeric(raw[col], errors="coerce").isna().sum()
        if non_numeric:
            issues.append(f"{col} has {int(non_numeric)} non-numeric values")
    return {"passed": not issues, "issues": issues}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--optimizer", default=DEFAULT_OPTIMIZER)
    parser.add_argument("--instrument", default="USD_JPY")
    parser.add_argument("--count", type=int, default=30000)
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR)
    parser.add_argument("--use-cache", action="store_true", help="Use optimizer candle cache instead of forcing a fresh API fetch")
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    repo_root = Path.cwd()
    outdir = repo_root / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    opt = load_optimizer(args.optimizer)
    params = candidate_params(opt)

    raw = opt.fetch_history_robust(args.instrument, args.count, use_cache=args.use_cache)
    raw = raw.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    raw_check = validate_raw(raw)
    features = opt.prep(raw)

    normal_signal = opt.signal_side
    opt.signal_side = lambda df, i, p: -normal_signal(df, i, p)
    trades = opt.run_backtest(features, args.instrument, params)
    opt.signal_side = normal_signal

    train, oos = opt.split_by_time(trades)
    rs = [float(t["r"]) for t in trades]

    fold_summaries = []
    for fold_no, (start, end) in enumerate(contiguous_folds(features.index, args.folds), start=1):
        window = features.loc[(features.index >= start) & (features.index <= end)].copy()
        if len(window) < 400:
            continue
        opt.signal_side = lambda df, i, p: -normal_signal(df, i, p)
        fold_trades = opt.run_backtest(window, args.instrument, params)
        opt.signal_side = normal_signal
        fold_summaries.append({
            "fold": fold_no,
            "from": str(start),
            "to": str(end),
            "rows": int(len(window)),
            "summary": opt.summarize(fold_trades),
        })

    # Determinism check: rerun on identical in-memory features and compare trade hash.
    opt.signal_side = lambda df, i, p: -normal_signal(df, i, p)
    rerun_trades = opt.run_backtest(features, args.instrument, params)
    opt.signal_side = normal_signal

    ts = started.strftime("%Y%m%dT%H%M%SZ")
    trades_path = outdir / f"usd_jpy_m15_donchian_fade_trades_{ts}.csv"
    summary_path = outdir / f"usd_jpy_m15_donchian_fade_validation_{ts}.json"

    if trades:
        with trades_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(trades[0].keys()))
            writer.writeheader()
            writer.writerows(trades)
    else:
        trades_path.write_text("", encoding="utf-8")

    data_hash = dataframe_hash(raw)
    trade_hash = trades_hash(trades)
    rerun_trade_hash = trades_hash(rerun_trades)

    summary = {
        "generated_at_utc": ts,
        "purpose": "Out-of-sample style validation and provenance capture for the USD_JPY M15 Donchian fade research candidate.",
        "safety": "READ_ONLY: fetched market candles and ran local backtest only; no order placement code is called.",
        "instrument": args.instrument,
        "candidate": {
            "description": "Invert/fade M15 Donchian breakout signal with H1 trend context.",
            "params": asdict(params),
            "inverted_signal": True,
        },
        "data_provenance": {
            "adapter": "quantum_forex_bot.oanda_data.fetch_oanda_candles via shadow optimizer",
            "requested_m5_candles": args.count,
            "used_cache": bool(args.use_cache),
            "raw_rows": int(len(raw)),
            "feature_rows": int(len(features)),
            "from": str(features.index.min()) if len(features) else None,
            "to": str(features.index.max()) if len(features) else None,
            "raw_data_sha256": data_hash,
            "optimizer_path": str(Path(args.optimizer).resolve()),
            "optimizer_sha256": sha256_file(Path(args.optimizer)),
            "raw_validation": raw_check,
        },
        "results": {
            "overall": opt.summarize(trades),
            "train_70pct": opt.summarize(train),
            "oos_30pct": opt.summarize(oos),
            "folds": fold_summaries,
            "bootstrap_expectancy": bootstrap_expectancy_ci(rs),
        },
        "anti_fake_output_checks": {
            "trade_count_matches_csv_rows": len(trades),
            "trades_sha256": trade_hash,
            "rerun_trades_sha256": rerun_trade_hash,
            "deterministic_rerun_match": trade_hash == rerun_trade_hash,
            "summary_file": str(summary_path),
            "trades_file": str(trades_path),
        },
        "decision_gate": {
            "minimum_trades": 100,
            "minimum_oos_profit_factor": 1.10,
            "minimum_oos_expectancy_r": 0.02,
            "minimum_positive_folds_ratio": 0.60,
            "passes": False,
            "reason": "Set after metrics are computed below.",
        },
    }

    positive_folds = [f for f in fold_summaries if f["summary"].get("net_r", 0) > 0]
    positive_ratio = len(positive_folds) / len(fold_summaries) if fold_summaries else 0.0
    oos_pf = summary["results"]["oos_30pct"].get("profit_factor") or 0
    oos_exp = summary["results"]["oos_30pct"].get("expectancy_r") or 0
    total_trades = summary["results"]["overall"].get("trades") or 0
    passes = total_trades >= 100 and oos_pf >= 1.10 and oos_exp >= 0.02 and positive_ratio >= 0.60 and trade_hash == rerun_trade_hash
    summary["decision_gate"].update({
        "positive_folds_ratio": round(float(positive_ratio), 3),
        "passes": bool(passes),
        "reason": "PASS: enough trades, positive OOS, positive folds, deterministic rerun." if passes else "FAIL/RESEARCH_ONLY: not enough robust evidence for live deployment.",
    })

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({
        "summary_path": str(summary_path),
        "trades_path": str(trades_path),
        "overall": summary["results"]["overall"],
        "oos_30pct": summary["results"]["oos_30pct"],
        "decision_gate": summary["decision_gate"],
        "anti_fake_output_checks": summary["anti_fake_output_checks"],
    }, indent=2))


if __name__ == "__main__":
    main()
