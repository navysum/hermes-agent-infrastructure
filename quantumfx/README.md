# QuantumFX — walk-forward validated FX trading bot

A quantitative FX trading system built end-to-end in one research cycle: a
**10-strategy backtest tournament** on 7½ years of OANDA candle data with real
per-bar bid/ask spreads, **multi-agent robustness validation**, and a
production bot deployed as a 24/5 systemd service on the same VPS that runs
the Hermes agent infrastructure.

> Like the rest of this repository, this is a **sanitized extract** of a live
> deployment: no credentials, account identifiers or runtime state. Paths are
> genericized. The research reports contain real backtest numbers.

## The process (the interesting part)

1. **Constraints first** — retail spread costs, 30:1 UK leverage, a tiny live
   test account, and honest expectations are written down *before* any
   backtest ([research/STRATEGY_RESEARCH.md](research/STRATEGY_RESEARCH.md)).
2. **14 candidate strategies researched, 10 implemented and backtested** in a
   shared vectorized harness ([research/harness.py](research/harness.py),
   [research/strategies_lib.py](research/strategies_lib.py)): trend following,
   cross-sectional momentum, z-score & Ornstein-Uhlenbeck mean reversion,
   cointegration stat-arb, London-open breakout, gradient-boosting ML, a
   regime-switching ensemble, weekend gap fade.
3. **Walk-forward only** — expanding-window yearly folds, parameters selected
   on train folds, judged on out-of-sample; costs charged from **real per-bar
   half-spreads** (candles fetched with `price=MBA`) stress-tested to 2-3x.
4. **Result: 9 of 10 strategies lose money net of costs.** The survivor is
   OU-gated mean reversion — fade z-score extremes *only* while the pair
   statistically behaves as a mean-reverting process (rolling AR(1) half-life
   + variance-ratio gates). The same signal without the gates loses: the
   regime filter *is* the edge ([research/reports/leaderboard.md](research/reports/leaderboard.md)).
5. **Two validation agents ran in parallel** before deployment: a parameter/
   universe/cost robustness study ([reports/agentA_s4_robustness.md](research/reports/agentA_s4_robustness.md))
   and a portfolio-construction + Monte-Carlo study
   ([reports/agentB_s4_portfolio.md](research/reports/agentB_s4_portfolio.md)).
   They vetoed my initial guesses: the restricted universe I picked tested
   negative, time-stops hurt, and portfolio vol-targeting destroyed Sharpe —
   all removed. Final verified config: **OOS Sharpe 0.80, +10.6%/yr, max
   drawdown -16.2%** at 1.5x costs (holds at 2x).
6. **Post-deployment evolution, still gated by evidence** — a frequency-frontier
   study ([reports/freq_frontier.md](research/reports/freq_frontier.md)) set the
   entry threshold to the most-active config that still clears a pre-stated
   quality bar, and a TA-gate study ([reports/ta_gates.md](research/reports/ta_gates.md),
   robustness in [reports/d1veto_robustness.md](research/reports/d1veto_robustness.md))
   added a **daily-trend veto** — never fade a pair >2% from its 200-day SMA —
   lifting OOS Sharpe **0.80 → 0.94**. Every change beat the incumbent
   out-of-sample before shipping; a scalping/"more trades" variant was tested
   the same way and **rejected**.

## Production engineering

- **Fail-safe by construction**: every order carries a server-side stop loss,
  so nothing depends on the VPS staying alive; `KILL` file freezes entries
  instantly; 4% daily-loss halt; JPY vol circuit breaker (2024 carry-unwind
  defence).
- **Coexists with another live bot on one account**: orders tagged via OANDA
  client extensions; never stacks onto pairs already held by the other bot or
  a manual trade.
- **Margin-utilization sizing with a legacy mode**: entries are sized to a
  fixed fraction (≤45%) of the margin *available at order time* — successive
  positions consume geometrically less, so the account can never be sized into
  a closeout — with the original vol-targeted/backtest-matched sizing one env
  var away (`QFX_SIZING=vol`).
- **AI-reviewed, not AI-driven**: every trading day is reconstructed from
  broker transactions and graded on *process* separately from *outcome* by the
  AI model the Hermes agent currently runs (see
  [docs/SELF_HEALING.md](../docs/SELF_HEALING.md)); parameter suggestions land
  in a queue that only a weekend walk-forward research gate can promote.
  Execution stays 100% deterministic.
- **Quantum-inspired allocation**: same-cycle entry candidates are pruned by a
  simulated-annealing selector maximizing signal strength minus a pairwise
  correlation penalty — validated against naive top-N selection before
  adoption.
- **Operable from Telegram**: instant quick-commands (`/qfx`, `/qfxtrades`,
  `/compare`, `/qfxkill`, `/qfxresume`) through the Hermes gateway.
- Deploy gates: pytest suite ([tests/](tests/)), manifest checks and a global
  risk governor must pass before the service ships.

## Honest limitations

Documented in the research report, not hidden: single macro regime in the
OOS window, JPY-cross concentration, realistic forward Sharpe ≈ 0.5 after
selection-bias shrinkage, and pennies-scale P&L at test-account size. The
deliverable is a *live-verified track record*, not a get-rich claim.

## Layout

```
quantumfx/
├── quantumfx/            # live bot package (strategy, risk, execution, state)
├── research/             # data fetcher, harness, 10 strategies, tournament runner
│   └── reports/          # leaderboard, agent validation, frequency-frontier,
│                         #   TA-gate + D1-veto robustness reports
├── scripts/              # operational tooling (bot comparison)
├── systemd/              # service unit
└── tests/                # deploy-gate test suite
```
