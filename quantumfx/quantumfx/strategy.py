"""QuantumFX live signal engine — exact port of research S4 (OU mean reversion).

The alpha: fade z-score extremes ONLY when the pair currently behaves like an
Ornstein-Uhlenbeck process — rolling AR(1) half-life short enough AND variance
ratio < threshold (sub-random-walk). All rolling windows use info ≤ last
completed bar, mirroring research/strategies_lib.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class StrategyConfig:
    n: int = 48                # z-score window
    z_in: float = 2.0          # entry threshold
    z_out: float = 0.25        # exit threshold (toward mean)
    hl_max: float = 60.0       # max OU half-life (bars)
    hl_min: float = 1.0
    vr_max: float = 0.95       # variance ratio gate (<1 = mean reverting)
    vr_window: int = 200
    vr_q: int = 8
    hl_window: int = 250
    atr_n: int = 14
    time_stop_mult: float = 0.0  # 0 = disabled (Agent B: every time-stop tested hurt)
    vol_lookback: int = 72       # ann-vol window for position sizing
    bars_per_year: float = 1560.0  # H4 bars/yr (24/5 market)
    min_bars: int = 520
    d1_veto_x: float = 0.02      # block fades against daily trend > x from SMA (0 = off)
    d1_sma_len: int = 200        # daily SMA length for the trend veto


def candles_to_df(candles: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "time": c["time"],
            "open": float(c["mid"]["o"]),
            "high": float(c["mid"]["h"]),
            "low": float(c["mid"]["l"]),
            "close": float(c["mid"]["c"]),
        }
        for c in candles
    ]
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"])
    return df.set_index("time").sort_index()


def indicators(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """Latest-bar indicator snapshot; NaN-safe."""
    c = df["close"]
    sma = c.rolling(cfg.n).mean()
    sd = c.rolling(cfg.n).std()
    z = (c - sma) / sd

    lp = np.log(c)
    dlp = lp.diff()
    lag = lp.shift(1)
    cov = dlp.rolling(cfg.hl_window).cov(lag)
    var = lag.rolling(cfg.hl_window).var()
    beta = cov / var
    phi = (1 + beta).clip(1e-6, 0.999999)
    half_life = -np.log(2) / np.log(phi)

    lr = lp.diff()
    lrq = lp.diff(cfg.vr_q)
    vr = lrq.rolling(cfg.vr_window).var() / (cfg.vr_q * lr.rolling(cfg.vr_window).var())

    pc = c.shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(cfg.atr_n).mean()

    ann_vol_s = c.pct_change().rolling(cfg.vol_lookback).std() * np.sqrt(cfg.bars_per_year)

    last = -1
    return {
        "time": df.index[last],
        "close": float(c.iloc[last]),
        "z": float(z.iloc[last]) if np.isfinite(z.iloc[last]) else 0.0,
        "half_life": float(half_life.iloc[last]) if np.isfinite(half_life.iloc[last]) else 1e9,
        "vr": float(vr.iloc[last]) if np.isfinite(vr.iloc[last]) else 1e9,
        "atr": float(atr.iloc[last]) if np.isfinite(atr.iloc[last]) else 0.0,
        "sma": float(sma.iloc[last]) if np.isfinite(sma.iloc[last]) else float(c.iloc[last]),
        "ann_vol": float(ann_vol_s.iloc[last]) if np.isfinite(ann_vol_s.iloc[last]) else 0.0,
    }


def entry_signal(ind: dict, cfg: StrategyConfig) -> int:
    """+1 long, -1 short, 0 none — OU gates + z extreme."""
    if not (cfg.hl_min < ind["half_life"] < cfg.hl_max):
        return 0
    if ind["vr"] >= cfg.vr_max:
        return 0
    if ind["z"] <= -cfg.z_in:
        return 1
    if ind["z"] >= cfg.z_in:
        return -1
    return 0


def d1_trend_dist(daily_df: pd.DataFrame, sma_len: int = 200) -> float | None:
    """Signed % distance of the last COMPLETED daily close from its SMA.

    Validated 2026-07-02 (research/reports/ta_gates.md + d1veto_robustness.md):
    vetoing entries that fade a daily trend stronger than 2% lifted OOS 2022-26
    Sharpe 0.80 -> 0.94 at 1.5x costs (0.72 -> 0.87 at 2x), 5/5 positive years,
    and improved the 2019-21 holdout; robust across x in 1-3% and SMA 100-250.
    """
    c = daily_df["close"]
    if len(c) < sma_len + 1:
        return None
    sma = c.rolling(sma_len).mean().iloc[-1]
    if not np.isfinite(sma) or sma <= 0:
        return None
    return float(c.iloc[-1] / sma - 1)


def d1_veto(sig: int, dist: float, x: float) -> bool:
    """True = block: long into a >x downtrend, or short into a >x uptrend."""
    if x <= 0:
        return False
    return (sig > 0 and dist < -x) or (sig < 0 and dist > x)


def jpy_vol_spike(usdjpy_df: pd.DataFrame, atr_n: int = 14, window: int = 250, mult: float = 2.0) -> bool:
    """True when USD_JPY vol is in a spike regime (yen-unwind circuit breaker).

    Agent A attribution: the strategy's PnL concentrates in JPY crosses and its
    worst regime was the 2024H2 carry unwind — block NEW JPY-pair entries while
    ATR% runs above `mult` x its rolling median.
    """
    c = usdjpy_df["close"]
    pc = c.shift(1)
    tr = pd.concat(
        [usdjpy_df["high"] - usdjpy_df["low"], (usdjpy_df["high"] - pc).abs(), (usdjpy_df["low"] - pc).abs()],
        axis=1,
    ).max(axis=1)
    atrp = tr.rolling(atr_n).mean() / c
    med = atrp.rolling(window).median()
    cur, base = atrp.iloc[-1], med.iloc[-1]
    if not (np.isfinite(cur) and np.isfinite(base)) or base <= 0:
        return False
    return bool(cur > mult * base)


def exit_signal(direction: int, ind: dict, bars_held: float, entry_half_life: float, cfg: StrategyConfig) -> str | None:
    """Reason string if the open trade should close now."""
    if direction > 0 and ind["z"] >= -cfg.z_out:
        return "z_exit"
    if direction < 0 and ind["z"] <= cfg.z_out:
        return "z_exit"
    if cfg.time_stop_mult > 0 and bars_held >= cfg.time_stop_mult * max(entry_half_life, 2.0):
        return "time_stop"
    return None


def anneal_candidates(candidates: list[dict], corr: pd.DataFrame, lam: float = 0.2, n_iter: int = 400, seed: int = 7) -> list[dict]:
    """Quantum-inspired annealer over same-cycle entry candidates: keep the
    subset maximizing sum(|z|) - lam * sum(|pairwise corr|). Validated by
    Agent B (beats plain top-N under contention; the corr penalty is the value).
    """
    if len(candidates) <= 1:
        return candidates
    rng = np.random.default_rng(seed)
    n = len(candidates)
    scores = np.array([abs(c["ind"]["z"]) for c in candidates])
    cm = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                try:
                    cm[i, j] = abs(corr.loc[candidates[i]["pair"], candidates[j]["pair"]])
                except KeyError:
                    cm[i, j] = 0.0

    def energy(x):
        sel = np.flatnonzero(x)
        if len(sel) == 0:
            return 0.0
        e = scores[sel].sum()
        if len(sel) > 1:
            e -= lam * cm[np.ix_(sel, sel)].sum() / 2
        return e

    x = np.ones(n, dtype=bool)
    cur = energy(x)
    t = 1.0
    for _ in range(n_iter):
        cand = x.copy()
        cand[rng.integers(n)] ^= True
        e = energy(cand)
        if e > cur or rng.random() < np.exp((e - cur) / max(t, 1e-9)):
            x, cur = cand, e
        t *= 0.985
    keep = [c for c, k in zip(candidates, x) if k]
    return sorted(keep, key=lambda c: -abs(c["ind"]["z"]))
