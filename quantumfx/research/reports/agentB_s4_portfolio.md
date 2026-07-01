# S4 portfolio construction (agent B)

Alpha frozen throughout: `s4_ou_mr(n=48, z_in=2.0, z_out=0.25, hl_max=60, vr_max=0.95)`,
H4, all 12 pairs, real per-bar half-spread x1.5 + slippage. Construction engine
(`agents/agentB/s4_construct.py`) reproduces `strategies_lib.s4_ou_mr` bit-exactly with all
layers off (0/140,256 cells differ) and the baseline walk-forward headline (Sharpe 0.521,
+6.3%/yr, maxDD -24.6%, 4/5 folds). Stage comparisons: fixed-param, full-period, metrics on
2022+ slice. Finalists: `harness.walk_forward`, first_test_year=2022, 4-point alpha grid.

## E1 — Time-stop (exit after k x half-life-at-entry, re-arm cooldown)

| k | Sharpe | ann | maxDD |
|---|---:|---:|---:|
| none | **0.207** | +2.0% | **-30.6%** |
| 1 | 0.068 | -0.1% | -36.0% |
| 2 | 0.086 | +0.2% | -35.2% |
| 3 | 0.064 | -0.2% | -34.9% |

**Verdict: no time-stop.** Every k hurts both Sharpe and DD — S4's z-exit already ends winners;
the time-stop mostly crystallizes losers early and re-enters worse.

## E2 — Portfolio-level vol target (trailing 250-bar realized, scale cap 2x)

On baseline: Sharpe 0.207 -> 0.019 at all of {8,10,12}% (scale <1 almost always, cap never
binds, so the three targets are the same series x a constant — identical Sharpe is the
tell-tale). Stacked on the best capped book (anneal k=2): 0.359 -> 0.21-0.22; 20% hysteresis
doesn't rescue it (0.22). It does cut DD (-20.8% -> -13.0% at 8%) but MAR falls too
(0.19 -> 0.11): it's inverse-vol timing of a strategy whose payoff clusters in high-vol
regimes, plus re-scaling turnover.

**Verdict: skip the portfolio vol layer.** Bar net returns are *exactly* linear in the
per-position vol target (PnL and all cost terms proportional to w), so a lower constant
per-position vol delivers any desired DD at **unchanged Sharpe** — strictly dominates the
dynamic layer here.

## E3 — Max concurrent positions (top-|z| ranking, full period 2022+)

| N | Sharpe | ann | maxDD | avg pos |
|---|---:|---:|---:|---:|
| 2 | **0.270** | +2.9% | **-25.5%** | 1.6 |
| 3 | 0.177 | +1.6% | -34.4% | 2.3 |
| 4 | 0.161 | +1.3% | -33.1% | 2.7 |
| unlimited | 0.207 | +2.0% | -30.6% | 3.5 (max 11) |

N=2 is the best cap; N=3/4 keep the worst marginal entries while losing breadth.
**Margin reality (tiny account @ 30:1):** harness gross is capped at 3.0 -> max notional ~3x NAV, margin
~10% of NAV — margin never binds, even unlimited. The real small-account bind is granularity
(roughly 1-1.5x NAV per position — a handful of units, fine on OANDA) and monitoring; N=2 is an operational choice.
Its walk-forward cost vs unlimited: -0.15 Sharpe (top-N) / -0.11 (anneal), see finalists.

## E4 — Annealed basket selection vs plain top-N (full period 2022+)

| selector | Sharpe | ann | maxDD |
|---|---:|---:|---:|
| top-N, k=2 | 0.270 | +2.9% | -25.5% |
| anneal k=2, lam=0.2 | **0.359** | +4.1% | **-20.8%** |
| anneal k=2, lam=0.35 | 0.349 | +3.9% | -20.8% |
| anneal k=2, lam=0.5 | 0.290 | +3.1% | -23.2% |
| top-N, k=3 | 0.177 | +1.6% | -34.4% |
| anneal k=3 (best lam) | 0.242 | +2.6% | -26.4% |

**The annealer genuinely beats top-N at k=2** (+0.09 Sharpe, -4.7pt DD full-period; +0.04
Sharpe, -0.9pt DD walk-forward, holds at 2x costs). The edge comes from the corr penalty
vetoing redundant/correlated second entries, not from the optimizer itself. lam 0.2 vs 0.35
is a wash (identical under walk-forward). At k=3 the edge shrinks; with unlimited slots the
annealer is pointless.

## E6 — Finalist walk-forward OOS 2022-2026 (expanding folds, alpha grid selected per fold)

| construction | cost | Sharpe | ann | maxDD | +folds |
|---|---|---:|---:|---:|---:|
| unlimited @pvol 0.10 (baseline) | 1.5x | 0.521 | +6.3% | -24.6% | 4/5 |
| unlimited @pvol 0.10 | 2.0x | 0.422 | +4.9% | -25.5% | 3/5 |
| top-N=2 @0.10 | 1.5x | 0.373 | +4.4% | -21.0% | 3/5 |
| top-N=2 @0.10 | 2.0x | 0.320 | +3.6% | -21.9% | 3/5 |
| **anneal k=2 lam=0.2/0.35 @0.10** | 1.5x | **0.414** | **+5.1%** | **-20.1%** | 2/5 |
| **anneal k=2 lam=0.2/0.35 @0.10** | 2.0x | **0.362** | **+4.3%** | **-20.3%** | 2/5 |

Exact de-lever rows (same Sharpe by construction): anneal k=2 @0.08 -> +4.2%/yr, DD -16.4%;
@0.07 -> +3.8%/yr, DD -14.4%. Unlimited @0.08 -> Sharpe 0.521, +5.2%/yr, DD -20.1%.

Honest caveats: (i) the capped books concentrate — 2025 (+42%) carries the anneal OOS, folds
2022/2024/2026 mildly negative (2/5 positive vs baseline 4/5); (ii) if you can run all 12
pairs, **unlimited @0.08 dominates the capped book on paper** (same -20% DD, Sharpe 0.521 vs
0.414). The cap is justified by account practicality, not by the numbers.

## E5 — Monte Carlo ruin (stationary block bootstrap, mean block 60 H4 bars ~ 2 weeks, 2000 x 1yr, finalist OOS stream, cost 1.5x)

| sizing | ann ret med [p5, p95] | P(yr<0) | maxDD med | maxDD p5 | P(DD<-20%) | P(DD<-50%) ruin |
|---|---|---:|---:|---:|---:|---:|
| anneal k=2 @0.10 | +5.3% [-15.4%, +29.9%] | 34% | -12.7% | -23.3% | 10.9% | 0/2000 (<0.05%) |
| anneal k=2 @0.07 | +3.9% [-10.8%, +20.4%] | 33% | -9.0% | -16.8% | 1.8% | 0/2000 |
| unlimited @0.08 | (Sharpe 0.521 stream x0.8) | 31% | -9.7% | -19.2% | 3.8% | 0/2000 |

## Recommendation

- **Time-stop: none.** All k in {1,2,3} strictly hurt Sharpe and DD.
- **Portfolio vol target: none.** Cuts Sharpe ~40%+ in every variant; DD control belongs in
  the constant per-position vol knob (exactly Sharpe-preserving). Run **per-position vol
  0.07-0.08** for the tiny account.
- **Max positions: 2** — realistic for the account and the best cap tested; quantified cost
  vs unlimited is -0.11 WF Sharpe (with anneal). If sizing granularity ever allows the full
  book, unlimited @0.08 is the better paper construction.
- **Selection: annealed basket (lam 0.2-0.35, k=2).** Yes — it beats plain top-N at every
  cost and horizon tested (WF 0.414 vs 0.373; full-period 0.359 vs 0.270; DD better ~1-5pt).
  Modest but consistent; keep it. A cheap "greedy corr-veto" would likely capture most of it.

Scripts: `agents/agentB/{s4_construct,test_engine,run_experiments,run_exp2b,run_finalist,run_delever}.py`.
Full numbers: `reports/agentB_s4_portfolio.json`.
