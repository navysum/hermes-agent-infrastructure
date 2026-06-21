#!/bin/bash
LOGS="$(journalctl -u hermes-gateway --since '1 hour ago' --no-pager)"

COUNT="$(echo "$LOGS" | grep -E "429|usage_limit_reached|RateLimitError|credential pool.*exhausted" | wc -l)"

if [ "$COUNT" -gt 0 ]; then
  LAST="$(echo "$LOGS" | grep -E "429|usage_limit_reached|RateLimitError|credential pool.*exhausted" | tail -1)"
  echo "⚠️ Hermes/Codex warning: $COUNT rate-limit related event(s) in the last hour.

Latest:
$LAST

Fallback chain:
$(hermes fallback list)"
fi
