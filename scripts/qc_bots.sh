#!/bin/bash
echo "🤖 BOTS"
for s in fx-bot market-bot market-bot-lab scanner fx-exec.timer predictions-ultra; do
  printf '• %s: %s\n' "${s%.timer}" "$(systemctl is-active "$s" 2>/dev/null)"
done
