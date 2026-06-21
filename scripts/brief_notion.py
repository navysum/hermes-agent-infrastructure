#!/usr/local/lib/hermes-agent/venv/bin/python3
"""Deterministic Notion fetch for the Morning Brief.

Replaces the per-run Composio COMPOSIO_SEARCH_TOOLS discovery flow (slow + flaky)
with three direct Notion API calls. Prints a compact plain-text block the brief
agent injects verbatim into its HEALTH and TASKS sections.

Reads NOTION_API_KEY from /root/.hermes/.env. Every failure degrades to a single
"err:" line so the brief never hangs or breaks.
"""
import json
import os
import sys
import urllib.request
import urllib.error

ENV = "/root/.hermes/.env"
NV = "2022-06-28"
HEALTH_DB = "<UUID>"  # Whoop Heath Log
TODO_DB = "<UUID>"    # To-Do List
PROJ_DB = "<UUID>"    # Projects
TIMEOUT = 12


def _token():
    try:
        with open(ENV) as f:
            for line in f:
                if line.startswith("NOTION_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return os.environ.get("NOTION_API_KEY", "")


def _post(path, token, body):
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{path}",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NV,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _title(prop):
    parts = prop.get("title") or prop.get("rich_text") or []
    return "".join(p.get("plain_text", "") for p in parts).strip()


def _num(prop):
    return prop.get("number")


def _date(prop):
    d = prop.get("date") or {}
    return d.get("start")


def _sel(prop):
    s = prop.get("select") or {}
    return s.get("name")


def _status(prop):
    s = prop.get("status") or {}
    return s.get("name")


def health(token):
    out = ["HEALTH (latest Whoop Health Log):"]
    try:
        d = _post(f"databases/{HEALTH_DB}/query", token, {
            "sorts": [{"property": "Date", "direction": "descending"}],
            "page_size": 1,
        })
        res = d.get("results") or []
        if not res:
            out.append("- err: no Health Log entries")
            return out
        p = res[0]["properties"]
        date = _date(p.get("Date", {}))
        rec = _num(p.get("Recovery Score", {}))
        sleep = _num(p.get("Sleep Duration", {}))
        hrv = _num(p.get("HRV (ms)", {}))
        strain = _num(p.get("Strain", {}))
        rhr = _num(p.get("Resting HR", {}))
        zone = _sel(p.get("Recovery Zone", {}))
        mode = _sel(p.get("Daily Mode", {}))
        out.append(
            f"- {date or '?'}: Recovery {rec if rec is not None else '?'}% | "
            f"Sleep {sleep if sleep is not None else '?'}h | "
            f"HRV {hrv if hrv is not None else '?'} | "
            f"Strain {strain if strain is not None else '?'} | "
            f"RHR {rhr if rhr is not None else '?'}"
        )
        if zone or mode:
            out.append(f"- Zone {zone or '?'} | Mode {mode or '?'}")
    except urllib.error.HTTPError as e:
        out.append(f"- err: Notion HTTP {e.code}")
    except Exception as e:
        out.append(f"- err: {type(e).__name__}")
    return out


def tasks(token):
    out = ["TASKS (Notion To-Do, not done, by deadline):"]
    try:
        d = _post(f"databases/{TODO_DB}/query", token, {
            "filter": {"property": "Status", "status": {"does_not_equal": "Done"}},
            "sorts": [{"property": "Deadline", "direction": "ascending"}],
            "page_size": 10,
        })
        res = d.get("results") or []
        if not res:
            out.append("- Nothing. All good.")
        for p in res[:8]:
            pr = p["properties"]
            name = _title(pr.get("Name", {})) or "(untitled)"
            st = _status(pr.get("Status", {})) or "?"
            dl = _date(pr.get("Deadline", {}))
            out.append(f"- {name} [{st}]" + (f" due {dl}" if dl else ""))
    except urllib.error.HTTPError as e:
        out.append(f"- err: Notion HTTP {e.code}")
    except Exception as e:
        out.append(f"- err: {type(e).__name__}")
    return out


def projects(token):
    out = ["PROJECTS (in progress):"]
    try:
        d = _post(f"databases/{PROJ_DB}/query", token, {
            "filter": {"property": "Status", "status": {"equals": "In progress"}},
            "page_size": 8,
        })
        res = d.get("results") or []
        if not res:
            out.append("- none active")
        for p in res[:6]:
            pr = p["properties"]
            name = _title(pr.get("Name", {})) or "(untitled)"
            cat = _sel(pr.get("Select", {})) or ""
            out.append(f"- {name}" + (f" ({cat})" if cat else ""))
    except Exception:
        out.append("- err: projects query failed")
    return out


def main():
    token = _token()
    if not token:
        print("NOTION err: no NOTION_API_KEY")
        return
    lines = []
    lines += health(token)
    lines.append("")
    lines += tasks(token)
    lines.append("")
    lines += projects(token)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
