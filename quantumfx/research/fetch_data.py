#!/usr/bin/env python3
"""Fetch multi-year OANDA candles (mid+bid+ask) for backtesting.

Paginates the v20 REST API from a start date to now, saves one parquet per
instrument+granularity under research/data/. Reads creds from the canonical
fx-live-bot .env (read-only usage).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ENV_PATH = Path("/root/fx-live-bot/.env")
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

PAIRS = [
    "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "NZD_USD", "USD_CAD",
    "USD_CHF", "EUR_JPY", "GBP_JPY", "EUR_GBP", "AUD_NZD", "EUR_CHF",
]

PLANS = [  # (granularity, from_date)
    ("H4", "2019-01-01"),
    ("H1", "2022-01-01"),
    ("D", "2016-01-01"),
]


def load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main() -> None:
    env = load_env()
    token = env["OANDA_API_KEY"]
    host = "https://api-fxtrade.oanda.com"
    ses = requests.Session()
    ses.headers.update({"Authorization": f"Bearer {token}"})

    for gran, start in PLANS:
        for pair in PAIRS:
            out = DATA_DIR / f"{pair}_{gran}.pkl"
            if out.exists():
                print(f"skip {out.name}")
                continue
            frm = f"{start}T00:00:00Z"
            rows = []
            while True:
                r = ses.get(
                    f"{host}/v3/instruments/{pair}/candles",
                    params={
                        "granularity": gran,
                        "from": frm,
                        "count": 5000,
                        "price": "MBA",
                    },
                    timeout=30,
                )
                r.raise_for_status()
                candles = r.json().get("candles", [])
                if not candles:
                    break
                for c in candles:
                    if not c["complete"]:
                        continue
                    rows.append(
                        {
                            "time": c["time"],
                            "open": float(c["mid"]["o"]),
                            "high": float(c["mid"]["h"]),
                            "low": float(c["mid"]["l"]),
                            "close": float(c["mid"]["c"]),
                            "bid_close": float(c["bid"]["c"]),
                            "ask_close": float(c["ask"]["c"]),
                            "volume": int(c["volume"]),
                        }
                    )
                last_time = candles[-1]["time"]
                if len(candles) < 5000 or last_time == frm:
                    break
                frm = last_time
                time.sleep(0.15)
            df = pd.DataFrame(rows)
            if df.empty:
                print(f"EMPTY {pair} {gran}")
                continue
            df["time"] = pd.to_datetime(df["time"])
            df = df.drop_duplicates("time").set_index("time").sort_index()
            df["spread"] = df["ask_close"] - df["bid_close"]
            df.to_pickle(out)
            print(
                f"{pair} {gran}: {len(df)} bars {df.index[0].date()} -> "
                f"{df.index[-1].date()} med_spread={df['spread'].median():.5f}"
            )

    print("DONE")


if __name__ == "__main__":
    now = datetime.now(timezone.utc).isoformat()
    print(f"fetch start {now}")
    sys.stdout.flush()
    main()
