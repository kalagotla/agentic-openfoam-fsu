#!/usr/bin/env python3
"""Token use of a Kilo session, split by model (frontier vs local).

    python3 scripts/session-tokens.py              # the most recent session
    python3 scripts/session-tokens.py ses_abc...   # a given session
    python3 scripts/session-tokens.py A B          # compare two sessions

Follows the subagent sessions a session delegated to (cfd-orchestrator ->
cfd-worker), so an orchestrated run shows how much ran on the frontier
model and how much on the local one. "Processed" counts every input token
the model read (fresh + cached) plus its output: what a paid API bills for,
and what the free gateway's latency grows with.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict


def kilo(*args: str) -> str:
    return subprocess.run(["kilo", *args], capture_output=True, text=True, timeout=120).stdout


def export(session: str) -> dict:
    text = kilo("export", session)
    return json.loads(text[text.index("{"):]) if "{" in text else {}


def latest_session() -> str:
    ids = re.findall(r"ses_[A-Za-z0-9]+", kilo("session", "list"))
    if not ids:
        sys.exit("No Kilo sessions found.")
    return ids[0]


def usage(session: str, seen: set[str] | None = None) -> dict[str, dict[str, int]]:
    seen = seen if seen is not None else set()
    if session in seen:
        return {}
    seen.add(session)
    data = export(session)
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    children: list[str] = []
    for msg in data.get("messages", []):
        info = msg.get("info", {})
        tok = info.get("tokens")
        if info.get("role") == "assistant" and tok:
            model = f"{info.get('providerID', '?')}/{info.get('modelID', '?')}"
            t = totals[model]
            t["calls"] += 1
            t["input"] += tok.get("input", 0)
            t["cached"] += tok.get("cache", {}).get("read", 0)
            t["output"] += tok.get("output", 0)
        for part in msg.get("parts", []):
            out = json.dumps(part.get("state", {}).get("output", "")) if part.get("type") == "tool" else ""
            children += [c for c in re.findall(r"ses_[A-Za-z0-9]+", out) if c != session]
    for child in dict.fromkeys(children):
        for model, t in usage(child, seen).items():
            for k, v in t.items():
                totals[model][k] += v
    return totals


def show(session: str) -> int:
    totals = usage(session)
    print(f"Session {session}")
    grand = 0
    for model, t in sorted(totals.items(), key=lambda kv: -(kv[1]["input"] + kv[1]["cached"])):
        processed = t["input"] + t["cached"] + t["output"]
        grand += processed
        local = model.startswith("ollama/")
        print(f"  {model:55s} {t['calls']:4d} calls  {processed/1e6:7.2f} M tokens processed"
              f"  ({t['output']/1e3:.1f} k output){'  [local, free]' if local else ''}")
    frontier = sum(t["input"] + t["cached"] + t["output"] for m, t in totals.items() if not m.startswith("ollama/"))
    print(f"  frontier model total: {frontier/1e6:.2f} M tokens")
    return frontier


if __name__ == "__main__":
    ids = sys.argv[1:] or [latest_session()]
    results = [show(s) for s in ids]
    if len(results) == 2 and results[0] and results[1]:
        a, b = results
        print(f"\nThe second run used {100 * (1 - b / a):.0f}% fewer frontier tokens than the first."
              if b < a else f"\nThe second run used {100 * (b / a - 1):.0f}% more frontier tokens than the first.")
