"""SQLite state for QuantumFX: trades, daily anchors, heartbeat."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
STATE_DIR.mkdir(exist_ok=True)
DB = STATE_DIR / "quantumfx.sqlite3"
HEARTBEAT = STATE_DIR / "heartbeat.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    pair TEXT NOT NULL,
    action TEXT NOT NULL,          -- OPEN / CLOSE / SL_ATTACH / REJECTED
    units INTEGER,
    price REAL,
    oanda_trade_id TEXT,
    reason TEXT,
    z REAL,
    half_life REAL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    ts TEXT PRIMARY KEY,
    nav REAL,
    margin_used REAL,
    open_trades INTEGER
);
"""


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=10)
    c.executescript(SCHEMA)
    return c


def log_trade(pair: str, action: str, **kw) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO trades (ts,pair,action,units,price,oanda_trade_id,reason,z,half_life,detail)"
            " VALUES (datetime('now'),?,?,?,?,?,?,?,?,?)",
            (
                pair, action, kw.get("units"), kw.get("price"),
                str(kw.get("oanda_trade_id") or ""), kw.get("reason"),
                kw.get("z"), kw.get("half_life"),
                json.dumps(kw.get("detail", {}), default=str)[:2000],
            ),
        )


def set_meta(key: str, value) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO meta (key,value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


def get_meta(key: str, default=None):
    with conn() as c:
        row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def snapshot_equity(nav: float, margin_used: float, open_trades: int) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO equity (ts,nav,margin_used,open_trades)"
            " VALUES (datetime('now'),?,?,?)",
            (nav, margin_used, open_trades),
        )


def heartbeat(status: str, extra: dict | None = None) -> None:
    HEARTBEAT.write_text(
        json.dumps({"ts": time.time(), "status": status, **(extra or {})})
    )
