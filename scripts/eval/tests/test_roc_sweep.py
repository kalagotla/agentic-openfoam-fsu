"""Tests for the detection curve.

The curve's job is to make a recall number comparable: a detector that
flags everything scores perfect recall, so recall only means something
next to the false-alarm rate it was bought at. These tests pin the
properties that make the curve honest — that it moves the real thresholds
rather than a copy of them, that it is monotone in the right direction,
and that a false-alarm budget the tool cannot meet is reported as no
operating point rather than as the nearest one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from consultant_mcp.assessments import (
    DEFAULT_MESH_THRESHOLDS,
    DEFAULT_RESIDUAL_THRESHOLDS,
)
from roc_sweep import (
    DEFAULT_FACTORS,
    mesh_probes,
    operating_point,
    recall_at_false_alarm_rate,
    residual_probes,
    sweep,
)


def test_scaling_moves_every_band_together() -> None:
    tight = DEFAULT_MESH_THRESHOLDS.scaled(0.5)
    loose = DEFAULT_MESH_THRESHOLDS.scaled(2.0)
    assert tight.non_orthogonality == (30.0, 35.0, 40.0)
    assert loose.skewness == (2.0, 8.0, 20.0)
    assert loose.aspect_ratio == (20.0, 200.0, 2000.0)


def test_a_degenerate_cell_is_broken_at_any_strictness() -> None:
    # 90 degrees is checkMesh calling the cell broken, not a quality band.
    for factor in (0.5, 1.0, 4.0):
        scaled = DEFAULT_MESH_THRESHOLDS.scaled(factor)
        assert scaled.degenerate_non_orthogonality == 90.0


def test_scaling_by_a_non_positive_factor_is_refused() -> None:
    with pytest.raises(ValueError):
        DEFAULT_MESH_THRESHOLDS.scaled(0.0)


def test_the_shipped_point_is_on_the_curve(tmp_path: Path) -> None:
    # Otherwise the curve describes a tool nobody runs.
    assert 1.0 in DEFAULT_FACTORS
    report = sweep(tmp_path, factors=(1.0,))
    assert report["shipped"] is not None
    assert report["shipped"]["factor"] == 1.0


def test_loosening_never_raises_recall(tmp_path: Path) -> None:
    """Monotonicity is what makes this a curve rather than a scatter.

    A looser threshold cannot catch a fault a stricter one missed, so
    recall must be non-increasing in the factor. If it is not, the sweep
    is not moving the decision boundary it thinks it is.
    """
    probes = mesh_probes()
    recalls = [
        operating_point(probes, f, tmp_path)["recall"]
        for f in (0.6, 1.0, 2.0, 6.0)
    ]
    assert recalls == sorted(recalls, reverse=True)


def test_tightening_never_lowers_the_false_alarm_rate(tmp_path: Path) -> None:
    probes = mesh_probes()
    alarms = [
        operating_point(probes, f, tmp_path)["false_alarm_rate"]
        for f in (0.6, 1.0, 2.0, 6.0)
    ]
    assert alarms == sorted(alarms, reverse=True)


def test_an_unmeetable_budget_has_no_operating_point() -> None:
    points = [
        {"factor": 1.0, "recall": 1.0, "false_alarm_rate": 0.25},
        {"factor": 2.0, "recall": 0.6, "false_alarm_rate": 0.25},
    ]
    # Reporting the nearest point instead would credit the tool with a
    # quietness it never achieves.
    assert recall_at_false_alarm_rate(points, 0.0) is None


def test_the_budget_picks_the_best_recall_within_it() -> None:
    points = [
        {"factor": 0.8, "recall": 1.0, "false_alarm_rate": 0.25},
        {"factor": 2.0, "recall": 0.6, "false_alarm_rate": 0.10},
        {"factor": 4.0, "recall": 0.4, "false_alarm_rate": 0.00},
    ]
    assert recall_at_false_alarm_rate(points, 0.25)["factor"] == 0.8
    assert recall_at_false_alarm_rate(points, 0.10)["factor"] == 2.0


# ---------------------------------------------------------------------------
# The residual detector's knob points the other way
# ---------------------------------------------------------------------------


def test_sensitivity_moves_every_residual_cut_toward_flagging() -> None:
    """The reason this is `sensitivity` and not a plain scale.

    These cuts are not oriented alike: a smaller oscillation cut flags
    more, a smaller stall cut flags less. A single multiplier would move
    them against each other, and the resulting curve would not be ordered.
    """
    base = DEFAULT_RESIDUAL_THRESHOLDS
    eager = base.at_sensitivity(2.0)

    assert eager.oscillating_cov < base.oscillating_cov   # smaller wobble flags
    assert eager.stalled_cov > base.stalled_cov           # larger wobble flags
    assert eager.diverging_factor < base.diverging_factor  # smaller rise flags
    assert eager.converged < base.converged                # harder to pass


def test_a_non_positive_sensitivity_is_refused() -> None:
    with pytest.raises(ValueError):
        DEFAULT_RESIDUAL_THRESHOLDS.at_sensitivity(0.0)


def test_residual_recall_never_falls_as_sensitivity_rises(tmp_path: Path) -> None:
    probes = residual_probes()
    recalls = [
        operating_point(probes, f, tmp_path, "assess_residuals")["recall"]
        for f in (0.6, 1.0, 2.0, 6.0)
    ]
    assert recalls == sorted(recalls)


def test_the_residual_sweep_covers_only_its_own_probes(tmp_path: Path) -> None:
    # A curve built over probes another detector owns would report that
    # detector's blind spots as this one's.
    report = sweep(tmp_path, factors=(1.0,), detector="assess_residuals")
    assert report["detector"] == "assess_residuals"
    assert report["n_probes"] == len(residual_probes())
    assert all(p.expected_detector == "assess_residuals" for p in residual_probes())


def test_each_detector_writes_its_probes_somewhere_of_its_own(
    tmp_path: Path,
) -> None:
    # Two detectors sweeping the same probe id must not share a directory,
    # or the second overwrites what the first is being scored on.
    operating_point(mesh_probes(), 1.0, tmp_path, "assess_mesh_quality")
    operating_point(residual_probes(), 1.0, tmp_path, "assess_residuals")
    dirs = {d.name for d in tmp_path.iterdir() if d.is_dir()}
    assert any(d.startswith("assess_mesh_quality") for d in dirs)
    assert any(d.startswith("assess_residuals") for d in dirs)
