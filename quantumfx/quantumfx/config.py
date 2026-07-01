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
STRATEGY = StrategyConfig(
    n=_i("QFX_N", 96),
    z_in=_f("QFX_Z_IN", 2.25),
    z_out=_f("QFX_Z_OUT", 0.25),
    hl_max=_f("QFX_HL_MAX", 60.0),
    vr_max=_f("QFX_VR_MAX", 0.95),
    time_stop_mult=_f("QFX_TIME_STOP", 0.0),  # disabled — Agent B: all stops hurt
)

RISK = RiskConfig(
    per_position_vol=_f("QFX_PVOL", 0.07),
    max_gross=_f("QFX_MAX_GROSS", 3.0),
    risk_pct=_f("QFX_RISK_PCT", 1.5),
    max_positions=_i("QFX_MAX_POSITIONS", 12),
    max_units=_i("QFX_MAX_UNITS", 200),
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
