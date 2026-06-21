#!/bin/bash
curl -s --max-time 12 http://127.0.0.1:9131/worldcup-ultra/api/live | python3 -c "
import sys,json
try: d=json.load(sys.stdin)
except: print('⚽ WC: feed unreachable'); sys.exit()
ms=d.get('matches',[])
print('⚽ WORLD CUP — TODAY')
if not ms: print('no matches today')
for m in ms:
    print(f\"• {m.get('home_team')} {m.get('home_score','-')}-{m.get('away_score','-')} {m.get('away_team')} [{m.get('status')}]\")
"
