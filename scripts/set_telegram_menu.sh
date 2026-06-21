#!/bin/bash
# Re-asserts the operator's custom Telegram command menu on Hermes's bot.
# The gateway rebuilds the menu to native-only on restart; this keeps the
# custom quick-command shortcuts visible. Silent on success.
HT=$(grep '^TELEGRAM_BOT_TOKEN=' /root/.hermes/.env | cut -d= -f2-)
[ -z "$HT" ] && { echo "no telegram token"; exit 1; }
python3 - "$HT" <<'PY'
import sys, json, urllib.request, urllib.parse
tok = sys.argv[1]
cmds = [("trades","Open OANDA trades (live)"),("money","Account equity & P&L"),
 ("sys","System & services status"),("bots","Trading bot status"),
 ("cal","Apple/iCloud calendar — 7 days"),("wc","World Cup — today"),
 ("logs","ForexBot recent log"),("memory","Hermes memory"),
 ("name","Switch persona/profile"),("help","Show all commands"),
 ("new","Start a fresh session"),("profile","Show active persona"),
 ("usage","Token usage & limits")]
for scope in ({"type":"all_private_chats"}, {"type":"default"}):
    body = json.dumps({"commands":[{"command":c,"description":d} for c,d in cmds],
                       "scope":scope}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/setMyCommands",
            data=body, headers={"Content-Type":"application/json"})
    ok = json.load(urllib.request.urlopen(req, timeout=10)).get("ok")
    if not ok: print("menu set failed for", scope)
PY
