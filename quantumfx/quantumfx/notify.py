"""Telegram notifications via the operator's Hermes bot. Never raises."""
from __future__ import annotations

import logging
from pathlib import Path

import requests

log = logging.getLogger("quantumfx.notify")

# Hermes bot (the operator’s Telegram bot) is the operator's primary channel;
# predictions .env (older bot) kept as fallback.
TG_ENVS = [
    (Path("/root/.hermes/.env"), "TELEGRAM_BOT_TOKEN", "TELEGRAM_HOME_CHANNEL"),
    (Path("/root/predictions-bot/.env"), "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
]
_cache: dict = {}


def _creds() -> tuple[str, str] | None:
    if "token" in _cache:
        return _cache["token"]
    for path, token_key, chat_key in TG_ENVS:
        try:
            env = {}
            for line in path.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
            token = env.get(token_key, "")
            chat = env.get(chat_key, "")
            if token and chat:
                _cache["token"] = (token, chat)
                return _cache["token"]
        except Exception:
            continue
    _cache["token"] = None
    return _cache["token"]


def send(text: str) -> bool:
    """Plain-text Telegram message (the operator's rule: no markdown tables/headers)."""
    creds = _creds()
    if not creds:
        log.info("telegram disabled: %s", text)
        return False
    token, chat = creds
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": f"⚛️ QuantumFX\n{text}"},
            timeout=10,
        )
        return r.ok
    except Exception as e:
        log.warning("telegram send failed: %s", e)
        return False
