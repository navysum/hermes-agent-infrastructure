#!/bin/bash
echo "🤖 BOTS"
for s in forexbot crypto-bot crypto-bot-lab arb-scanner quantum-fx-usdjpy-execution.timer worldcup-ultra; do
  printf '• %s: %s\n' "${s%.timer}" "$(systemctl is-active "$s" 2>/dev/null)"
done
