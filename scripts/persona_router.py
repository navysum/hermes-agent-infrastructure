#!/usr/local/lib/hermes-agent/venv/bin/python3
"""Hermes pre_llm_call hook: auto-select the best Simpson persona per question.

Reads the hook payload on stdin and, for real inbound user messages, emits a
``{"context": "..."}`` directive that steers the gateway agent (default Homer)
to answer as the right family member:

  * MARGE  — health / wellbeing questions
  * BART   — finding loopholes / edges / improvements in the trading strategy
  * HOMER  — everything else (default; no injection)

Routing is keyword-based (deterministic, no extra model call). It only fires on
interactive inbound messages (non-empty sender_id, platform != cron) so the
agentic crons (morning brief, nightly reflect) keep their own behaviour.

Contract: always exit 0. Print the JSON directive on stdout, or nothing.
"""
import json
import re
import sys


def _load():
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


# --- keyword vocab -----------------------------------------------------------
HEALTH = (
    "health", "wellbeing", "well-being", "sleep", "slept", "nap", "whoop",
    "recovery", "recover", "recovered", "strain", "hrv", "rhr", "resting heart",
    "heart rate", "workout", "work out", "exercise", "gym", "run", "running",
    "cardio", "lifting", "diet", "nutrition", "calorie", "calories", "macros",
    "hydrate", "hydration", "stress", "rest", "rested", "fatigue", "tired",
    "energy", "fitness", "steps", "weight", "injury", "injured", "sore",
    "sick", "illness", "ill ", "wellness", "meditat", "mental health", "mood",
    "burnout", "fasting",
)

# Bart = improving / exploiting the TRADING strategy. Needs a trading-scope term
# AND an improvement/flaw intent, OR an explicit edge/loophole word.
TRADING = (
    "trade", "trading", "forex", "fx", "oanda", "strategy", "strat", "signal",
    "backtest", "back-test", "pair", "position", "entry", "exit", "stop loss",
    "stop-loss", "take profit", "take-profit", "win rate", "winrate",
    "expectancy", "drawdown", "risk reward", "risk-reward", "rr ", " rr",
    "pip", "pips", "eur_usd", "eur/usd", "gbp_usd", "usd_jpy", "forexbot",
    "bot", "sharpe", "equity curve", "p&l", "pnl", "session", "spread",
)
IMPROVE = (
    "loophole", "edge", "exploit", "flaw", "weakness", "weak", "inefficien",
    "leak", "improve", "improvement", "better", "optimis", "optimiz", "sharpen",
    "tweak", "refine", "what's wrong", "whats wrong", "what is wrong",
    "underperform", "fix", "boost", "upgrade", "smarter", "more profit",
    "profitable", "find a way", "hole", "gap", "missing", "stronger",
)
EXPLICIT_EDGE = ("loophole", "edge", "exploit", "arbitrage", "inefficien")


def _has(text, terms):
    return any(t in text for t in terms)


MARGE = (
    "[PERSONA ROUTING -> respond as MARGE]\n"
    "This is a health / wellbeing question. Answer in Marge Simpson's caring, "
    "protective persona: warm, sensible, and focused on the operator's long-term "
    "wellbeing -- sleep, recovery, strain, HRV, training load and stress. "
    "Ground answers in his Whoop / Notion health data when relevant, and gently "
    "but firmly flag anything that puts his health at risk."
)

BART = (
    "[PERSONA ROUTING -> respond as BART]\n"
    "This is about finding loopholes, edges and improvements in the operator's trading. "
    "Answer in Bart Simpson's flaw-finder persona: sharp, irreverent, and "
    "relentless about poking holes. Hunt for weaknesses, inefficiencies and "
    "exploitable edges in the strategy and data. Be specific and quantitative -- "
    "give concrete, testable changes (params, filters, sizing, sessions, RR) "
    "over praise. Ground claims in live OANDA data via the operator-live-data-tools "
    "skill (oanda_trades.py) and the trading wiki. No sugar-coating."
)


def route(msg):
    t = " " + msg.lower() + " "
    if _has(t, TRADING) and _has(t, IMPROVE):
        return BART
    if _has(t, EXPLICIT_EDGE) and _has(t, TRADING):
        return BART
    if _has(t, HEALTH):
        return MARGE
    return None  # Homer default — no injection


def main():
    data = _load()
    extra = data.get("extra") or {}
    sender = str(extra.get("sender_id") or "").strip()
    platform = str(extra.get("platform") or "").strip().lower()
    msg = extra.get("user_message")
    if not isinstance(msg, str):
        msg = str(msg or "")

    # Only steer real interactive inbound messages; leave cron/agentic runs alone.
    if not sender or platform in ("", "cron", "local"):
        return
    if not msg.strip():
        return

    directive = route(msg)
    if directive:
        sys.stdout.write(json.dumps({"context": directive}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
