#!/usr/bin/env python3
"""Run walk-forward backtests for all QuantumFX strategy candidates.

Usage: run_backtests.py [--only S1,S9] [--cost 1.5]
Writes reports/leaderboard.json + leaderboard.md.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import harness as H
import strategies_lib as S

REPORTS = Path(__file__).parent / "reports"
REPORTS.mkdir(exist_ok=True)

RANGE_CROSSES = ("AUD_NZD", "EUR_GBP", "EUR_CHF", "EUR_USD", "USD_CHF", "USD_CAD")


def sized(fn, **fixed):
    """Wrap a raw-signal strategy so walk_forward gets vol-targeted weights."""
    def wrapped(panel, per_position_vol=0.10, **params):
        raw = fn(panel, **{**fixed, **params})
        return H.vol_target_weights(raw, panel["close"], per_position_vol)
    return wrapped


def ml_walk_forward(panel, first_test_year, cost_mult, horizon=8, thresh=0.60):
    """S8: HistGB per fold; long/short when P(up) crosses threshold."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    X = S.ml_features(panel)
    close = panel["close"]
    fwd = close.pct_change(horizon).shift(-horizon)
    y = (fwd.stack() > 0).astype(int)
    y.name = "y"
    df = X.join(y, how="inner").dropna()
    index = close.index
    folds = H.yearly_folds(index, first_test_year)
    oos_parts, records = [], []
    for tr, te in folds:
        tr_end = tr[-1] - pd.Timedelta(hours=horizon * 5)  # embargo leakage gap
        dtr = df[df.index.get_level_values(0) <= tr_end]
        dte = df[(df.index.get_level_values(0) >= te[0]) & (df.index.get_level_values(0) <= te[-1])]
        if len(dtr) < 5000 or len(dte) < 500:
            continue
        clf = HistGradientBoostingClassifier(
            max_depth=4, max_iter=150, learning_rate=0.07,
            l2_regularization=1.0, random_state=42,
        )
        feats = [c for c in df.columns if c != "y"]
        clf.fit(dtr[feats], dtr["y"])
        proba = pd.Series(clf.predict_proba(dte[feats])[:, 1], index=dte.index)
        sig = pd.Series(0.0, index=dte.index)
        sig[proba > thresh] = 1.0
        sig[proba < 1 - thresh] = -1.0
        raw = sig.unstack().reindex(index=te, columns=close.columns).fillna(0.0)
        w = H.vol_target_weights(raw, close.loc[te[0]:te[-1]], 0.10)
        net = H.portfolio_returns(w, {k: v.loc[te[0]:te[-1]] for k, v in panel.items()}, cost_mult)
        m = H.metrics(net, w)
        records.append({"test_year": te[0].year, "params": {"horizon": horizon, "thresh": thresh}, **m})
        oos_parts.append(net)
    oos = pd.concat(oos_parts).sort_index() if oos_parts else pd.Series(dtype=float)
    return oos, records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--cost", type=float, default=1.5)
    args = ap.parse_args()

    print("loading panels...")
    h4 = H.load_panel("H4")
    h1 = H.load_panel("H1")

    specs = {
        "S1_trend_donchian_H4": dict(
            fn=sized(S.s1_trend_donchian), panel=h4, first=2022,
            grid=[{"entry_n": e, "exit_n": x} for e, x in [(55, 20), (110, 40), (30, 10), (165, 55)]],
        ),
        "S1b_trend_macross_H4": dict(
            fn=sized(S.s1_trend_macross), panel=h4, first=2022,
            grid=[{"fast": f, "slow": s} for f, s in [(30, 150), (20, 100), (50, 250)]],
        ),
        "S2_xsec_momentum_H4": dict(
            fn=sized(S.s2_xsec_momentum), panel=h4, first=2022,
            grid=[{"lookback": lb, "top_n": n} for lb in (120, 250, 500) for n in (2, 3)],
        ),
        "S3_zscore_mr_H4": dict(
            fn=sized(S.s3_zscore_mr, subset=RANGE_CROSSES), panel=h4, first=2022,
            grid=[{"n": n, "z_in": z} for n in (24, 48, 96) for z in (1.75, 2.25)],
        ),
        "S4_ou_mr_H4": dict(
            fn=sized(S.s4_ou_mr), panel=h4, first=2022,
            grid=[{"n": n, "z_in": z, "hl_max": hl} for n, z, hl in
                  [(48, 2.0, 60), (48, 2.5, 40), (96, 2.0, 80), (24, 2.0, 40)]],
        ),
        "S5_pairs_statarb_H4": dict(
            fn=sized(S.s5_pairs), panel=h4, first=2022,
            grid=[{"window": w, "z_in": z} for w in (350, 500, 750) for z in (2.0, 2.5)],
        ),
        "S6_london_breakout_H1": dict(
            fn=sized(S.s6_london_breakout), panel=h1, first=2024,
            grid=[{"k": k, "exit_h": e} for k in (0.0, 0.15) for e in (14, 16)],
        ),
        "S9_ensemble_H4": dict(
            fn=sized(S.s9_ensemble), panel=h4, first=2022,
            grid=[
                {"vr_hi": 1.05, "vr_lo": 0.97, "top_k": 3},
                {"vr_hi": 1.02, "vr_lo": 0.95, "top_k": 3},
                {"vr_hi": 1.05, "vr_lo": 0.97, "top_k": 4},
                {"vr_hi": 1.00, "vr_lo": 1.00, "top_k": 3},  # trend-only when vr>=1
            ],
        ),
        "S14_gap_fade_H1": dict(
            fn=sized(S.s14_gap_fade), panel=h1, first=2024,
            grid=[{"min_gap_atr": g} for g in (0.25, 0.5, 1.0)],
        ),
    }

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    results = []
    for name, spec in specs.items():
        if only and not any(name.startswith(o) for o in only):
            continue
        t0 = time.time()
        print(f"running {name} ...", flush=True)
        try:
            oos, recs = H.walk_forward(
                spec["fn"], spec["grid"], spec["panel"], spec["first"], args.cost
            )
            summary = H.summarize_wf(name, oos, recs)
            oos.to_pickle(REPORTS / f"oos_{name}.pkl")
        except Exception as e:  # keep the sweep alive; report the failure
            summary = {"strategy": name, "error": repr(e)}
        summary["elapsed_s"] = round(time.time() - t0, 1)
        results.append(summary)
        print(f"  -> {summary.get('oos', summary.get('error'))}", flush=True)

    if not only or "S8" in only:
        t0 = time.time()
        print("running S8_ml_H4 ...", flush=True)
        try:
            oos, recs = ml_walk_forward(h4, 2022, args.cost)
            summary = H.summarize_wf("S8_ml_H4", oos, recs)
            oos.to_pickle(REPORTS / "oos_S8_ml_H4.pkl")
        except Exception as e:
            summary = {"strategy": "S8_ml_H4", "error": repr(e)}
        summary["elapsed_s"] = round(time.time() - t0, 1)
        results.append(summary)
        print(f"  -> {summary.get('oos', summary.get('error'))}", flush=True)

    results.sort(key=lambda r: r.get("oos", {}).get("sharpe", -99), reverse=True)
    H.save_report({"cost_mult": args.cost, "results": results}, REPORTS / "leaderboard.json")

    lines = [
        f"# QuantumFX leaderboard (cost x{args.cost}, walk-forward OOS)",
        "",
        "| strategy | OOS Sharpe | ann ret | maxDD | bar PF | +folds | trades/yr |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        o = r.get("oos", {})
        if not o:
            lines.append(f"| {r['strategy']} | ERROR: {r.get('error','?')[:60]} | | | | | |")
            continue
        lines.append(
            f"| {r['strategy']} | {o['sharpe']} | {o['ann_return']:.1%} | {o['max_dd']:.1%} "
            f"| {o['bar_pf']} | {r['positive_folds']} | {r['folds'][-1].get('approx_trades_per_year','-')} |"
        )
    (REPORTS / "leaderboard.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
