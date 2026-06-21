#!/bin/bash
# self_heal.sh — autonomous remediation, every 30 minutes.
# Finds problems AND FIXES them. Telegrams the operator only when:
#   • it had to fix something (so he knows it happened), or
#   • it tried and FAILED (so he knows to step in).
# Silent when everything is healthy. No AI/credits used.

TK=$(grep '^TELEGRAM_BOT_TOKEN=' /root/trading-secrets.env | cut -d= -f2-)
CH=$(grep '^TELEGRAM_HOME_CHANNEL=' /root/trading-secrets.env | cut -d= -f2-)
ACTIONS=""

act() { ACTIONS="$ACTIONS$1
"; }

# ── 1. Core services: restart anything down ───────────────────────────────────
# trading-agent-telegram removed 2026-06-16 — it is now a FAILSAFE only, managed
# in section 6 (started only if Hermes is down). Don't unconditionally restart it.
for s in forexbot forexbot-enhanced-dashboard analytics-dashboard worldcup-ultra \
         life-os-portal bots-dashboard crypto-bot crypto-bot-lab arb-scanner; do
  st=$(systemctl is-active "$s.service")
  if [ "$st" != "active" ]; then
    systemctl restart "$s.service" 2>/dev/null
    sleep 4
    if [ "$(systemctl is-active $s.service)" = "active" ]; then
      act "🔧 FIXED: $s was $st → restarted OK"
    else
      act "🚨 FAILED TO FIX: $s is $(systemctl is-active $s.service) after restart — needs you"
    fi
  fi
done

# ── 2. Timers: re-enable anything that dropped off ────────────────────────────
# morning-brief removed 2026-06-16 — the brief is now a Hermes cron job ("Morning Brief").
for t in forexbot-analyst quantum-fx-usdjpy-execution worldcup-odds-refresh; do
  if ! systemctl is-active --quiet "$t.timer"; then
    systemctl enable --now "$t.timer" 2>/dev/null
    systemctl is-active --quiet "$t.timer" \
      && act "🔧 FIXED: $t.timer was off → re-enabled" \
      || act "🚨 FAILED TO FIX: $t.timer won't start — needs you"
  fi
done

# ── 3. ForexBot heartbeat: log stale >10 min while service "active" = hung ───
LOG=/root/bots/forexbot/bot.log
if systemctl is-active --quiet forexbot.service && [ -z "$(find $LOG -mmin -10 2>/dev/null)" ]; then
  systemctl restart forexbot.service
  sleep 8
  [ -n "$(find $LOG -mmin -1 2>/dev/null)" ] \
    && act "🔧 FIXED: ForexBot was hung (log stale) → restarted, heartbeat back" \
    || act "🚨 FAILED TO FIX: ForexBot restarted but no heartbeat yet — check bot.log"
fi

# ── 4. OANDA live auth: nothing to auto-fix, but catch it within 30 min ──────
ENVF=/root/bots/forexbot/.env
KEY=$(grep '^OANDA_API_KEY=' $ENVF | head -1 | cut -d= -f2)
ACC=$(grep '^OANDA_ACCOUNT_ID=' $ENVF | head -1 | cut -d= -f2)
CODE=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $KEY" \
  "https://api-fxtrade.oanda.com/v3/accounts/$ACC/summary")
[ "$CODE" != "200" ] && act "🚨 OANDA live auth returning HTTP $CODE — token may be revoked, needs you"

# ── 5. Hermes must stay ALIVE (now the primary agent; gateway + dashboard) ────
#    Gateway = Telegram receive + interactive agent + cron scheduler (~160MB,
#    cloud model so no llama OOM). Dashboard = web UI. Both kept up. Phase 3.
for h in hermes-gateway hermes-dashboard; do
  if ! systemctl is-active --quiet "$h.service"; then
    systemctl unmask "$h.service" 2>/dev/null
    systemctl restart "$h.service" 2>/dev/null
    sleep 4
    if systemctl is-active --quiet "$h.service"; then
      act "🔧 FIXED: $h was down → restarted (Hermes is the primary agent now)"
    else
      act "🚨 FAILED TO FIX: $h won't start — needs you"
    fi
  fi
done

# ── 6. CLAUDE FAILSAFE: trading-agent revives ONLY if Hermes gateway is down ───
#    Hermes (gateway) is the primary interactive agent. trading-agent-telegram is
#    kept dormant. If Hermes can't be brought up (section 5 failed), start the
#    Claude bridge as a backup so the operator still has an agent. Park it again once
#    Hermes is healthy, to avoid two agents answering at once.
if ! systemctl is-active --quiet hermes-gateway.service; then
  if ! systemctl is-active --quiet trading-agent-telegram.service; then
    systemctl start trading-agent-telegram.service 2>/dev/null
    act "🚨 FAILSAFE ENGAGED: Hermes gateway DOWN → started trading-agent (Claude) backup on @your_Hermes_bot. Investigate Hermes."
  fi
else
  if systemctl is-active --quiet trading-agent-telegram.service; then
    systemctl stop trading-agent-telegram.service 2>/dev/null
    act "🔧 Hermes healthy again → parked trading-agent failsafe (no double-agent)."
  fi
fi

# ── Deliver only if something happened (dedup via state hash) ─────────────────
if [ -n "$ACTIONS" ]; then
  STATE=/root/trading-agent/.job_state/self_heal.hash
  mkdir -p "$(dirname $STATE)"
  NEW=$(echo "$ACTIONS" | tr -d '0-9' | md5sum | cut -d' ' -f1)
  echo "[$(date -Is)] actions:"; echo "$ACTIONS"
  if [ "$NEW" != "$(cat $STATE 2>/dev/null)" ]; then
    curl -s "https://api.telegram.org/bot$TK/sendMessage" \
      --data-urlencode "chat_id=$CH" \
      --data-urlencode "text=🤖 Self-Heal Report — $(date '+%H:%M')
$(echo "$ACTIONS" | head -c 3800)" > /dev/null
  fi
  echo "$NEW" > "$STATE"
else
  rm -f /root/trading-agent/.job_state/self_heal.hash
fi
