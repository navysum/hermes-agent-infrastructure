# Agent A — S4 OU Mean-Reversion Robustness Audit

Data: OANDA H4, 12 pairs, 2019-01-01 → 2026-07-01, real per-bar spreads. Eval window 2022-01-01+ (4.5y).
Costs: real half-spread x cost_mult + 0.2pip slippage per side. Sizing: vol-target 10%/position, gross cap 3.0 (run_backtests `sized` convention).
Sanity: causality verified (signals identical when future bars removed, max diff 0.0); no NaN/inf weights; per-pair PnL decomposition exact (err <1e-15).

## 1. Parameter neighborhood (full-period 2022+, cost 1.5x)

**65 configs swept; 95.4% positive Sharpe. Median 0.49, IQR 0.37–0.61, min -0.28, max 0.97.** It is a plateau, not a spike — but the plateau tilts: slow lookbacks (n≥72) and higher entry bars (z_in≥2.0) are uniformly better; the previously fold-selected n=48 sits on the weak edge.

Pass A — Sharpe, n × z_in (z_out=0.25, hl_max=60, vr_max=0.95):

| n \ z_in | 1.75 | 2.00 | 2.25 | 2.50 |
|---|---:|---:|---:|---:|
| 36 | -0.28 | -0.01 | 0.15 | 0.61 |
| 48 | -0.08 | 0.20 | 0.20 | 0.40 |
| 72 | 0.23 | 0.54 | 0.62 | 0.84 |
| 96 | 0.34 | 0.66 | 0.72 | 0.61 |
| 120 | 0.49 | 0.54 | 0.51 | 0.57 |

Stable center by neighborhood-mean Sharpe: **n=96, z_in≈2.25** (only 3/20 cells negative, all at n≤48 & z_in<2.25).

Pass B — Sharpe, hl_max × vr_max at n=96, z_in=2.5 (z_out=0.25 slice; z_out=0.0/0.5 tables in JSON):

| hl_max \ vr_max | 0.90 | 0.95 | 1.00 |
|---|---:|---:|---:|
| 30 | 0.97 | 0.83 | 0.56 |
| 40 | 0.58 | 0.60 | 0.46 |
| 60 | 0.55 | 0.61 | 0.39 |
| 80 | 0.67 | 0.53 | 0.36 |
| 100 | 0.75 | 0.58 | 0.41 |

- All 45 pass-B cells positive. z_out=0.25 ≥ z_out=0.5 > z_out=0.0 everywhere.
- vr gate earns its keep: vr_max=1.00 is the worst column in every row → the variance-ratio filter is real signal, not decoration.
- **hl_max=30 is a spike** (0.97 → 0.58 one step away, grid edge). Do not chase it. hl_max 40–100 is flat (0.5–0.75): the half-life gate barely matters beyond "not trending".

## 2. Cost stress (full-period 2022+, top-3 neighborhood-stable configs; all n=96, z_in=2.5)

| config (hl/vr/z_out) | 1.0x | 1.5x | 2.0x | 3.0x |
|---|---:|---:|---:|---:|
| 30 / 0.90 / 0.25 | 1.02 | 0.97 | 0.92 | 0.81 |
| 30 / 0.90 / 0.50 | 0.92 | 0.86 | 0.81 | 0.71 |
| 30 / 0.95 / 0.25 | 0.88 | 0.83 | 0.78 | 0.67 |

Sharpe decays ~0.05 per +0.5x cost and stays positive at 3x. Turnover ~213/yr, ~80 trades/yr — cost robustness is genuine, not borderline. (Recommended config at WF: 0.72 @1.5x → 0.64 @2.0x, same gentle slope.)

## 3. Per-pair attribution (n=96, z_in=2.25, hl=60, cum net 2022+, all12 book)

| pair | 2022 | 2023 | 2024 | 2025 | 2026 | total |
|---|---:|---:|---:|---:|---:|---:|
| EUR_JPY | +.061 | +.037 | +.001 | +.077 | +.016 | **+.191** |
| GBP_JPY | +.034 | +.055 | +.013 | +.023 | +.016 | **+.140** |
| AUD_USD | -.008 | +.049 | -.017 | +.126 | -.027 | +.123 |
| EUR_CHF | +.020 | +.019 | +.020 | +.034 | -.004 | +.090 |
| EUR_USD | +.022 | -.027 | +.039 | +.019 | -.003 | +.051 |
| EUR_GBP | -.034 | +.023 | +.028 | -.012 | +.022 | +.028 |
| USD_CAD | +.079 | -.041 | -.006 | -.007 | +.000 | +.024 |
| NZD_USD | -.025 | +.022 | -.031 | +.038 | +.015 | +.019 |
| USD_CHF | -.038 | -.007 | -.001 | +.036 | +.007 | -.003 |
| USD_JPY | -.038 | +.012 | -.055 | -.002 | +.032 | -.051 |
| GBP_USD | -.052 | -.006 | -.003 | -.009 | +.018 | -.053 |
| AUD_NZD | +.008 | +.001 | -.008 | -.027 | -.030 | -.057 |

- **The edge is concentrated: EUR_JPY + GBP_JPY + AUD_USD + EUR_CHF ≈ 0.54 cum vs portfolio 0.50** — the bottom 4 pairs are a net -0.16 drag. Same top-4 under the two legacy fold configs (n48/z2.5/hl40 and n96/z2.0/hl80) → pair ranking is config-stable, and EUR_JPY/GBP_JPY are positive in all 5 calendar years.
- JPY pairs do NOT drag as a group — the JPY *crosses* are the engine; USD_JPY itself is negative. High spread isn't the discriminator either (AUD_NZD 1.56bp half-spread loses, GBP_JPY 1.07bp wins; USD_JPY has the lowest spread and loses).
- Ex-JPY the strategy nearly dies: full-period Sharpe 0.72 → **0.395**.

## 4. Universe walk-forward (first_test_year=2022, cost 1.5x, 6-config grid)

| universe | OOS Sharpe | ann ret | maxDD | +folds |
|---|---:|---:|---:|---:|
| complement6 (GBP_USD, USD_JPY, AUD_USD, NZD_USD, EUR_JPY, GBP_JPY) | **0.88** | +13.4% | -34.2% | 4/5 |
| all12 | 0.73 | +10.1% | -32.5% | 4/5 |
| crosses3 (AUD_NZD, EUR_GBP, EUR_CHF) | 0.11 | +0.5% | -13.6% | 3/5 |
| crossesUSD6 (crosses3 + EUR_USD, USD_CHF, USD_CAD) | **-0.11** | -1.7% | -23.7% | 2/5 |

The "quiet range-bound crosses" story is dead for S4: the restricted low-vol universe is flat-to-negative; the JPY-cross/USD-major half carries everything. (Note: grid-WF maxDD numbers are inflated by fold param-switching — see §5.)

## 5. Temporal stability

- Grid-WF complement6 stream: median 6m Sharpe 1.35, 19% of 6m windows negative, **worst 6m = 2024-06-21 → 2024-12-20: Sharpe -3.9, -39.6%**. 2024 fold = -23% while the same grid made +33%/+46% in 2023/2025 → **one regime (2024 H2 JPY carry-unwind/intervention chop), not a slow bleed**.
- Fixed-config all12 (n=96, z_in=2.25, hl=60): 2024 monthly shows the same shape — Jan–Jun all positive (+11.5%), then Jul -6.6%, Aug -6.1%, Oct -3.3%, Dec -3.1%. Worst 6m -17.3% (Sharpe -1.96); 26% of 6m windows negative; year ends only -2.1%.
- **Fold param-selection amplified 2024**: the grid picked n=48/z2.5/hl80 for 2024 (best on 2022–23 train) and lost -24%; the fixed n=96 center lost -3%. The selection layer is itself a fragility source — prefer a fixed config.

## Verdict and recommendation

**Verdict: MIXED.** Parameter surface and cost robustness are genuinely broad (95% of neighborhood positive, survives 3x spreads, VR gate adds value, no lookahead artifacts). But the PnL is carried by ~4 pairs — above all the JPY crosses — with a demonstrated -17% (fixed cfg) to -40% (grid, concentrated book) 6-month tail when the yen regime breaks, and 2025 supplies ~half the OOS return.

**Recommended production config (stability over peak):** universe **all12** (keeps diversification; avoids post-hoc universe cherry-pick; complement6-only is the higher-octane variant with 3/5 folds), **n=96, z_in=2.25, z_out=0.25, hl_max=60, vr_max=0.95**, fixed — no per-fold param selection.

Walk-forward OOS (first_test_year=2022), that config, all12:

| cost | Sharpe | ann ret | maxDD | +folds | yearly ret |
|---|---:|---:|---:|---:|---|
| 1.5x | **0.72** | **+10.6%** | **-18.1%** | 4/5 | '22 +1.0, '23 +13.4, '24 -3.1, '25 +33.0, '26H1 +6.4 (%) |
| 2.0x | **0.64** | **+9.2%** | **-18.7%** | 3/5 | '22 -0.3, '23 +12.2, '24 -4.2, '25 +30.8, '26H1 +5.8 (%) |

**Three biggest caveats**
1. **Pair concentration / JPY dependence.** EUR_JPY+GBP_JPY+AUD_USD+EUR_CHF ≈ 100%+ of net PnL; ex-JPY Sharpe is 0.395. A yen carry-unwind regime (Jul–Dec 2024 replay) costs -6%/month for months at this sizing; size for that tail, consider a JPY-vol circuit breaker.
2. **Config chosen with full-period visibility.** The n=96/z2.25 center came from a 2022–26 sensitivity map (chosen for neighborhood stability, not peak, but still the same data the WF is scored on), and 2025 alone contributes ~half the OOS return — true forward Sharpe is plausibly nearer the neighborhood median ~0.5 than 0.72.
3. **Short, regime-sparse sample.** 4.5y OOS, H4 close-to-close fills, one MR-friendly macro cycle (2023/2025); hl_max is doing almost nothing on the plateau (gate rarely binds 40–100), so the "OU" framing is mostly a VR filter + slow z-score — expect the 2024-style failure mode to recur, and don't chase the hl_max=30 corner (grid-edge spike).

Artifacts: `reports/agentA_s4_robustness.json` (all tables), `agents/agentA/{s4_sweep,s4_universe_wf,s4_deepdive_2024}.py`, `agents/agentA/out_{sweep,universe,deepdive}.json`, OOS streams `agents/agentA/oos_*.pkl`.
