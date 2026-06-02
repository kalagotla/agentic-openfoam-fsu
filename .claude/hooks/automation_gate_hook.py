#!/usr/bin/env python3
"""Claude Code PreToolUse hook enforcing the scenario's automation_level.

Reads the tool call on stdin, asks the shared policy in
``scripts/automation_gate.py`` whether the step should pause, and emits
``permissionDecision: "ask"`` for gated steps so Claude Code prompts the
researcher to approve before the tool runs. Non-gated steps produce no
output, so Claude Code's normal permission flow is untouched.

Registered in ``.claude/settings.json`` for the openfoam phase tools.
Stdlib only — runs without the project venv.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

try:
    from automation_gate import gate_decision
except Exception:
    # Never block tool use because the gate failed to import.
    sys.exit(0)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}

    try:
        decision, reason = gate_decision(tool_name, tool_input)
    except Exception:
        sys.exit(0)

    if decision == "ask":
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "ask",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
