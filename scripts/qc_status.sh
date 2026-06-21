#!/bin/bash
echo "🩺 STATUS $(date '+%H:%M %Z')"
for s in fx-bot hermes-gateway hermes-dashboard predictions-ultra market-bot scanner life-os-portal; do
  printf '• %s: %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null)"
done
/root/bots/fx-bot/venv/bin/python /root/trading-agent/oanda_trades.py summary 2>/dev/null
