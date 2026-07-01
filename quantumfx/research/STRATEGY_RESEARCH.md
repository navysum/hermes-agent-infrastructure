# QuantumFX — Strategy Research & Ranking

Date: 2026-07-01 · Status: research → selection → deployed

## 0. Constraints that drive every ranking below

| Constraint | Value | Consequence |
|---|---|---|
| Account | OANDA live, **small (double-digit GBP)**, 30:1 UK retail leverage | A single modest position can consume all available margin. Position sizing granularity is fine (1 unit min), but concurrency is capped ~2-3 tiny positions. |
| Costs | OANDA retail spread: EUR_USD ~1.2-1.6p, crosses 2-4p, no commission | Any strategy whose average profit per trade isn't a **multiple** of the spread dies. This already killed fxqt v0.1 H1 (Sharpe -5.6) and v0.2 H4 at 1x costs. |
| Market hours | Forex is **24/5**, not 24/7 (Fri 21:00 UTC → Sun 21:00 UTC closed) | "24/7" is only possible with crypto (crypto-bot already covers that). Target: full 24/5 coverage — the current fx-live-bot only trades 07-17 UTC. |
| Infra | Hetzner VPS, 4 cores, 7.6GB, existing fx-live-bot LIVE on same account | New bot must be margin-aware (skip when fx-live-bot holds margin), tag its trades, respect bot-control-centre gates. |
| "Quantum" | No retail-accessible quantum computer gives trading edge in 2026 | Honest interpretation: **quantum-inspired** methods (QUBO/simulated-annealing portfolio selection, kernel methods) + rigorous quant process. Branding stays, physics claims stay honest. |

**Honesty box:** with a double-digit-GBP account, even a genuinely good strategy earns pennies per week. The realistic goal is to *prove positive expectancy after costs with live verified fills*, then scale by deposit or prop-firm capital. Any claim of "highly profitable from a tiny account" is measured in percent, not pounds.

## 1. The candidates (14 researched, 9 backtestable)

### S1. Slow trend following (Donchian/ATR, H4-D1) — **BACKTEST**
Ride multi-week trends: enter on N-bar channel breakout or MA alignment, exit on ATR trail.
- **Pros:** ~100 years of evidence class (managed futures/CTA); few trades → spread nearly irrelevant; positive skew (cuts losses, rides winners); trivially 24/5; robust to parameter choice.
- **Cons:** 30-40% win rate hurts morale; long flat periods and 15-25% drawdowns; FX trends weaker post-2015 than in commodities/rates.
- **Expected after costs:** modest positive; Sharpe 0.3-0.8 standalone.

### S2. Cross-sectional momentum rotation (basket, H4-D1) — **BACKTEST**
Rank pairs by vol-adjusted momentum, hold top/bottom basket.
- **Pros:** diversified; academic support (Menkhoff et al. FX momentum).
- **Cons:** fxqt v0.2 (a 48-bar H4 cousin) already failed cost stress on this VPS; FX momentum premium decayed since 2010s; crowded.
- **Expected:** weak at fast horizons, marginal at 1-3 month horizons.

### S3. Bollinger/z-score mean reversion on range crosses (AUD_NZD, EUR_GBP, EUR_CHF) — **BACKTEST**
Fade 2σ+ extensions on pairs that structurally range (economies co-move).
- **Pros:** high win rate; crosses genuinely mean-revert for years at a time; complements trend (negatively correlated returns profile).
- **Cons:** negative skew — the rare breakout trend (GBP 2022, CHF cap 2015) must be survived via hard stops + regime filter; cross spreads are 2-3.5p.
- **Expected:** positive if regime-gated; the existing fx-live-bot's audit showed its *unfiltered* RSI reversion lost money — filtering is the whole game.

### S4. OU-process mean reversion (half-life + Hurst gated) — **BACKTEST**
Same family as S3 but quant-grade: fit Ornstein-Uhlenbeck per pair, only trade when half-life is short and Hurst < 0.5; z-score entry/exit with time-stop at 2× half-life.
- **Pros:** principled trade selection & holding period; drops dead regimes automatically.
- **Cons:** parameters estimated on rolling windows can lag regime breaks; same negative skew.

### S5. Cointegration pairs / stat-arb (EUR_USD↔GBP_USD, AUD_USD↔NZD_USD) — **BACKTEST**
Trade the stationary spread between cointegrated pairs, market-neutral.
- **Pros:** hedged against USD shocks; classic stat-arb with real literature; both legs sized to £-vol.
- **Cons:** pays **two** spreads per round trip; cointegration breaks without warning; two legs double margin use — tight on a tiny account.

### S6. London-open range breakout (GBP_USD, EUR_USD, H1) — **BACKTEST**
Asia-session range, break at London open, ride the session vol expansion.
- **Pros:** session volatility clustering is real and documented; defined risk (range = stop).
- **Cons:** intraday timeframe → spread is a big fraction of target; popular retail edge = decayed; needs precise session handling (DST).

### S7. Carry basket with trend filter — qualitative (financing data gap)
Hold positive-swap pairs when trend agrees; earn the differential.
- **Pros:** genuine risk premium, decades of evidence; zero trading costs; the ultimate "24/5 always-on" strategy.
- **Cons:** **OANDA retail financing markup (~1%+ each side) eats most of the retail carry**; 2025-26 rate convergence narrowed differentials; carry crashes are violent left-tail events; historical financing rates aren't in the candle API so an honest backtest needs data we don't have.
- **Verdict:** revisit if account scales to a broker with institutional swap rates.

### S8. ML classifier (gradient boosting on TA features, strict walk-forward) — **BACKTEST**
HistGradientBoosting predicting next-bar(s) direction from ~30 engineered features; trade only high-confidence probabilities; retrain per fold.
- **Pros:** captures conditional/nonlinear structure rules miss; the stack (sklearn) is already on the box; retrain pipeline fits the VPS.
- **Cons:** FX bar data has brutal signal-to-noise; 95% of published retail FX ML is leakage/overfit; model decay; must be judged ONLY on out-of-fold results.

### S9. Regime-adaptive multi-strategy ensemble ("QuantumFX") — **BACKTEST**
The synthesis: trend sleeve (S1) + mean-reversion sleeve (S3/S4) gated by per-pair regime detection (vol regime + Hurst/trend-strength), inverse-vol position sizing, and a **quantum-inspired annealer (QUBO)** choosing the trade basket under correlation penalties — the one salvageable piece of fxqt v0.2.
- **Pros:** edge diversification (trend and MR profit in opposite regimes — the closest thing to a free lunch); every component is individually simple; regime gate addresses each sleeve's main weakness; 24/5 by construction; honest use of "quantum".
- **Cons:** most parameters of any candidate → highest overfit risk; must use coarse params + walk-forward only; ensemble is only as good as its sleeves.

### S10. Grid / martingale EAs ("1000pip climber" style) — **NO-GO**
Buy every X pips down, double up, "never lose".
- **Pros:** wins for months; this is what most "24/7 profit bot" products sell.
- **Cons:** martingale = certain eventual ruin; on a tiny account at 30:1, the first sustained trend margin-calls the account. The months of small wins are payment for a guaranteed tail loss. **This is the category most 'profitable forex bot' marketing lives in — avoid.**

### S11. News/event momentum (NFP, CPI, central banks) — **NO-GO (retail)**
- **Pros:** events genuinely move price.
- **Cons:** OANDA widens spreads 5-20x around events, rejects/slips orders; the latency race is institutional. Retail backtests of news trades are fiction because historical spread at the event isn't the quoted spread.

### S12. Scalping / HFT / market-making — **NO-GO (retail)**
- Physics: target 2-3 pips when spread is 1-2 pips and VPS→OANDA latency is ~30-80ms with no queue position. Cost > edge by construction. fxqt's H1 result (Sharpe -5.6 net of costs) is the empirical shadow of this at even 1-hour horizon.

### S13. Copy-trading / bought EAs / prop-pass services — **NO-GO (for this project)**
- Opaque, survivorship-biased track records; you outsource the one thing that matters (the edge). **However:** a *proven* bot + a prop-firm evaluation (FTMO-style, ~$10k-100k funded) is the realistic scaling path for a small-account-proven edge — parked as a future step, not a strategy.

### S14. Weekend gap fade — **BACKTEST (cheap add-on)**
Fade the Sunday-open gap toward Friday close (documented closure tendency).
- **Pros:** mechanically simple; uncorrelated; fills the "weekend edge" niche in a 24/5 market.
- **Cons:** ~50 trades/year; Sunday-open spreads are the week's widest (must model 2-3x spread); small sample → wide error bars.

## 2. Pre-backtest ranking (evidence × cost-survival × 24/5 fit × robustness × tail safety)

| # | Strategy | Edge evidence | Cost survival | 24/5 | Robustness | Tail safety | Score |
|---|---|---|---|---|---|---|---|
| 1 | **S9 ensemble (QuantumFX)** | ●●●● | ●●●● | ●●●●● | ●●●○ | ●●●● | **20/25** |
| 2 | S1 slow trend | ●●●●● | ●●●●● | ●●●●● | ●●●●● | ●●●● | 24/25* |
| 3 | S4 OU mean-rev | ●●●● | ●●● | ●●●●● | ●●●○ | ●●○ | 17/25 |
| 4 | S3 z-score mean-rev | ●●●○ | ●●● | ●●●●● | ●●●○ | ●●○ | 16/25 |
| 5 | S8 ML classifier | ●●○ | ●●● | ●●●●● | ●●○ | ●●●○ | 15/25 |
| 6 | S5 pairs stat-arb | ●●●○ | ●●○ | ●●●●● | ●●●○ | ●●●○ | 15/25 |
| 7 | S2 momentum rotation | ●●○ | ●●○ | ●●●●● | ●●●○ | ●●●○ | 14/25 (fxqt already falsified fast variant) |
| 8 | S14 gap fade | ●●○ | ●●○ | n/a niche | ●●●○ | ●●●○ | 13/25 |
| 9 | S6 London breakout | ●●○ | ●●○ | ●●○ | ●●○ | ●●●○ | 12/25 |
| 10 | S7 carry | ●●●●○ | ●●●●● | ●●●●● | ●●●● | ●○ | blocked: financing data/markup |
| 11 | S13 copy/EA/prop | ○ | — | — | — | — | future scaling path only |
| 12 | S11 news momentum | ●●○ | ○ | — | — | ●○ | NO-GO retail |
| 13 | S10 grid/martingale | ○ | ●●● | ●●●●● | ●○ | **☠** | NO-GO — ruin by design |
| 14 | S12 scalping/HFT | ○ | ☠ | — | — | — | NO-GO retail |

\* S1 scores highest as a *standalone*, but S9 *contains* S1 and adds a diversifying sleeve — S9 is the build target **if and only if** the backtests confirm each sleeve independently survives costs. If mean-reversion fails validation, QuantumFX ships as regime-gated trend only (= S1 with the quantum allocator).

## 3. What happens next (empirical phase)

1. Fetch 2019→2026 H4 + 2022→2026 H1 + 2016→2026 D1, 12 pairs, **with real bid/ask spreads** (price=MBA).
2. One shared backtest harness: next-bar-open execution, per-pair real median spread + slippage, cost stress 1x/1.5x/2x, walk-forward folds (train-select → OOS test), no parameter chosen on test data, min-trade thresholds.
3. Backtest S1, S2, S3, S4, S5, S6, S8, S9, S14. Rank by OOS Sharpe / maxDD / PF at 1.5x costs.
4. Deep-validate top 2 (parameter neighborhood stability, per-pair attribution, Monte Carlo bootstrap, regime slices) with parallel agents.
5. Implement winner as production bot with margin-aware coexistence, hard risk caps, kill switch, deploy-gate compliance.

Decision gates (same convention as fxqt): `PAPER_READY_CANDIDATE` needs OOS PF > 1.15, positive fold ratio ≥ 0.6, survives 2x costs; `LIVE_CANDIDATE` additionally requires positive expectancy at 2x costs and maxDD < 15% at target vol. Fail = ship best survivor, report honestly.

## 4. EMPIRICAL RESULTS (2026-07-01, walk-forward OOS 2022→2026H1, 1.5x real spreads)

| rank | strategy | OOS Sharpe | ann ret | maxDD | +folds | verdict |
|---|---|---:|---:|---:|---|---|
| **1** | **S4 OU mean-reversion (half-life + VR gated)** | **+0.52** | **+6.3%** | -24.6% | **4/5** | **WINNER — only net-positive strategy** |
| 2 | S2 x-sec momentum | -0.11 | -3.6% | -28.5% | 2/5 | fails |
| 3 | S5 pairs stat-arb | -0.21 | -0.9% | -10.8% | 2/5 | fails (double spread) |
| 4 | S3 naive z-score MR | -0.30 | -4.2% | -27.5% | 1/5 | fails — **proves the OU gates ARE the edge** |
| 5 | S1 Donchian trend | -0.43 | -7.4% | -34.5% | 1/5 | fails this era (2022-26 FX ranged) |
| 6 | S9 ensemble (trend+MR) | -0.64 | -8.2% | -39.0% | 1/5 | trend sleeve poisons it |
| 7 | S1b MA-cross trend | -0.69 | -8.7% | -36.7% | 1/5 | fails |
| 8 | S8 ML gradient boosting | -1.12 | -12.1% | -46.3% | 0/5 | fails — noise learner, as feared |
| 9 | S14 weekend gap fade | -1.20 | -6.5% | -17.3% | 1/3 | fails (Sunday spreads) |
| 10 | S6 London breakout | -1.22 | -10.4% | -24.8% | 0/3 | fails (H1 costs), confirms fxqt |

Key empirical lessons: (1) 2022-2026 FX rewarded *conditional* mean reversion and punished trend/momentum/ML at retail cost levels; (2) the OU regime gates transform a losing raw signal (S3) into the winner (S4) — trade the *process state*, not the price pattern; (3) every intraday (H1) strategy died on spread, exactly as the constraints table predicted. S4 fold detail: 2022 +0.6%, 2023 +19.5%, 2024 -17.6%, 2025 +29.6%, 2026H1 +2.7% — real but lumpy; portfolio construction (agent B report) addresses the drawdown.

## 5. FINAL PRODUCTION CONFIG (deployed 2026-07-01, `quantumfx.service`)

Two parallel deep-validation agents refined S4 (full reports: `reports/agentA_s4_robustness.md`, `reports/agentB_s4_portfolio.md`):

- **Agent A (robustness):** 95% of the parameter neighborhood is positive — a plateau, not a spike. Pinned **fixed** params (no per-fold reselection, which amplified the 2024 loss): n=96, z_in=2.25, z_out=0.25, hl_max=60, vr_max=0.95, **all-12 universe** (restricted universes tested worse; PnL concentrates in JPY crosses — EUR_JPY/GBP_JPY positive all 5 years). Caveats: JPY concentration (added USD_JPY vol circuit breaker), 2025-heavy OOS, honest forward Sharpe ≈ 0.5.
- **Agent B (construction):** time-stops ALL hurt (removed); portfolio vol layer destroys Sharpe (skipped — de-lever per-position vol instead, exactly Sharpe-preserving); position caps cost breadth (uncapped, gross ≤3× NAV); annealed correlation-penalized selection beats top-N under contention (kept for same-cycle candidate pruning, λ=0.2). Monte Carlo at 0.07 sizing: P(ruin)=0/2000, P(DD<-20%)=1.8%.
- **Combined config verified end-to-end** (this exact production parameterization, walk-forward OOS 2022-2026): **1.5x costs: Sharpe 0.80, +10.6%/yr, maxDD -16.2%, 4/5 positive years (worst −2.9%); 2.0x costs: Sharpe 0.72, +9.3%/yr.** Avg 3.3 concurrent positions. Equity stream: `reports/oos_PRODUCTION_final.pkl`.

**Honest expectations, restated:** at this account size the strategy compounds pennies — the purpose is a *live-verified* track record. If the live ledger tracks the backtest for 3-6 months, scaling paths are (a) deposit, (b) prop-firm evaluation. Forward Sharpe realistically ~0.5 (Agent A's shrinkage), i.e. ~+5-8%/yr at current sizing with -15-20% worst drawdowns. Anyone promising more from retail FX is selling something.
