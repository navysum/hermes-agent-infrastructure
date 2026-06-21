#!/usr/bin/env bash
# Deterministic Notion block for the Morning Brief (health + tasks + projects).
# No Composio discovery — direct Notion API. See brief_notion.py.
exec /usr/local/lib/hermes-agent/venv/bin/python3 /root/.hermes/scripts/brief_notion.py
