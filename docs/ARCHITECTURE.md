# Architecture

This document describes how the Hermes Agent infrastructure is put together.
It is a sanitized view of a live, single-host deployment on an Ubuntu VPS.

## High-level

The system is a long-running AI agent plus the operational scaffolding that
makes it dependable: model routing with fallback, a messaging control plane,
a scheduler, third-party integrations, and a self-healing watchdog.

```
                       ┌──────────────────────────────────────────┐
   Telegram  ◀───────▶ │  hermes-gateway (systemd, Restart=always) │
                       │   • inbound message receive               │
   Private dashboard ─▶│   • native cron scheduler                 │
   (Tailscale only)    │   • dispatch to agent loop                │
                       └───────────────┬──────────────────────────┘
                                       │
                              ┌────────▼─────────┐
                              │   Agent loop     │
                              │  personas (SOUL) │
                              │  skills (SKILL)  │
                              │  tools / MCP     │
                              └────────┬─────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │      Model router        │
                          │  cloud-first + fallback  │
                          └───┬──────────────────┬───┘
                              │                  │
                  ┌───────────▼───┐      ┌───────▼─────────┐
                  │  Cloud LLMs   │      │  Local LLM      │
                  │  OpenAI/Codex │      │  Ollama qwen3   │
                  │  Anthropic    │      │  (cheap/offline)│
                  │  OpenRouter   │      └─────────────────┘
                  │  Gemini       │
                  └───────────────┘
```

## Components

### 1. Model routing (`config/config.example.yaml`)
- A declarative `providers` list and `fallback_providers` chain.
- Default model is **cloud-hosted** (to avoid OOM on a small VPS); a **local
  Ollama model** is the cheap/offline floor.
- Provider credentials are referenced from the environment, never inlined.

### 2. Agent runtime
- The `hermes` agent (installed separately) runs as two systemd units:
  - `hermes-gateway` — message receive + native cron scheduler.
  - `hermes-dashboard` — local web UI, bound to localhost.
- Behaviour is shaped by **personas** (`SOUL.md` / profiles) and **skills**.

### 3. Personas (`scripts/persona_router.py`)
- A lightweight keyword/intent classifier selects a response persona
  (e.g. an analytical "find the edge" persona vs. a protective default).
- Keeps tone/role consistent without a separate model call.

### 4. Skills (`skills/`)
Self-contained capability packs the agent discovers and loads on demand. Each is
a single Markdown file with YAML frontmatter (`name`, `description`, `tags`); the
agent matches the description against user intent and loads the body on demand:
- **service-health-check** — a generic, read-only skill that inspects systemd
  service state, port bindings, heartbeat freshness and recent errors, then
  reports a concise status. Safe to run unattended.
- **infrastructure-audit** — a framework for auditing service health and data
  pipelines, separating infrastructure health from data/model readiness and
  producing severity-rated reports with remediation steps.

### 5. Scheduling (`scripts/job_*.sh`, `scripts/jw_lib.sh`)
Two classes of scheduled work, both driven by the agent's cron scheduler:
- **Deterministic** — run a script, alert only on non-empty output
  (OANDA signals, Whoop sync, strategy watchdogs, predictions odds refresh).
- **Agentic** — the agent itself generates the output (daily morning brief,
  nightly reflection) and delivers it over Telegram.
- `jw_lib.sh` provides **de-duplication** and per-job state so re-runs or
  overlapping ticks never double-post; outputs are archived per job.

### 6. Telegram control plane (`scripts/qc_*.sh`, `scripts/set_telegram_menu.sh`)
- **Quick commands** (`type: exec`) answer status queries in sub-second time by
  bypassing the LLM entirely (`/money`, `/trades`, `/sys`, `/bots`, `/wc`, …).
- **Conversational** mode handles open-ended requests and long operations.
- The command menu is re-asserted via a scheduled `setMyCommands` sync so it
  survives gateway restarts.

### 7. Integrations
- **OANDA v20** — read-only NAV / P&L / open positions.
- **Whoop** — OAuth2 recovery/sleep data, synced into Notion; refresh-token
  flow serialized to avoid burning single-use tokens.
- **Notion** — tasks, projects, and a health log (queried by database ID).
- **iCloud CalDAV** — calendar read.
- **Composio** — MCP tool router for additional SaaS actions.

### 8. Operational resilience (`ops/`)
- **`self_heal.sh`** — a watchdog run on a short interval: unmasks/restarts the
  core services if down, and **fails over to a backup agent** if the primary
  gateway is unhealthy, re-parking it automatically once health returns.
- **`hermes-dashboard-tailnet-proxy.py`** — a localhost-bound reverse proxy that
  lets a private Tailscale network reach the dashboard while the dashboard
  itself keeps rejecting non-local `Host` headers. The dashboard is never bound
  to a public interface.

## Security model

See [the README](../README.md#security-considerations). In short: 12-factor
secrets, all runtime state git-ignored, read-only money/health integrations,
a command allowlist + approvals layer, secret redaction in logs, and a
private-network-only management surface.

## Why single-host

The deployment is intentionally a single well-instrumented VPS: it keeps the
blast radius small, makes the watchdog/failover story simple, and is the right
size for a personal/experimental agent. The same component boundaries
(router, agent, scheduler, integrations, watchdog) would map cleanly onto
separate services if horizontal scale were ever needed.
