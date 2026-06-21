---
name: operator-live-data-tools
description: "the operator's concrete CLI tools for his OWN live data — LIVE OANDA trades/P&L/positions, his Apple/iCloud calendar (CalDAV), and his second-brain note vault (RAG). Use whenever the operator asks about his trades, account balance/equity, open positions, profit/loss, what's on his Apple/iCloud calendar, or to search/recall/save his personal trading/health/idea notes. These were ported from the Claude trading-agent on 2026-06-16; they are the authoritative source, prefer them over cached dashboards or guessing."
version: 1.0.0
metadata:
  hermes:
    tags: [operator, oanda, trading, pnl, calendar, icloud, caldav, notes, second-brain, live-data]
    related_skills: [hermes-operator-operations]
---

# the operator's Live Data CLI Tools

Three command-line tools give you direct, authoritative access to the operator's own
live data. They print **JSON** (calendar/OANDA) or plain bullets (notes). Run
them via Bash. Each needs a specific venv — using the wrong python will fail on
imports.

> Ported from the Claude trading-agent (`/root/trading-agent/`) on 2026-06-16 as
> part of consolidating everything into Hermes. The scripts still live under
> `/root/trading-agent/` (kept as the failsafe); call them in place.

---

## 1. LIVE OANDA trades / P&L  →  `oanda_trades.py`

For ANY question about the operator's trades, positions, balance/equity, or profit &
loss, use this. It hits OANDA **directly** (authoritative, fresh). The forexbot's
local `metrics.sqlite3` lags or misses trades — never answer "no trades" from a
dashboard/DB without checking this first. For broader "loophole", edge, bot-readiness,
or opportunistic trading questions, use the read-only audit pattern in
`references/read-only-trading-edge-audit.md`: OANDA state → ForexBot logs/session filters →
Quantum readiness/current signals → concise go/no-go verdict. Do not place trades.

For World Cup prediction profitability/staking-safety work, use
`references/worldcup-profitability-gate.md`: keep raw model-vs-market edges separated
into blocked/quarantined/paper/staking buckets, require ledger profitability before
staking, and verify both CLI snapshot generation and the live dashboard service path.

```bash
/root/bots/forexbot/venv/bin/python /root/trading-agent/oanda_trades.py summary
/root/bots/forexbot/venv/bin/python /root/trading-agent/oanda_trades.py open
/root/bots/forexbot/venv/bin/python /root/trading-agent/oanda_trades.py closed 20
/root/bots/forexbot/venv/bin/python /root/trading-agent/oanda_trades.py today
```

- **Must** use `/root/bots/forexbot/venv/bin/python` — that venv has `oandapyV20`.
- Output is JSON, e.g. `summary` → `{equity_gbp, open_count, open_pairs,
  closed_recent_30, net_realized_recent_30_gbp, closed_today, realized_pl_today_gbp}`.
- The account is **LIVE** (real GBP). This tool is **read-only** — it never places,
  modifies, or closes trades. Never use a broker API to trade on the operator's behalf.

## 2. Apple / iCloud calendar  →  `icloud_calendar.py`  (CalDAV)

the operator's **Apple** calendars (Personal, University, CyberPath, Fitness, Heathrow,
Moments with Mates, Reminders) live in iCloud and are reached via CalDAV — NOT
Composio/Google. iCloud is the **default source of truth** for "what's on the operator's
calendar" unless he explicitly says Google.

```bash
/usr/local/lib/trading-venv/bin/python /root/trading-agent/icloud_calendar.py today
/usr/local/lib/trading-venv/bin/python /root/trading-agent/icloud_calendar.py week
/usr/local/lib/trading-venv/bin/python /root/trading-agent/icloud_calendar.py range 2026-06-20 2026-06-27
/usr/local/lib/trading-venv/bin/python /root/trading-agent/icloud_calendar.py search "judo"
/usr/local/lib/trading-venv/bin/python /root/trading-agent/icloud_calendar.py list_calendars
# writes (confirm with the operator first):
/usr/local/lib/trading-venv/bin/python /root/trading-agent/icloud_calendar.py create Personal "Title" 2026-06-20T14:00 2026-06-20T15:00 "optional notes"
/usr/local/lib/trading-venv/bin/python /root/trading-agent/icloud_calendar.py delete Personal <event-uid>
```

- **Must** use `/usr/local/lib/trading-venv/bin/python` — it has the `caldav` lib.
- Creds resolve from `/root/trading-secrets.env` (`ICLOUD_CALDAV_URL`,
  `ICLOUD_USERNAME`, `ICLOUD_APP_PASSWORD`). Never print them.
- Output is JSON. Confirm before `create`/`delete` (calendar writes are outward-facing).

## 3. Obsidian / second-brain notes

See `references/obsidian-vaults.md` for the verified vault map and write rules.

the operator has two agent-readable Obsidian-style stores:

- `/root/second-brain` — personal second-brain notes with an FTS5 search index.
- `<OBSIDIAN_VAULT_PATH>` — shared LLM/Obsidian wiki for trades, World Cup predictions, learning, bot logs, and Claude/Hermes handoff context.

The second-brain holds his dated trading, health, and idea notes. Search it before answering questions about his past trades, decisions, or notes; write a note after something notable happens.

```bash
/root/trading-agent/venv/bin/python /root/trading-agent/brain.py search "query"
/root/trading-agent/venv/bin/python /root/trading-agent/brain.py add "Title" "body text" "20-Trading"
/root/trading-agent/venv/bin/python /root/trading-agent/brain.py daily "one-line journal entry"
```

- **Must** use `/root/trading-agent/venv/bin/python`.
- Folders: `00-Inbox 10-Daily 20-Trading 30-Health 40-Ideas 50-Agent-Notes`.

---

## Composio (Notion / Gmail / Calendar / Drive / Sheets / GitHub / Slack)

Use your **native Composio** tool router for ALL of these — Notion included
(verified 2026-06-16: `NOTION_LIST_USERS` and Notion search execute fine on your
router). Do **NOT** use the trading-agent's `composio_tool.py`; you don't need it.

**Key usage rule — how the router exposes tools:** the router pre-lists only ONE
representative tool per app (e.g. `NOTION_LIST_USERS`, `GMAIL_LIST_LABELS`,
`GOOGLECALENDAR_LIST_CALENDARS`) plus meta-tools. For ANY other action you must
DISCOVER the specific tool first, then execute it:

1. `COMPOSIO_SEARCH_TOOLS` with `use_case` + `toolkits:["notion"]` → returns the
   exact slugs (e.g. `NOTION_SEARCH_NOTION_PAGE`, `NOTION_QUERY_DATABASE_WITH_FILTER`,
   `NOTION_FETCH_DATABASE`, `NOTION_GET_PAGE_MARKDOWN`).
2. `COMPOSIO_MULTI_EXECUTE_TOOL` (or the discovered tool directly) to run it.

If a direct call returns "Unknown tool", you skipped step 1 — search first, don't
fall back to a bridge or conclude Notion is disconnected.

**FAST PATH for Health Log + To-Do tasks + Projects (preferred — no discovery):**
run `bash /root/.hermes/scripts/brief_notion.sh`. It hits the Notion API directly
(LIfeOS Sync integration, `NOTION_API_KEY`) and returns, in ~3s and deterministically:
the latest Whoop Health Log entry (recovery/sleep/HRV/strain/zone), open To-Do List
tasks by deadline, and active Projects. Use this for the morning brief and for any
interactive "what are my tasks / how's my recovery" question — it is faster and more
stable than the Composio discovery dance. Hardcoded DB ids live in `brief_notion.py`
(Health Log `36375335…`, To-Do `35d75335…8046`, Projects `35d75335…8010`). Only fall
back to the `COMPOSIO_SEARCH_TOOLS` flow above for other Notion DBs/pages or writes.

**Whoop / health data** lives in Notion's "Health Log" (written by your Whoop→Notion
cron jobs). The app summary (127.0.0.1:9126) does NOT carry whoop — use the fast path
above. (Note: the operator's Google Calendar via Composio is a *different* calendar set from
his iCloud calendar in section 2.)

## References

- `references/obsidian-vaults.md` — verified vault map and write rules.
- `references/read-only-trading-edge-audit.md` — operator-mode audit for the operator's live trading and prediction stack: OANDA state, ForexBot pair/hour/session edge cuts, bot live-vs-dashboard classification, Quantum readiness/current signals, World Cup model health/betting-readiness checks, stale-proposal guard, and concise go/no-go reporting.
- `references/worldcup-profitability-gate.md` — implementation pattern for World Cup value gating: blocked/quarantined/paper/staking buckets, ledger-readiness guard, thresholds, and service/CLI verification checklist.

## Safety

- OANDA tool is read-only; never trade on the operator's behalf via any broker API.
- Confirm calendar `create`/`delete` before running.
- Never print secrets from `trading-secrets.env`.
- These scripts read creds from files (not env), so they run fine from cron/agent
  context. If one errors, report the actual error line — don't conclude "needs auth".
