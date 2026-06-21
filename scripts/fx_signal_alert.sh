#!/usr/bin/env bash
set -euo pipefail
cd /root/fx-signal-bot
mkdir -p state reports
OUT=$(PYTHONPATH=src python scripts/current_signal.py --instrument USD_JPY --threshold 0.50 --target-mode tp_sl --target-horizon 24 --regime-split --allow-live-data)
EVENT=$(python3 - <<'PY' "$OUT"
import json, sys, datetime
payload=json.loads(sys.argv[1])
payload['observed_at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
print(json.dumps(payload, separators=(',', ':')))
PY
)
printf '%s\n' "$EVENT" >> state/shadow_alerts.jsonl
PYTHONPATH=src python scripts/shadow_alert_report.py >/dev/null
SIG=$(python3 - <<'PY' "$OUT"
import json,sys
print(json.loads(sys.argv[1]).get('signal','FLAT'))
PY
)
if [ "$SIG" != "FLAT" ]; then
  printf 'USD_JPY shadow alert only — no order placed. operator approval required for any real-money execution.\n%s\nReport: /root/fx-signal-bot/reports/shadow_alert_report.md\n' "$OUT"
fi
