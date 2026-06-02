"""Tests for the shared automation-level gate policy.

Run with: ``uv run pytest scripts/test_automation_gate.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from automation_gate import (  # noqa: E402
    gate_decision,
    raw_tool_name,
    read_automation_level,
)


def _make_case(tmp_path: Path, *, level: int | None, scenario: bool = True) -> str:
    """Build a tmp repo with cases/scenarios/<name>.yaml + cases/work/<name>.

    ``level=None`` writes a scenario YAML without an automation_level key;
    ``scenario=False`` writes no scenario file at all.
    """
    (tmp_path / "cases" / "scenarios").mkdir(parents=True)
    case = tmp_path / "cases" / "work" / "demo"
    case.mkdir(parents=True)
    if scenario:
        body = "name: demo\n"
        if level is not None:
            body += f"automation_level: {level}\n"
        (tmp_path / "cases" / "scenarios" / "demo.yaml").write_text(body)
    return str(case)


class TestRawToolName:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("mcp__openfoam__run_solver", "run_solver"),
            ("openfoam__run_solver", "run_solver"),
            ("run_solver", "run_solver"),
            ("mcp__openfoam__record_step", "record_step"),
        ],
    )
    def test_strips_prefix(self, name: str, expected: str) -> None:
        assert raw_tool_name(name) == expected


class TestReadAutomationLevel:
    def test_reads_declared_level(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=3)
        assert read_automation_level(case) == 3

    def test_defaults_to_2_when_key_absent(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=None)
        assert read_automation_level(case) == 2

    def test_none_when_no_scenario(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=None, scenario=False)
        assert read_automation_level(case) is None


class TestGateDecision:
    def _ask(self, decision: tuple[str, str]) -> bool:
        return decision[0] == "ask"

    def test_level_2_gates_action_tools(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=2)
        for tool in [
            "mcp__openfoam__run_blockmesh",
            "mcp__openfoam__check_mesh",
            "mcp__openfoam__run_solver",
            "openfoam__decompose_par",
            "mcp__validation__run_analysis",  # executes agent-authored code
        ]:
            assert self._ask(gate_decision(tool, {"case_path": case})), tool

    def test_run_analysis_gated_at_1_2_but_not_3_4_5(self, tmp_path: Path) -> None:
        # run_analysis is a phase tool: gated before it runs at levels 1-2,
        # left alone at 3+ (level 3 pauses at the validation report instead).
        for level in (1, 2):
            case = _make_case(tmp_path / f"l{level}", level=level)
            assert self._ask(
                gate_decision("mcp__validation__run_analysis", {"case_path": case})
            )
        for level in (3, 4, 5):
            case = _make_case(tmp_path / f"l{level}", level=level)
            assert not self._ask(
                gate_decision("mcp__validation__run_analysis", {"case_path": case})
            )

    def test_level_2_allows_nonvalidation_record_step(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=2)
        assert not self._ask(
            gate_decision(
                "mcp__openfoam__record_step",
                {"case_path": case, "phase": "mesh"},
            )
        )

    def test_level_2_gates_validation_record_step(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=2)
        assert self._ask(
            gate_decision(
                "mcp__openfoam__record_step",
                {"case_path": case, "phase": "validation"},
            )
        )

    def test_level_1_gates_every_record_step(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=1)
        assert self._ask(
            gate_decision(
                "mcp__openfoam__record_step",
                {"case_path": case, "phase": "geometry"},
            )
        )
        assert self._ask(
            gate_decision("mcp__openfoam__run_solver", {"case_path": case})
        )

    def test_level_3_gates_only_validation_step(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=3)
        # Phases run through untouched...
        assert not self._ask(
            gate_decision("mcp__openfoam__run_solver", {"case_path": case})
        )
        assert not self._ask(
            gate_decision("mcp__openfoam__check_mesh", {"case_path": case})
        )
        assert not self._ask(
            gate_decision(
                "mcp__openfoam__record_step",
                {"case_path": case, "phase": "mesh"},
            )
        )
        # ...but the validation report pauses.
        assert self._ask(
            gate_decision(
                "mcp__openfoam__record_step",
                {"case_path": case, "phase": "validation"},
            )
        )

    @pytest.mark.parametrize("level", [4, 5])
    def test_levels_4_5_never_gate(self, tmp_path: Path, level: int) -> None:
        case = _make_case(tmp_path, level=level)
        assert not self._ask(
            gate_decision("mcp__openfoam__run_solver", {"case_path": case})
        )

    def test_non_gated_tool_always_allowed(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=1)
        # list_tutorials / write_dict are never phase-gates.
        assert not self._ask(
            gate_decision("mcp__openfoam__write_dict", {"case_path": case})
        )
        assert not self._ask(
            gate_decision("mcp__openfoam__list_tutorials", {})
        )

    def test_no_scenario_allows(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=None, scenario=False)
        assert not self._ask(
            gate_decision("mcp__openfoam__run_solver", {"case_path": case})
        )

    def test_missing_case_path_allows(self, tmp_path: Path) -> None:
        assert not self._ask(gate_decision("mcp__openfoam__run_solver", {}))

    def test_default_level_2_gates_when_key_absent(self, tmp_path: Path) -> None:
        case = _make_case(tmp_path, level=None)  # scenario file, no key → 2
        assert self._ask(
            gate_decision("mcp__openfoam__run_solver", {"case_path": case})
        )
