#!/usr/bin/env python3
"""Whoop awake detector + Notion health-log upsert.

Intended cron window: every 15 minutes from 03:00 through 10:00 Europe/London.
- Detects the operator is awake when latest non-nap sleep is SCORED and ended recently.
- Runs once per local day unless --force is passed.
- Refreshes Whoop tokens correctly: no redirect_uri/scope on refresh, stores new refresh token.
- Upserts the Whoop Health Log row in Notion using API 2025-09-03.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


class WhoopTransientError(RuntimeError):
    """Raised when Whoop returns a 5xx — treat as retry-later, not fatal."""

ENV_PATH = Path.home() / ".hermes" / ".env"
STATE_DIR = Path.home() / ".hermes" / "state"
STATE_PATH = STATE_DIR / "whoop_awake_sync.json"
LOCK_PATH = STATE_DIR / "whoop_awake_sync.lock"

WHOOP_BASE = "https://api.prod.whoop.com/developer/v2"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
TZ = ZoneInfo("Europe/London")

EARLIEST_HOUR = 3
LATEST_HOUR = 10  # inclusive only at exactly 10:00; script gates < 10:15
AWAKE_WINDOW_HOURS = 3.0


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        raise RuntimeError(f"Missing env file: {path}")
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def replace_env_value(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    replacement = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(replacement, text)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + replacement + "\n"


def update_env_tokens(access_token: str, refresh_token: str | None) -> None:
    text = ENV_PATH.read_text()
    text = replace_env_value(text, "WHOOP_ACCESS_TOKEN", access_token)
    if refresh_token:
        text = replace_env_value(text, "WHOOP_REFRESH_TOKEN", refresh_token)
    ENV_PATH.write_text(text)


def required(env: dict[str, str], key: str) -> str:
    value = env.get(key)
    if not value:
        raise RuntimeError(f"Missing required env var: {key}")
    return value


def whoop_headers(env: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {required(env, 'WHOOP_ACCESS_TOKEN')}"}


def notion_headers(env: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {required(env, 'NOTION_API_KEY')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def refresh_whoop_token(env: dict[str, str]) -> bool:
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": required(env, "WHOOP_REFRESH_TOKEN"),
        "client_id": required(env, "WHOOP_CLIENT_ID"),
        "client_secret": required(env, "WHOOP_CLIENT_SECRET"),
    }
    response = requests.post(WHOOP_TOKEN_URL, data=payload, timeout=20)
    if response.status_code >= 500:
        raise WhoopTransientError(f"Whoop token refresh transient {response.status_code}")
    if response.status_code != 200:
        raise RuntimeError(f"Whoop token refresh failed ({response.status_code}): {response.text[:500]}")

    data = response.json()
    access = data["access_token"]
    refresh = data.get("refresh_token")
    env["WHOOP_ACCESS_TOKEN"] = access
    if refresh:
        env["WHOOP_REFRESH_TOKEN"] = refresh
    update_env_tokens(access, refresh)
    print("✓ Whoop token refreshed")
    return True


def whoop_get(env: dict[str, str], path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{WHOOP_BASE}{path}"
    response = requests.get(url, headers=whoop_headers(env), params=params, timeout=25)
    if response.status_code == 401:
        refresh_whoop_token(env)
        response = requests.get(url, headers=whoop_headers(env), params=params, timeout=25)
    if response.status_code != 200:
        raise RuntimeError(f"Whoop {path} failed ({response.status_code}): {response.text[:500]}")
    return response.json()


def latest_main_sleep(env: dict[str, str]) -> dict[str, Any] | None:
    data = whoop_get(env, "/activity/sleep", {"limit": 5})
    records = [r for r in data.get("records", []) if not r.get("nap")]
    return records[0] if records else None


def detect_awake(env: dict[str, str], now: datetime) -> tuple[bool, str, dict[str, Any] | None]:
    sleep = latest_main_sleep(env)
    if not sleep:
        return False, "no main sleep record returned", None

    score_state = sleep.get("score_state")
    end_raw = sleep.get("end")
    if score_state != "SCORED":
        return False, f"latest sleep not scored yet ({score_state})", sleep
    if not end_raw:
        return False, "latest sleep has no end timestamp", sleep

    end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
    hours_since = (now.astimezone(timezone.utc) - end_dt).total_seconds() / 3600
    if 0 <= hours_since <= AWAKE_WINDOW_HOURS:
        return True, f"latest scored sleep ended {hours_since:.2f}h ago", sleep
    return False, f"latest scored sleep ended {hours_since:.2f}h ago; outside {AWAKE_WINDOW_HOURS:.0f}h awake window", sleep


def recovery_zone(score: float) -> str:
    if score >= 67:
        return "🟢 Green"
    if score >= 34:
        return "🟡 Yellow"
    return "🔴 Red"


def notion_number(value: Any) -> dict[str, Any]:
    if value is None:
        return {"number": None}
    try:
        return {"number": round(float(value), 2)}
    except (TypeError, ValueError):
        return {"number": None}


def millis_to_minutes(ms: Any) -> float:
    return round(float(ms or 0) / 60000, 1)


def millis_to_hours(ms: Any) -> float:
    return round(float(ms or 0) / 3600000, 2)


def notion_get(env: dict[str, str], endpoint: str) -> requests.Response:
    return requests.get(f"{NOTION_BASE}{endpoint}", headers=notion_headers(env), timeout=25)


def resolve_notion_ids(env: dict[str, str]) -> tuple[str, str]:
    """Return (database_id, data_source_id). WHOOP_NOTION_DB_ID may be either."""
    configured = required(env, "WHOOP_NOTION_DB_ID")

    db_response = notion_get(env, f"/databases/{configured}")
    if db_response.status_code == 200:
        body = db_response.json()
        sources = body.get("data_sources") or []
        data_source_id = sources[0]["id"] if sources else configured
        return configured, data_source_id

    ds_response = notion_get(env, f"/data_sources/{configured}")
    if ds_response.status_code == 200:
        body = ds_response.json()
        parent = body.get("parent") or {}
        database_id = parent.get("database_id") or configured
        return database_id, configured

    raise RuntimeError(
        f"Could not resolve WHOOP_NOTION_DB_ID as database ({db_response.status_code}) "
        f"or data source ({ds_response.status_code})"
    )


def query_existing_page(env: dict[str, str], data_source_id: str, date_str: str) -> str | None:
    payload = {"filter": {"property": "Date", "date": {"equals": date_str}}, "page_size": 1}
    response = requests.post(
        f"{NOTION_BASE}/data_sources/{data_source_id}/query",
        headers=notion_headers(env),
        json=payload,
        timeout=25,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Notion query failed ({response.status_code}): {response.text[:500]}")
    results = response.json().get("results", [])
    return results[0]["id"] if results else None


def get_whoop_summary(env: dict[str, str]) -> tuple[str, dict[str, Any]]:
    recovery_records = whoop_get(env, "/recovery", {"limit": 1}).get("records", [])
    if not recovery_records:
        raise RuntimeError("No Whoop recovery record available yet")
    recovery = recovery_records[0]
    sleep = latest_main_sleep(env)
    try:
        cycle_records = whoop_get(env, "/cycle", {"limit": 1}).get("records", [])
        cycle = cycle_records[0] if cycle_records else None
    except RuntimeError as exc:
        # Cycle/strain scope can fail independently of recovery/sleep. Don't let that
        # block the actual wake-triggered health log upsert.
        print(f"⚠ Cycle data unavailable; writing strain/calories as 0 ({exc})")
        cycle = None

    score = recovery.get("score") or {}
    recovery_pct = score.get("recovery_score") or 0
    date_str = (recovery.get("created_at") or datetime.now(TZ).date().isoformat())[:10]

    sleep_hours = sleep_perf = deep_sleep = rem_sleep = 0
    if sleep and sleep.get("score"):
        stage = (sleep["score"] or {}).get("stage_summary") or {}
        sleep_hours = millis_to_hours((stage.get("total_in_bed_time_milli") or 0) - (stage.get("total_awake_time_milli") or 0))
        sleep_perf = (sleep["score"] or {}).get("sleep_performance_percentage") or 0
        deep_sleep = millis_to_minutes(stage.get("total_slow_wave_sleep_time_milli"))
        rem_sleep = millis_to_minutes(stage.get("total_rem_sleep_time_milli"))

    cycle_score = (cycle or {}).get("score") or {}
    props = {
        "Date": {"date": {"start": date_str}},
        "Recovery Score": notion_number(recovery_pct),
        "HRV (ms)": notion_number(score.get("hrv_rmssd_milli")),
        "Resting HR": notion_number(score.get("resting_heart_rate")),
        "Sleep Duration": notion_number(sleep_hours),
        "Sleep Performance": notion_number(sleep_perf),
        "Deep Sleep (min)": notion_number(deep_sleep),
        "REM Sleep (min)": notion_number(rem_sleep),
        "Strain": notion_number(cycle_score.get("strain") or 0),
        "Calories (kJ)": notion_number(cycle_score.get("kilojoule") or 0),
        "SpO2 (%)": notion_number(score.get("spo2_percentage")),
        "Recovery Zone": {"select": {"name": recovery_zone(float(recovery_pct or 0))}},
    }
    return date_str, props


def upsert_health_log(env: dict[str, str], dry_run: bool = False) -> tuple[str, str]:
    database_id, data_source_id = resolve_notion_ids(env)
    date_str, props = get_whoop_summary(env)
    existing_id = query_existing_page(env, data_source_id, date_str)

    properties = {"Notes": {"title": [{"text": {"content": f"Whoop — {date_str}"}}]}, **props}
    if dry_run:
        action = "would update" if existing_id else "would create"
        return date_str, action

    if existing_id:
        response = requests.patch(
            f"{NOTION_BASE}/pages/{existing_id}",
            headers=notion_headers(env),
            json={"properties": properties},
            timeout=25,
        )
        action = "updated"
    else:
        response = requests.post(
            f"{NOTION_BASE}/pages",
            headers=notion_headers(env),
            json={"parent": {"database_id": database_id}, "properties": properties},
            timeout=25,
        )
        action = "created"

    if response.status_code not in (200, 201):
        raise RuntimeError(f"Notion upsert failed ({response.status_code}): {response.text[:500]}")
    return date_str, action


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def in_window(now: datetime) -> bool:
    local = now.astimezone(TZ)
    if EARLIEST_HOUR <= local.hour < LATEST_HOUR:
        return True
    return local.hour == LATEST_HOUR and local.minute == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Run Notion sync regardless of awake detection/state")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and decide, but do not write Notion/state")
    parser.add_argument("--ignore-window", action="store_true", help="Do not enforce 03:00-10:00 local window")
    args = parser.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Stale-lock recovery: if the lock file exists, is older than 10 minutes, and
    # no process currently holds the fcntl lock, remove it before re-opening.
    try:
        if LOCK_PATH.exists() and (time.time() - LOCK_PATH.stat().st_mtime) > 600:
            with LOCK_PATH.open("r+") as probe:
                try:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                    LOCK_PATH.unlink(missing_ok=True)
                    print("Removed stale lock file")
                except BlockingIOError:
                    pass
    except OSError:
        pass

    with LOCK_PATH.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        now = datetime.now(TZ)
        today = now.date().isoformat()
        if not args.force and not args.ignore_window and not in_window(now):
            print(f"Outside wake-check window at {now:%H:%M}; no action")
            return 0

        state = load_state()
        env = load_env()
        awake, reason, sleep = detect_awake(env, now)
        print(f"Wake check: {'awake' if awake else 'not awake'} — {reason}")

        latest_sleep_date = None
        if sleep and sleep.get("end"):
            try:
                latest_sleep_date = datetime.fromisoformat(sleep["end"].replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
            except (TypeError, ValueError):
                latest_sleep_date = None

        # De-duplicate by the Whoop sleep/recovery day, not by local calendar day.
        # The 8am briefing may force a stale yesterday row before Whoop has scored
        # today's sleep; if we mark the local day as "done" at that point, the later
        # real wake sync gets blocked. That's Patty and Selma guarding the wrong door.
        if not args.force:
            if latest_sleep_date and state.get("last_whoop_date") == latest_sleep_date:
                print(f"Already synced Whoop sleep date {latest_sleep_date}; no action")
                return 0
            if not latest_sleep_date and state.get("last_triggered_date") == today:
                print(f"Already triggered for {today}; no action")
                return 0

        if not awake and not args.force:
            return 0

        date_str, action = upsert_health_log(env, dry_run=args.dry_run)
        print(f"✓ Notion Health Log {action} for {date_str}")
        if not args.dry_run:
            state["last_triggered_date"] = date_str
            state["last_triggered_at"] = now.isoformat()
            state["last_whoop_date"] = date_str
            save_state(state)
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BlockingIOError:
        print("Another whoop_awake_sync run is already active; exiting")
        raise SystemExit(0)
    except WhoopTransientError as exc:
        print(f"Whoop transient error, will retry next cron tick: {exc}")
        raise SystemExit(0)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
