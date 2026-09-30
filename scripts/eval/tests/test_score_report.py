"""Tests for the run scorer.

The scorer's job is to report what a run's artefacts actually show. These
tests pin the two ways that can go wrong: reading an intentional absence
as a failure, and reading an unscoreable artefact as a pass.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from score_report import (
    authoring_stats,
    detect_run_kind,
    narration_stats,
    score_case,
    validation_stats,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHIVED_CASE = REPO_ROOT / "cases" / "examples" / "lid-cavity" / "baseline"


def write_metrics(case: Path, payload: dict) -> Path:
    out = case / "postProcessing" / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(payload))
    return out / "metrics.json"


@pytest.fixture
def case(tmp_path: Path) -> Path:
    d = tmp_path / "case"
    (d / "system").mkdir(parents=True)
    for name in ("controlDict", "fvSchemes", "fvSolution"):
        (d / "system" / name).write_text("application simpleFoam;\n")
    return d


# ---------------------------------------------------------------------------
# Run kind — an archive is not a failed run
# ---------------------------------------------------------------------------


def test_archived_case_is_detected(case: Path) -> None:
    (case / "REPORT.md").write_text("# Case setup report\n")
    write_metrics(case, {"verdict": "PASS"})
    assert detect_run_kind(case) == "archive"


def test_live_run_is_detected(case: Path) -> None:
    (case / "log.blockMesh").write_text("End\n")
    assert detect_run_kind(case) == "live"


def _tracked(path: Path) -> bool:
    # In the workshop repo this directory is written by an attendee's own
    # Step 1 run (end_of_run.archive_case), so only a committed, curated
    # baseline has contents this test can pin.
    r = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path / "REPORT.md")],
        cwd=REPO_ROOT, capture_output=True,
    )
    return r.returncode == 0


def test_archive_reports_setup_as_unmeasured_not_failed() -> None:
    if not ARCHIVED_CASE.is_dir() or not _tracked(ARCHIVED_CASE):
        pytest.skip("no committed archived baseline")
    record = score_case(ARCHIVED_CASE)
    assert record["run"]["run_kind"] == "archive"
    # The mesh is skipped by archive_case on purpose. Reporting False here
    # would turn an intentional omission into a false failure.
    assert record["capability"]["setup_success"] is None
    assert record["capability"]["validated"] is True


def test_live_run_missing_its_mesh_is_a_real_failure(case: Path) -> None:
    (case / "log.blockMesh").write_text("FOAM FATAL ERROR\n")
    record = score_case(case)
    assert record["run"]["run_kind"] == "live"
    assert record["capability"]["setup_success"] is False


# ---------------------------------------------------------------------------
# Validation — an unscoreable metrics.json is a finding, not a pass
# ---------------------------------------------------------------------------


def test_checks_schema_drives_the_verdict(case: Path) -> None:
    write_metrics(
        case,
        {
            "verdict": "PASS",
            "checks": [
                {"quantity": "u", "within_tolerance": True},
                {"quantity": "v", "within_tolerance": False},
            ],
        },
    )
    stats = validation_stats(case)
    assert stats["schema"] == "checks"
    # Per-check booleans win over a top-level verdict string that disagrees:
    # they come straight from compare_profiles, the tested code.
    assert stats["validated"] is False


def test_verdict_only_schema_is_a_fallback(case: Path) -> None:
    write_metrics(case, {"verdict": "PASS"})
    stats = validation_stats(case)
    assert stats["schema"] == "verdict_only"
    assert stats["validated"] is True


def test_nonconforming_metrics_are_unscoreable_not_failing(case: Path) -> None:
    write_metrics(case, {"u_l2": 0.002, "v_l2": 0.01})
    stats = validation_stats(case)
    assert stats["schema"] == "nonconforming"
    assert stats["validated"] is None


def test_absent_metrics_json_is_unscoreable(case: Path) -> None:
    stats = validation_stats(case)
    assert stats["metrics_json_present"] is False
    assert stats["validated"] is None


def test_missing_provenance_is_itemised(case: Path) -> None:
    write_metrics(case, {"verdict": "PASS", "provenance": {"git_commit": "abc123"}})
    stats = validation_stats(case)
    assert stats["provenance_present"] == ["git_commit"]
    assert "numpy_version" in stats["provenance_missing"]


def test_first_try_validated_requires_knowing_the_verdict(case: Path) -> None:
    record = score_case(case)
    assert record["capability"]["validated"] is None
    # Cannot be "first try" if we do not know it validated at all.
    assert record["capability"]["first_try_validated"] is None


def test_application_is_read_from_control_dict(case: Path) -> None:
    assert authoring_stats(case)["application"] == "simpleFoam"


# ---------------------------------------------------------------------------
# Convergence — the classification is the pattern, not the quality band
# ---------------------------------------------------------------------------


def fake_residuals(monkeypatch, fields: list[dict]) -> None:
    from consultant_mcp import tools as consultant

    monkeypatch.setattr(
        consultant,
        "assess_residuals",
        lambda _p: {"success": True, "fields": fields},
    )


def test_converged_reads_the_pattern_not_the_verdict(case: Path, monkeypatch) -> None:
    # assess_residuals returns two judgements per field: `pattern` is the
    # convergence classification and `verdict` is the quality band. A
    # converged field is spelled pattern="converged", verdict="good", so
    # reading `verdict` would report a converged run as unconverged — which
    # is exactly what the first scored live run did.
    fake_residuals(
        monkeypatch,
        [
            {"field": "Ux", "pattern": "converged", "verdict": "good"},
            {"field": "p", "pattern": "converged", "verdict": "good"},
        ],
    )
    from score_report import convergence_stats

    stats = convergence_stats(case)
    assert stats["converged"] is True
    assert stats["patterns"] == ["converged"]


def test_a_stalled_field_blocks_convergence(case: Path, monkeypatch) -> None:
    fake_residuals(
        monkeypatch,
        [
            {"field": "Ux", "pattern": "converged", "verdict": "good"},
            {"field": "p", "pattern": "stalled", "verdict": "marginal"},
        ],
    )
    from score_report import convergence_stats

    stats = convergence_stats(case)
    assert stats["converged"] is False
    assert stats["patterns"] == ["converged", "stalled"]


def test_missing_solver_log_leaves_convergence_unmeasured(case: Path) -> None:
    from score_report import convergence_stats

    out = convergence_stats(case)
    assert out["converged"] is None
    assert out["reason"] == "solver_log_missing"


def test_checks_keyed_by_name_are_read(case: Path) -> None:
    # A script writing {"u_centerline": compare_profiles(...)} produces the
    # same evidence as one appending to a checks list. Reading only the list
    # form would report a validated run as unscoreable purely over how its
    # script happened to collect results — which is what the first
    # subscription run did.
    write_metrics(
        case,
        {
            "u_centerline": {"within_tolerance": True, "l2_error": 0.0016},
            "v_centerline": {"within_tolerance": True, "l2_error": 0.0359},
            "provenance": {"git_commit": "abc"},
        },
    )
    stats = validation_stats(case)
    assert stats["schema"] == "checks_by_name"
    assert stats["validated"] is True
    assert len(stats["checks"]) == 2


def test_one_failing_keyed_check_fails_the_run(case: Path) -> None:
    write_metrics(
        case,
        {
            "u_centerline": {"within_tolerance": True},
            "v_centerline": {"within_tolerance": False},
        },
    )
    assert validation_stats(case)["validated"] is False


def test_a_provenance_block_is_not_mistaken_for_a_check(case: Path) -> None:
    write_metrics(case, {"provenance": {"git_commit": "abc", "numpy_version": "2"}})
    stats = validation_stats(case)
    # Provenance carries no within_tolerance, so it cannot be read as a
    # passing check — which would turn a file with no results at all into a
    # pass.
    assert stats["schema"] == "nonconforming"
    assert stats["validated"] is None


# ---------------------------------------------------------------------------
# How far a run got
# ---------------------------------------------------------------------------


def test_phase_reached_tracks_the_pipeline(case: Path) -> None:
    from score_report import phase_reached

    authored = {"case_authored": True}
    assert phase_reached(authored, {}, {}, {}) == "authored"
    assert phase_reached(authored, {"meshed": True}, {}, {}) == "meshed"
    assert phase_reached(authored, {"meshed": True}, {"solved": True}, {}) == "solved"
    assert (
        phase_reached(authored, {"meshed": True}, {"solved": True}, {"validated": True})
        == "validated"
    )


def test_nothing_authored_reads_as_nothing() -> None:
    from score_report import phase_reached

    assert phase_reached({"case_authored": False}, {}, {}, {}) == "nothing"


def test_coverage_says_when_the_run_stopped_early(case: Path) -> None:
    # A run that stopped after authoring cannot have narrated a mesh
    # decision. Without this the checklist gap reads as an agent that failed
    # to narrate rather than a run that never got there.
    record = score_case(case)
    assert record["run"]["phase_reached"] == "authored"
    assert record["trust"]["decision_coverage"]["complete_run"] is False


# ---------------------------------------------------------------------------
# Narration folded into the record
# ---------------------------------------------------------------------------


def test_narration_travels_with_the_rest_of_the_record(case: Path) -> None:
    (case / "REPORT.md").write_text(
        "## [10:00:00] solver_config / ok — Solver\n"
        "\n"
        "- **Decision:** simpleFoam for the steady incompressible solve\n"
    )
    record = score_case(case)
    # Scored in the same pass as everything else, so a run's trust numbers
    # and its narration numbers cannot drift apart.
    assert "narration" in record
    assert record["narration"]["precision"] is not None


def test_narration_recall_says_why_it_is_absent(case: Path) -> None:
    (case / "REPORT.md").write_text("## [10:00:00] mesh / ok — Meshed\n")
    record = score_case(case)
    # No template means the recall half cannot run; the precision half still
    # stands and the reason is recorded rather than the number invented.
    assert record["narration"]["recall"] is None
    assert record["narration"]["recall_unavailable"]


def test_an_audit_failure_is_recorded_not_raised(case: Path, monkeypatch) -> None:
    import score_report

    def boom(*_a, **_k):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(score_report, "narration_audit", boom)
    record = score_case(case)
    # One broken audit must not cost the whole record.
    assert "error" in record["narration"]
    assert record["capability"] is not None


def test_the_record_says_where_the_template_came_from(tmp_path: Path) -> None:
    """Recall against a declared template is weaker than against a fixed one.

    The suite names a template for a few cases only, so most runs are scored
    against the one their own report declares. Presenting both as a single
    number would hide that the second has a denominator the run chose.
    """
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application     simpleFoam;\n")
    (case / "REPORT.md").write_text(
        "## [10:00:00] geometry / ok — Template\n"
        "\n"
        "- **Decision:** simpleFoam for the steady solve.\n"
    )
    stats = narration_stats(case, None)
    assert stats["template_source"] == "unresolved"
    assert stats["recall"] is None
