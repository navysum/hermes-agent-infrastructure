# Self-healing & self-evolution

Everything about how this system keeps itself alive, diagnoses its own
problems, and improves its own parameters lives in this document. There are
three layers, deliberately ordered from dumb-and-fast to smart-and-slow, and
each layer can only do strictly bounded things.

```
 fast, dumb, frequent                                   slow, smart, rare
 ┌──────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
 │ L0 watchdog      │   │ L1 AI daily review   │   │ L2 evolution gate   │
 │ every 30 min     │──▶│ nightly, 21:06 UTC   │──▶│ weekends only       │
 │ restart dead     │   │ current-model        │   │ walk-forward        │
 │ services, no AI  │   │ diagnosis + heal     │   │ backtest referee    │
 └──────────────────┘   └──────────────────────┘   └─────────────────────┘
```

## L0 — deterministic watchdog (`ops/self_heal.sh`, every 30 min)

No AI, no credits, no judgement calls: restart dead services, re-enable
dropped timers, detect hung processes by log staleness, fail over to a backup
agent if the primary gateway dies, and re-park the backup when health returns.
Telegrams the operator only when it fixed something or failed to. This layer
is the floor — everything above it assumes it exists.

## L1 — AI daily review & smart heal (`ops/ai_daily_review.py`, nightly)

The interesting layer. Once per trading day it:

1. **Reconstructs the day from the broker, not from bot logs** — every OANDA
   transaction is pulled and rebuilt into trades, attributed to a bot via
   order client-extension tags. Untagged orders are an alarm by definition.
2. **Grades process separately from outcome.** A losing trade with a stop,
   sane leverage and in-budget risk is *fine*; a winning trade with no stop is
   *flagged*. Budgets live in code, not in the model's imagination.
3. **Runs a deterministic heal floor** (restart dead services, restart on
   stale heartbeat) — identical to L0 semantics, so the system heals even if
   every AI provider is down.
4. **Hands the full evidence bundle to the current model for diagnosis**:
   service states, heartbeat age, risk-governor output, any standing risk
   block and its original cause, log tails, the day's anomalies. The model
   replies with a diagnosis and proposed actions.
5. **Validates every proposed action against live facts before executing.**
   The action vocabulary is a hard whitelist (`restart_service`,
   `clear_stale_risk_block`, `none`). A restart of a healthy service is
   rejected; clearing a risk block is only allowed if a *fresh* risk-governor
   run no longer blocks. The model proposes; the code disposes.
6. **Queues evolution candidates instead of applying them.** The model may
   suggest bounded parameter changes (each parameter has a hard whitelist
   range in code). Suggestions go to a queue file — never to live config.

### Model-agnostic by construction

The review does **not** hardcode a model. It routes through the Hermes agent's
one-shot mode, which answers with whatever model the agent is *currently*
configured to run (read live from the agent's config — a Codex model today,
anything else tomorrow). Swap the agent's model and the nightly reviewer,
the heal diagnosis and the lesson-writing all upgrade with it, zero code
changes. If the agent is unreachable it falls back to a secondary CLI, and if
that fails the review still completes — numbers, grades and deterministic
heals don't need a model.

Design rule: **static thresholds are for safety, models are for judgement.**
Thresholds (risk budgets, leverage caps, whitelist bounds) are hardcoded and
boring on purpose — they are the guardrails. The model interprets *why* the
day looked the way it did and what deserves attention, which is exactly the
part fixed numbers can't do.

## L2 — evolution gate (weekends only)

Parameter candidates queued by L1 are judged by a walk-forward backtest
referee on the weekend, while markets are closed. A candidate ships only if
it beats the incumbent out-of-sample on Sharpe (at stressed costs), drawdown,
holdout performance *and* keeps ≥85% of the incumbent's trade frequency —
then the service restarts with the new config and the decision is journaled.
No human forgetting to review, no model editing live parameters: the
promotion path is quantitative or nothing.

## Why three layers

- A dead service at 3am needs a restart in minutes, not an essay — L0.
- "The block file's cause was fixed yesterday but nothing cleared it" needs
  *judgement with evidence* — L1 (this exact failure mode is why L1 exists:
  a resolved incident once left a stale block silently preventing new trades
  for a day).
- "Should z_in be 2.1?" needs a backtest, not an opinion — L2.
