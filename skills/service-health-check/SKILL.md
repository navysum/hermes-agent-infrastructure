---
name: service-health-check
title: Service Health Check
description: A reusable agent skill for inspecting the health of a systemd-based deployment — service state, port bindings, recent errors, and heartbeat freshness — and reporting a concise, actionable status. Read-only and safe to run unattended.
version: 1.0.0
tags:
  - operations
  - systemd
  - monitoring
  - health-check
  - devops
---

# Service Health Check

A generic, read-only operations skill. Use it when the agent is asked to "check
the system", "are the services up?", "why is X down?", or before/after a deploy.
It never restarts, mutates, or stops anything — it only observes and reports.

> This is an illustrative example of the `SKILL.md` capability-pack format used
> in this project. Replace the example service/port lists with your own.

## When to use

- A user asks for system or service status.
- A scheduled job needs a health snapshot to alert on.
- You want a pre/post-deploy sanity check.

## Inputs

| Input | Default | Notes |
|---|---|---|
| `services` | from config | systemd unit names to check |
| `ports` | from config | TCP ports expected to be listening |
| `heartbeat_files` | optional | files whose mtime should be recent |
| `max_age_minutes` | `15` | a heartbeat older than this is "stale" |

## Procedure

1. **Service state** — for each unit, read `systemctl is-active <unit>` and
   `is-enabled`. Flag anything not `active` (or not `enabled` if it should be).
2. **Port bindings** — confirm each expected port is listening locally
   (e.g. via `ss -ltn`). Flag missing or unexpectedly-public bindings.
3. **Heartbeat freshness** — for each heartbeat file, compare mtime to now.
   A unit reported `active` but with a stale heartbeat is "hung", not healthy —
   surface that distinction explicitly.
4. **Recent errors** — scan the last N lines of each unit's journal for
   `error`/`traceback`/`fatal`. Summarize counts, don't dump raw logs.
5. **Report** — produce a compact status block. Silence-on-success is preferred
   for scheduled use: emit output only when something needs attention.

## Output format

```
✅ all healthy            # or, when something is wrong:
🚨 web.service: inactive (last active 12m ago)
⚠️  worker.service: active but heartbeat stale (22m > 15m) — likely hung
⚠️  :8080 not listening (expected for api.service)
```

## Safety rules

- **Read-only.** Never call `restart`, `stop`, `mask`, or edit config. Remediation
  is a human/operator decision; this skill only diagnoses.
- **No secrets in output.** Redact tokens/keys if any appear in logs.
- **Bounded work.** Cap journal reads and per-check timeouts so a hung unit can't
  hang the check itself.

## Example invocation

```
> check the system
→ loads service-health-check, runs the 5 steps against the configured units,
  returns the status block above (or "✅ all healthy").
```

## Notes for authors

Skills are self-contained Markdown with YAML frontmatter (`name`, `description`,
`tags`). The agent discovers them, matches the `description` against the user's
intent, and loads the body on demand. Keep each skill single-purpose, state its
safety boundaries, and prefer deterministic, read-only steps where possible.
