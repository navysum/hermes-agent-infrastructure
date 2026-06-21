#!/bin/bash
echo "🩺 STATUS $(date '+%H:%M %Z')"
for s in forexbot hermes-gateway hermes-dashboard worldcup-ultra crypto-bot arb-scanner life-os-portal; do
  printf '• %s: %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null)"
done
/root/bots/forexbot/venv/bin/python /root/trading-agent/oanda_trades.py summary 2>/dev/null
