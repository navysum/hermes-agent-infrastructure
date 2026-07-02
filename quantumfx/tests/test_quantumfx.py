"""Deploy-gate tests for QuantumFX — pure logic, no network."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantumfx.risk import RiskConfig, margin_ok, position_units
from quantumfx.strategy import StrategyConfig, entry_signal, exit_signal, indicators


def make_ou_df(n=800, seed=3, mu=1.10, theta=0.05, sigma=0.002):
    rng = np.random.default_rng(seed)
    x = np.empty(n)
    x[0] = mu
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (mu - x[i - 1]) + rng.normal(0, sigma)
    idx = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame(
        {"open": x, "high": x * 1.0005, "low": x * 0.9995, "close": x}, index=idx
    )


def test_ou_series_passes_gates_and_signals():
    cfg = StrategyConfig()
    df = make_ou_df()
    # force an extreme: pull last close far below the rolling mean
    df.iloc[-1, df.columns.get_loc("close")] = df["close"].iloc[-60:-1].mean() * 0.99
    ind = indicators(df, cfg)
    assert ind["half_life"] < cfg.hl_max          # OU process detected
    assert ind["vr"] < 1.05                        # not trending
    if ind["vr"] < cfg.vr_max and abs(ind["z"]) >= cfg.z_in:
        assert entry_signal(ind, cfg) == (1 if ind["z"] < 0 else -1)


def test_random_walk_is_gated_out():
    cfg = StrategyConfig()
    rng = np.random.default_rng(11)
    x = 1.10 * np.exp(np.cumsum(rng.normal(0, 0.002, 800)))
    idx = pd.date_range("2025-01-01", periods=800, freq="4h", tz="UTC")
    df = pd.DataFrame({"open": x, "high": x * 1.0005, "low": x * 0.9995, "close": x}, index=idx)
    ind = indicators(df, cfg)
    # a pure random walk should usually fail the OU gates; force z extreme
    ind["z"] = 3.0
    if ind["half_life"] >= cfg.hl_max or ind["vr"] >= cfg.vr_max:
        assert entry_signal(ind, cfg) == 0


def test_exit_signal_z_and_time_stop():
    cfg = StrategyConfig(z_out=0.25, time_stop_mult=2.0)
    base = {"close": 1.1, "half_life": 20, "vr": 0.9, "atr": 0.001, "sma": 1.1}
    assert exit_signal(1, {**base, "z": -0.1}, 1, 20, cfg) == "z_exit"
    assert exit_signal(1, {**base, "z": -1.0}, 1, 20, cfg) is None
    assert exit_signal(-1, {**base, "z": 0.1}, 1, 20, cfg) == "z_exit"
    assert exit_signal(1, {**base, "z": -1.0}, 41, 20, cfg) == "time_stop"


def test_position_units_risk_cap_only():
    cfg = RiskConfig(risk_pct=1.5, max_units=200)
    prices = {"GBP_USD": {"bids": [{"price": "1.25"}], "asks": [{"price": "1.2502"}]}}
    # no ann_vol -> pure risk cap: toy NAV 16, risk 1.5%; SL 60 pips; USD->GBP = 1/1.2501
    units = position_units(16.0, 1.1000, 1.0940, "EUR_USD", prices, cfg)
    expected = int((16 * 0.015) / (0.0060 / 1.2501))
    assert units == min(expected, 200)
    assert units > 0


def test_position_units_vol_targeted_below_risk_cap():
    cfg = RiskConfig(per_position_vol=0.07, risk_pct=1.5, max_units=200)
    prices = {"GBP_USD": {"bids": [{"price": "1.25"}], "asks": [{"price": "1.25"}]}}
    # ann_vol 8% -> weight 0.875 -> notional £14 -> ~16 units; risk cap is ~50 -> vol binds
    units = position_units(16.0, 1.1000, 1.0940, "EUR_USD", prices, cfg, ann_vol=0.08)
    weight = 0.07 / 0.08
    expected_vol_units = int(16.0 * weight / (1.1 / 1.25))
    assert units == expected_vol_units
    # very low vol -> weight capped at max_weight 1.5, still bounded by risk cap
    units_lowvol = position_units(16.0, 1.1000, 1.0940, "EUR_USD", prices, cfg, ann_vol=0.01)
    assert units_lowvol <= int((16 * 0.015) / (0.0060 / 1.25)) + 1


def test_position_units_zero_distance():
    cfg = RiskConfig()
    assert position_units(16.0, 1.1, 1.1, "EUR_USD", {}, cfg) == 0


def test_position_units_margin_mode():
    cfg = RiskConfig()  # sizing_mode defaults to "margin"
    prices = {"GBP_USD": {"bids": [{"price": "1.25"}], "asks": [{"price": "1.25"}]}}
    units = position_units(16.0, 1.1000, 1.0940, "EUR_USD", prices, cfg,
                           ann_vol=0.08, margin_available=16.0, margin_rate=0.0333)
    # budget = 45% of toy margin at 3.33% -> ~245 units
    expected = int(16.0 * 0.45 / ((1.1 / 1.25) * 0.0333))
    assert units == min(expected, cfg.max_units)
    assert units > 100  # order of magnitude above the legacy vol sizing
    # missing margin data falls back to the legacy vol/risk sizing
    fallback = position_units(16.0, 1.1000, 1.0940, "EUR_USD", prices, cfg, ann_vol=0.08)
    assert 0 < fallback < 60


def test_anneal_drops_correlated_duplicate():
    from quantumfx.strategy import anneal_candidates
    cands = [
        {"pair": "EUR_JPY", "sig": -1, "ind": {"z": 2.6}},
        {"pair": "GBP_JPY", "sig": -1, "ind": {"z": 2.35}},
        {"pair": "AUD_NZD", "sig": 1, "ind": {"z": -2.4}},
    ]
    corr = pd.DataFrame(
        [[1.0, 0.93, 0.05], [0.93, 1.0, 0.02], [0.05, 0.02, 1.0]],
        index=["EUR_JPY", "GBP_JPY", "AUD_NZD"],
        columns=["EUR_JPY", "GBP_JPY", "AUD_NZD"],
    )
    # with a strong penalty the near-duplicate JPY cross should be dropped
    kept = anneal_candidates(cands, corr, lam=3.0)
    pairs = {c["pair"] for c in kept}
    assert "AUD_NZD" in pairs
    assert not {"EUR_JPY", "GBP_JPY"} <= pairs
    # with tiny penalty everything survives
    assert len(anneal_candidates(cands, corr, lam=0.001)) == 3


def test_margin_guard_blocks_oversize():
    cfg = RiskConfig(margin_budget_frac=0.45)
    prices = {"GBP_USD": {"bids": [{"price": "1.25"}], "asks": [{"price": "1.25"}]}}
    # 500 units EUR_USD ≈ £440 notional, 3.33% margin ≈ £14.7 > 45% of £10
    assert not margin_ok(500, "EUR_USD", 1.10, 10.0, 0.0333, prices, cfg)
    assert margin_ok(30, "EUR_USD", 1.10, 10.0, 0.0333, prices, cfg)


def test_gbp_quote_pair_conversion_identity():
    cfg = RiskConfig(risk_pct=1.5, max_units=200)
    units = position_units(16.0, 0.8600, 0.8560, "EUR_GBP", {}, cfg)
    assert abs(units - (16 * 0.015) / 0.0040) <= 1  # float truncation tolerance


def test_d1_trend_veto():
    from quantumfx.strategy import d1_trend_dist, d1_veto
    idx = pd.date_range("2025-01-01", periods=260, freq="D", tz="UTC")
    # steady 20% grind up over a year -> last close well above SMA200
    up = pd.DataFrame({"close": np.linspace(1.00, 1.20, 260)}, index=idx)
    dist = d1_trend_dist(up, 200)
    assert dist is not None and dist > 0.02
    assert d1_veto(-1, dist, 0.02) is True      # short fades the uptrend: veto
    assert d1_veto(1, dist, 0.02) is False      # long rides it: allowed
    down = pd.DataFrame({"close": np.linspace(1.20, 1.00, 260)}, index=idx)
    dist_dn = d1_trend_dist(down, 200)
    assert dist_dn is not None and dist_dn < -0.02
    assert d1_veto(1, dist_dn, 0.02) is True    # long fades the downtrend: veto
    assert d1_veto(-1, dist_dn, 0.02) is False
    # flat market: nothing vetoed either way
    flat = pd.DataFrame({"close": np.full(260, 1.10)}, index=idx)
    assert d1_veto(1, d1_trend_dist(flat, 200), 0.02) is False
    assert d1_veto(-1, d1_trend_dist(flat, 200), 0.02) is False
    # x=0 disables; short history returns None
    assert d1_veto(-1, 0.5, 0.0) is False
    assert d1_trend_dist(up.iloc[:100], 200) is None


def test_jpy_circuit_breaker():
    from quantumfx.strategy import jpy_vol_spike
    rng = np.random.default_rng(5)
    n = 400
    calm = 150 * np.exp(np.cumsum(rng.normal(0, 0.0008, n)))
    idx = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame({"open": calm, "high": calm * 1.0006, "low": calm * 0.9994, "close": calm}, index=idx)
    assert jpy_vol_spike(df, window=250, mult=2.0) is False
    spike = df.copy()
    spike.iloc[-20:, spike.columns.get_loc("high")] *= 1.004
    spike.iloc[-20:, spike.columns.get_loc("low")] *= 0.996
    assert jpy_vol_spike(spike, window=250, mult=2.0) is True
