---
name: hermes-operator-operations
description: "Operate the operator's Hermes environment as a class-level runbook: live VPS/dashboard/gateway safety, profile/persona SOUL.md management, OAuth/credential handling, and broad system checks. Load after the protected hermes-agent skill for the operator-specific conventions."
version: 1.0.0
author: Hermes Agent
metadata:
  hermes:
    tags: [hermes, operations, profiles, personas, systemd, oauth, dashboard, credentials, operator]
    related_skills: [hermes-agent]
---

# the operator's Hermes Operations

## Recent the operator-specific operations patterns

- For Telegram cutovers and post-reboot checks, migrate active job deliveries first, verify Telegram after reboot, then disable Slack before revoking/deleting the Slack workspace. See `references/telegram-cutover-post-reboot.md`.

Use this skill when operating or changing the operator's Hermes Agent environment rather than implementing generic Hermes features. It consolidates the recurring the operator-specific runbooks for:

1. Live server / VPS operations
2. Dashboard, WebUI, gateway, Slack, and systemd service checks
3. OAuth callback ports and refresh-token chain issues
4. Deployment credentials and safe secret handling
5. Profile/persona/SOUL.md setup for named Hermes roles
6. Broad “check everything” operational health reviews
7. Skill hub install operations from chat, including ambiguity resolution and verification
8. Health dashboard production hardening into a real Life OS health surface
9. Bot Control Room dashboard operations for the operator's trading bots, including read-only P/L aggregation and Tailscale access
10. World Cup Prediction Bot operations: fixture/date correctness, kickoff countdowns, dashboard health, prediction snapshots, odds-feed readiness gates, Odds-API.io setup, alias reconciliation, and scheduled live-odds refreshes
11. Targeted read-only trading-bot live-mode/arming audits, especially systemd timer + broker execution safety checks
12. VPS security/port audits: public exposure review, UFW/fail2ban/Tailscale checks, safe cleanup, and lockout-avoidant hardening
12. Composio router/profile migrations: make connected SaaS apps available across the operator's Hermes profiles, update cron/workflow guidance to prefer Composio, and verify live app smoke tests
13. Live Hermes upgrades and Lisa/Maggie post-upgrade sweeps: update Hermes safely, recover from gateway restarts, verify dashboard/service health, and distinguish blocked internet noise from confirmed breaches
14. Telegram-primary notification migrations: move cron/watchdog/bot alert delivery away from Slack or ambiguous `origin`, verify Telegram delivery, and avoid unnecessary live trading restarts
14. Telegram bot command menu operations: keep `/` menu entries aligned with real Hermes gateway commands and avoid dead shortcut buttons unless handlers are implemented
15. Fresh Hermes install handovers: before reinstalling or wiping anything, create a root-only restore map covering Hermes config/memories/skills/cron/profiles/scripts, trading bots, World Cup systems, Whoop/Notion, dashboards, systemd units, secret-file locations, and smoke tests. See `references/fresh-install-handover-and-restore.md`.
16. Trading bot noisy-error cleanup: for the operator's `arb-scanner.service`, repeated Odds API HTTP 401/403 lines are an auth/key fault, not per-sport failures. Patch scanner code to stop the current scan after the first auth error, record it in `arb_status.json`, surface it once on the Bot Control Room dashboard, and direct the operator to rotate/fix `ODDS_API_KEY` server-side in `/root/.hermes/.env` without pasting secrets into chat.
17. LiteLLM local fallback and router operations: when the operator asks to install/repair LiteLLM, set up Codex usage-limit fallback, or implement a three-tier model policy, isolate the proxy from Hermes/ForexBot, bind it to loopback, map local Ollama models through OpenAI-compatible model names, wire Hermes `fallback_providers` and `auxiliary` helper/router slots to the LiteLLM provider, and verify both proxy smoke tests and live services. See `references/litellm-local-fallback-proxy.md`.
18. Bot Control Room ForexBot metrics drift fixes: when the dashboard disagrees with live trading services, reconcile hardcoded dashboard paths/service names against systemd and the real ledgers before trusting cards. Patch dashboard-only drift without restarting live trading services, and report the ForexBot 100-trade counter from `/root/bots/forexbot/metrics.sqlite3` confirmed trades. See `references/bot-control-room-forexbot-metrics-drift.md`.
19. Sunday World Cup/trading readiness checks: distinguish overall research/dashboard health from live staking readiness, verify `health-gate`, profitability ledger status, odds freshness, service timers, and any partially implemented model features before giving a go/no-go. See `references/worldcup-weekly-readiness-check.md`. 

Always load the protected `hermes-agent` skill first for official Hermes commands/docs.

## Operating Principles

- the operator is moving operational Hermes notifications to Telegram. When changing delivery channels, migrate and verify active cron/watchdog/bot alert routes before disabling old adapters. For Slack retirement, disable Hermes Slack config/tokens and verify Telegram still works before revoking/deleting the Slack app/workspace. See `references/telegram-first-slack-retirement.md`.


1. **Keep secrets out of chat.** Never ask the operator to paste tokens, OAuth URLs with state, `.env` contents, API keys, or credentials into Slack/chat. Direct him to SSH into the server and enter secrets there.
2. **Prefer local-only admin surfaces.** Dashboards and config UIs should bind to `127.0.0.1` and be accessed through SSH tunnels unless the operator explicitly asks for public exposure and accepts the security trade-off.
3. **Separate OAuth callback ports from dashboards.** Do not run WebUIs on callback ports used by integrations.
4. **Verify live state before advising.** Check service status, listeners, process ownership, logs, and file state before claiming a port/service/profile is fixed.
5. **Archive before deleting.** When removing old/community UI installs or obsolete config, stop/disable services first, preserve rollback copies, then verify the live replacement.
6. **Patch, do not blindly overwrite.** For SOUL.md/profile work, preserve existing operational context unless the operator explicitly asks for a full replacement.

## When to use

Load this skill for requests like:

- “check Hermes / the server / the Slack runtime”
- “fix the dashboard / WebUI / gateway”
- “open the dashboard on my phone”
- “Whoop OAuth keeps needing re-auth”
- “deploy the Hermes dashboard / health dashboard”
- “turn the health dashboard into a Life OS command centre”
- “add real Whoop / Notion writeback / trend calculations to the health dashboard”
- “make me a website dashboard of all my bots”
- “show profit/loss for all my bots”
- “what’s the World Cup countdown / when does it start?”
- “is the World Cup prediction bot ready?”
- “fix the World Cup fixture dates / kickoff times / dashboard”
- “why is the World Cup bot production gate blocked?”
- “is the quantum forex bot live or paper?”
- “is this bot armed / ready to place real OANDA orders?”
- “when is the next bot run and what happened last time?”
- “check everything is running correctly”
- “I’ve rebooted, check now”
- “run a Lisa-level and Maggie-level system check”
- “audit the whole system / clean up anything / close ports that don't need to be open”
- “what ports are open on the VPS?”
- “harden SSH / firewall / Tailscale access”
- “get Composio working” / “use Composio instead of the APIs” / “make sure all profiles can use Composio”
- “update Hermes” / “upgrade Hermes” / “check Hermes after restart” / “gateway restarted, verify it worked”
- “move alerts to Telegram” / “stop sending watchdogs to Slack” / “make Telegram the main delivery channel” / “migrate cron notifications”
- “has the VPS been breached?” / “run Lisa and Maggie checks” / “audit after updating packages”
- “create/update Homer/Lisa/Marge/Bart/Maggie profiles”
- “drop each section into the corresponding agent’s SOUL.md”
- “make all profiles use this persona”
- “hermes skills install <skill-id>” from chat, especially when the install needs confirmation, trusted-source selection, or verification
- “create a handover for a fresh Hermes install” / “I want to reinstall Hermes but keep my bots/data/context” / “make a backup map before wiping Hermes”
- “install LiteLLM” / “set up fallback models” / “when Codex hits usage limits use local models” / “route Hermes fallback through local Ollama models”
- “Sunday readiness” / “get trading ready for the week” / “check the World Cup profitability gate” / “make sure the World Cup model changes are implemented”

Do **not** use this as the primary skill for generic Hermes Agent setup, plugin authoring, or in-repo Hermes development; use the protected `hermes-agent` and relevant software-development skills first, then load this only when the operator's live environment or profile conventions matter.

## the operator's current port conventions

- `8787` is reserved for Whoop OAuth callbacks/re-auth.
- `9119` is the official Hermes Dashboard port, bound to `127.0.0.1`.
- Access dashboard via SSH tunnel, not public bind:

```bash
ssh -L 9119:localhost:9119 root@<SERVER_IP>
```

Then open:

```text
http://127.0.0.1:9119
```

## Dashboard / WebUI runbook

1. Confirm what owns relevant ports:
   ```bash
   ss -ltnp '( sport = :8787 or sport = :9119 or sport = :9120 )'
   ```
2. Check the dashboard unit before assuming it exists:
   ```bash
   systemctl is-active hermes-dashboard.service 2>/dev/null || true
   systemctl is-enabled hermes-dashboard.service 2>/dev/null || true
   systemctl list-units --type=service --all 'hermes*dashboard*' --no-pager || true
   ```
3. Stop/disable obsolete community WebUI services before starting official dashboard.
4. If removing a community WebUI:
   ```bash
   systemctl stop <service>
   systemctl disable <service>
   rm /etc/systemd/system/<service>.service
   systemctl daemon-reload
   mkdir -p /root/.hermes/archived-webui
   mv <old-app-dir> /root/.hermes/archived-webui/<name>-$(date +%Y%m%d-%H%M%S)
   ```
5. Start official dashboard as a systemd service with local-only bind. Current proven ExecStart pattern:
   ```ini
   ExecStart=/root/.local/bin/hermes dashboard --host 127.0.0.1 --port 9119 --no-open --skip-build
   ```
   Use a PATH/HOME-aware systemd unit if the service was missing entirely; see `references/hermes-dashboard-systemd-recovery.md`.
6. Verify:
   - service is `active/running`
   - service is `enabled`
   - `127.0.0.1:9119` is listening
   - `curl` GET `http://127.0.0.1:9119/` returns HTTP 200
   - port `8787` remains free or owned only by the OAuth listener currently in use

Important: verify the dashboard with a GET request, not `curl -I`; the dashboard may return `405 Method Not Allowed` for HEAD while `GET /` is healthy.

### Temporary phone access via Tailscale

When the operator asks to open a local/dev dashboard from his phone, prefer Tailscale over public exposure. For the official Hermes Dashboard specifically, keep it bound to `127.0.0.1:9119`; do not rebind it to a Tailscale IP or use `--insecure` casually. If phone access is needed, use Tailscale Serve plus a loopback-only host-rewrite proxy.

Quick pattern:

1. Verify Tailscale and collect this server's tailnet IP:
   ```bash
   tailscale ip -4
   tailscale status --self
   ```
2. Verify the app is listening before giving the operator a URL:
   ```bash
   ss -ltnp | grep ':<port>' || true
   ```
3. If a dev app was started on `127.0.0.1`, restart/bind it to the Tailscale interface or `0.0.0.0` when appropriate.
4. For the official Hermes Dashboard, prefer a dedicated Tailscale HTTPS port that points to the host-rewrite proxy, not a subpath:
   ```bash
   systemctl enable --now hermes-dashboard.service
   systemctl enable --now hermes-dashboard-tailnet-proxy.service
   tailscale serve --yes --bg --https=9119 http://127.0.0.1:9120
   ```
   Then give the operator `https://<tailnet-name>:9119/`. Avoid `https://<tailnet-name>/hermes/` for the dashboard: Hermes rejects non-local Host headers, and the SPA uses root-relative assets like `/assets/...`.
5. Verify locally and through the proxy before reporting success:
   ```bash
   curl -sS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:9119/
   curl -sS -H 'Host: <tailnet-name>:9119' -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:9120/
   tailscale serve status
   ```
6. Then give the operator the phone URL and remind him to connect the iPhone/laptop Tailscale app.

Security note: binding to the Tailscale IP exposes the dev server only inside the tailnet, which is usually preferable to opening a public VPS port. Still treat Vite/dev dashboards as temporary and shut them down when done. For Hermes Dashboard, do not use `--insecure` or public-IP binding unless the operator explicitly accepts the admin/API-key exposure risk.

See `references/hermes-dashboard-tailnet-dedicated-port-host-rewrite.md` for the session-proven dedicated-port pattern and Windows SSH fallback notes.

## Whoop OAuth / daily re-auth pattern

Whoop re-auth has two separate failure classes:

- **Callback conflict:** wrong process owns `8787`, so manual OAuth cannot complete.
- **Refresh-token chain break:** Whoop refresh tokens are single-use; two scripts/jobs refreshing in parallel can burn the chain and force daily manual re-auth.

Do not conflate them. Fix port conflicts for the callback, then inspect the refresh path separately.

Preferred pattern:

1. Reserve `8787` for `/root/whoop_reauth.py` only during manual re-auth.
2. Ensure recurring Whoop sync jobs all delegate to one central refresh implementation with a lock file.
3. If logs show repeated successful refreshes followed by `400`, suspect multiple refresh consumers or stale token-chain writes.

See `references/2026-05-22-dashboard-whoop-deploy.md` for the session runbook that established these conventions.

## Deployment credentials pattern

For GitHub/Vercel deploy work:

1. Check token presence/scope without printing token values.
2. GitHub deployment usually needs `repo`, `workflow`, and sometimes `read:org`, not merely `read:packages`.
3. Vercel deploy needs a valid `VERCEL_TOKEN`.
4. If tokens are missing/insufficient, create or use a root-only helper that prompts hidden input over SSH and updates `/root/.hermes/.env`.
5. After the operator enters credentials, verify metadata/scopes only; never display secret values.

## Profile/persona/SOUL.md operations

Use this subsection when the operator asks to create, update, install, or align role-specific Hermes personas/profiles, especially Simpson-family agents or any future named profile family.

### Workflow

1. Check existing profiles before creating new ones:
   ```bash
   hermes profile list
   ```
2. Create missing profiles by cloning the default profile unless the operator specifies a clean profile:
   ```bash
   hermes profile create <name> --clone
   ```
3. Write profile soul files to uppercase `SOUL.md`, not lowercase `soul.md`:
   ```text
   ~/.hermes/profiles/<profile>/SOUL.md
   ```
   Hermes uses uppercase `SOUL.md`; Linux paths are case-sensitive, so lowercase may silently fail to load.
4. Keep the default profile aligned if the operator says “everything” or “main agent too”:
   ```text
   ~/.hermes/SOUL.md
   ```
5. Record a compact profile map in the default `SOUL.md` when multiple named profiles exist, so the main agent knows which role to delegate to.
6. Update memory only for durable role boundaries, not full copied soul text.
7. Verify:
   ```bash
   for p in homer lisa marge bart maggie; do
     f="$HOME/.hermes/profiles/$p/SOUL.md"
     printf '%s: ' "$p"
     test -s "$f" && grep -m1 '^# ' "$f" || echo MISSING
   done
   hermes profile list
   ```

### the operator's current Simpson family mapping

- `homer` — General / Main Hermes
- `lisa` — Research & Analysis
- `marge` — Personal Assistant / Wellbeing
- `bart` — Arb Scanner / Trading Alerts
- `maggie` — Security / Silent Monitoring

## Health dashboard / Life OS command centre pattern

When hardening the operator's health dashboard, keep the production architecture as:

```text
Hermes locked Whoop sync → Notion Whoop Health Log → dashboard API → frontend → optional Notion writeback
```

Do not add a second Whoop refresh-token consumer in Vercel/frontend code. The dashboard should read Notion-backed live data and write action-plan notes back to Notion. Verify both `/api/dashboard/summary` and `/api/dashboard/writeback` in local dev and production before calling it production-grade.

See `references/health-dashboard-life-os-command-centre.md` for the repo paths, Vercel alias, required env names, trend metrics, writeback smoke test, and reporting checklist.

## Bot Control Room / trading bots dashboard pattern

When the operator asks for a website/dashboard of all bots and their profit/loss, build or operate a **read-only monitoring surface**. Treat it like Sector 7-G's wall display: it may show balances, P/L, open exposure, service status, and recent events, but it must not add trade buttons or start a new execution loop.

Current convention: `/root/bots-dashboard/server.py` runs as `bots-dashboard.service`, binds to `127.0.0.1:9125`, and is exposed inside the tailnet at `/bots` through Tailscale Serve. Keep it loopback-only and use Tailscale rather than opening a public VPS port.

Implementation checklist:

1. Discover bot ledgers and services first (`systemd`, SQLite schemas, JSONL/log files).
2. Query existing state files read-only; never introduce a second broker/API refresher just for the dashboard.
3. Show per-bot source-of-truth cards rather than hiding currency/source differences in one blended number.
4. When the operator asks “how many trades” or “out of the 100 trades,” disambiguate the counter before giving a headline: open live broker trades, confirmed broker fills, paper trade intents, closed ledger trades, and arbitrage opportunities are different gauges. For Quantum FX 100-trade samples, report both `trade_intents` progress and confirmed `ORDER_FILLED` broker fills; do not let arb opportunities inflate executed-trade counts.
5. Warn when totals mix currencies, especially USD crypto ledgers and GBP OANDA account data.
5. Make routes subpath-aware for Tailscale Serve (`/bots/` and `/bots/api/bots` as well as `/` and `/api/bots`).
6. Verify local service health, local API JSON, Tailscale URL/API, and a browser smoke test before reporting success.

See `references/bot-control-room-dashboard.md` for the current data sources, query quirks, paths, and pitfalls. For the specific ForexBot metrics drift / dead BB-RSI path fix pattern, see `references/bot-control-room-forexbot-metrics-drift.md`.

### Dashboard enhancement workflow: audit → fix → test → document

When enhancing the Bot Control Room dashboard (e.g., adding missing metrics, fixing bugs, enabling alerts), use this pattern:

1. **Systematic audit** (7-point checklist from `infrastructure-audit` skill):
   - Basic health (service status, port, accessibility, known bugs)
   - Data sources (SQLite, APIs, logs, systemd)
   - Coverage (which bots tracked, which metrics shown, what's missing)
   - Accuracy (does P/L match ledger, currency handling, real-time lag)
   - Metrics completeness (per-bot, account-level, system-level, alerts)
   - Reliability (edge cases: offline bots, database locks, auth, refresh rate)
   - Verdict (rate each dimension, recommend minimum fixes)

2. **Implement fixes** as coordinated changes to a single file:
   - Group related fixes into one deployment (e.g., 7 fixes in one server.py → one restart)
   - Test each fix in isolation (`python3 -m py_compile`, spot-check queries, HTTP smoke tests)
   - Create a backup of the original (`server.py.backup`)
   - Restart service and verify with HTTP tests (HEAD, GET /api/bots, JSON validity)

3. **Record the changes**:
   - Create a `DEPLOYMENT_SUMMARY.md` in the dashboard directory
   - Include fix list, test results, config notes, rollback path
   - Provide exact line numbers and SQL queries used for verification

4. **Document to Obsidian vault** (see subsection below)

See `references/bot-dashboard-audit-and-enhancement.md` for the May 26 example (7 fixes: HEAD 501, Arb Scanner tracking, Quantum FX fills, win rate/profit factor, margin visibility, stale warnings, Telegram alerts).

See `references/trading-bot-live-mode-audit.md` for the Quantum FX USD/JPY command set and reporting pattern.

## World Cup Prediction Bot operations pattern

When the operator asks about the World Cup bot, countdown, fixtures, dashboard, prediction snapshots, or production readiness, treat it like a read-only research bot unless explicitly told otherwise. Verify live state first: FIFA start date, service status, fixture count, next kickoff rows, dashboard API, and odds-feed health.

Key lesson: OpenFootball fixtures may encode kickoff as separate `date` plus `time` with a UTC offset, e.g. `2026-06-11` + `13:00 UTC-6`. The parser must convert that to ISO UTC (`2026-06-11T19:00:00Z`), not flatten it to midnight. After changing fixture normalization, re-ingestion can create duplicate logical matches if old source IDs included the stale kickoff; back up the SQLite DB, deduplicate legacy midnight rows, regenerate prediction snapshots, restart `worldcup-dashboard.service`, and verify `127.0.0.1:9130/api/dashboard`.

Do not call the bot market-ready just because fixtures/model/predictions pass. Real odds can still block the production gate. API-Football free plan may reject 2026 season access, and The Odds API may be disabled by quota governor. Report that as an odds-feed readiness blocker.

When using Odds-API.io for the World Cup bot, prefer `ODDS_API_IO_KEY`, league `international-fifa-world-cup`, bookmakers `Bet365,Unibet`, explicit User-Agent `HermesWorldCupBot/1.0`, and a quiet script-only cron refresh. Add provider-name aliases such as `Turkiye -> Turkey` and `IR Iran -> Iran`, then backfill old unmatched provider events so reconciliation gauges become truly clean.

Detailed checklist: `references/worldcup-prediction-bot-operations.md`. Odds-API.io implementation and refresh details: `references/worldcup-odds-api-io-refresh.md`.er-name aliases such as `Turkiye -> Turkey` and `IR Iran -> Iran`, then backfill old unmatched provider events so reconciliation gauges become truly clean.

Detailed checklist: `references/worldcup-prediction-bot-operations.md`. Odds-API.io implementation and refresh details: `references/worldcup-odds-api-io-refresh.md`.

## Infrastructure documentation to Obsidian Karpathy wiki

When the operator has made infrastructure changes (dashboard fixes, new bot configurations, system audits), document them into his Obsidian Karpathy LLM wiki. The vault follows Andrej Karpathy's LLM Wiki pattern (raw_sources → wiki pages → schema) and runs at `/root/life-os-v2-obsidian`.

Workflow:

1. **Identify the scope:** Is this a single system change (e.g., Bot Dashboard fix), a suite of related changes (7 coordinated fixes), or a broader infrastructure audit?

2. **Create individual system pages** (one per logical system, not one-off):
   - **System-level pages:** Bot-Dashboard-2026-05-26, Bot-Control-Room, BB-RSI-FX-Bot-Status, Arbitrage-Scanner, Crypto-Bot, etc.
   - **Each page includes:** YAML frontmatter (title, created, updated, type, tags, sources, confidence), what the system does, current state/metrics, recent changes, related systems (wikilinks), next steps
   - **Wikilink strategy:** Every page links to 2+ other pages (builds a connected knowledge graph, not isolated notes)

3. **Update the index** (`index.md`):
   - Add a new section like "## System Updates & Infrastructure (Week of May 20-26)"
   - List new pages with one-line summaries
   - Keep total sections scannable (50 entries → split by first letter or domain)

4. **Update the log** (`log.md`):
   - Append: `## [YYYY-MM-DD] update | Your change summary`
   - List every file created or modified
   - Include the reasoning (e.g., "7 fixes deployed to monitoring dashboard")

5. **Run a lint check:**
   - Verify all `[[wikilinks]]` resolve to existing pages
   - Check for orphan pages (no inbound links) — they should have 2+ inbound references
   - Validate YAML frontmatter (title, created, updated, type, tags, sources)
   - Check tag consistency (tags should be used across pages for searchability)

6. **Integration points:**
   - Pages should cross-reference via wikilinks, not URLs
   - New pages become discoverable via Obsidian Graph View and Dataview queries
   - the operator can browse vault in Obsidian.app on his laptop/phone; it syncs automatically

**Key patterns:**
- Type: `system` or `system-update` for infrastructure pages
- Tags: [bots, dashboard, monitoring, fx, crypto, infrastructure, etc.] — build a consistent taxonomy
- Confidence: Mark as `medium` or `low` when a claim is one-source or uncertain; `high` for well-supported facts
- Frontmatter example:
  ```yaml
  ---
  title: Bot Dashboard — 7 Fixes Deployed May 26
  created: 2026-05-26
  updated: 2026-05-26
  type: system-update
  tags: [bots, dashboard, monitoring, infrastructure]
  sources: [DEPLOYMENT_SUMMARY.md]
  ---
  ```

**What NOT to document:** One-off manual task narratives ("summarize today's market"), transient errors that resolved, session-specific debugging paths. Document structural changes, monitoring improvements, system audits, and architectural decisions.

See `references/obsidian-karpathy-wiki-infrastructure.md` for the May 26 example (6 wiki pages, cross-reference network, lint validation) and how to query the vault programmatically.

## Skill hub install runbook

When the operator sends a direct command like `hermes skills install <id>`, treat that as permission to perform the install rather than explain it. Use `printf 'y\n' | hermes skills install <id>` to satisfy the CLI confirmation, resolve ambiguous short names toward official/trusted identifiers when obvious, and verify with `hermes skills list` before reporting success. Keep the reply concise: resolved source, scan verdict, install path/name, and verification.

See `references/hermes-skill-install-runbook.md` for the detailed pattern and ambiguity pitfalls.

## VPS security / port audit runbook

When the operator asks for a whole-system audit, cleanup, or to close unnecessary ports, perform a conservative live security sweep: inventory listeners, classify public vs tailnet vs loopback exposure, harden only what is safe, and verify services after changes. See `references/vps-security-port-audit.md` for the detailed command pattern.

Key rules:

1. Do **not** fully close public SSH unless the operator's Tailscale SSH path is verified from at least one trusted client; otherwise prefer UFW `limit OpenSSH`.
2. Keep dashboard/admin surfaces loopback-only and route phone access through Tailscale Serve/proxy.
3. Clean temp secret/session artifacts only when clearly disposable; otherwise tighten permissions.
4. Report exact exposure classes and changes, not raw command dumps.

## Full systems check runbook

When the operator asks to “check everything” or “make sure everything is running correctly”, perform a broad live operational check rather than only inspecting Hermes itself. See `references/full-systems-check-runbook.md` for the current checklist covering host resources, Hermes gateway/dashboard, cron/morning briefing, trading bots, health dashboard, Notion, iCloud Calendar, ports, and safe cleanup of stale local dashboard dev processes.

When the operator asks for a “Lisa-level” check, treat it as an analytical reliability/ops review: host resources, update/reboot state, services, timers, dashboard HTTP checks, cron, and warning/error logs. When he asks for a “Maggie-level” check, treat it as a quiet security review: exposure, UFW, SSH effective config, fail2ban, auth logs, shell/sudo users, persistence, secret-file permissions, and temp secret/session hygiene. See `references/post-reboot-lisa-maggie-checks.md`.

Key reporting pattern:

1. Overall verdict first: healthy / degraded / broken.
2. Summarise what is running correctly.
3. Call out anything fixed during the check.
4. List watch-outs and concrete next actions.
5. Do not dump raw command output unless the operator asks.

## Live Hermes upgrade + Lisa/Maggie security sweep pattern

When updating the operator's live Hermes install or recovering from a gateway restart during an update, verify both app state and server security posture before reporting success. Treat `hermes update` like a Sector 7-G maintenance shift: the plant may come back online, but you still check the gauges.

Minimum post-update checks:

1. `hermes --version`, git status/up-to-date state, and `hermes doctor`.
2. `systemctl` active/enabled checks for `hermes-gateway`, `hermes-dashboard`, and dashboard proxy services.
3. Loopback HTTP checks for Hermes dashboard/proxy and the operator's key local dashboards.
4. APT/reboot-required state, especially after AppArmor/kernel-related package upgrades.
5. Lisa-level ops sweep: host resources, failed units, timers, cron jobs, service logs.
6. Maggie-level security sweep: public listeners, UFW, SSH effective config, fail2ban, auth logs, shell/sudo users, persistence, and secret-file permissions.
7. Report breach/no-breach separately from blocked internet noise.

See `references/hermes-live-upgrade-and-security-sweep.md` for the detailed checklist and reporting pattern.

## Telegram-primary notification migration pattern

When the operator asks to move operational Hermes notifications away from Slack, treat it as a full delivery migration rather than a cosmetic channel rename. Inventory cron jobs, origin metadata, prompt text, bot alert code, gateway adapter state, and Slack credential presence; set active deliveries explicitly to `telegram`; verify Telegram auth and delivery; and avoid restarting live trading services unless the operator authorizes it.

Core rules:

1. Do not rely on `origin` when historical origin metadata may still point to Slack.
2. Do not print `.env` values while checking Telegram/Slack variables.
3. Replace the underlying transport (`chat.postMessage` → Telegram Bot API), not just labels/log text.
4. Compile/smoke-test changed scripts and grep for leftover direct Slack posting symbols.
5. If bots are live, report that changed alert code will load on restart/reboot rather than forcing a service restart.
6. Before deleting a Slack workspace or revoking the Slack app, disable Hermes' Slack adapter first: remove/comment Slack credentials from `~/.hermes/.env`, restart `hermes-gateway`, verify `hermes status --all` shows Slack not configured and Telegram still works, then wait one normal cron/watchdog cycle before revoking/deleting Slack. Do not delete the workspace first or the gateway may keep trying to connect to a dead Socket Mode endpoint.
6. After a reboot, perform a concrete Telegram migration verification pass: gateway/dashboard HTTP checks, systemd active/enabled checks, Telegram send smoke, `TELEGRAM_GET_ME`, cron delivery audit, and quiet watchdog script smoke tests. Quiet output from watchdogs is success when the script is designed to print only anomalies.
7. the operator's arbitrage scanner service is `arb-scanner.service`; do not report it missing just because `arbitrage-scanner.service` is absent. Check the real service name and process command before flagging a fault.

See `references/telegram-primary-delivery-migration.md` for the detailed checklist and reporting shape. See `references/telegram-post-reboot-verification.md` for the post-reboot verification pattern proven after the Telegram migration.

## Telegram bot command menu pattern

When the operator asks to add Telegram `/` commands, distinguish the **Telegram menu** from **Hermes command handlers**. Telegram Bot API `setMyCommands` only changes what the client suggests; unknown commands still route through Hermes gateway command dispatch and may fail. Prefer registering only real Hermes gateway commands unless also implementing a handler in the central command registry/gateway path. See `references/telegram-command-menu-operations.md`.

Quick rules:

1. Check current bot commands with Telegram Bot API `getMyCommands` without printing the bot token.
2. Use `setMyCommands` for all relevant scopes: default, all private chats, and all group chats.
3. Keep the menu concise and the operator-useful: `/help`, `/commands`, `/status`, `/platforms`, `/profile`, `/cron`, `/new`, `/stop`, `/retry`, `/undo`, `/queue`, `/background`, `/approve`, `/deny`, `/restart`, `/topic`.
4. Do not add `/briefing`, `/trades`, `/whoop`, etc. as menu entries unless they are real gateway commands or plugin/skill slash handlers.
5. Remember gateway startup derives the Telegram menu from Hermes' central command registry and may overwrite direct Bot API menu edits. For durable custom commands, add them through the supported registry/plugin path rather than only calling `setMyCommands`.

## Composio router/profile migration pattern

When the operator asks to “get Composio working”, “use Composio instead of the APIs”, or “update everything to use Composio”, treat it as a whole-Hermes integration migration, not just an OAuth check. Composio connections may be active while the current Hermes/Tool Router session is scoped too narrowly, so verify both the account connections and Hermes tool discovery.

Core workflow:

1. Load protected `hermes-agent` first for official MCP/config commands.
2. Verify active app connections and tool discovery before edits.
3. If the operator says a connected app should be available through Composio, do not deny capability from memory. Use the relevant Composio/direct tool or connection manager to verify live access. For Google Calendar reminders, list calendars first, then create/update the calendar event with strict schema-compliant arguments; use iCloud/CalDAV only when the operator explicitly chooses Apple Calendar.
4. Update every active profile, not only default: default, `homer`, `lisa`, `marge`, `bart`, and `maggie`.
4. Back up configs and cron job definitions before bulk edits.
5. Prefer Composio for connected SaaS apps: Gmail, Google Calendar, Google Drive, Google Sheets, GitHub, Linear, Notion, Slack, and Telegram.
6. Keep non-Composio integrations as direct/fallback paths only; for example the operator's iCloud Calendar remains CalDAV unless an Apple/iCloud Composio integration is actually configured.
7. Update cron/toolsets and skill/workflow guidance that still prefers raw app APIs.
8. Run harmless read-only smoke tests for each connected app and profile-level MCP discovery before reporting success.

See `references/composio-router-profile-migration.md` for the detailed checklist, reporting shape, and pitfalls from the June 2026 migration.

## References

- `references/simpson-family-profiles.md` — current Simpson family role map and SOUL.md placement notes from the operator's setup.
- `references/hermes-dashboard-tailscale-serve-proxy.md` — loopback-safe dashboard access through Tailscale Serve.
- `references/hermes-dashboard-tailnet-dedicated-port-host-rewrite.md` — session-proven Hermes Dashboard access via dedicated Tailscale HTTPS port, Host-rewrite proxy, and Windows SSH tunnel fallback.
- `references/hermes-dashboard-obsidian-gui-access.md` — GUI access pattern for Hermes Dashboard + Obsidian: use the dedicated `:9119/` Tailscale URL or SSH tunnel, avoid stale `/hermes/` Host-header failures, and sync the operator's Windows vault onto the VPS path configured by `OBSIDIAN_VAULT_PATH`.
- `references/hermes-dashboard-systemd-recovery.md` — recover a stopped/missing official dashboard service, including the proven loopback-only systemd unit, GET-based health check, and public-IP safety note.
- `references/tailscale-dashboard-troubleshooting.md` — diagnose "site can't be reached" from phone; distinguishes server-side failures from an offline iPhone/Tailscale client.
- `references/tailscale-dev-dashboard-access.md` — temporary phone access pattern for local/dev dashboards.
- `references/hermes-auto-update-systemd.md` — conservative weekly systemd timer pattern for safe Hermes updates outside live Slack turns.
- `references/2026-05-22-dashboard-whoop-deploy.md` — session runbook for dashboard/Whoop/deploy conventions.
- `references/full-systems-check-runbook.md` — broad operational health-check checklist, including stale dashboard LSP cleanup, secret-file permission fixes, read-only OANDA verification, and interpreting dashboard API/page mismatches.
- `references/vps-security-port-audit.md` — conservative VPS security/port audit pattern: classify public/tailnet/loopback exposure, rate-limit SSH without lockout, clean temp secret artifacts, and verify dashboards/bots after cleanup.
- `references/full-system-health-check-2026-05-29.md` — worked read-only health-check pattern for the operator's trading bots + Hermes gateway + OANDA + host resources; includes segmented probe strategy, Quantum FX live/armed/readiness interpretation, OANDA openPositions verification, and compact reporting shape.
- `references/post-reboot-lisa-maggie-checks.md` — post-update/reboot verification pattern and the meanings of the operator's “Lisa-level” analytical health check and “Maggie-level” quiet security audit.
- `references/health-dashboard-life-os-command-centre.md` — harden the operator's health dashboard with live Notion-backed Whoop data, trend metrics, production smoke checks, and Notion writeback.
- `references/bot-control-room-dashboard.md` — operate/build the operator's read-only trading bot P/L dashboard, data sources, service/Tailscale paths, and query pitfalls.
- `references/worldcup-prediction-bot-operations.md` — operate the operator's World Cup Prediction Bot: FIFA start-date verification, OpenFootball kickoff parsing, duplicate fixture cleanup, dashboard checks, and odds-feed readiness blockers.
- `references/worldcup-weekly-readiness-check.md` — Sunday/week-ahead World Cup trading readiness check: service health, `health-gate`, profitability ledger blockers, provider-plan interpretation, and model-feature implementation audit.
- `references/bot-dashboard-audit-and-enhancement.md` — systematic 7-point audit checklist for dashboard improvements; May 26 example (7 fixes: HEAD 501, Arb Scanner, win rate/profit factor, margin visibility, stale warnings, Telegram alerts).
- `references/trading-bot-live-mode-audit.md` — targeted read-only bot live/paper/armed/readiness audit pattern, including Quantum FX USD/JPY systemd/timer/journal checks.
- `references/hermes-skill-install-runbook.md` — non-interactive Hermes skill installation from chat, trusted-source ambiguity handling, scan reporting, and verification.
- `references/obsidian-karpathy-wiki-infrastructure.md` — document infrastructure changes to Obsidian Karpathy LLM wiki; May 26 example (6 wiki pages, cross-reference network, lint validation, wikilink patterns).
- `references/composio-router-profile-migration.md` — migrate the operator's Hermes profiles/workflows to prefer Composio for connected SaaS apps; includes router-session scoping pitfall, app smoke tests, profile-wide MCP verification, and reporting shape.
- `references/hermes-live-upgrade-and-security-sweep.md` — safe live Hermes update and gateway-restart recovery pattern; includes Lisa/Maggie operational/security checks, dashboard/service verification, reboot-required handling, and breach-vs-blocked-noise reporting.
- `references/telegram-primary-delivery-migration.md` — migrate the operator's cron/watchdog/bot alerts from Slack or ambiguous `origin` to Telegram, including Telegram smoke tests, bot alert code checks, and live-trading restart caution.
- `references/telegram-command-menu-operations.md` — safely manage the operator's Telegram bot `/` menu: register only real Hermes gateway commands, set all scopes, and avoid dead custom shortcuts unless handlers exist.
- `references/fresh-install-handover-and-restore.md` — create a root-only restore map before a fresh Hermes install, preserving Hermes config/memories/skills/cron/profiles, trading bots, World Cup systems, Whoop/Notion, dashboards, systemd units, and secret-file locations without exposing secrets.

## Pitfalls

- Do not expose official Hermes Dashboard publicly just because it is convenient; it can manage config/environment/state.
- Do not use the Hermes Dashboard `--insecure` override merely to bind it to a Tailscale or public interface. Treat the built-in refusal as a safety rail, not an obstacle to bypass.
- Do not run WebUIs on OAuth callback ports, especially `8787`.
- Do not use `pkill -f` with a broad pattern from inside a shell command that also contains the same pattern; it can kill the command shell itself. Prefer service-specific stops, exact PIDs, or safer `pgrep`/manual verification.
- Do not treat local health-dashboard dev processes (`vite`, `tsserver.js`, TypeScript LSP) as the public dashboard. The public Vercel dashboard can be healthy while stale local dev processes waste RAM under the gateway cgroup; kill only exact dashboard-dev patterns and verify `9119`/`8787` afterwards.
- Do not restart `hermes-gateway` casually from a live Slack session; it can interrupt the current conversation. Prefer targeted cleanup first, and recommend a later restart only if needed.
- `hermes update` may restart `hermes-gateway` and interrupt the live Slack turn. After reconnecting, verify `hermes --version`, git HEAD/up-to-date state, `hermes doctor`, gateway/dashboard service status, and dashboard/proxy HTTP checks before reporting success.
- Hermes update intentionally stops running dashboard backends when frontend/backend assets no longer match. Under systemd this can look like a dashboard crash/restart. For auto-update scripts, restart `hermes-dashboard.service` and `hermes-dashboard-tailnet-proxy.service`, then poll `127.0.0.1:9119` and `127.0.0.1:9120` with retries before failing the unit; a single immediate `curl` can race startup and falsely mark auto-update failed.
- Do not claim OAuth will be permanent forever. Say it should remain authenticated as long as the refresh-token chain is preserved and only one locked refresh path touches it.
- Do not write `soul.md` only. Use `SOUL.md`.
- Do not overwrite operational context in `~/.hermes/SOUL.md` unless the operator explicitly asks for a full replacement.
- Do not paste secrets into profile soul files.
- Do not assume profile creation starts gateways. `hermes profile create` creates the profile; gateways usually remain stopped until configured/started.
- If a profile already exists, treat the operation as an update, not a duplicate creation.
- Do not save transient port ownership or token validity as long-term memory unless it represents a deliberate convention.

- Do not assume active Composio OAuth means Hermes can see or call every connected app. Verify both Composio account state and the current Tool Router/MCP discovery scope; a router session may be pinned to a subset of toolkits.
- Do not deny calendar/reminder capability when Composio Google Calendar tools are available. For reminder/calendar requests, first check/use the connected calendar tools (or the Google Workspace/Apple Calendar skill as appropriate) rather than claiming external calendar access is unavailable.
- Do not replace iCloud/CalDAV workflows with Composio just because Google Workspace is connected; only migrate services that are actually connected and smoke-tested through Composio.
- Do not stop Composio migrations after default profile config. When the operator says "everything", check all Simpson profiles and cron jobs that need app tools.
- Do not claim a Composio migration is complete without harmless live smoke tests for the connected apps and profile-level MCP discovery checks.
- **World Cup Odds-API.io league slug**: the correct free-tier league slug is `international-fifa-world-cup` (returns 104 events). `international-world-cup` returns 0 events and silently passes ingest while failing the freshness gate. If cron job `worldcup_odds_refresh.sh` or the provider default in `app/providers.py` uses the wrong slug, fix both. See `references/worldcup-odds-api-io-refresh.md`.

## Verification checklist

- [ ] Protected `hermes-agent` skill was loaded first for official commands.
- [ ] Live state was checked before making operational claims.
- [ ] No secrets, OAuth state URLs, tokens, or `.env` values were printed.
- [ ] Dashboard/admin surfaces remain loopback-only unless the operator explicitly accepted exposure.
- [ ] OAuth callback ports remain separated from dashboards/WebUIs.
- [ ] Profile SOUL files use uppercase `SOUL.md` and existing content was preserved unless replacement was requested.
- [ ] Any archived/replaced service/app/config has a rollback path.
- [ ] For Composio migrations, active connections, app smoke tests, and profile-level MCP/tool discovery were verified across all affected profiles.
