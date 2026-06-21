#!/usr/bin/env python3
"""Small local Qwen/Ollama fallback wrapper for the operator's Hermes box.

This intentionally avoids the full Hermes agent prompt/tool payload. The full
Hermes prompt can exceed Ollama's CPU/RAM budget on this VPS and OOM-kill the
service. Use this as a minimal local reasoning fallback when Codex/cloud is down.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen3:4b"


def read_prompt(args: argparse.Namespace) -> str:
    parts: list[str] = []
    if args.prompt:
        parts.append(args.prompt)
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            parts.append(f.read())
    if not sys.stdin.isatty():
        stdin = sys.stdin.read().strip()
        if stdin:
            parts.append(stdin)
    prompt = "\n\n".join(p.strip() for p in parts if p and p.strip()).strip()
    if not prompt:
        raise SystemExit("No prompt supplied. Use -p/--prompt, --file, or stdin.")
    return prompt


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal Ollama/Qwen local fallback wrapper")
    parser.add_argument("-p", "--prompt", help="Prompt text")
    parser.add_argument("--file", help="Read prompt from file")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--num-ctx", type=int, default=2048, help="Small context to avoid OOM")
    parser.add_argument("--num-predict", type=int, default=256, help="Output token cap")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()

    prompt = read_prompt(args)
    # Qwen3 defaults to hidden thinking; /no_think keeps this wrapper quick and cheap.
    if "/no_think" not in prompt[:100].lower():
        prompt = "/no_think\n" + prompt

    payload = {
        "model": args.model,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You are a concise local fallback assistant. Answer directly. Do not use tools."},
            {"role": "user", "content": prompt},
        ],
        "options": {
            "num_ctx": args.num_ctx,
            "num_predict": args.num_predict,
            "temperature": args.temperature,
        },
    }
    req = urllib.request.Request(
        args.url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"qwen-lite error: {exc}", file=sys.stderr)
        return 2

    msg = (data.get("message") or {}).get("content") or data.get("response") or ""
    print(msg.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
