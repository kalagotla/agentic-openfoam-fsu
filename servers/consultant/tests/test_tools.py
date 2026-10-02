"""Tests for the Consultant MCP server tools.

These tests don't touch OpenFOAM — they exercise the parsing,
threshold, and annotation-lookup logic with synthetic checkMesh logs
and a fixture annotation tree pointed at via AGENTIC_OPENFOAM_ROOT.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from consultant_mcp import annotations as ann_mod
from consultant_mcp import assessments as assessments_mod
from consultant_mcp.annotations import (
    AnnotationNotFoundError,
    annotation_path_for,
    read_annotation,
)
from consultant_mcp.assessments import (
    CITATION_SOURCES,
    aggregate_verdict,
    assess_aspect_ratio,
    assess_non_orthogonality,
    assess_residual_pattern,
    assess_severe_non_orthogonal,
    assess_skewness,
    classify_turbulence_model,
)
from consultant_mcp.assessments import (
    assess_y_plus as assess_y_plus_band,
)
from consultant_mcp.tools import (
    _find_latest_yplus_file,
    _orphan_citations,
    _parse_check_mesh_log,
    _parse_residual_log,
    _parse_y_plus_dat,
    _read_turbulence_properties,
    assess_mesh_quality,
    assess_residuals,
    assess_y_plus,
    draft_annotation_from_report,
    flag_uncited_claims,
    get_tutorial_annotation,
    list_tutorial_annotations,
)

# ---------------------------------------------------------------------------
# Synthetic checkMesh log snippets (modelled on real OpenFOAM v2412 output).
# ---------------------------------------------------------------------------

CLEAN_LOG = """\
Mesh stats
    points:           1764
    faces:            3360
    internal faces:   3200
    cells:            1600
    faces per cell:   4.2
    boundary patches: 4

Checking geometry...
    Overall domain bounding box (0 0 0) (1 1 0.1)
    Mesh has 2 geometric (non-empty/wedge) directions (1 1 0)
    Mesh has 2 solution (non-empty/wedge) directions (1 1 0)
    All edges aligned with or perpendicular to non-empty directions.
    Boundary openness (1.1e-19 -7.5e-18 -2.1e-18) OK.
    Max cell openness = 2.7e-16 OK.
    Max aspect ratio = 1.5 OK.
    Minimum face area = 0.0025. Maximum face area = 0.0025.  Face area magnitudes OK.
    Min volume = 6.25e-05. Max volume = 6.25e-05.  Total volume = 0.1.  Cell volumes OK.
    Mesh non-orthogonality Max: 0 average: 0
    Non-orthogonality check OK.
    Face pyramids OK.
    Max skewness = 1e-12 OK.
    Coupled point location match (average 0) OK.

Mesh OK.

End
"""

MARGINAL_LOG = """\
Mesh stats
    points:           50000
    faces:            120000
    internal faces:   115000
    cells:            40000
    boundary patches: 6

Checking geometry...
    Max aspect ratio = 250.4 OK.
    Mesh non-orthogonality Max: 74.2 average: 12.1
   *Number of severely non-orthogonal (> 70 degrees) faces: 42.
    Non-orthogonality check OK.
    Max skewness = 3.8 OK.

Mesh OK.

End
"""

POOR_LOG = """\
Mesh stats
    points:           5000
    faces:            12000
    cells:            4000

Checking geometry...
    Max aspect ratio = 1500 OK.
    Mesh non-orthogonality Max: 87.5 average: 25.3
   *Number of severely non-orthogonal (> 70 degrees) faces: 500.
 ***Error in non-orthogonality check.
    Max skewness = 15.2 ***Max skewness too large
 ***Failed 2 mesh checks.

End
"""


# ---------------------------------------------------------------------------
# assessments.py — per-metric verdicts.
# ---------------------------------------------------------------------------


class TestNonOrthogonality:
    def test_good(self) -> None:
        v = assess_non_orthogonality(30.0)
        assert v.verdict == "good"
        assert "of_check_mesh_src" in v.cites

    def test_acceptable(self) -> None:
        v = assess_non_orthogonality(65.0)
        assert v.verdict == "acceptable"
        assert "nNonOrthogonalCorrectors" in v.recommendation

    def test_marginal(self) -> None:
        v = assess_non_orthogonality(74.0)
        assert v.verdict == "marginal"

    def test_poor(self) -> None:
        v = assess_non_orthogonality(87.0)
        assert v.verdict == "poor"

    def test_outright_fail(self) -> None:
        v = assess_non_orthogonality(92.0)
        assert v.verdict == "poor"
        assert "degenerate" in v.recommendation.lower() or "re-mesh" in v.recommendation.lower()

    def test_unknown_when_none(self) -> None:
        v = assess_non_orthogonality(None)
        assert v.verdict == "unknown"


class TestSkewness:
    def test_good(self) -> None:
        assert assess_skewness(0.5).verdict == "good"

    def test_acceptable(self) -> None:
        assert assess_skewness(2.0).verdict == "acceptable"

    def test_marginal(self) -> None:
        assert assess_skewness(7.0).verdict == "marginal"

    def test_poor(self) -> None:
        assert assess_skewness(20.0).verdict == "poor"


class TestAspectRatio:
    def test_good(self) -> None:
        assert assess_aspect_ratio(2.0).verdict == "good"

    def test_acceptable(self) -> None:
        assert assess_aspect_ratio(50.0).verdict == "acceptable"

    def test_marginal(self) -> None:
        assert assess_aspect_ratio(500.0).verdict == "marginal"

    def test_poor(self) -> None:
        assert assess_aspect_ratio(2000.0).verdict == "poor"


class TestSevereNonOrthogonal:
    def test_zero(self) -> None:
        assert assess_severe_non_orthogonal(0, 1000).verdict == "good"

    def test_tolerable(self) -> None:
        # 5 faces over 100k cells = 5e-5 < 0.1%.
        assert assess_severe_non_orthogonal(5, 100000).verdict == "acceptable"

    def test_marginal(self) -> None:
        # 50 faces over 100k cells = 5e-4 < 1% but > 0.1%.
        assert assess_severe_non_orthogonal(500, 100000).verdict == "marginal"

    def test_poor(self) -> None:
        # 5000 over 100k = 5% > 1%.
        assert assess_severe_non_orthogonal(5000, 100000).verdict == "poor"

    def test_unknown_count(self) -> None:
        assert assess_severe_non_orthogonal(None, 1000).verdict == "unknown"

    def test_unknown_when_cell_count_missing(self) -> None:
        # Regression: a few severe faces with an unparsed/zero cell count
        # must NOT be condemned to "poor" (the severity bands are a
        # fraction of cells, which can't be computed without n_cells).
        assert assess_severe_non_orthogonal(5, None).verdict == "unknown"
        assert assess_severe_non_orthogonal(5, 0).verdict == "unknown"


class TestAggregateVerdict:
    def test_worst_wins(self) -> None:
        v1 = assess_non_orthogonality(30.0)   # good
        v2 = assess_skewness(7.0)              # marginal
        v3 = assess_aspect_ratio(50.0)         # acceptable
        assert aggregate_verdict([v1, v2, v3]) == "marginal"

    def test_unknown_ignored(self) -> None:
        v1 = assess_non_orthogonality(None)    # unknown
        v2 = assess_skewness(0.5)              # good
        assert aggregate_verdict([v1, v2]) == "good"

    def test_all_unknown(self) -> None:
        v1 = assess_non_orthogonality(None)
        v2 = assess_skewness(None)
        assert aggregate_verdict([v1, v2]) == "unknown"


# ---------------------------------------------------------------------------
# tools._parse_check_mesh_log — log parsing.
# ---------------------------------------------------------------------------


class TestParseCheckMeshLog:
    def test_clean(self) -> None:
        parsed = _parse_check_mesh_log(CLEAN_LOG)
        assert parsed["n_cells"] == 1600
        assert parsed["max_aspect_ratio"] == 1.5
        assert parsed["max_non_orthogonality"] == 0.0
        assert parsed["max_skewness"] == 1e-12
        assert parsed["quality_pass"] is True
        # CLEAN_LOG has no "Number of severely non-orthogonal..." line
        # because there are zero such faces. Parser must infer 0, not None.
        assert parsed["severe_non_orthogonal_faces"] == 0

    def test_severe_faces_zero_when_omitted_but_log_otherwise_parsed(self) -> None:
        """checkMesh omits the severe-faces line when count is 0.

        Regression: the parser used to leave the field as None in this
        case, which then triggered verdict "unknown" downstream — even
        though semantically it's zero faces (good).
        """
        log = (
            "Mesh stats\n"
            "    cells:            1000\n"
            "Checking geometry...\n"
            "    Max aspect ratio = 1.5 OK.\n"
            "    Mesh non-orthogonality Max: 25.0 average: 5.0\n"
            "    Non-orthogonality check OK.\n"
            "    Max skewness = 0.5 OK.\n"
            "Mesh OK.\n"
        )
        parsed = _parse_check_mesh_log(log)
        assert parsed["max_non_orthogonality"] == 25.0
        assert parsed["severe_non_orthogonal_faces"] == 0

    def test_severe_faces_none_when_log_unparseable(self) -> None:
        """If the log is empty / mangled enough that non-ortho doesn't
        parse, severe_non_orthogonal_faces stays None (don't fabricate)."""
        parsed = _parse_check_mesh_log("totally unrelated content\n")
        assert parsed["max_non_orthogonality"] is None
        assert parsed["severe_non_orthogonal_faces"] is None

    def test_marginal(self) -> None:
        parsed = _parse_check_mesh_log(MARGINAL_LOG)
        assert parsed["n_cells"] == 40000
        assert parsed["max_aspect_ratio"] == 250.4
        assert parsed["max_non_orthogonality"] == 74.2
        assert parsed["severe_non_orthogonal_faces"] == 42
        assert parsed["quality_pass"] is True

    def test_poor(self) -> None:
        parsed = _parse_check_mesh_log(POOR_LOG)
        assert parsed["n_cells"] == 4000
        assert parsed["max_non_orthogonality"] == 87.5
        assert parsed["max_skewness"] == 15.2
        # Failed N mesh checks → quality_pass is False.
        assert parsed["quality_pass"] is False


# ---------------------------------------------------------------------------
# tools.assess_mesh_quality — end-to-end on synthetic logs.
# ---------------------------------------------------------------------------


class TestAssessMeshQuality:
    def test_clean_case(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.checkMesh").write_text(CLEAN_LOG)
        result = assess_mesh_quality(str(case))
        assert result["success"] is True
        assert result["overall_verdict"] == "good"
        assert result["checkmesh_quality_pass"] is True
        assert result["n_cells"] == 1600
        # All four metrics reported.
        assert len(result["metrics"]) == 4
        # Summary mentions the overall verdict.
        assert "good" in result["summary"].lower()
        # Citation sources populated for the verdicts that referenced them.
        assert "of_check_mesh_src" in result["citation_sources"]

    def test_marginal_case(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.checkMesh").write_text(MARGINAL_LOG)
        result = assess_mesh_quality(str(case))
        assert result["success"] is True
        # Non-ortho 74.2 is marginal; aspect ratio 250 is marginal too.
        assert result["overall_verdict"] == "marginal"
        # Each metric's verdict accessible.
        verdicts = {m["metric"]: m["verdict"] for m in result["metrics"]}
        assert verdicts["max_non_orthogonality"] == "marginal"
        assert verdicts["max_aspect_ratio"] == "marginal"

    def test_poor_case(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.checkMesh").write_text(POOR_LOG)
        result = assess_mesh_quality(str(case))
        assert result["success"] is True
        assert result["overall_verdict"] == "poor"
        assert result["checkmesh_quality_pass"] is False

    def test_missing_log(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = assess_mesh_quality(str(case))
        assert result["success"] is False
        assert result["reason"] == "checkmesh_log_missing"

    def test_invalid_case_path(self, tmp_path: Path) -> None:
        result = assess_mesh_quality(str(tmp_path / "nope"))
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

    def test_empty_log(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.checkMesh").write_text("")
        result = assess_mesh_quality(str(case))
        assert result["success"] is False
        assert result["reason"] == "checkmesh_log_empty"


# ---------------------------------------------------------------------------
# annotations + get_tutorial_annotation.
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_annotations_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Spin up a minimal corpus tree and point the lookup at it."""
    root = tmp_path / "fake-repo"
    annotations = root / "corpus"
    annotations.mkdir(parents=True)

    good = annotations / "incompressible" / "icoFoam" / "cavity"
    good.mkdir(parents=True)
    (good / "cavity.md").write_text(
        "---\n"
        "tutorial_path: incompressible/icoFoam/cavity/cavity\n"
        "solver: icoFoam\n"
        "suitable_for_template:\n"
        "  - laminar cavity\n"
        "---\n"
        "\n"
        "# Body\n"
        "\n"
        "Some prose explaining the choices.\n"
    )

    malformed = annotations / "broken"
    malformed.mkdir()
    # No frontmatter at all.
    (malformed / "noframe.md").write_text("Just markdown, no frontmatter.\n")
    # Bad YAML inside the frontmatter.
    (malformed / "badyaml.md").write_text(
        "---\n: : not valid yaml ::\n---\nbody\n"
    )

    monkeypatch.setenv(ann_mod.ENV_ROOT_OVERRIDE, str(root))
    return root


class TestReadAnnotation:
    def test_happy_path(self, fixture_annotations_root: Path) -> None:
        ann = read_annotation("incompressible/icoFoam/cavity/cavity")
        assert ann.metadata["solver"] == "icoFoam"
        assert "Body" in ann.body
        assert ann.tutorial_path == "incompressible/icoFoam/cavity/cavity"

    def test_missing(self, fixture_annotations_root: Path) -> None:
        with pytest.raises(AnnotationNotFoundError):
            read_annotation("nonexistent/case")

    def test_directory_form_resolves_to_nested_case(
        self, fixture_annotations_root: Path
    ) -> None:
        # Agents pass the tutorial directory; the case nests under the same name.
        ann = read_annotation("incompressible/icoFoam/cavity")
        assert ann.metadata["solver"] == "icoFoam"
        assert ann.tutorial_path == "incompressible/icoFoam/cavity/cavity"

    def test_no_frontmatter(self, fixture_annotations_root: Path) -> None:
        with pytest.raises(ValueError, match="missing YAML frontmatter"):
            read_annotation("broken/noframe")

    def test_bad_yaml(self, fixture_annotations_root: Path) -> None:
        with pytest.raises(ValueError, match="malformed"):
            read_annotation("broken/badyaml")

    def test_strips_leading_and_trailing_slashes(
        self, fixture_annotations_root: Path
    ) -> None:
        # Same tutorial; tolerated path variants.
        for variant in [
            "/incompressible/icoFoam/cavity/cavity",
            "incompressible/icoFoam/cavity/cavity/",
            "  incompressible/icoFoam/cavity/cavity  ",
        ]:
            ann = read_annotation(variant)
            assert ann.metadata["solver"] == "icoFoam"

    def test_empty_path_rejected(self, fixture_annotations_root: Path) -> None:
        with pytest.raises(ValueError):
            annotation_path_for("")

    def test_env_override_invalid(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(ann_mod.ENV_ROOT_OVERRIDE, str(tmp_path / "no-such"))
        with pytest.raises(FileNotFoundError, match="does not exist"):
            ann_mod.find_repo_root()


class TestGetTutorialAnnotation:
    def test_happy_path(self, fixture_annotations_root: Path) -> None:
        result = get_tutorial_annotation("incompressible/icoFoam/cavity/cavity")
        assert result["success"] is True
        assert result["metadata"]["solver"] == "icoFoam"
        assert "Body" in result["body"]
        assert "annotation_path" in result

    def test_missing_returns_structured_failure(
        self, fixture_annotations_root: Path
    ) -> None:
        result = get_tutorial_annotation("nonexistent/case")
        assert result["success"] is False
        assert result["reason"] == "no_annotation"
        assert "expected_path" in result
        # The detail must explicitly discourage hallucinated rationale.
        assert "uncited" in result["detail"].lower() or "inventing" in result["detail"].lower()

    def test_malformed(self, fixture_annotations_root: Path) -> None:
        result = get_tutorial_annotation("broken/noframe")
        assert result["success"] is False
        assert result["reason"] == "malformed_annotation"


class TestListTutorialAnnotations:
    def test_lists_real_annotations(
        self, fixture_annotations_root: Path
    ) -> None:
        result = list_tutorial_annotations()
        assert result["success"] is True
        paths = [e["tutorial_path"] for e in result["annotations"]]
        assert "incompressible/icoFoam/cavity/cavity" in paths
        # README.md was excluded.
        assert not any(p.lower().endswith("readme") for p in paths)
        # Malformed files are still listed by path — listing doesn't parse.
        assert "broken/noframe" in paths

    def test_excludes_drafts(self, fixture_annotations_root: Path) -> None:
        # A .draft.md is staging, not a promoted annotation — it must not
        # appear in the enumeration (nor leak as a "<name>.draft" path).
        draft = (
            fixture_annotations_root
            / "corpus"
            / "incompressible"
            / "icoFoam"
            / "cavity"
            / "cavity.draft.md"
        )
        draft.write_text("---\ntutorial_path: x\n---\nbody\n")
        paths = [e["tutorial_path"] for e in list_tutorial_annotations()["annotations"]]
        assert not any(p.endswith(".draft") for p in paths)


# ---------------------------------------------------------------------------
# assess_residual_pattern + assess_residuals
# ---------------------------------------------------------------------------


def _decaying(start: float, decay: float, n: int) -> list[float]:
    return [start * decay ** i for i in range(n)]


class TestAssessResidualPattern:
    def test_converged(self) -> None:
        # All values well below threshold.
        history = [1e-6] * 60
        v = assess_residual_pattern("Ux", history, threshold=1e-5)
        assert v.pattern == "converged"
        assert v.verdict == "good"

    def test_still_running(self) -> None:
        # Monotonic decay, far above threshold, dropping by orders of magnitude.
        history = _decaying(1e-1, 0.9, 60)
        v = assess_residual_pattern("Ux", history, threshold=1e-8)
        assert v.pattern in {"still_running"}
        assert v.verdict == "acceptable"

    def test_stalled(self) -> None:
        # Near-constant residual above threshold (CoV < 0.05).
        history = [1.005e-3, 1.004e-3, 1.002e-3, 1.005e-3, 1.003e-3] * 12
        v = assess_residual_pattern("p", history, threshold=1e-5)
        assert v.pattern == "stalled"
        assert v.verdict == "marginal"
        assert "plateau" in v.recommendation.lower()

    def test_oscillating(self) -> None:
        # High variance, non-monotonic.
        history = []
        for i in range(60):
            history.append(1e-3 if i % 2 == 0 else 1e-1)
        v = assess_residual_pattern("Ux", history, threshold=1e-5)
        assert v.pattern == "oscillating"
        assert v.verdict == "marginal"
        assert "URF" in v.recommendation or "relaxation" in v.recommendation.lower()

    def test_diverging(self) -> None:
        history = [1e-4 * 1.1 ** i for i in range(60)]
        v = assess_residual_pattern("Ux", history, threshold=1e-5)
        assert v.pattern == "diverging"
        assert v.verdict == "poor"

    def test_insufficient_data(self) -> None:
        v = assess_residual_pattern("Ux", [1e-3, 2e-3], threshold=1e-5)
        assert v.pattern == "insufficient_data"
        assert v.verdict == "unknown"

    def test_converged_at_residual_control_floor(self) -> None:
        """Regression: solver hit residualControl=1e-6 cleanly, last
        few iters hovering around 5e-7. Earlier strict 'whole window
        below threshold' rule misclassified this as still_running; the
        relaxed 'last + tail of last 10' rule correctly says converged.
        """
        # Decay from 1e-2 to ~3e-7 over 60 iters, with last 10 all
        # at or below 1e-6 (the threshold).
        history = [1e-2 * 0.6 ** i for i in range(60)]
        # Confirm the test fixture matches the intended pattern.
        assert history[-1] < 1e-6
        assert max(history[-10:]) < 2.0e-6
        v = assess_residual_pattern("p", history, threshold=1e-6)
        assert v.pattern == "converged"
        assert v.verdict == "good"

    def test_not_converged_when_tail_has_spike(self) -> None:
        """Tail-based check still catches a tail spike."""
        history = [1e-7] * 55 + [1e-3, 1e-7, 1e-3, 1e-7, 5e-7]
        # last value is below threshold, but the tail has spikes 1000x.
        v = assess_residual_pattern("p", history, threshold=1e-6)
        # Should NOT be converged — the tail spike is too large.
        assert v.pattern != "converged"

    def test_diverging_from_zero_first(self) -> None:
        # Regression: a blow-up whose window starts at exactly 0.0 must
        # still be caught as diverging. The old `first > 0` guard let it
        # fall through to still_running / acceptable (read as healthy).
        v = assess_residual_pattern("p", [0.0, 1e-3, 1e-1, 1e1, 1e3, 1e5], threshold=1e-5)
        assert v.pattern == "diverging" and v.verdict == "poor"

    def test_nonfinite_is_diverging(self) -> None:
        # Regression: NaN/Inf in the window means the solve blew up. NaN
        # compares False to everything, so it used to fall through to
        # "still_running" / "acceptable".
        nan = float("nan")
        v = assess_residual_pattern("p", [1e-2, 1e-1, 1.0, 10.0, nan, nan], threshold=1e-5)
        assert v.pattern == "diverging" and v.verdict == "poor"
        vi = assess_residual_pattern(
            "p", [1e-2, 1e-1, 1.0, 10.0, 1e3, float("inf")], threshold=1e-5
        )
        assert vi.pattern == "diverging" and vi.verdict == "poor"


_SAMPLE_LOG_RESIDUALS = """\
Starting time loop

Time = 1
smoothSolver: Solving for Ux, Initial residual = 1.000000e-01, Final residual = 1e-3
smoothSolver: Solving for Uy, Initial residual = 9.000000e-02, Final residual = 1e-3
GAMG: Solving for p, Initial residual = 5.000000e-01, Final residual = 1e-3

Time = 2
smoothSolver: Solving for Ux, Initial residual = 5.000000e-02, Final residual = 1e-4
smoothSolver: Solving for Uy, Initial residual = 4.500000e-02, Final residual = 1e-4
GAMG: Solving for p, Initial residual = 2.000000e-01, Final residual = 1e-4
"""


class TestParseResidualLog:
    def test_extracts_per_field_histories(self) -> None:
        h = _parse_residual_log(_SAMPLE_LOG_RESIDUALS)
        assert set(h) == {"Ux", "Uy", "p"}
        assert h["Ux"] == [0.1, 0.05]
        assert h["p"] == [0.5, 0.2]

    def test_empty(self) -> None:
        assert _parse_residual_log("") == {}

    def test_captures_nan_residual(self) -> None:
        # Regression: a blown-up solve prints "Initial residual = nan".
        # The parser must capture it (not silently drop the line) so the
        # classifier can flag the divergence.
        log = (
            "GAMG:  Solving for p, Initial residual = nan, "
            "Final residual = nan, No Iterations 1000\n"
        )
        h = _parse_residual_log(log)
        assert "p" in h and len(h["p"]) == 1
        import math

        assert math.isnan(h["p"][0])


def _make_solver_log(case: Path, name: str, fields_and_starts: dict) -> Path:
    """Build a synthetic solver log with N iterations of decaying residuals."""
    lines = ["Starting time loop", ""]
    n = max(len(h) for h in fields_and_starts.values())
    for i in range(n):
        lines.append(f"Time = {i + 1}")
        for field, history in fields_and_starts.items():
            if i < len(history):
                lines.append(
                    f"GAMG:  Solving for {field}, "
                    f"Initial residual = {history[i]:.6e}, "
                    f"Final residual = 1e-6, No Iterations 1"
                )
        lines.append("")
    log = case / name
    log.write_text("\n".join(lines))
    return log


class TestAssessResiduals:
    def test_converged_clean(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        # 80 iters of geometric decay so the WHOLE 50-wide window
        # (indices 30..79) sits below threshold = 1e-5.
        _make_solver_log(case, "log.simpleFoam", {
            "Ux": _decaying(1e-1, 0.5, 80),
            "p": _decaying(1e-1, 0.5, 80),
        })
        result = assess_residuals(str(case))
        assert result["success"] is True
        assert result["overall_verdict"] == "good"
        fields = {f["field"]: f for f in result["fields"]}
        assert fields["Ux"]["pattern"] == "converged"

    def test_diverging_pulls_overall_to_poor(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        _make_solver_log(case, "log.simpleFoam", {
            "Ux": _decaying(1e-1, 0.5, 80),
            "p": [1e-4 * 1.1 ** i for i in range(60)],
        })
        result = assess_residuals(str(case))
        assert result["success"] is True
        assert result["overall_verdict"] == "poor"

    def test_missing_log(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = assess_residuals(str(case))
        assert result["success"] is False
        assert result["reason"] == "solver_log_missing"

    def test_log_with_no_residuals(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.simpleFoam").write_text("Build  : v2412\nExec   : simpleFoam\n")
        result = assess_residuals(str(case))
        assert result["success"] is False
        assert result["reason"] == "no_residuals_found"

    def test_explicit_log_path(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        custom = case / "log.weirdname"
        _make_solver_log(case, custom.name, {"Ux": _decaying(1e-1, 0.5, 60)})
        result = assess_residuals(str(case), log_path=str(custom))
        assert result["success"] is True

    def test_auxiliary_logs_skipped(self, tmp_path: Path) -> None:
        """log.blockMesh / log.checkMesh must not be picked up as solver logs."""
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.blockMesh").write_text("not a solver log")
        (case / "log.checkMesh").write_text("not a solver log")
        # No real solver log, so this should report missing.
        result = assess_residuals(str(case))
        assert result["success"] is False
        assert result["reason"] == "solver_log_missing"

    def test_invalid_case_path(self, tmp_path: Path) -> None:
        result = assess_residuals(str(tmp_path / "nope"))
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"


# ---------------------------------------------------------------------------
# Turbulence model classification + assess_y_plus + assess_y_plus tool
# ---------------------------------------------------------------------------


class TestClassifyTurbulenceModel:
    def test_laminar(self) -> None:
        assert classify_turbulence_model("laminar") == "laminar"

    def test_kepsilon_is_high_re(self) -> None:
        assert classify_turbulence_model("RAS", ras_model="kEpsilon") == "high_re_wall_function"

    def test_komegasst_is_hybrid(self) -> None:
        assert classify_turbulence_model("RAS", ras_model="kOmegaSST") == "hybrid"

    def test_spalart_allmaras_low_re(self) -> None:
        assert classify_turbulence_model("RAS", ras_model="SpalartAllmaras") == "low_re_resolved"

    def test_les_smagorinsky(self) -> None:
        assert classify_turbulence_model("LES", les_model="Smagorinsky") == "les"

    def test_unknown_model(self) -> None:
        assert classify_turbulence_model("RAS", ras_model="madeUpModel") == "unknown"

    def test_komegasst_not_misread_as_komega(self) -> None:
        # Regression: longest-needle-first matching, so 'kOmegaSST' -> hybrid
        # and bare 'kOmega' -> low_re_resolved, independent of dict order.
        assert classify_turbulence_model("RAS", ras_model="kOmegaSST") == "hybrid"
        assert classify_turbulence_model("RAS", ras_model="kOmega") == "low_re_resolved"

    def test_launder_sharma_is_low_re(self) -> None:
        # Regression: LaunderSharmaKE is a low-Re k-epsilon — was 'unknown'.
        assert (
            classify_turbulence_model("RAS", ras_model="LaunderSharmaKE")
            == "low_re_resolved"
        )


class TestAssessYPlusBand:
    def test_kepsilon_in_log_layer(self) -> None:
        v = assess_y_plus_band("walls", 30, 80, 60, "high_re_wall_function")
        assert v.verdict == "good"

    def test_kepsilon_too_fine(self) -> None:
        v = assess_y_plus_band("walls", 0.5, 0.8, 0.6, "high_re_wall_function")
        assert v.verdict == "poor"
        assert "viscous sublayer" in v.band.lower() or "y+ < 11" in v.band.lower()

    def test_kepsilon_buffer_layer(self) -> None:
        v = assess_y_plus_band("walls", 15, 25, 20, "high_re_wall_function")
        assert v.verdict == "marginal"

    def test_komegasst_resolved(self) -> None:
        v = assess_y_plus_band("walls", 0.1, 0.8, 0.4, "hybrid")
        assert v.verdict == "good"

    def test_komegasst_acceptable_at_3(self) -> None:
        v = assess_y_plus_band("walls", 1.1, 3.0, 2.0, "hybrid")
        assert v.verdict == "acceptable"

    def test_komegasst_buffer(self) -> None:
        v = assess_y_plus_band("walls", 5, 20, 10, "hybrid")
        assert v.verdict == "marginal"

    def test_komegasst_wall_function_regime(self) -> None:
        v = assess_y_plus_band("walls", 30, 80, 50, "hybrid")
        assert v.verdict == "poor"

    def test_low_re_resolved(self) -> None:
        v = assess_y_plus_band("walls", 0.3, 0.9, 0.6, "low_re_resolved")
        assert v.verdict == "good"

    def test_low_re_too_coarse(self) -> None:
        v = assess_y_plus_band("walls", 5, 20, 10, "low_re_resolved")
        assert v.verdict == "poor"

    def test_laminar_skips(self) -> None:
        v = assess_y_plus_band("walls", None, None, None, "laminar")
        assert v.verdict == "unknown"
        assert v.band == "not_applicable"


_SAMPLE_YPLUS_DAT = """\
# yPlus
# Time           patch                 min          max          average
500              walls                 0.5          2.3          1.2
500              wing                  0.3          1.8          1.0
"""


class TestParseYPlusDat:
    def test_parses_two_patches(self) -> None:
        records = _parse_y_plus_dat(_SAMPLE_YPLUS_DAT)
        assert len(records) == 2
        walls = next(r for r in records if r["patch"] == "walls")
        assert walls["y_plus_max"] == 2.3
        assert walls["y_plus_avg"] == 1.2
        assert walls["time"] == 500.0

    def test_handles_comments_and_blanks(self) -> None:
        text = "\n# header\n\n# another\n500 walls 1 2 1.5\n\n"
        records = _parse_y_plus_dat(text)
        assert len(records) == 1
        assert records[0]["patch"] == "walls"


def _write_turb_props(case: Path, sim_type: str, model: str | None = None) -> None:
    constant = case / "constant"
    constant.mkdir(exist_ok=True)
    body = f"simulationType  {sim_type};\n"
    if sim_type == "RAS" and model:
        body += f"RAS\n{{\n    RASModel        {model};\n    turbulence on;\n}}\n"
    elif sim_type == "LES" and model:
        body += f"LES\n{{\n    LESModel        {model};\n    turbulence on;\n}}\n"
    (constant / "turbulenceProperties").write_text(body)


def _write_yplus_dat(case: Path, time: str, text: str) -> Path:
    pp = case / "postProcessing" / "yPlus" / time
    pp.mkdir(parents=True)
    f = pp / "yPlus.dat"
    f.write_text(text)
    return f


class TestFindLatestYplusFile:
    def test_picks_scientific_notation_time_dir(self, tmp_path: Path) -> None:
        # Regression: small-deltaT transient runs write time directories
        # like "1e-05" / "2.5e-3"; a digit-only filter wrongly rejected
        # them, returning None -> spurious y_plus_data_missing.
        case = tmp_path / "case"
        _write_yplus_dat(case, "1e-05", "# t patch min max avg\n1e-05 walls 1 2 1.5\n")
        _write_yplus_dat(case, "2.5e-3", "# t patch min max avg\n2.5e-3 walls 1 2 1.5\n")
        found = _find_latest_yplus_file(case, "latest")
        assert found is not None
        # 2.5e-3 = 0.0025 > 1e-05, so it is the latest.
        assert found.parent.name == "2.5e-3"

    def test_picks_highest_numeric_time(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        for t in ("100", "200", "50"):
            _write_yplus_dat(case, t, f"# t patch min max avg\n{t} walls 1 2 1.5\n")
        found = _find_latest_yplus_file(case, "latest")
        assert found is not None and found.parent.name == "200"


class TestReadTurbulenceProperties:
    def test_laminar(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        _write_turb_props(case, "laminar")
        tp = _read_turbulence_properties(case)
        assert tp["simulation_type"] == "laminar"
        assert tp["ras_model"] is None

    def test_ras_kepsilon(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        _write_turb_props(case, "RAS", "kEpsilon")
        tp = _read_turbulence_properties(case)
        assert tp["simulation_type"] == "RAS"
        assert tp["ras_model"] == "kEpsilon"

    def test_file_missing(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        tp = _read_turbulence_properties(case)
        assert tp["simulation_type"] is None


class TestAssessYPlusTool:
    def test_laminar_short_circuits(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        _write_turb_props(case, "laminar")
        result = assess_y_plus(str(case))
        assert result["success"] is True
        assert result["model_class"] == "laminar"
        assert result["patches"] == []
        assert "not apply" in result["summary"]

    def test_missing_y_plus_data(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        _write_turb_props(case, "RAS", "kOmegaSST")
        result = assess_y_plus(str(case))
        assert result["success"] is False
        assert result["reason"] == "y_plus_data_missing"
        assert "postProcess -func yPlus" in result["detail"]

    def test_komegasst_good(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        _write_turb_props(case, "RAS", "kOmegaSST")
        _write_yplus_dat(case, "500", _SAMPLE_YPLUS_DAT)
        result = assess_y_plus(str(case))
        assert result["success"] is True
        assert result["model_class"] == "hybrid"
        # max y+ on both patches is 2.3 and 1.8 → acceptable for kOmegaSST
        # (1 < y+ < 5).
        assert result["overall_verdict"] == "acceptable"

    def test_kepsilon_poor_when_too_fine(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        _write_turb_props(case, "RAS", "kEpsilon")
        _write_yplus_dat(case, "500", _SAMPLE_YPLUS_DAT)
        result = assess_y_plus(str(case))
        assert result["success"] is True
        assert result["overall_verdict"] == "poor"

    def test_latest_picks_highest_time(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        _write_turb_props(case, "RAS", "kOmegaSST")
        _write_yplus_dat(case, "100", "500 walls 100 200 150\n")  # poor
        _write_yplus_dat(case, "500", _SAMPLE_YPLUS_DAT)          # acceptable
        result = assess_y_plus(str(case), time="latest")
        assert result["success"] is True
        assert "yPlus/500" in result["y_plus_path"]

    def test_explicit_time(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        _write_turb_props(case, "RAS", "kOmegaSST")
        _write_yplus_dat(case, "100", "100 walls 0.1 0.5 0.3\n")
        _write_yplus_dat(case, "500", "500 walls 50 100 70\n")
        result = assess_y_plus(str(case), time="100")
        assert result["success"] is True
        assert "yPlus/100" in result["y_plus_path"]

    def test_invalid_case_path(self, tmp_path: Path) -> None:
        result = assess_y_plus(str(tmp_path / "nope"))
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

    def test_turbulence_properties_missing(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = assess_y_plus(str(case))
        assert result["success"] is False
        assert result["reason"] == "turbulence_properties_missing"


# ---------------------------------------------------------------------------
# draft_annotation_from_report.
# ---------------------------------------------------------------------------


_REPORT_WITH_DECISIONS = """\
# Case setup report

Live narration from the agent.

---

## [10:00:01] mesh / ok — Selected blockMesh template

- **Decision:** icoFoam/cavity blockMeshDict, 60x60 uniform.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Cavity at Re=400 matches Ghia 1982 setup. _(cites: corpus/incompressible/icoFoam/cavity/cavity.md)_
- **Alternatives:** 20x20 (under-resolved); 80x80 (slower).
- **When it breaks:** Re > 1000 (transitional).

</details>

## [10:00:05] solver_config / ok — Chose simpleFoam

- **Decision:** simpleFoam steady laminar.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Ghia is a steady benchmark; Re=400 is below cavity transition.
- **Alternatives:** icoFoam (transient); pisoFoam/RAS (wrong regime).
- **When it breaks:** Re > 7500 (transition).

</details>
"""

_REPORT_ONLY_INFO = """\
# Case setup report

---

## [10:00:01] geometry / ok — Read scenario YAML

Loaded cases/scenarios/lid-cavity.yaml.
"""

_REPORT_NO_DECISIONS = """\
# Case setup report

## [10:00:01] info / ok — Streamed narration with no decision fields.

Just streamed narration, no consultant-schema fields.
"""


@pytest.fixture
def fresh_corpus_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """A clean fake-repo with an empty corpus/ tree."""
    root = tmp_path / "fake-repo"
    (root / "corpus").mkdir(parents=True)
    monkeypatch.setenv(ann_mod.ENV_ROOT_OVERRIDE, str(root))
    return root


def _write_report(case: Path, body: str) -> Path:
    case.mkdir(parents=True, exist_ok=True)
    report = case / "REPORT.md"
    report.write_text(body, encoding="utf-8")
    return report


class TestDraftAnnotationFromReport:
    def test_happy_path(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        case = tmp_path / "work" / "lid-cavity"
        _write_report(case, _REPORT_WITH_DECISIONS)

        result = draft_annotation_from_report(
            case_path=str(case),
            tutorial_path="incompressible/icoFoam/cavity/cavity",
        )

        assert result["success"] is True
        assert result["n_decisions"] == 2
        assert result["annotation_exists"] is False

        draft_path = Path(result["draft_path"])
        assert draft_path.name == "cavity.draft.md"
        assert draft_path.is_file()

        text = draft_path.read_text()
        # Frontmatter is present with the tutorial path and provenance.
        assert "tutorial_path: incompressible/icoFoam/cavity/cavity" in text
        assert f"derived_from: {case}" in text
        assert "draft_status:" in text
        # Frontmatter must be valid YAML — the <fill in: ...> placeholders
        # contain ':' so they must be quoted, else a tool/editor parsing the
        # draft chokes with "mapping values are not allowed here".
        import yaml
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        assert m is not None, "draft has no frontmatter fence"
        meta = yaml.safe_load(m.group(1))
        assert isinstance(meta, dict)
        assert meta["tutorial_path"] == "incompressible/icoFoam/cavity/cavity"
        assert "fill in" in meta["solver"]  # placeholder survived as a string
        # The annotation table uses "Choice" not "Phase".
        assert "| Choice | Decision | Why | Alternatives | When it breaks |" in text
        # Decision rows from the run made it across.
        assert "icoFoam/cavity blockMeshDict, 60x60 uniform." in text
        assert "simpleFoam steady laminar." in text
        # Notes section is included as a fill-in prompt.
        assert "## Notes" in text

    def test_metadata_args_fill_frontmatter(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        # The agent ran the case, so it can fill the frontmatter it knows
        # rather than leaving the human a blank scaffold. Values with colons
        # (e.g. a citation "48:387-411") must round-trip as valid YAML.
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        result = draft_annotation_from_report(
            str(case),
            "incompressible/icoFoam/cavity/cavity",
            solver="simpleFoam (steady)",
            physics="incompressible, steady, laminar; valid Re up to ~7500",
            geometry="2-D unit square lid-driven cavity",
            suitable_for=["steady laminar cavity benchmarks"],
            not_suitable_for=["Re above ~7500 (unsteady)"],
            references=["Ghia 1982 JCP 48:387-411"],
        )
        assert result["success"] is True
        import yaml
        text = Path(result["draft_path"]).read_text()
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        meta = yaml.safe_load(m.group(1))
        assert meta["solver"] == "simpleFoam (steady)"
        assert "Re up to ~7500" in meta["physics"]
        assert meta["suitable_for_template"] == ["steady laminar cavity benchmarks"]
        assert meta["references"] == ["Ghia 1982 JCP 48:387-411"]
        assert "fill in" not in meta["solver"]  # filled, not a placeholder

    def test_draft_does_not_shadow_live_annotation_lookup(
        self,
        tmp_path: Path,
        fresh_corpus_root: Path,
    ) -> None:
        # Even after writing a .draft.md, get_tutorial_annotation still
        # treats the tutorial as un-annotated (the live .md doesn't exist).
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        draft_annotation_from_report(
            str(case), "incompressible/icoFoam/cavity/cavity"
        )

        result = get_tutorial_annotation(
            "incompressible/icoFoam/cavity/cavity"
        )
        # The corpus is empty (only the draft exists), so lookup misses.
        assert result["success"] is False
        assert result["reason"] == "no_annotation"

    def test_refuses_when_draft_already_exists(
        self,
        tmp_path: Path,
        fresh_corpus_root: Path,
    ) -> None:
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        first = draft_annotation_from_report(
            str(case), "incompressible/icoFoam/cavity/cavity"
        )
        assert first["success"] is True

        second = draft_annotation_from_report(
            str(case), "incompressible/icoFoam/cavity/cavity"
        )
        assert second["success"] is False
        assert second["reason"] == "draft_already_exists"

    def test_overwrite_flag_replaces_existing_draft(
        self,
        tmp_path: Path,
        fresh_corpus_root: Path,
    ) -> None:
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        draft_annotation_from_report(
            str(case), "incompressible/icoFoam/cavity/cavity"
        )

        # Mutate the draft so we can verify it was rewritten.
        draft_path = (
            fresh_corpus_root
            / "corpus"
            / "incompressible"
            / "icoFoam"
            / "cavity"
            / "cavity.draft.md"
        )
        draft_path.write_text("MUTATED\n")

        result = draft_annotation_from_report(
            str(case),
            "incompressible/icoFoam/cavity/cavity",
            overwrite=True,
        )
        assert result["success"] is True
        assert "MUTATED" not in draft_path.read_text()

    def test_live_annotation_already_present_flags_in_result(
        self,
        tmp_path: Path,
        fresh_corpus_root: Path,
    ) -> None:
        # Drop a live .md so annotation_exists should be True.
        live = (
            fresh_corpus_root
            / "corpus"
            / "incompressible"
            / "icoFoam"
            / "cavity"
        )
        live.mkdir(parents=True)
        (live / "cavity.md").write_text(
            "---\ntutorial_path: incompressible/icoFoam/cavity/cavity\n---\nlive\n"
        )

        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)

        result = draft_annotation_from_report(
            str(case), "incompressible/icoFoam/cavity/cavity"
        )
        assert result["success"] is True
        assert result["annotation_exists"] is True
        # The live annotation is untouched.
        assert (live / "cavity.md").read_text().endswith("live\n")
        # The draft is a parallel file.
        assert (live / "cavity.draft.md").is_file()

    def test_report_not_found(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        case = tmp_path / "empty"
        case.mkdir()
        result = draft_annotation_from_report(
            str(case), "incompressible/icoFoam/cavity/cavity"
        )
        assert result["success"] is False
        assert result["reason"] == "report_not_found"

    def test_invalid_case_path(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        result = draft_annotation_from_report(
            str(tmp_path / "nope"), "incompressible/icoFoam/cavity/cavity"
        )
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

    def test_invalid_tutorial_path(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        result = draft_annotation_from_report(str(case), "   ")
        assert result["success"] is False
        assert result["reason"] == "invalid_tutorial_path"

    def test_no_decisions_when_only_info(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        # An info-only entry carries no consultant fields, so there is
        # nothing to draft.
        case = tmp_path / "case"
        _write_report(case, _REPORT_ONLY_INFO)
        result = draft_annotation_from_report(
            str(case), "incompressible/icoFoam/cavity/cavity"
        )
        assert result["success"] is False
        assert result["reason"] == "no_decisions_found"

    def test_no_decisions_when_no_consultant_fields(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        case = tmp_path / "case"
        _write_report(case, _REPORT_NO_DECISIONS)
        result = draft_annotation_from_report(
            str(case), "incompressible/icoFoam/cavity/cavity"
        )
        assert result["success"] is False
        assert result["reason"] == "no_decisions_found"

    def test_creates_nested_corpus_dirs(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        # Tutorial path several levels deep — the tool should create
        # intermediate directories under corpus/.
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        result = draft_annotation_from_report(
            str(case), "a/b/c/d/leaf"
        )
        assert result["success"] is True
        assert (
            fresh_corpus_root / "corpus" / "a" / "b" / "c" / "d"
            / "leaf.draft.md"
        ).is_file()

    def test_tutorial_path_slashes_tolerated(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        result = draft_annotation_from_report(
            str(case), "/incompressible/icoFoam/cavity/cavity/"
        )
        assert result["success"] is True
        assert Path(result["draft_path"]).name == "cavity.draft.md"

    def test_corpus_subpath_overrides_location_not_frontmatter(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        # A case family filed by experiment: the draft lands at the
        # corpus_subpath location, but the frontmatter tutorial_path still
        # records the real template it derived from. This is the whole point
        # — decoupling where the entry lives from which tutorial it borrowed.
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        result = draft_annotation_from_report(
            str(case),
            tutorial_path="compressible/rhoCentralFoam/biconic25-55Run35",
            corpus_subpath=(
                "compressible/rhoCentralFoam/supersonic-half-cones/"
                "twin-cone-snappy"
            ),
        )
        assert result["success"] is True
        draft_path = Path(result["draft_path"])
        assert draft_path == (
            fresh_corpus_root / "corpus" / "compressible" / "rhoCentralFoam"
            / "supersonic-half-cones" / "twin-cone-snappy.draft.md"
        )
        assert draft_path.is_file()
        # frontmatter template is unchanged by the relocation
        assert (
            "tutorial_path: compressible/rhoCentralFoam/biconic25-55Run35"
            in draft_path.read_text()
        )

    def test_corpus_subpath_tolerates_suffix_and_slashes(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        result = draft_annotation_from_report(
            str(case),
            "incompressible/icoFoam/cavity/cavity",
            corpus_subpath="/incompressible/lid/cavity-hot.draft.md/",
        )
        assert result["success"] is True
        assert Path(result["draft_path"]).name == "cavity-hot.draft.md"
        assert (
            fresh_corpus_root / "corpus" / "incompressible" / "lid"
            / "cavity-hot.draft.md"
        ).is_file()

    def test_invalid_corpus_subpath(
        self, tmp_path: Path, fresh_corpus_root: Path
    ) -> None:
        case = tmp_path / "case"
        _write_report(case, _REPORT_WITH_DECISIONS)
        for bad in ("   ", "a/../escape"):
            result = draft_annotation_from_report(
                str(case),
                "incompressible/icoFoam/cavity/cavity",
                corpus_subpath=bad,
            )
            assert result["success"] is False
            assert result["reason"] == "invalid_corpus_subpath"


# ---------------------------------------------------------------------------
# Citation integrity — the consultant's value is *auditable* provenance, so
# a citation that points nowhere is worse than no citation. These tests fail
# if a cites tag has no source entry, if a source is never cited, or if the
# source-code citation stops resolving to a file with the thresholds we cite.
# ---------------------------------------------------------------------------


class TestCitationIntegrity:
    @staticmethod
    def _tags_used_in_cites() -> set[str]:
        src = Path(assessments_mod.__file__).read_text()
        tags: set[str] = set()
        for block in re.findall(r"cites=\[([^\]]*)\]", src):
            tags.update(re.findall(r'"([^"]+)"', block))
        return tags

    def test_every_cited_tag_is_defined(self) -> None:
        undefined = self._tags_used_in_cites() - set(CITATION_SOURCES)
        assert not undefined, (
            f"cites tags with no CITATION_SOURCES entry: {sorted(undefined)}"
        )

    def test_no_orphan_citation_sources(self) -> None:
        orphans = set(CITATION_SOURCES) - self._tags_used_in_cites()
        assert not orphans, (
            f"CITATION_SOURCES entries never cited: {sorted(orphans)}"
        )

    def test_doc_and_web_sources_carry_a_url(self) -> None:
        for tag in ("of_user_guide", "of_user_guide_urf", "nasa_tmr"):
            assert "https://" in CITATION_SOURCES[tag], f"{tag} has no URL"

    def test_stale_foundation_section_numbers_gone(self) -> None:
        # Regression guard: the original citations used Foundation-guide
        # "§5.2"/"§5.3" numbers that are wrong for the ESI v2412 install.
        for tag in ("of_user_guide", "of_user_guide_urf"):
            text = CITATION_SOURCES[tag]
            assert "5.2" not in text and "5.3" not in text, (
                f"{tag} still cites a stale §5.x section number"
            )

    def test_nasa_tmr_uses_live_mirror(self) -> None:
        # turbmodels.larc.nasa.gov 301-redirects to a NASA landing page;
        # the verifiable content lives on the GitHub mirror.
        assert "tmbwg.github.io" in CITATION_SOURCES["nasa_tmr"]

    def test_every_tag_has_an_offline_references_entry(self) -> None:
        # The offline literature repo (corpus/references/manifest.json) must carry
        # an entry for every consultant citation, so each one can be read
        # offline. Keeps the citations and the manifest in sync.
        repo_root = Path(__file__).resolve().parents[3]
        manifest_path = repo_root / "corpus" / "references" / "manifest.json"
        if not manifest_path.is_file():
            pytest.skip(f"references manifest not found at {manifest_path}")
        import json

        manifest = json.loads(manifest_path.read_text())
        manifest_tags = {
            s["consultant_tag"]
            for s in manifest["sources"]
            if "consultant_tag" in s
        }
        missing = set(CITATION_SOURCES) - manifest_tags
        assert not missing, (
            f"CITATION_SOURCES tags absent from corpus/references/manifest.json: "
            f"{sorted(missing)}"
        )

    @pytest.mark.skipif(
        "FOAM_SRC" not in os.environ,
        reason="OpenFOAM not sourced (FOAM_SRC unset) — source-code citation unresolvable",
    )
    def test_check_mesh_src_path_resolves_with_cited_thresholds(self) -> None:
        text = CITATION_SOURCES["of_check_mesh_src"]
        m = re.search(r"\$FOAM_SRC(/\S+\.C)\b", text)
        assert m, "of_check_mesh_src no longer names a $FOAM_SRC/...C source path"
        path = Path(os.environ["FOAM_SRC"] + m.group(1))
        assert path.is_file(), f"cited source file does not exist: {path}"
        body = path.read_text(errors="replace")
        # The mesh-quality bands lean on these exact defaults; if a future
        # OpenFOAM version changes them, this fails and forces a re-check.
        assert re.search(r"nonOrthThreshold_\s*=\s*70\b", body), "non-ortho default != 70"
        assert re.search(r"skewThreshold_\s*=\s*4\b", body), "skewness default != 4"
        assert re.search(r"aspectThreshold_\s*=\s*1000\b", body), "aspect default != 1000"

    @pytest.mark.skipif(
        "WM_PROJECT_DIR" not in os.environ,
        reason="OpenFOAM not sourced (WM_PROJECT_DIR unset) — meshQualityDict unresolvable",
    )
    def test_mesh_quality_dict_resolves_with_cited_defaults(self) -> None:
        text = CITATION_SOURCES["of_mesh_quality_dict"]
        m = re.search(r"\$WM_PROJECT_DIR(/\S+meshQualityDict)\b", text)
        assert m, "of_mesh_quality_dict no longer names a $WM_PROJECT_DIR/...meshQualityDict path"
        path = Path(os.environ["WM_PROJECT_DIR"] + m.group(1))
        assert path.is_file(), f"cited meshQualityDict does not exist: {path}"
        body = path.read_text(errors="replace")
        assert re.search(r"maxNonOrtho\s+65\b", body), "maxNonOrtho default != 65"
        assert re.search(r"maxInternalSkewness\s+4\b", body), "maxInternalSkewness default != 4"


# ---------------------------------------------------------------------------
# tools.flag_uncited_claims — end-of-run integrity audit.
# ---------------------------------------------------------------------------


class TestFlagUncitedClaims:
    def _write(self, tmp_path: Path, body: str) -> str:
        (tmp_path / "REPORT.md").write_text(body, encoding="utf-8")
        return str(tmp_path)

    def _signals(self, result: dict) -> set:
        return {s for f in result["flags"] for s in f["signals"]}

    def test_authority_and_regime_claim_flagged(self, tmp_path: Path) -> None:
        case = self._write(
            tmp_path,
            "## [10:00:00] solver_config / warning — Hopf claim\n\n"
            "- **Decision:** Use a steady solver.\n"
            "- **Why:** It is well-known that the cavity transitions at Re 8000.\n",
        )
        r = flag_uncited_claims(case)
        assert r["success"] and r["mode"] == "entries"
        sigs = self._signals(r)
        assert "authority_appeal" in sigs
        assert "regime_claim" in sigs

    def test_self_admitted_flagged_even_with_citation(self, tmp_path: Path) -> None:
        case = self._write(
            tmp_path,
            "## [10:00:00] solver_config / ok — Admitted gap\n\n"
            "- **Decision:** Note the high-Re limit.\n"
            "- **Why:** Useful, but not yet tied to a specific citation. "
            "_(cites: Ghia 1982)_\n",
        )
        r = flag_uncited_claims(case)
        assert "self_admitted_uncited" in self._signals(r)

    def test_first_principles_entry_not_flagged(self, tmp_path: Path) -> None:
        case = self._write(
            tmp_path,
            "## [10:00:00] solver_config / ok — Pressure reference\n\n"
            "- **Decision:** Pin a pressure reference cell.\n"
            "- **Why:** A closed all-wall domain has a singular pressure "
            "equation, defined only up to a constant, so one cell must be "
            "pinned.\n",
        )
        r = flag_uncited_claims(case)
        assert r["success"]
        assert self._signals(r) == set()

    def test_cited_run_observation_not_flagged(self, tmp_path: Path) -> None:
        case = self._write(
            tmp_path,
            "## [10:00:00] mesh / ok — Mesh accepted\n\n"
            "- **Decision:** Accept the 80x80 mesh.\n"
            "- **Why:** checkMesh reports max non-orthogonality 0 and skewness "
            "1e-13. _(cites: of_check_mesh_src)_\n",
        )
        r = flag_uncited_claims(case)
        assert r["success"]
        assert self._signals(r) == set()

    def test_target_not_found(self, tmp_path: Path) -> None:
        r = flag_uncited_claims(str(tmp_path))
        assert not r["success"]
        assert r["reason"] == "target_not_found"

    def test_orphan_citation_detection_unit(self) -> None:
        index = {
            "tags": {"of_check_mesh_src"},
            "blobs": ['{"citation": "ghia, ghia & shin (1982) jcp 48"}'],
        }
        assert _orphan_citations("Ghia, Ghia & Shin (1982)", index) == []
        assert _orphan_citations("Bogus et al. (2099)", index) == ["Bogus 2099"]
        # No library -> orphan check is skipped, not failed.
        assert _orphan_citations("Bogus et al. (2099)", None) == []

    def test_orphan_ignores_camelcase_solver_names(self) -> None:
        # The "Foam" in icoFoam/simpleFoam/OpenFOAM is not an author surname,
        # and a token inside one parenthetical must not borrow a year that
        # belongs to a real citation elsewhere on the line.
        index = {
            "tags": set(),
            "blobs": ['{"citation": "versteeg & malalasekera (2007)"}'],
        }
        # icoFoam path beside a real parenthesised year -> only the real cite
        # is considered, and it resolves, so no orphan.
        assert (
            _orphan_citations(
                "corpus/incompressible/icoFoam/cavity/cavity.md, "
                "Versteeg & Malalasekera (2007)",
                index,
            )
            == []
        )
        # OpenFOAM is inside its own parenthetical and cannot reach the later
        # (2099); only the genuine "Bogus & Co (2099)" surfaces as the orphan.
        assert _orphan_citations(
            "of_check_mesh_src (OpenFOAM v2412 thresholds); Bogus & Co (2099)",
            index,
        ) == ["Bogus 2099"]

    def test_orphan_requires_parenthesised_year(self) -> None:
        # A bare 4-digit number that is not a parenthesised year (e.g. a cell
        # count) is not an author-year citation.
        assert _orphan_citations("Mesh with 2024 cells", {"tags": set(), "blobs": []}) == []

    def test_orphan_picks_author_adjacent_to_year(self) -> None:
        # A capitalised prose word earlier in the same line/field must not be
        # paired with a real citation's year later in it (the lines-mode case
        # where a whole table row is one unit) — the surname adjacent to the
        # parenthesised year is the author.
        index = {"tags": set(), "blobs": ['{"citation": "ghia, ghia & shin (1982)"}']}
        assert _orphan_citations(
            "Accept the 100x100 result vs Ghia, Ghia & Shin (1982).", index
        ) == []  # resolves to ghia — not a phantom "Accept 1982"
        assert _orphan_citations(
            "Accept the result; see Bogus et al. (2099).", index
        ) == ["Bogus 2099"]

    def test_self_admitted_gap_sentinel_not_flagged(self, tmp_path: Path) -> None:
        # record_step's empty-field sentinel ("_uncited choice_") is a schema
        # gap (surfaced via consultant_gaps), not a factual claim.
        case = self._write(
            tmp_path,
            "## [10:00:00] solver_config / ok — Gap entry\n\n"
            "- **Decision:** Adopt the tutorial template.\n"
            "- **Why:** _uncited choice — no annotation, reference, or paper cited._\n",
        )
        assert "self_admitted_uncited" not in self._signals(flag_uncited_claims(case))

    def test_contrastive_uncited_with_citation_not_flagged(self, tmp_path: Path) -> None:
        # "cited ..., not uncited" is contrastive prose in a cited entry, not an
        # admission — the bare word "uncited" must not trip the self-admit signal.
        case = self._write(
            tmp_path,
            "## [10:00:00] solver_config / ok — Reuse\n\n"
            "- **Decision:** Reuse the promoted corpus entry.\n"
            "- **Why:** The choices are cited to a prior validated run, not "
            "uncited re-derivations. _(cites: corpus/incompressible/icoFoam/"
            "cavity/cavity.md)_\n",
        )
        assert "self_admitted_uncited" not in self._signals(flag_uncited_claims(case))

    def test_regime_number_in_other_field_not_flagged(self, tmp_path: Path) -> None:
        # Blessed first-principles form: a number in the decision (Re=400) plus a
        # number-free regime derivation in the why must not co-trip regime_claim.
        case = self._write(
            tmp_path,
            "## [10:00:00] solver_config / ok — Steady solver\n\n"
            "- **Decision:** Use simpleFoam for the Re=400 cavity.\n"
            "- **Why:** A steady solve stalls once the 2-D cavity becomes "
            "time-periodic above a critical Reynolds number; the stall itself "
            "is the diagnostic.\n",
        )
        assert "regime_claim" not in self._signals(flag_uncited_claims(case))


class TestAssessGridConvergence:
    def test_good_when_second_order_and_small(self) -> None:
        from consultant_mcp.tools import assess_grid_convergence

        h = [0.05, 0.025, 0.0125]
        r = assess_grid_convergence(h, [1 + 3 * x**2 for x in h], quantity="Cd")
        assert r["success"] and r["verdict"] == "good"
        assert r["apparent_order"] == pytest.approx(2.0, abs=1e-6)
        assert "celik_2008" in r["cites"] and "Cd" in r["summary"]

    def test_marginal_when_uncertainty_above_target(self) -> None:
        from consultant_mcp.tools import assess_grid_convergence

        h = [1.0, 2.0, 4.0]
        r = assess_grid_convergence(h, [1 + 0.5 * x for x in h], gci_target=0.05)
        assert r["verdict"] == "marginal" and "refine" in r["recommendation"]

    def test_oscillatory_and_divergent(self) -> None:
        from consultant_mcp.tools import assess_grid_convergence

        assert assess_grid_convergence([1, 2, 4], [1.0, 1.1, 0.95])["verdict"] == "marginal"
        assert assess_grid_convergence([1, 2, 4], [1.0, 1.2, 1.25])["verdict"] == "poor"

    def test_profile_uses_median(self) -> None:
        from consultant_mcp.tools import assess_grid_convergence

        h = [1 / 20, 1 / 40, 1 / 80]
        prof = [[1 + 2 * x**2, 2 - 5 * x**2, 0.5 + x**2] for x in h]
        r = assess_grid_convergence(h, prof, quantity="u_centerline")
        assert r["success"] and r["verdict"] == "good"
