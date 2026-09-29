"""Tests for the subscription-billed backend.

Two things must not go wrong quietly. A run meant to draw on a
subscription must not be diverted onto API billing by a stray environment
variable — the failure is invisible until an invoice arrives. And a
transcript from Claude Code must reduce to the same ledger shape
`run_agent.py` produces, or runs from the two backends cannot be compared
on cost at all.
"""

from __future__ import annotations

import json

from run_matrix import (
    API_BILLING_VARS,
    CLAUDE_CLI_BACKENDS,
    Run,
    _claude_cli_command,
    parse_claude_stream,
)

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]


def a_run(backend: str = "claude-cli", model: str = "claude-sonnet-5") -> Run:
    return Run(
        case_key="lid-cavity",
        scenario="cases/scenarios/lid-cavity.yaml",
        model=model,
        backend=backend,
        corpus_state="seeded",
        repeat=1,
    )


def stream(*messages: dict) -> str:
    return "\n".join(json.dumps(m) for m in messages)


def assistant(*blocks: dict) -> dict:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def tool_use(name: str) -> dict:
    return {"type": "tool_use", "name": name, "input": {}}


def result(**kw) -> dict:
    base = {
        "type": "result",
        "subtype": "success",
        "num_turns": 12,
        "stop_reason": "end_turn",
        "session_id": "abc-123",
        "total_cost_usd": 0.42,
        "permission_denials": [],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 250,
            "cache_read_input_tokens": 9000,
            "cache_creation_input_tokens": 500,
        },
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------


def test_the_command_targets_headless_claude_code() -> None:
    cmd = _claude_cli_command(a_run(), REPO_ROOT, "do the thing", approve_gates=False)
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--output-format" in cmd and "stream-json" in cmd
    # The repo's own MCP wiring, not whatever the ambient session had.
    assert str(REPO_ROOT / ".mcp.json") in cmd


def test_api_key_variables_are_named_for_stripping() -> None:
    # Claude Code prefers an API key when one is present, so a shell that
    # sourced .env would bill the API on a subscription machine. The runner
    # removes these from the child environment.
    assert "ANTHROPIC_API_KEY" in API_BILLING_VARS
    assert "ANTHROPIC_AUTH_TOKEN" in API_BILLING_VARS


def test_backend_aliases_resolve() -> None:
    assert "claude-cli" in CLAUDE_CLI_BACKENDS
    assert "claude-code" in CLAUDE_CLI_BACKENDS
    assert "anthropic" not in CLAUDE_CLI_BACKENDS


def test_gate_pre_approval_changes_the_permission_mode() -> None:
    gated = _claude_cli_command(a_run(), REPO_ROOT, "p", approve_gates=False)
    bypassed = _claude_cli_command(a_run(), REPO_ROOT, "p", approve_gates=True)
    # Without pre-approval the gate's "ask" decisions are left to be denied
    # and recorded, which is what keeps HITL compliance measurable.
    assert "acceptEdits" in gated
    assert "bypassPermissions" in bypassed


def test_a_model_is_only_passed_when_named() -> None:
    assert "--model" in _claude_cli_command(a_run(), REPO_ROOT, "p", False)
    assert "--model" not in _claude_cli_command(a_run(model=""), REPO_ROOT, "p", False)


# ---------------------------------------------------------------------------
# Transcript → ledger
# ---------------------------------------------------------------------------


def test_usage_and_turns_are_read_from_the_result() -> None:
    summary = parse_claude_stream(stream(result()))
    assert summary["iterations"] == 12
    assert summary["input_tokens"] == 100
    assert summary["output_tokens"] == 250
    assert summary["cache_read_tokens"] == 9000
    assert summary["cache_write_tokens"] == 500
    assert summary["stop_reason"] == "end_turn"
    assert summary["session_id"] == "abc-123"


def test_cost_is_labelled_an_equivalent_not_a_charge() -> None:
    summary = parse_claude_stream(stream(result()))
    # On a subscription nothing is billed per run; the figure is what the
    # same tokens would have cost through the API. Naming it "cost_usd"
    # would invite reading it as an invoice.
    assert summary["cost_usd_equivalent"] == 0.42
    assert "cost_usd" not in summary
    assert summary["billing"] == "subscription"


def test_tool_calls_are_counted_per_tool() -> None:
    summary = parse_claude_stream(
        stream(
            assistant(tool_use("mcp__openfoam__run_blockmesh")),
            assistant(tool_use("mcp__openfoam__check_mesh"), tool_use("mcp__openfoam__check_mesh")),
            result(),
        )
    )
    assert summary["tool_calls"] == 3
    assert summary["per_tool"]["mcp__openfoam__check_mesh"] == 2


def test_tool_errors_are_counted() -> None:
    summary = parse_claude_stream(
        stream(
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "is_error": True, "content": "boom"},
                        {"type": "tool_result", "content": "fine"},
                    ]
                },
            },
            result(),
        )
    )
    assert summary["tool_errors"] == 1


def test_permission_denials_are_carried_through() -> None:
    denial = {"tool_name": "mcp__openfoam__run_solver", "tool_use_id": "x"}
    summary = parse_claude_stream(stream(result(permission_denials=[denial])))
    # The automation gate denying a step is the signal hitl_compliance is
    # built on, so it has to survive into the record.
    assert summary["permission_denials"] == [denial]


def test_a_transcript_with_no_result_line_still_parses() -> None:
    # A killed or timed-out run leaves a truncated transcript. What it did
    # before dying is still evidence.
    summary = parse_claude_stream(stream(assistant(tool_use("mcp__openfoam__prepare_case"))))
    assert summary["tool_calls"] == 1
    assert summary["iterations"] is None
    assert summary["stop_reason"] is None


def test_non_json_noise_is_ignored() -> None:
    text = "warning: something\n" + stream(result()) + "\nnot json at all\n"
    assert parse_claude_stream(text)["iterations"] == 12


def test_the_ledger_shape_matches_the_other_backend() -> None:
    from run_agent import RunLedger

    other = RunLedger(backend="anthropic", model="m", prompt="p").to_dict()
    summary = parse_claude_stream(stream(result()))
    shared = {
        "iterations",
        "stop_reason",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "tool_calls",
        "tool_errors",
        "per_tool",
    }
    # Runs from the two backends are only comparable on cost if they report
    # the same fields.
    assert shared <= set(other)
    assert shared <= set(summary)


def test_a_system_message_carrying_a_string_does_not_break_parsing() -> None:
    # Claude Code emits `message` as a dict on assistant and user turns and
    # as a plain string on system notices — the automation gate's prompt is
    # one of those. Assuming the dict shape crashed the first real
    # subscription run after the agent had already finished its work.
    text = stream(
        {"type": "system", "message": "automation_level 3 (Validate): approve"},
        {"type": "rate_limit_event", "message": None},
        assistant(tool_use("mcp__openfoam__run_solver")),
        result(),
    )
    summary = parse_claude_stream(text)
    assert summary["tool_calls"] == 1
    assert summary["iterations"] == 12


def test_messages_with_unexpected_content_types_are_skipped() -> None:
    text = stream(
        {"type": "assistant", "message": {"content": "a bare string"}},
        {"type": "user", "message": {"content": [None, 7, "text"]}},
        result(),
    )
    # Whatever the transcript holds, the summary is still produced.
    assert parse_claude_stream(text)["tool_calls"] == 0


def test_the_gate_is_recorded_as_unbypassable_on_this_backend() -> None:
    # Verified on a real run: under bypassPermissions the automation gate
    # still stopped a level-3 scenario at its validation record_step,
    # because the gate is a PreToolUse hook and no permission mode
    # overrides it. A safety gate a flag could switch off would not be one.
    import inspect

    import run_matrix

    source = inspect.getsource(run_matrix._claude_cli_command)
    assert "does NOT override" in source


def test_ungated_settings_grant_the_servers_as_well_as_dropping_the_hook(
    tmp_path,
) -> None:
    import json as _json

    from run_matrix import write_ungated_settings

    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text(
        _json.dumps(
            {
                "permissions": {"allow": ["mcp__openfoam__write_dict"]},
                "hooks": {"PreToolUse": [{"matcher": "x"}]},
            }
        )
    )
    out = tmp_path / "run"
    out.mkdir()
    written = _json.loads(write_ungated_settings(repo, out).read_text())

    # Dropping the gate is not enough: a run denied prepare_case stops and
    # asks, exits zero, and authors nothing.
    assert "hooks" not in written
    allow = written["permissions"]["allow"]
    for server in ("openfoam", "validation", "consultant", "research_assistant"):
        assert f"mcp__{server}" in allow
    # The project's own entries survive.
    assert "mcp__openfoam__write_dict" in allow
