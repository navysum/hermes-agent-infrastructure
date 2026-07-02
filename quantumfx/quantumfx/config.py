"""QuantumFX configuration. Env vars (QFX_*) override defaults.

Strategy parameters come from the walk-forward validated research
(research/reports/) — do not tune these against live results by hand;
rerun the research pipeline instead.
"""
from __future__ import annotations

import os

from .risk import RiskConfig
from .strategy import StrategyConfig


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


# Universe: full 12 pairs per Agent A attribution study (restricted universes
# tested WORSE; crossesUSD6 was net negative). Edge concentrates in JPY
# crosses but diversification stabilizes the walk-forward.
PAIRS = [
    p.strip()
    for p in os.environ.get(
        "QFX_PAIRS",
        "EUR_USD,GBP_USD,USD_JPY,AUD_USD,NZD_USD,USD_CAD,"
        "USD_CHF,EUR_JPY,GBP_JPY,EUR_GBP,AUD_NZD,EUR_CHF",
    ).split(",")
    if p.strip()
]

GRANULARITY = os.environ.get("QFX_GRANULARITY", "H4")
POLL_SECONDS = _i("QFX_POLL_SECONDS", 120)
EQUITY_SNAPSHOT_MINUTES = 60

# Pinned from the two-agent validation (2026-07-01), verified end to end:
# alpha per Agent A (fixed params, NO per-fold reselection) + construction per
# Agent B (no time stop, no portfolio vol layer, uncapped with gross limit,
# de-levered per-position vol). Final walk-forward OOS 2022-26 on this exact
# config: Sharpe 0.80 / +10.6%/yr / maxDD -16.2% at 1.5x costs (0.72 at 2x).
# z_in 2.25 -> 2.0 (2026-07-02, reports/freq_frontier.md): most-active config
# meeting the pre-stated bar — 99 entries/yr (+25%), OOS Sharpe 0.70 @1.5x /
# 0.61 @2x, maxDD -14.5%, 4/5 positive years, holdout positive.
STRATEGY = StrategyConfig(
    n=_i("QFX_N", 96),
    z_in=_f("QFX_Z_IN", 2.0),
    z_out=_f("QFX_Z_OUT", 0.25),
    hl_max=_f("QFX_HL_MAX", 60.0),
    vr_max=_f("QFX_VR_MAX", 0.95),
    time_stop_mult=_f("QFX_TIME_STOP", 0.0),  # disabled — Agent B: all stops hurt
    # D1 trend veto (added 2026-07-02, reports/ta_gates.md + d1veto_robustness.md):
    # never fade a pair >2% from its 200-day SMA. OOS Sharpe 0.80 -> 0.94.
    d1_veto_x=_f("QFX_D1_VETO", 0.02),
    d1_sma_len=_i("QFX_D1_SMA", 200),
)

# Sizing switched to margin-utilization 2026-07-02 (operator decision):
# use the account's available units instead of the ~30-50u the legacy vol
# sizing produced. QFX_SIZING=vol restores the backtest-matched sizing
# (with QFX_MAX_GROSS=3.0 QFX_MAX_UNITS=200).
RISK = RiskConfig(
    sizing_mode=os.environ.get("QFX_SIZING", "margin"),
    per_position_vol=_f("QFX_PVOL", 0.07),
    max_gross=_f("QFX_MAX_GROSS", 25.0),
    risk_pct=_f("QFX_RISK_PCT", 1.5),
    max_positions=_i("QFX_MAX_POSITIONS", 12),
    max_units=_i("QFX_MAX_UNITS", 600),
    margin_budget_frac=_f("QFX_MARGIN_BUDGET", 0.45),
    max_daily_loss_pct=_f("QFX_MAX_DAILY_LOSS", 4.0),
    sl_atr_mult=_f("QFX_SL_ATR", 3.0),
)

# annealed same-cycle candidate selection (Agent B: corr penalty is the value)
ANNEAL_LAMBDA = _f("QFX_ANNEAL_LAMBDA", 0.2)

# JPY circuit breaker: block new JPY-pair entries when USD_JPY ATR% exceeds
# this multiple of its 250-bar rolling median (2024H2 carry-unwind defence)
JPY_VOL_MULT = _f("QFX_JPY_VOL_MULT", 2.0)

TAG = "quantumfx"
DRY_RUN = os.environ.get("QFX_DRY_RUN", "0") == "1"
