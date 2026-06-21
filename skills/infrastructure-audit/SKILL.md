---
name: infrastructure-audit
title: Infrastructure Audit Framework
description: Systematic inspection of services, dashboards, and data pipelines. Covers service health, data sources, accuracy, reliability, and gap analysis. Produces detailed audit reports with severity ratings and remediation steps.
tags:
  - audit
  - infrastructure
  - monitoring
  - devops
  - reliability
---

# Infrastructure Audit Framework

## When to Use This
- **Service health inspection**: systemd units, port bindings, process stability
- **Data pipeline audits**: verify data sources, accuracy, lag, error handling
- **Dashboard/monitoring reliability**: coverage, metrics, alerting, edge cases
- **Trading bot infrastructure**: readiness checks, safety gates, account integration
- **Any multi-component system**: need to understand each part and how they interact

## The Seven-Section Audit Pattern

Most infrastructure audits benefit from this structure. Adapt the depth based on criticality:

### 1. Basic Health Check
**What to inspect:**
- Service status: `systemctl status <name>`
- Process info: PID, memory, CPU usage via `ps aux`
- Port binding: `ss -tlnp` or `netstat -tlnp` (shows which port and PID)
- Uptime: when did it start, any recent restarts
- **Any obvious bugs**: test GET/HEAD/POST, look for error responses, check if common methods work
- Network accessibility: localhost only vs. external vs. Tailscale

**Output:** Single-line summary of each metric. Flag any obvious bugs with reproduction command and one-line fix idea.

### 2. Data Sources
**What to document:**
- For each data input (SQLite, API, logs, systemd, files):
  - Type (database, HTTP, JSONL, logs, etc.)
  - Location (path or endpoint)
  - Freshness (when was last update)
  - Query mechanism (direct queries, API calls, log parsing)
- Error handling: what happens on missing file, locked database, API timeout
- Data consistency: are sources consistent with each other

**Output:** Table showing source type, location, status, freshness. Note any silent failures (returns empty vs. crashes).

### 3. Coverage
**What to check:**
- Which entities/bots/components are tracked
- Which are missing entirely
- For each tracked entity, what metrics are shown
- For each metric, note if it's:
  - ✅ Shown and correct
  - ⚠️ Shown but incomplete or unclear
  - ❌ Missing entirely

**Output:** Table per entity, columns = [Entity | Tracked? | Metrics Shown | Metrics Missing]. Highlight gaps.

### 4. Accuracy
**What to verify:**
- **P/L reconciliation**: does dashboard total match ledger sum
- **Counts**: trade count, open position count, win/loss split — do they add up
- **Currency handling**: mixed-currency display, conversion logic, currency symbols
- **Real-time lag**: measure time from data generation to display
- **Staleness**: are any ledgers >6 hours old without warning

**Output:** For each major metric, show dashboard value vs. ledger value and note if they match. Flag staleness.

### 5. Reliability
**What to test:**
- **Offline component**: disable one service, verify dashboard handles it gracefully
- **SQLite locks**: test dashboard read while bot has exclusive lock
- **Missing database**: what happens if a ledger file is deleted
- **Service restart**: bring down a service, does dashboard show stale or refresh
- **Concurrent reads/writes**: any race conditions or partial data visible
- **Authentication**: who can access, is it protected
- **Refresh mechanism**: client vs. server caching, is refresh interval tunable
- **Memory/CPU**: run for an hour, check for leaks

**Output:** Table of edge cases, expected behaviour, actual behaviour, risk level.

### 6. Missing Metrics
**What to list:**
- Group by criticality: Critical (affects trust), Important (reduces utility), Nice-to-have
- For each gap, note why it matters
- Do not mention things that are intentionally simple (this is not a feature list)

**Output:** Prioritized list of gaps with impact.

### 7. Verdict
**What to rate:**
- **Accuracy**: 0-10, do the numbers match truth
- **Coverage**: 0-10, are all important entities/metrics tracked
- **Reliability**: 0-10, does it handle failures gracefully, memory stable, uptime good
- **Alerting**: 0-10, does it notify on problems (0 if no alerts at all)
- **Overall**: synthesis of above

For each dimension, note:
- What the current rating reflects
- What would push it higher
- What the minimum fix is to unblock production use

## Pitfalls

1. **Confusing "missing" with "intentionally simple"**
   - A dashboard showing 5 metrics is not worse than one showing 50 if the 5 are correct and the 45 others are noise.
   - Compare to actual use cases: if the operator needs win rate for trading decisions, it's critical; if it's vanity, it's not.

2. **Assuming fresh == accurate**
   - A ledger updated 1 second ago can still have P/L mismatches, calculation errors, or currency bugs.
   - Always reconcile numbers against source truth.

3. **Testing only happy path**
   - SQLite errors are often silent (try/except returns empty).
   - Test what happens when data is locked, missing, or corrupted.

4. **Ignoring real-time lag in distributed systems**
   - A dashboard that reads 5 SQLite files might have 5 different timestamps because each bot wrote at a different time.
   - Flag if this matters to the use case (for trading, it might).

5. **Conflating service uptime with data recency**
   - A service can run for 100 days but its last ledger entry can be 3 days old.
   - Don't assume "running" means "current".

## Procedure

**Step 1: Scoping**
- Identify the main service/component to audit
- List all its data sources and dependencies
- Decide which sections to inspect based on criticality (full audit for production services, light audit for dashboards)

**Step 2: Data collection** (read-only, no changes)
- Run section 1 commands (systemctl, ps, ss, netstat, curl, journalctl)
- Run section 2 queries (find data files, check timestamps, test queries)
- Run section 3 inventory (list entities, map to code)
- Run section 4 spot checks (pick 2-3 metrics, reconcile against ledgers)
- Run section 5 edge cases (offline component, SQLite lock test, etc.)

**Step 3: Analysis**
- Compile findings into 7-section structure
- Rate each dimension 0-10 with reasoning
- Call out gaps and risks

**Step 4: Output**
- Generate markdown report with exact commands and results
- Provide minimum fix recommendations in priority order
- Deliver to user with one-line summary

## Tools
- `systemctl status/list-timers/is-active` — service state
- `ps aux | grep` — process info
- `ss -tlnp` or `netstat -tlnp` — port bindings
- `curl -i/-I` — HTTP health, HEAD 501 bugs, response headers
- `sqlite3 <db> "SELECT ..."` — ledger queries, count checks
- `journalctl -u <unit> --since "1 hour ago"` — service logs
- `find /path -name "*.sqlite3"` — locate data files
- `tail/head -n <count>` — recent data samples
- Memory/CPU: `ps aux` column 3 (CPU%), column 4 (memory%)

## Data-pipeline & model readiness

When a system includes a data pipeline or a model, separate **infrastructure
health** from **data/model readiness** explicitly:

- Validate the data source against an authoritative reference before trusting it
  (ordering, timestamps, timezone parsing — date-only ingestion can silently
  flatten timestamps and corrupt ordering/reconciliation).
- After parser/schema changes, check for duplicate logical rows introduced by
  changed source-ID seeds.
- Treat freshness as a hard gate: required rows present, recent, reconciled to
  their keys, and provider quota/metadata captured.
- Rate models honestly — if there is no feature set, calibration, or backtest,
  call it a research baseline rather than a production model.

## Output

Produce a sectioned report with a severity rating per finding (info / warning /
critical) and a concrete remediation step for each. Lead with a one-line verdict
(healthy / degraded / failing) so the result is scannable at a glance.
