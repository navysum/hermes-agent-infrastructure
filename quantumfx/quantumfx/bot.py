"""QuantumFX main loop — 24/5 OU mean-reversion bot on OANDA H4 candles.

Coexists with the live fx-live-bot on the same account: every order is tagged
'quantumfx', sized to ~1.5% NAV risk, margin-guarded against the SHARED
margin pool, and always carries a server-side stop loss so nothing depends
on this process staying alive.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from . import config, notify, risk, state, strategy
from .oanda import OandaClient

log = logging.getLogger("quantumfx.bot")

# median H4 close spreads from research data (research/fetch.log)
TYPICAL_SPREAD = {
    "EUR_USD": 0.00015, "GBP_USD": 0.00019, "USD_JPY": 0.016,
    "AUD_USD": 0.00013, "NZD_USD": 0.00016, "USD_CAD": 0.00019,
    "USD_CHF": 0.00016, "EUR_JPY": 0.020, "GBP_JPY": 0.030,
    "EUR_GBP": 0.00015, "AUD_NZD": 0.00027, "EUR_CHF": 0.00017,
}
SPREAD_SANITY_MULT = 3.0


class QuantumFX:
    def __init__(self):
        self.client = OandaClient()
        self.cfg = config.STRATEGY
        self.rcfg = config.RISK
        self.meta = self.client.instruments(config.PAIRS)
        self._dfs: dict = {}
        state.set_meta("started_at", datetime.now(timezone.utc).isoformat())
        log.info(
            "QuantumFX up: %s %s pairs=%s dry_run=%s",
            self.client.host, self.client.account_id, config.PAIRS, config.DRY_RUN,
        )

    # ── helpers ─────────────────────────────────────────────────────────
    def qfx_trades(self) -> list[dict]:
        out = []
        for t in self.client.open_trades():
            tag = (t.get("clientExtensions") or {}).get("tag", "")
            if tag == config.TAG:
                out.append(t)
        return out

    def day_anchor(self, nav: float) -> float:
        today = risk.utc_day()
        anchor = state.get_meta("day_anchor", {})
        if anchor.get("day") != today:
            anchor = {"day": today, "nav": nav}
            state.set_meta("day_anchor", anchor)
        return anchor["nav"]

    def spread_sane(self, pair: str, prices: dict) -> bool:
        p = prices.get(pair)
        if not p or not p.get("tradeable", True):
            return False
        cur = float(p["asks"][0]["price"]) - float(p["bids"][0]["price"])
        typ = TYPICAL_SPREAD.get(pair)
        if typ and cur > SPREAD_SANITY_MULT * typ:
            log.info("%s spread %.5f > %.1fx typical, skipping", pair, cur, SPREAD_SANITY_MULT)
            return False
        return True

    # ── core cycle ──────────────────────────────────────────────────────
    def process_pair(self, pair: str, open_by_pair: dict, prices: dict, halted: bool, jpy_blocked: bool) -> dict | None:
        """Handle exits for `pair`; return an entry candidate dict or None."""
        candles = self.client.candles(pair, config.GRANULARITY, count=600)
        if len(candles) < self.cfg.min_bars:
            return None
        newest = candles[-1]["time"]
        last_seen = state.get_meta(f"last_bar_{pair}")
        if newest == last_seen:
            return None
        df = strategy.candles_to_df(candles)
        self._dfs[pair] = df
        ind = strategy.indicators(df, self.cfg)
        state.set_meta(f"last_bar_{pair}", newest)
        log.info(
            "%s bar %s close=%.5f z=%.2f hl=%.1f vr=%.2f",
            pair, newest, ind["close"], ind["z"], ind["half_life"], ind["vr"],
        )

        trade = open_by_pair.get(pair)
        if trade:
            self.manage_exit(pair, trade, ind)
            return None

        if halted or risk.kill_switch_active():
            return None
        if jpy_blocked and pair.endswith("JPY"):
            log.info("%s entry blocked: JPY vol circuit breaker", pair)
            return None
        sig = strategy.entry_signal(ind, self.cfg)
        if sig == 0:
            return None
        if not self.spread_sane(pair, prices):
            return None
        return {"pair": pair, "sig": sig, "ind": ind}

    def candidate_corr(self, pairs: list[str]) -> "pd.DataFrame":
        import pandas as pd

        closes = pd.DataFrame({p: self._dfs[p]["close"] for p in pairs if p in self._dfs})
        return closes.pct_change().tail(500).corr().fillna(0.0)

    def enter(self, pair: str, sig: int, ind: dict, acct: dict, prices: dict) -> None:
        if ind["atr"] <= 0 or ind["ann_vol"] <= 0:
            return
        entry = ind["close"]
        sl = entry - sig * self.rcfg.sl_atr_mult * ind["atr"]
        nav = float(acct["NAV"])
        gross = risk.gross_exposure_gbp(self.qfx_trades(), prices)
        if gross >= self.rcfg.max_gross * nav:
            log.info("%s entry blocked: gross £%.2f >= %.1fx NAV", pair, gross, self.rcfg.max_gross)
            return
        units = risk.position_units(nav, entry, sl, pair, prices, self.rcfg, ann_vol=ind["ann_vol"])
        if units < 1:
            log.info("%s units<1 at NAV £%.2f, skip", pair, nav)
            return
        margin_rate = float(self.meta[pair].get("marginRate", 0.0333))
        if not risk.margin_ok(units, pair, entry, float(acct["marginAvailable"]), margin_rate, prices, self.rcfg):
            state.log_trade(pair, "REJECTED", reason="margin_guard", z=ind["z"])
            return
        signed_units = units * sig
        # mean-reversion target = SMA; only attach TP if it clears house min RR
        tp = ind["sma"]
        rr = abs(tp - entry) / max(abs(entry - sl), 1e-9)
        tp_price = tp if rr >= self.rcfg.min_rr_tp else None
        if config.DRY_RUN:
            log.info("DRY RUN: would open %s %+d @%.5f SL %.5f", pair, signed_units, entry, sl)
            return
        try:
            resp = self.client.market_order(pair, signed_units, sl_price=sl, tp_price=tp_price, tag=config.TAG)
        except Exception as e:
            state.log_trade(pair, "REJECTED", reason=f"order_error:{e}", z=ind["z"])
            return
        fill = resp.get("orderFillTransaction", {})
        trade_id = (fill.get("tradeOpened") or {}).get("tradeID", "")
        price = float(fill.get("price", entry))
        state.log_trade(
            pair, "OPEN", units=signed_units, price=price, oanda_trade_id=trade_id,
            reason="ou_entry", z=ind["z"], half_life=ind["half_life"],
        )
        if trade_id:
            state.set_meta(f"trade_hl_{trade_id}", ind["half_life"])
        notify.send(
            f"OPEN {pair} {'LONG' if sig>0 else 'SHORT'} {units}u @ {price:.5f}\n"
            f"z={ind['z']:.2f} hl={ind['half_life']:.0f} SL={sl:.5f}"
            + (f" TP={tp_price:.5f}" if tp_price else " (z-exit managed)")
        )

    def manage_exit(self, pair: str, trade: dict, ind: dict) -> None:
        units = int(float(trade["currentUnits"]))
        direction = 1 if units > 0 else -1
        opened = datetime.fromisoformat(trade["openTime"].split(".")[0] + "+00:00")
        hours = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
        bars_held = hours / 4.0
        entry_hl = state.get_meta(f"trade_hl_{trade['id']}", 20.0)
        reason = strategy.exit_signal(direction, ind, bars_held, entry_hl, self.cfg)
        if not reason:
            return
        if config.DRY_RUN:
            log.info("DRY RUN: would close %s (%s)", pair, reason)
            return
        try:
            resp = self.client.close_trade(trade["id"])
        except Exception as e:
            log.error("close %s failed: %s", trade["id"], e)
            return
        fill = resp.get("orderFillTransaction", {})
        pl = float(fill.get("pl", 0.0))
        state.log_trade(
            pair, "CLOSE", units=units, price=float(fill.get("price", 0)),
            oanda_trade_id=trade["id"], reason=reason, z=ind["z"], detail={"pl": pl},
        )
        notify.send(f"CLOSE {pair} ({reason}) P/L £{pl:+.2f} z={ind['z']:.2f}")

    def cycle(self) -> None:
        acct = self.client.summary()
        nav = float(acct["NAV"])
        anchor = self.day_anchor(nav)
        halted = risk.daily_halt(nav, anchor, self.rcfg)
        was_halted = state.get_meta("halted_today") == risk.utc_day()
        if halted and not was_halted:
            state.set_meta("halted_today", risk.utc_day())
            notify.send(f"DAILY HALT — NAV £{nav:.2f}, no new entries until tomorrow UTC")
        open_qfx = self.qfx_trades()
        open_by_pair = {t["instrument"]: t for t in open_qfx}
        prices = self.client.pricing(config.PAIRS)
        jpy_blocked = False
        try:
            uj = strategy.candles_to_df(self.client.candles("USD_JPY", config.GRANULARITY, count=600))
            jpy_blocked = strategy.jpy_vol_spike(uj, mult=config.JPY_VOL_MULT)
        except Exception:
            log.exception("jpy circuit breaker check failed (failing open=blocked)")
            jpy_blocked = True
        candidates = []
        for pair in config.PAIRS:
            try:
                cand = self.process_pair(pair, open_by_pair, prices, halted or was_halted, jpy_blocked)
                if cand:
                    candidates.append(cand)
            except Exception:
                log.exception("pair %s cycle error", pair)
        if candidates:
            if len(candidates) > 1:
                corr = self.candidate_corr([c["pair"] for c in candidates])
                kept = strategy.anneal_candidates(candidates, corr, lam=config.ANNEAL_LAMBDA)
                dropped = {c["pair"] for c in candidates} - {c["pair"] for c in kept}
                if dropped:
                    log.info("annealer dropped correlated candidates: %s", sorted(dropped))
                candidates = kept
            for cand in candidates:
                if len(self.qfx_trades()) >= self.rcfg.max_positions:
                    break
                try:
                    self.enter(cand["pair"], cand["sig"], cand["ind"], acct, prices)
                except Exception:
                    log.exception("entry %s failed", cand["pair"])
        last_snap = state.get_meta("last_equity_snap", 0)
        if time.time() - last_snap > config.EQUITY_SNAPSHOT_MINUTES * 60:
            state.snapshot_equity(nav, float(acct.get("marginUsed", 0)), len(open_qfx))
            state.set_meta("last_equity_snap", time.time())
        state.heartbeat("ok", {"nav": nav, "open_qfx": len(open_qfx), "halted": bool(halted or was_halted)})

    def run(self) -> None:
        notify.send(f"started ({'DRY RUN' if config.DRY_RUN else 'LIVE'}) — pairs: {', '.join(config.PAIRS)}")
        errors = 0
        while True:
            try:
                self.cycle()
                errors = 0
            except Exception:
                log.exception("cycle error")
                errors += 1
                if errors == 5:
                    notify.send("5 consecutive cycle errors — check logs")
                state.heartbeat("error")
            time.sleep(config.POLL_SECONDS)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    QuantumFX().run()


if __name__ == "__main__":
    main()
