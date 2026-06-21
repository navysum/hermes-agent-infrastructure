#!/usr/bin/env python3
"""Compatibility wrapper for Whoop → Notion Health Log sync.

The old version duplicated OAuth refresh logic and could race with
whoop_awake_sync.py. Whoop refresh tokens are single-use, so two scripts trying
to refresh around the same time can burn the token chain and force daily
re-auth. This wrapper routes manual/briefing syncs through the single locked
implementation in whoop_awake_sync.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path.home() / ".hermes" / "scripts" / "whoop_awake_sync.py"
PYTHON = sys.executable


def main() -> int:
    cmd = [PYTHON, str(SCRIPT), "--force", "--ignore-window"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
