"""Tests for Validation MCP tools.

Like the OpenFOAM tests, these exercise the tools directly without the
server — the server is a thin wiring layer on top of these functions.

Run with: ``uv run pytest servers/validation/tests``
"""

from __future__ import annotations

import math

import pytest
from validation_mcp.tools import (
    check_convergence,
    compare_profiles,
    compare_scalar,
    list_references,
    read_reference,
)


class TestListReferences:
    def test_discovers_shipped_references(self) -> None:
        """The repo ships at least the Armaly and Ghia references."""
        result = list_references()
        assert result["success"] is True
        names = {r["name"] for r in result["references"]}
        # Armaly's reattachment-length JSON and Ghia's centerline-profile JSON.
        assert "reattachment_length" in names
        assert "ghia_1982" in names


class TestReadReference:
    def test_reads_armaly_reattachment(self) -> None:
        result = read_reference("reattachment_length")
        assert result["success"] is True
        assert result["case"] == "pitz-daily"
        # Schema-level sanity check on the JSON shape.
        assert result["data"]["quantity"] == "reattachment_length"

    def test_reads_ghia_1982(self) -> None:
        result = read_reference("ghia_1982")
        assert result["success"] is True
        assert result["case"] == "lid-cavity"
        assert "ghia_re_400_u_centerline" in result["data"]["datasets"]

    def test_unknown_name_returns_structured_error(self) -> None:
        result = read_reference("does-not-exist")
        assert result["success"] is False
        assert "available" in result
        assert "does-not-exist" in result["reason"]

    def test_malformed_json_raises_typed_error(self, tmp_path) -> None:
        from validation_mcp.reference_data import (
            MalformedReferenceError,
            read_reference_json,
        )

        d = tmp_path / "cases" / "lid-cavity" / "reference"
        d.mkdir(parents=True)
        (d / "ghia_1982.json").write_text("{not valid json", encoding="utf-8")
        with pytest.raises(MalformedReferenceError):
            read_reference_json("ghia_1982", cases_dir=tmp_path / "cases")

    def test_read_reference_returns_structured_error_on_malformed(self, monkeypatch) -> None:
        # The MCP tool must never raise — a malformed file becomes a structured
        # failure the agent can recover from (the module's never-raise contract).
        from validation_mcp import tools as vt
        from validation_mcp.reference_data import MalformedReferenceError

        def boom(name: str):
            raise MalformedReferenceError("bad json")

        monkeypatch.setattr(vt, "read_reference_json", boom)
        r = vt.read_reference("ghia_1982")
        assert r["success"] is False
        assert r["reason"] == "malformed_reference_json"
        assert "bad json" in r["detail"]


class TestReferenceDiscoveryScoping:
    def _make_ref(self, base, case_subpath: str, name: str = "ghia_1982"):
        d = base / "cases" / case_subpath / "reference"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.json").write_text('{"ok": true}', encoding="utf-8")

    def test_canonical_reference_is_discovered(self, tmp_path) -> None:
        from validation_mcp.reference_data import discover_references

        self._make_ref(tmp_path, "lid-cavity")
        names = {e.name for e in discover_references(tmp_path / "cases")}
        assert "ghia_1982" in names

    def test_work_and_baseline_copies_are_skipped(self, tmp_path) -> None:
        # A reference/ dir inside cases/work/ or under a baseline/ archive must
        # not shadow or collide with the canonical dataset (else resolve raises
        # "ambiguous across cases").
        from validation_mcp.reference_data import (
            discover_references,
            resolve_reference,
        )

        self._make_ref(tmp_path, "lid-cavity")             # canonical
        self._make_ref(tmp_path, "work/lidcav-copy")       # in-progress copy
        self._make_ref(tmp_path, "examples/foo/baseline")  # archived copy
        cases = tmp_path / "cases"
        assert sorted({e.case for e in discover_references(cases)}) == ["lid-cavity"]
        assert resolve_reference("ghia_1982", cases).case == "lid-cavity"


class TestCompareProfiles:
    """compare_profiles takes raw arrays; no reference-registry plumbing."""

    def test_perfect_match_returns_zero_error(self) -> None:
        result = compare_profiles(
            sim_axis=[-1.0, -0.5, 0.0, 0.5, 1.0],
            sim_field=[0.0, 0.25, 0.5, 0.75, 1.0],
            ref_axis=[-1.0, -0.5, 0.0, 0.5, 1.0],
            ref_field=[0.0, 0.25, 0.5, 0.75, 1.0],
        )
        assert result["success"] is True
        assert result["l2_error"] == 0.0
        assert result["linf_error"] == 0.0
        assert result["within_tolerance"] is True

    def test_uniform_offset_picked_up(self) -> None:
        offset = 0.1
        result = compare_profiles(
            sim_axis=[-1.0, -0.5, 0.0, 0.5, 1.0],
            sim_field=[v + offset for v in [0.0, 0.25, 0.5, 0.75, 1.0]],
            ref_axis=[-1.0, -0.5, 0.0, 0.5, 1.0],
            ref_field=[0.0, 0.25, 0.5, 0.75, 1.0],
        )
        assert result["success"] is True
        assert math.isclose(result["l2_error"], offset, abs_tol=1e-9)
        assert math.isclose(result["linf_error"], offset, abs_tol=1e-9)

    def test_nan_in_simulation_is_a_structured_error(self) -> None:
        result = compare_profiles(
            sim_axis=[-1.0, 0.0, 1.0],
            sim_field=[0.0, float("nan"), 1.0],
            ref_axis=[-1.0, 0.0, 1.0],
            ref_field=[0.0, 0.5, 1.0],
        )
        assert result["success"] is False
        assert result["reason"] == "nan_or_inf_in_simulation"

    def test_no_axis_overlap_returns_failure(self) -> None:
        """Sim and ref ranges don't overlap → can't interpolate."""
        result = compare_profiles(
            sim_axis=[0.0, 1.0],
            sim_field=[0.0, 1.0],
            ref_axis=[2.0, 3.0],
            ref_field=[0.0, 1.0],
        )
        assert result["success"] is False
        assert result["reason"] == "no_overlap_in_axis"

    def test_explicit_tolerance_is_respected(self) -> None:
        """Caller can specify their own absolute L2 threshold."""
        # L2 = 0.1 exactly (uniform offset); declare 0.05 threshold → fail.
        result = compare_profiles(
            sim_axis=[0.0, 0.5, 1.0],
            sim_field=[0.1, 0.6, 1.1],
            ref_axis=[0.0, 0.5, 1.0],
            ref_field=[0.0, 0.5, 1.0],
            tolerance=0.05,
        )
        assert result["success"] is True
        assert math.isclose(result["l2_error"], 0.1, abs_tol=1e-9)
        assert result["tolerance_threshold"] == 0.05
        assert result["within_tolerance"] is False


class TestCompareScalar:
    """Single-coefficient comparison — the case compare_profiles rejects."""

    def test_naca_cl_within_relative_band(self) -> None:
        # The exact case compare_profiles rejects as too_few_points: one Cl
        # vs an XFOIL value. rel_error ~0.14% << 5% -> pass, on tested code.
        result = compare_scalar(1.06, 1.0585)
        assert result["success"] is True
        assert result["tolerance_basis"] == "relative"
        assert result["rel_error"] < 0.05
        assert result["within_tolerance"] is True

    def test_relative_error_over_band_fails(self) -> None:
        result = compare_scalar(1.06, 1.0, tolerance_relative=0.05)
        assert result["success"] is True
        assert math.isclose(result["rel_error"], 0.06, abs_tol=1e-9)
        assert result["within_tolerance"] is False

    def test_absolute_tolerance_takes_precedence(self) -> None:
        result = compare_scalar(6.0, 5.0, tolerance_absolute=1.5)
        assert result["success"] is True
        assert result["tolerance_basis"] == "absolute"
        assert result["abs_error"] == 1.0
        assert result["within_tolerance"] is True

    def test_reference_near_zero_refuses_relative(self) -> None:
        # A relative error is undefined against ~0; refuse rather than misgrade.
        result = compare_scalar(0.01, 0.0)
        assert result["success"] is False
        assert result["reason"] == "reference_near_zero"

    def test_reference_zero_with_absolute_tolerance_ok(self) -> None:
        result = compare_scalar(0.01, 0.0, tolerance_absolute=0.05)
        assert result["success"] is True
        assert result["within_tolerance"] is True
        assert result["rel_error"] is None

    def test_nan_input_is_structured_error(self) -> None:
        result = compare_scalar(float("nan"), 1.0)
        assert result["success"] is False
        assert result["reason"] == "nan_or_inf_input"


class TestCheckConvergence:
    def test_all_converged(self) -> None:
        """A clean exponential decay below threshold reports converged."""
        residuals = {
            "Ux": [1.0, 0.1, 0.01, 0.001, 1e-5],
            "p": [1.0, 0.5, 0.1, 0.01, 1e-5],
        }
        result = check_convergence(residuals, threshold=1e-4)
        assert result["success"] is True
        assert result["status"] == "converged"
        assert result["per_field"] == {"Ux": "converged", "p": "converged"}

    def test_diverged_on_nan(self) -> None:
        residuals = {"Ux": [0.5, 0.4, float("nan"), 0.3]}
        result = check_convergence(residuals)
        assert result["success"] is True
        assert result["status"] == "diverged"
        assert result["per_field"]["Ux"] == "diverged"

    def test_diverged_on_blowup(self) -> None:
        """Latest residual >100x initial → diverged."""
        residuals = {"Ux": [0.001, 0.01, 1.0, 10.0]}  # 0.001 -> 10.0 = 10000x
        result = check_convergence(residuals)
        assert result["success"] is True
        assert result["status"] == "diverged"

    def test_stalled_when_no_progress_in_window(self) -> None:
        """Flat residual plateau above threshold → stalled."""
        residuals = {
            "Ux": [1.0, 0.5, 0.1, 0.05] + [0.05] * 50,
        }
        result = check_convergence(residuals, threshold=1e-4, stall_window=20)
        assert result["success"] is True
        assert result["status"] == "stalled"
        assert "Ux" in result["recommendation"]

    def test_still_running_when_decreasing_above_threshold(self) -> None:
        """Monotonic decay still above threshold → still_running."""
        residuals = {"Ux": [1.0, 0.5, 0.1, 0.05, 0.01, 0.005]}
        result = check_convergence(residuals, threshold=1e-4, stall_window=3)
        assert result["success"] is True
        assert result["status"] == "still_running"

    def test_diverged_priority_over_stalled(self) -> None:
        """If any field diverged, overall is diverged even if others stall."""
        residuals = {
            "Ux": [1.0, 0.1, 0.05] + [0.05] * 50,            # stalled
            "epsilon": [1.0, 10.0, 100.0, 1e6],              # diverged
        }
        result = check_convergence(residuals, threshold=1e-4, stall_window=20)
        assert result["status"] == "diverged"
        assert "epsilon" in result["recommendation"]

    def test_empty_input_returns_failure(self) -> None:
        assert check_convergence({})["success"] is False
        assert check_convergence({"Ux": []})["success"] is False

    def test_invalid_threshold_returns_failure(self) -> None:
        result = check_convergence({"Ux": [1.0, 0.1]}, threshold=0)
        assert result["success"] is False
        assert result["reason"] == "threshold_must_be_positive"
