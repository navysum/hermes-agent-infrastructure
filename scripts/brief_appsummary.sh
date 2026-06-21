#!/bin/bash
# Compact app-summary for the morning brief — only the fields it needs, so the
# brief context stays small (avoids the slow ~10k-char full-summary compression).
curl -s --max-time 10 http://127.0.0.1:9126/app/api/summary | python3 -c "
import sys, json
try: d = json.load(sys.stdin)
except Exception as e: print('app summary unreachable:', e); sys.exit(0)
f=d.get('forex',{}) or {}; a=d.get('analyst',{}) or {}
b=d.get('bots_summary',{}) or {}; s=d.get('services',{}) or {}; al=d.get('alerts',[]) or []
print('FOREX equity_gbp=%s open=%s day_loss_pct=%s halted=%s' % (f.get('equity'),f.get('open_trades'),f.get('daily_loss_pct'),f.get('halted')))
print('ANALYST %s — %s' % (a.get('verdict'), a.get('summary')))
print('BOTS running=%s/%s closed=%s total_pnl_mixed_ccy=%s' % (b.get('running'),b.get('count'),b.get('closed_trades'),b.get('total_pnl')))
up=sum(1 for v in s.values() if str(v).lower()=='true'); down=[k for k,v in s.items() if str(v).lower()!='true']
print('SERVICES %d/%d up%s' % (up, len(s), (' DOWN: '+', '.join(down)) if down else ''))
if al:
    print('ALERTS:')
    for x in al[:5]:
        t = (x.get('text') or x.get('message') or x.get('title') or json.dumps(x)) if isinstance(x,dict) else str(x)
        print(' -', t[:120])
"
