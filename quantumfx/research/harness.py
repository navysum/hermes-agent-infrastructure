#!/usr/bin/env python3
"""Shared backtest harness for QuantumFX strategy research.

Model: signals computed on bar close t are held over bar t+1 (weights shifted
by 1 before PnL). Costs are charged on |weight change| using the REAL per-bar
half-spread from OANDA bid/ask data, times a stress multiplier, plus fixed
slippage. All strategies produce a weights DataFrame (index=time, cols=pairs,
values=signed exposure as a fraction of equity).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

PAIRS = [
    "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "NZD_USD", "USD_CAD",
    "USD_CHF", "EUR_JPY", "GBP_JPY", "EUR_GBP", "AUD_NZD", "EUR_CHF",
]

SLIPPAGE_FRAC = 0.00002  # 0.2 pip on a ~1.0 quote, per side, always applied


def load_panel(gran: str, pairs: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Return dict of field -> DataFrame[time, pair] for one granularity."""
    pairs = pairs or PAIRS
    frames = {}
    for p in pairs:
        df = pd.read_pickle(DATA_DIR / f"{p}_{gran}.pkl")
        frames[p] = df
    fields = ["open", "high", "low", "close", "spread", "volume"]
    panel = {
        f: pd.DataFrame({p: frames[p][f] for p in pairs}).sort_index()
        for f in fields
    }
    # forward-fill tiny gaps (missing bars on some pairs), never backfill
    for f in fields:
        panel[f] = panel[f].ffill(limit=3)
    return panel


def bars_per_year(index: pd.DatetimeIndex) -> float:
    years = (index[-1] - index[0]).days / 365.25
    return len(index) / max(years, 1e-9)


def portfolio_returns(
    weights: pd.DataFrame,
    panel: dict[str, pd.DataFrame],
    cost_mult: float = 1.5,
) -> pd.Series:
    """Net portfolio bar returns for a weights matrix."""
    close = panel["close"].loc[weights.index, weights.columns]
    spread = panel["spread"].loc[weights.index, weights.columns]
    rets = close.pct_change().fillna(0.0)
    w = weights.shift(1).fillna(0.0)          # positions held during bar t
    gross = (w * rets).sum(axis=1)
    half_spread_frac = (spread / 2 / close).clip(lower=0)
    turn = (weights - weights.shift(1)).abs().fillna(0.0)
    costs = (turn * (half_spread_frac * cost_mult + SLIPPAGE_FRAC)).sum(axis=1)
    return gross - costs


def metrics(net: pd.Series, weights: pd.DataFrame | None = None) -> dict:
    bpy = bars_per_year(net.index)
    eq = (1 + net).cumprod()
    n_years = len(net) / bpy
    ann_ret = eq.iloc[-1] ** (1 / max(n_years, 1e-9)) - 1
    vol = net.std() * np.sqrt(bpy)
    sharpe = (net.mean() * bpy) / vol if vol > 0 else 0.0
    dd = (eq / eq.cummax() - 1).min()
    pos = net[net > 0].sum()
    neg = -net[net < 0].sum()
    out = {
        "ann_return": round(float(ann_ret), 4),
        "sharpe": round(float(sharpe), 3),
        "max_dd": round(float(dd), 4),
        "bar_pf": round(float(pos / neg), 3) if neg > 0 else np.inf,
        "total_return": round(float(eq.iloc[-1] - 1), 4),
        "n_bars": int(len(net)),
    }
    if weights is not None:
        turn = (weights - weights.shift(1)).abs().sum(axis=1)
        out["ann_turnover"] = round(float(turn.mean() * bpy), 1)
        flips = (np.sign(weights) != np.sign(weights.shift(1))) & (
            weights.abs() + weights.shift(1).abs() > 0
        )
        out["approx_trades_per_year"] = round(
            float(flips.sum(axis=1).mean() * bpy / 2), 1
        )
    return out


def vol_target_weights(
    raw_sign: pd.DataFrame,
    close: pd.DataFrame,
    per_position_vol: float = 0.10,
    vol_lookback: int = 72,
    max_gross: float = 3.0,
    max_weight: float = 1.5,
) -> pd.DataFrame:
    """Scale +-1 signals to inverse-vol weights with a gross-leverage cap."""
    rets = close.pct_change()
    bpy = bars_per_year(close.index)
    bar_vol = rets.rolling(vol_lookback).std()
    ann_vol = bar_vol * np.sqrt(bpy)
    size = (per_position_vol / ann_vol).clip(upper=max_weight)
    w = (raw_sign * size).fillna(0.0)
    gross = w.abs().sum(axis=1)
    scale = (max_gross / gross).clip(upper=1.0).fillna(1.0)
    return w.mul(scale, axis=0)


def yearly_folds(index: pd.DatetimeIndex, first_test_year: int) -> list[tuple]:
    """Expanding-window folds: train = everything before test year."""
    last_year = index[-1].year
    folds = []
    for y in range(first_test_year, last_year + 1):
        tr = index[index < pd.Timestamp(f"{y}-01-01", tz="UTC")]
        te = index[
            (index >= pd.Timestamp(f"{y}-01-01", tz="UTC"))
            & (index < pd.Timestamp(f"{y + 1}-01-01", tz="UTC"))
        ]
        if len(tr) > 500 and len(te) > 100:
            folds.append((tr, te))
    return folds


def walk_forward(
    strategy_fn,
    param_grid: list[dict],
    panel: dict[str, pd.DataFrame],
    first_test_year: int,
    cost_mult: float = 1.5,
    select_metric: str = "sharpe",
):
    """For each fold: pick params on train net metric, evaluate OOS on test.

    strategy_fn(panel, **params) -> weights DataFrame over the full index.
    Returns (oos_net_returns, fold_records).
    """
    index = panel["close"].index
    folds = yearly_folds(index, first_test_year)
    candidates = [(params, strategy_fn(panel, **params)) for params in param_grid]
    oos_parts, records = [], []
    for tr, te in folds:
        best, best_params, best_score = None, None, -np.inf
        for params, w in candidates:
            net_tr = portfolio_returns(w.loc[tr[0]:tr[-1]], panel, cost_mult)
            m = metrics(net_tr)
            score = m[select_metric] if m["n_bars"] else -np.inf
            if score > best_score:
                best, best_params, best_score = w, params, score
        net_te = portfolio_returns(best.loc[te[0]:te[-1]], panel, cost_mult)
        m_te = metrics(net_te, best.loc[te[0]:te[-1]])
        records.append(
            {
                "test_year": te[0].year,
                "params": best_params,
                "train_score": round(float(best_score), 3),
                **m_te,
            }
        )
        oos_parts.append(net_te)
    oos = pd.concat(oos_parts).sort_index() if oos_parts else pd.Series(dtype=float)
    return oos, records


def summarize_wf(name: str, oos: pd.Series, records: list[dict]) -> dict:
    m = metrics(oos) if len(oos) else {}
    pos_folds = sum(1 for r in records if r["total_return"] > 0)
    return {
        "strategy": name,
        "oos": m,
        "positive_folds": f"{pos_folds}/{len(records)}",
        "folds": records,
    }


def save_report(payload: dict, path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"wrote {path}")
