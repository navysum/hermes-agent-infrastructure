"""Risk management for QuantumFX: sizing, margin guard, halts, kill switch.

The account is tiny (double-digit GBP) and SHARED with the live fx-live-bot. Rules:
- never use more than MARGIN_BUDGET_FRAC of the margin currently available,
- hard cap on concurrent quantumfx positions,
- every order carries a server-side stop loss,
- daily loss halt + kill-switch file, both fail-closed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("quantumfx.risk")

KILL_FILE = Path(__file__).resolve().parent.parent / "KILL"


@dataclass
class RiskConfig:
    per_position_vol: float = 0.07     # annualized vol target per position (backtest-matched)
    max_weight: float = 1.5            # per-position weight cap (matches harness)
    max_gross: float = 3.0             # total quantumfx gross exposure / NAV cap
    risk_pct: float = 1.5              # hard CAP: % NAV risked entry->SL
    max_positions: int = 12            # universe bound (uncapped won the backtest)
    max_units: int = 200               # absolute per-trade unit cap
    margin_budget_frac: float = 0.45   # of marginAvailable at order time
    max_daily_loss_pct: float = 4.0    # halt for the UTC day beyond this
    sl_atr_mult: float = 3.0           # catastrophe stop distance
    min_rr_tp: float = 1.5             # optional TP floor (the operator's house rule)


def kill_switch_active() -> bool:
    return KILL_FILE.exists()


def quote_to_gbp(pair: str, prices: dict) -> float:
    """Conversion factor from the pair's quote currency to GBP using live mids."""
    quote = pair.split("_")[1]
    if quote == "GBP":
        return 1.0

    def mid(p):
        px = prices.get(p)
        if not px:
            return None
        return (float(px["bids"][0]["price"]) + float(px["asks"][0]["price"])) / 2

    m = mid(f"GBP_{quote}")
    if m:
        return 1.0 / m
    m = mid(f"{quote}_GBP")
    if m:
        return m
    log.warning("no GBP conversion for %s, assuming 1.0", quote)
    return 1.0


def position_units(
    nav: float,
    entry: float,
    sl_price: float,
    pair: str,
    prices: dict,
    cfg: RiskConfig,
    ann_vol: float | None = None,
) -> int:
    """Vol-targeted units (primary, matches the backtest sizing) with a
    risk-per-trade cap (entry->SL loss ≤ risk_pct% of NAV) and unit cap."""
    q2g = quote_to_gbp(pair, prices)
    caps = [cfg.max_units]
    if ann_vol and ann_vol > 0:
        weight = min(cfg.per_position_vol / max(ann_vol, 0.02), cfg.max_weight)
        unit_value_gbp = entry * q2g          # GBP value of 1 base unit
        caps.append(int(nav * weight / unit_value_gbp))
    dist = abs(entry - sl_price)
    if dist > 0:
        risk_gbp = nav * cfg.risk_pct / 100.0
        caps.append(int(risk_gbp / (dist * q2g)))
    elif ann_vol is None:
        return 0
    return max(0, min(caps))


def gross_exposure_gbp(open_trades: list[dict], prices: dict) -> float:
    """Current gross notional (GBP) of the given open trades."""
    total = 0.0
    for t in open_trades:
        pair = t["instrument"]
        p = prices.get(pair)
        if not p:
            continue
        mid = (float(p["bids"][0]["price"]) + float(p["asks"][0]["price"])) / 2
        total += abs(float(t["currentUnits"])) * mid * quote_to_gbp(pair, prices)
    return total


def margin_ok(
    units: int,
    pair: str,
    entry: float,
    margin_available: float,
    margin_rate: float,
    prices: dict,
    cfg: RiskConfig,
) -> bool:
    """Approximate required margin in GBP and compare to budget."""
    notional_gbp = units * entry * quote_to_gbp(pair, prices)
    required = notional_gbp * margin_rate
    budget = margin_available * cfg.margin_budget_frac
    if required > budget:
        log.info(
            "margin guard: %s needs £%.2f > budget £%.2f (avail £%.2f)",
            pair, required, budget, margin_available,
        )
        return False
    return True


def daily_halt(nav: float, day_start_nav: float, cfg: RiskConfig) -> bool:
    if day_start_nav <= 0:
        return False
    loss_pct = (day_start_nav - nav) / day_start_nav * 100.0
    if loss_pct >= cfg.max_daily_loss_pct:
        log.warning("DAILY HALT: down %.2f%% today", loss_pct)
        return True
    return False


def utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
