#!/usr/bin/env python3
"""Strategy signal generators for QuantumFX research.

Every public strategy returns a DataFrame of raw signed signals (typically
-1/0/+1) indexed like panel["close"]; the run script converts raw signals to
vol-targeted weights. No function may look ahead: only *_prev (shifted)
rolling values feed entry/exit decisions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ── generic state machine ────────────────────────────────────────────────────

def stateful_positions(
    entry_long: pd.DataFrame,
    entry_short: pd.DataFrame,
    exit_long: pd.DataFrame,
    exit_short: pd.DataFrame,
) -> pd.DataFrame:
    """Per-column position state machine: entries flip, exits flatten."""
    el, es = entry_long.to_numpy(), entry_short.to_numpy()
    xl, xs = exit_long.to_numpy(), exit_short.to_numpy()
    out = np.zeros(el.shape, dtype=np.float64)
    for j in range(el.shape[1]):
        pos = 0.0
        elj, esj, xlj, xsj = el[:, j], es[:, j], xl[:, j], xs[:, j]
        for i in range(el.shape[0]):
            if pos > 0 and xlj[i]:
                pos = 0.0
            elif pos < 0 and xsj[i]:
                pos = 0.0
            if elj[i] and pos <= 0:
                pos = 1.0
            elif esj[i] and pos >= 0:
                pos = -1.0
            out[i, j] = pos
    return pd.DataFrame(out, index=entry_long.index, columns=entry_long.columns)


# ── shared features ──────────────────────────────────────────────────────────

def atr(panel: dict, n: int = 14) -> pd.DataFrame:
    h, l, c = panel["high"], panel["low"], panel["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()]).groupby(level=0).max()
    return tr.sort_index().rolling(n).mean()


def variance_ratio(close: pd.DataFrame, window: int = 200, q: int = 8) -> pd.DataFrame:
    """Rolling VR(q): >1 trending, <1 mean-reverting."""
    lr = np.log(close).diff()
    lrq = np.log(close).diff(q)
    v1 = lr.rolling(window).var()
    vq = lrq.rolling(window).var()
    return vq / (q * v1)


def rolling_half_life(close: pd.DataFrame, window: int = 250) -> pd.DataFrame:
    """OU half-life from rolling AR(1) of log price (bars)."""
    lp = np.log(close)
    dlp = lp.diff()
    lag = lp.shift(1)
    cov = dlp.rolling(window).cov(lag)
    var = lag.rolling(window).var()
    beta = cov / var
    phi = (1 + beta).clip(1e-6, 0.999999)
    return -np.log(2) / np.log(phi)


# ── S1: slow trend following (Donchian channel) ──────────────────────────────

def s1_trend_donchian(panel: dict, entry_n: int = 55, exit_n: int = 20, **_) -> pd.DataFrame:
    c, h, l = panel["close"], panel["high"], panel["low"]
    hi_prev = h.rolling(entry_n).max().shift(1)
    lo_prev = l.rolling(entry_n).min().shift(1)
    xhi_prev = h.rolling(exit_n).max().shift(1)
    xlo_prev = l.rolling(exit_n).min().shift(1)
    return stateful_positions(c.gt(hi_prev), c.lt(lo_prev), c.lt(xlo_prev), c.gt(xhi_prev))


def s1_trend_macross(panel: dict, fast: int = 30, slow: int = 150, strength_min: float = 0.001, **_) -> pd.DataFrame:
    c = panel["close"]
    f, s = c.rolling(fast).mean(), c.rolling(slow).mean()
    strength = (f - s).abs() / s
    sig = np.sign(f - s).where(strength > strength_min, 0.0)
    return sig.fillna(0.0)


# ── S2: cross-sectional momentum rotation ────────────────────────────────────

def s2_xsec_momentum(panel: dict, lookback: int = 250, top_n: int = 3, rebal: int = 30, **_) -> pd.DataFrame:
    c = panel["close"]
    r = c.pct_change(lookback)
    vol = c.pct_change().rolling(lookback // 2).std()
    score = r / (vol * np.sqrt(lookback))
    ranks = score.rank(axis=1)
    n = c.shape[1]
    raw = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    raw[ranks > n - top_n] = 1.0
    raw[ranks <= top_n] = -1.0
    mask = np.arange(len(c)) % rebal == 0
    held = raw.where(pd.Series(mask, index=c.index), np.nan).ffill().fillna(0.0)
    return held


# ── S3: z-score mean reversion with trend veto ───────────────────────────────

def s3_zscore_mr(
    panel: dict, n: int = 48, z_in: float = 2.0, z_out: float = 0.5,
    veto_q: float = 0.8, subset: tuple = ("AUD_NZD", "EUR_GBP", "EUR_CHF", "EUR_USD", "USD_CHF", "USD_CAD"),
    **_,
) -> pd.DataFrame:
    c = panel["close"]
    sma, sd = c.rolling(n).mean(), c.rolling(n).std()
    z = ((c - sma) / sd).shift(0)  # uses info up to close t only
    f, s = c.rolling(20).mean(), c.rolling(100).mean()
    strength = ((f - s).abs() / s)
    veto = strength.gt(strength.rolling(500).quantile(veto_q))
    entry_long = z.lt(-z_in) & ~veto
    entry_short = z.gt(z_in) & ~veto
    exit_long = z.gt(-z_out)
    exit_short = z.lt(z_out)
    pos = stateful_positions(entry_long, entry_short, exit_long, exit_short)
    keep = [p for p in c.columns if p in subset]
    pos.loc[:, [p for p in c.columns if p not in keep]] = 0.0
    return pos


# ── S4: OU mean reversion (half-life + VR gated) ─────────────────────────────

def s4_ou_mr(
    panel: dict, n: int = 48, z_in: float = 2.0, z_out: float = 0.25,
    hl_max: float = 60.0, vr_max: float = 0.95, **_,
) -> pd.DataFrame:
    c = panel["close"]
    sma, sd = c.rolling(n).mean(), c.rolling(n).std()
    z = (c - sma) / sd
    hl = rolling_half_life(c, 250)
    vr = variance_ratio(c, 200, 8)
    ok = hl.lt(hl_max) & hl.gt(1) & vr.lt(vr_max)
    entry_long = z.lt(-z_in) & ok
    entry_short = z.gt(z_in) & ok
    exit_long = z.gt(-z_out)
    exit_short = z.lt(z_out)
    return stateful_positions(entry_long, entry_short, exit_long, exit_short)


# ── S5: cointegration pairs stat-arb ─────────────────────────────────────────

def s5_pairs(
    panel: dict, window: int = 500, z_in: float = 2.0, z_out: float = 0.3,
    legs: tuple = (("EUR_USD", "GBP_USD"), ("AUD_USD", "NZD_USD")),
    **_,
) -> pd.DataFrame:
    c = panel["close"]
    out = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    for a, b in legs:
        la, lb = np.log(c[a]), np.log(c[b])
        cov = la.rolling(window).cov(lb)
        var = lb.rolling(window).var()
        beta = (cov / var).clip(0.2, 3.0)
        spread = la - beta * lb
        mu, sd = spread.rolling(window).mean(), spread.rolling(window).std()
        z = ((spread - mu) / sd).to_frame("z")
        e_l = z.lt(-z_in)
        e_s = z.gt(z_in)
        x_l = z.gt(-z_out)
        x_s = z.lt(z_out)
        pos = stateful_positions(e_l, e_s, x_l, x_s)["z"]
        out[a] = out[a] + pos
        out[b] = out[b] - pos * beta.clip(0.3, 2.0).fillna(1.0)
    return out


# ── S6: London-open range breakout (H1 panel) ────────────────────────────────

def s6_london_breakout(
    panel: dict, pairs: tuple = ("GBP_USD", "EUR_USD"), k: float = 0.0,
    entry_end_h: int = 10, exit_h: int = 16, **_,
) -> pd.DataFrame:
    c = panel["close"]
    out = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    hours = c.index.hour
    dates = c.index.date
    for p in pairs:
        h, l, cl = panel["high"][p], panel["low"][p], c[p]
        asia = pd.Series(np.where((hours >= 0) & (hours < 7), 1, np.nan), index=c.index)
        d = pd.Series(dates, index=c.index)
        rng_hi = (h * asia).groupby(d).cummax().groupby(d).ffill()
        rng_lo = (l * asia).groupby(d).cummin().groupby(d).ffill()
        span = rng_hi - rng_lo
        in_window = (hours >= 7) & (hours < entry_end_h)
        long_e = cl.gt(rng_hi + k * span) & in_window
        short_e = cl.lt(rng_lo - k * span) & in_window
        pos = np.zeros(len(cl))
        cur, cur_day = 0.0, None
        le, se = long_e.to_numpy(), short_e.to_numpy()
        hrs = hours
        dts = dates
        for i in range(len(cl)):
            if cur_day != dts[i]:
                cur_day, cur = dts[i], cur if hrs[i] < exit_h else 0.0
            if hrs[i] >= exit_h:
                cur = 0.0
            elif cur == 0.0:
                if le[i]:
                    cur = 1.0
                elif se[i]:
                    cur = -1.0
            pos[i] = cur
        out[p] = pos
    return out


# ── S14: weekend gap fade (H1 panel) ─────────────────────────────────────────

def s14_gap_fade(panel: dict, min_gap_atr: float = 0.3, max_hold: int = 24, **_) -> pd.DataFrame:
    c, o = panel["close"], panel["open"]
    out = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    a = atr(panel, 24)
    idx = c.index
    dow = idx.dayofweek
    # first bar after weekend: previous bar is >24h older
    gap_bar = (idx.to_series().diff() > pd.Timedelta("24h")).to_numpy()
    for j, p in enumerate(c.columns):
        op, cl, aa = o[p].to_numpy(), c[p].to_numpy(), a[p].to_numpy()
        pos = np.zeros(len(cl))
        hold, target, cur = 0, 0.0, 0.0
        for i in range(1, len(cl)):
            if cur != 0.0:
                hold += 1
                filled = (cur > 0 and cl[i] >= target) or (cur < 0 and cl[i] <= target)
                if filled or hold >= max_hold:
                    cur = 0.0
            if gap_bar[i] and cur == 0.0 and np.isfinite(aa[i - 1]):
                gap = op[i] - cl[i - 1]
                if abs(gap) > min_gap_atr * aa[i - 1]:
                    cur = -np.sign(gap)
                    target = cl[i - 1]
                    hold = 0
            pos[i] = cur
        out[p] = pos
    return out


# ── S9: regime-adaptive ensemble with annealed basket selection ──────────────

def _anneal_select(scores: np.ndarray, corr: np.ndarray, k: int, lam: float, n_iter: int = 300, seed: int = 7) -> np.ndarray:
    """Pick binary basket maximizing sum(score) - lam*sum(|corr| overlaps)."""
    rng = np.random.default_rng(seed)
    n = len(scores)
    active = np.flatnonzero(scores != 0)
    if len(active) == 0:
        return np.zeros(n, dtype=bool)
    x = np.zeros(n, dtype=bool)

    def energy(xv):
        sel = np.flatnonzero(xv)
        if len(sel) == 0:
            return 0.0
        e = scores[sel].sum()
        if len(sel) > 1:
            sub = np.abs(corr[np.ix_(sel, sel)])
            e -= lam * (sub.sum() - len(sel)) / 2
        return e

    cur = energy(x)
    t = 1.0
    for it in range(n_iter):
        cand = x.copy()
        flip = rng.choice(active)
        cand[flip] = ~cand[flip]
        if cand.sum() > k:
            continue
        e = energy(cand)
        if e > cur or rng.random() < np.exp((e - cur) / max(t, 1e-9)):
            x, cur = cand, e
        t *= 0.985
    return x


def s9_ensemble(
    panel: dict,
    trend_entry: int = 55, trend_exit: int = 20,
    mr_n: int = 48, mr_z_in: float = 2.0, mr_z_out: float = 0.5,
    vr_hi: float = 1.05, vr_lo: float = 0.97,
    top_k: int = 3, lam: float = 0.35, rebal: int = 30,
    **_,
) -> pd.DataFrame:
    c = panel["close"]
    trend_sig = s1_trend_donchian(panel, trend_entry, trend_exit)
    mr_sig = s4_ou_mr(panel, mr_n, mr_z_in, mr_z_out, hl_max=80, vr_max=vr_lo)
    vr = variance_ratio(c, 200, 8)
    combined = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    combined[vr > vr_hi] = trend_sig[vr > vr_hi]
    combined[vr < vr_lo] = mr_sig[vr < vr_lo]
    # annealed basket selection at rebalance points
    rets = c.pct_change()
    corr = rets.rolling(500).corr()
    strength = combined.abs()
    out = np.zeros(combined.shape)
    comb = combined.to_numpy()
    sel_mask = np.zeros(c.shape[1], dtype=bool)
    for i in range(len(c)):
        if i % rebal == 0 and i > 500:
            cm = corr.loc[c.index[i]].to_numpy()
            cm = np.nan_to_num(cm, nan=0.0)
            scores = np.abs(comb[i]).astype(float)
            sel_mask = _anneal_select(scores, cm, top_k, lam, seed=i)
        row = comb[i].copy()
        row[~sel_mask] = 0.0
        out[i] = row
    return pd.DataFrame(out, index=c.index, columns=c.columns)


# ── S8: ML features (model fit happens in run script, per fold) ──────────────

def ml_features(panel: dict) -> pd.DataFrame:
    """Stacked (time, pair) feature frame. All features use info <= t."""
    c = panel["close"]
    r1 = c.pct_change()
    feats = {
        "r1": r1, "r4": c.pct_change(4), "r12": c.pct_change(12),
        "r48": c.pct_change(48), "r120": c.pct_change(120),
        "vol24": r1.rolling(24).std(), "vol96": r1.rolling(96).std(),
        "z48": (c - c.rolling(48).mean()) / c.rolling(48).std(),
        "z120": (c - c.rolling(120).mean()) / c.rolling(120).std(),
        "vr": variance_ratio(c, 200, 8),
        "hl": rolling_half_life(c, 250).clip(0, 500),
        "dist_hi55": c / c.rolling(55).max().shift(1) - 1,
        "dist_lo55": c / c.rolling(55).min().shift(1) - 1,
        "atrp": atr(panel, 14) / c,
        "volu": panel["volume"].rolling(24).mean() / panel["volume"].rolling(240).mean(),
    }
    parts = []
    for name, df in feats.items():
        s = df.stack()
        s.name = name
        parts.append(s)
    X = pd.concat(parts, axis=1)
    hour = X.index.get_level_values(0).hour
    dow = X.index.get_level_values(0).dayofweek
    X["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    X["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    X["dow"] = dow
    return X
