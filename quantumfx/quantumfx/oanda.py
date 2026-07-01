"""Minimal OANDA v20 REST client for QuantumFX (requests-based, no SDK)."""
from __future__ import annotations

import logging
from pathlib import Path

import requests

log = logging.getLogger("quantumfx.oanda")

CANONICAL_ENV = Path("/root/fx-live-bot/.env")


def load_env(path: Path = CANONICAL_ENV) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


class OandaClient:
    def __init__(self, env: dict | None = None):
        env = env or load_env()
        self.token = env["OANDA_API_KEY"]
        self.account_id = env["OANDA_ACCOUNT_ID"]
        mode = env.get("OANDA_ENVIRONMENT", env.get("OANDA_ENV", "practice"))
        self.host = (
            "https://api-fxtrade.oanda.com"
            if mode == "live"
            else "https://api-fxpractice.oanda.com"
        )
        self.ses = requests.Session()
        self.ses.headers.update(
            {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        )

    def _get(self, path: str, **params) -> dict:
        r = self.ses.get(f"{self.host}{path}", params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, payload: dict) -> dict:
        r = self.ses.post(f"{self.host}{path}", json=payload, timeout=20)
        if r.status_code >= 400:
            log.error("POST %s -> %s %s", path, r.status_code, r.text[:400])
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, payload: dict | None = None) -> dict:
        r = self.ses.put(f"{self.host}{path}", json=payload or {}, timeout=20)
        if r.status_code >= 400:
            log.error("PUT %s -> %s %s", path, r.status_code, r.text[:400])
        r.raise_for_status()
        return r.json()

    # ── account ──────────────────────────────────────────────────────────
    def account(self) -> dict:
        return self._get(f"/v3/accounts/{self.account_id}")["account"]

    def summary(self) -> dict:
        return self._get(f"/v3/accounts/{self.account_id}/summary")["account"]

    def instruments(self, names: list[str]) -> dict:
        data = self._get(
            f"/v3/accounts/{self.account_id}/instruments",
            instruments=",".join(names),
        )
        return {i["name"]: i for i in data["instruments"]}

    # ── market data ──────────────────────────────────────────────────────
    def candles(self, instrument: str, granularity: str = "H4", count: int = 500) -> list[dict]:
        data = self._get(
            f"/v3/instruments/{instrument}/candles",
            granularity=granularity,
            count=count,
            price="MBA",
        )
        return [c for c in data["candles"] if c["complete"]]

    def pricing(self, instruments: list[str]) -> dict:
        data = self._get(
            f"/v3/accounts/{self.account_id}/pricing",
            instruments=",".join(instruments),
        )
        return {p["instrument"]: p for p in data["prices"]}

    # ── positions / orders ───────────────────────────────────────────────
    def open_trades(self) -> list[dict]:
        return self._get(f"/v3/accounts/{self.account_id}/openTrades")["trades"]

    def market_order(
        self,
        instrument: str,
        units: int,
        sl_price: float | None = None,
        tp_price: float | None = None,
        tag: str = "quantumfx",
    ) -> dict:
        order: dict = {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "clientExtensions": {"tag": tag, "comment": "quantumfx-auto"},
            "tradeClientExtensions": {"tag": tag},
        }
        prec = 3 if instrument.endswith("JPY") else 5
        if sl_price is not None:
            order["stopLossOnFill"] = {"price": f"{sl_price:.{prec}f}", "timeInForce": "GTC"}
        if tp_price is not None:
            order["takeProfitOnFill"] = {"price": f"{tp_price:.{prec}f}", "timeInForce": "GTC"}
        return self._post(f"/v3/accounts/{self.account_id}/orders", {"order": order})

    def close_trade(self, trade_id: str) -> dict:
        return self._put(f"/v3/accounts/{self.account_id}/trades/{trade_id}/close")
