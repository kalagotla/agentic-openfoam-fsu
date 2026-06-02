"""Shared automation-level gate policy.

``automation_level`` (1–5, declared in a scenario YAML) is otherwise an
honor-system instruction — nothing forces the agent to pause. This module
turns it into an enforceable decision that two callers share:

- ``.claude/hooks/automation_gate_hook.py`` — a Claude Code PreToolUse
  hook that emits ``permissionDecision: "ask"`` so Claude Code prompts
  the researcher before a gated step.
- ``scripts/run_agent.py`` — the bring-your-own-agent harness, which
  prompts the operator on stdin before dispatching a gated tool.

The level → gate mapping (matches the table in CLAUDE.md). It keys off
both the tool name and, for ``record_step``, its ``phase`` field — so the
pause lands at the phase the level cares about:

    1 Consult  → ask before every state-changing tool (before each phase)
                 AND on every record_step (after each phase)
    2 Review   → ask before every state-changing tool, plus on the        (default)
                 validation record_step (so the verdict is reviewed)
    3 Validate → ask only on the validation record_step
    4 Notify   → no gate (stop-on-failure stays a prompt-side rule)
    5 Auto     → no gate

Stdlib only — the hook must run without the project's venv.
"""

from __future__ import annotations

import re
from pathlib import Path

# State-changing "phase" tools. Gating these forces a pause before each
# phase actually mutates the case (mesh, solve, decomposition).
GATED_ACTION_TOOLS = frozenset(
    {
        "run_blockmesh",
        "run_snappy_hex_mesh",
        "check_mesh",
        "run_solver",
        "decompose_par",
        "reconstruct_par",
        # run_analysis executes an agent-authored Python script — gate it like
        # any other state-changing phase so the researcher approves running it.
        "run_analysis",
    }
)

_AUTOMATION_RE = re.compile(r"^\s*automation_level\s*:\s*(\d+)", re.MULTILINE)
_DEFAULT_LEVEL = 2


def raw_tool_name(tool_name: str) -> str:
    """Strip any server prefix: ``mcp__openfoam__run_solver`` → ``run_solver``.

    Handles both the Claude Code namespacing (``mcp__<server>__<tool>``)
    and the harness namespacing (``<server>__<tool>``).
    """
    return tool_name.rsplit("__", 1)[-1] if "__" in tool_name else tool_name


def _scenario_yaml_for(case_path: str) -> Path | None:
    """Locate ``cases/scenarios/<case-dir-name>.yaml`` for a work case.

    By convention a case lives at ``<repo>/cases/work/<scenario-name>/``,
    so the scenario file is ``<repo>/cases/scenarios/<scenario-name>.yaml``.
    Walks up from the (possibly relative) case path to find the repo root.
    """
    p = Path(case_path)
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    name = p.name
    for ancestor in (p, *p.parents):
        candidate = ancestor / "cases" / "scenarios" / f"{name}.yaml"
        if candidate.is_file():
            return candidate
    return None


def read_automation_level(case_path: str) -> int | None:
    """Return the scenario's ``automation_level``, or None if undeterminable.

    Returns the declared integer, ``2`` when the scenario file exists but
    omits the key, or ``None`` when no scenario file can be located (in
    which case the gate stays out of the way).
    """
    yaml_path = _scenario_yaml_for(case_path)
    if yaml_path is None:
        return None
    try:
        text = yaml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _AUTOMATION_RE.search(text)
    return int(m.group(1)) if m else _DEFAULT_LEVEL


def gate_decision(tool_name: str, tool_input: dict | None) -> tuple[str, str]:
    """Decide whether a tool call should pause for researcher approval.

    Returns ``(decision, reason)`` where ``decision`` is ``"ask"`` (force
    an approval prompt) or ``"allow"`` (proceed normally). ``reason`` is a
    short human-readable explanation shown in the prompt.
    """
    raw = raw_tool_name(tool_name)
    is_record = raw == "record_step"
    if raw not in GATED_ACTION_TOOLS and not is_record:
        return ("allow", "")

    info = tool_input or {}
    case_path = info.get("case_path")
    if not case_path:
        return ("allow", "no case_path on the call")

    level = read_automation_level(case_path)
    if level is None:
        return ("allow", "no scenario file — automation_level undetermined")
    if level >= 4:
        return ("allow", f"automation_level {level}: runs unattended")

    is_validation = is_record and "validation" in str(info.get("phase", "")).lower()

    if level == 3:
        if is_validation:
            return ("ask", "automation_level 3 (Validate): approve the validation outcome")
        return ("allow", "automation_level 3: phases run through; only validation pauses")

    # Levels 1 and 2: pause before every state-changing phase.
    if raw in GATED_ACTION_TOOLS:
        return (
            "ask",
            f"automation_level {level}: approve the {raw} step before it runs",
        )
    if is_record:
        if level == 1:
            return ("ask", "automation_level 1 (Consult): approve this narrated step")
        if level == 2 and is_validation:
            return ("ask", "automation_level 2 (Review): approve the validation outcome")
    return ("allow", "")
