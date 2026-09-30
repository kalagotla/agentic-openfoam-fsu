"""Tests for the fault corpus and the probe harness.

A detection benchmark is only as good as its ground truth, so these check
the corpus itself as much as the runner: that clean controls exist in
quantity, that every probe declares what is wrong with it, and that the
scoring cannot report a recall without the false-alarm rate that gives it
meaning.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from faults.injectors import (
    ALL_PROBES,
    clean_mesh,
    converged_residuals,
    diverging_residuals,
    severe_non_orthogonality,
    stalled_residuals,
)
from probe_runner import ProbeOutcome, run_all, run_probe, score

# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------


def test_the_corpus_has_enough_clean_controls() -> None:
    clean = [p for p in ALL_PROBES if not p.fault_present]
    # Without negatives, recall is meaningless: an assessor that flags
    # everything would score perfectly. The plan asks for at least 40%.
    assert len(clean) / len(ALL_PROBES) >= 0.40


def test_every_faulty_probe_says_where_the_fault_is() -> None:
    for probe in ALL_PROBES:
        if probe.fault_present:
            assert probe.localization, f"{probe.probe_id} has no localisation target"
            assert probe.fault_class != "none"


def test_probe_ids_are_unique() -> None:
    ids = [p.probe_id for p in ALL_PROBES]
    assert len(ids) == len(set(ids))


def test_the_corpus_spans_tool_and_reasoning_detection() -> None:
    # The split is the point of the taxonomy: it separates detection the
    # engineering provides from detection the model provides.
    assert any(p.tool_detectable for p in ALL_PROBES)
    assert any(not p.tool_detectable for p in ALL_PROBES)


def test_injected_faults_are_visible_in_the_artefact() -> None:
    probe = severe_non_orthogonality(78.4)
    assert "78.4" in probe.content
    assert "Mesh OK." not in probe.content


def test_clean_probes_keep_the_captured_log_intact() -> None:
    # The clean baseline is a real captured log; a synthetic one risks
    # being detectably synthetic.
    assert "Mesh OK." in clean_mesh().content


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


def test_a_severe_mesh_fault_is_detected_and_localised(tmp_path: Path) -> None:
    outcome = run_probe(severe_non_orthogonality(), tmp_path)
    assert outcome.detected is True
    assert outcome.localised is True


def test_a_clean_mesh_is_not_flagged(tmp_path: Path) -> None:
    assert run_probe(clean_mesh(), tmp_path).detected is False


def test_stalled_residuals_are_detected(tmp_path: Path) -> None:
    outcome = run_probe(stalled_residuals(), tmp_path)
    assert outcome.detected is True
    assert outcome.localised is True


def test_diverging_residuals_are_detected(tmp_path: Path) -> None:
    assert run_probe(diverging_residuals(), tmp_path).detected is True


def test_converged_residuals_are_not_flagged(tmp_path: Path) -> None:
    assert run_probe(converged_residuals(), tmp_path).detected is False


def test_reasoning_probes_are_reported_as_not_run(tmp_path: Path) -> None:
    from faults.injectors import borderline_non_orthogonality

    outcome = run_probe(borderline_non_orthogonality(), tmp_path)
    # Carried in the catalogue rather than dropped, so the coverage gap
    # stays visible instead of quietly shrinking the denominator.
    assert "not run" in outcome.detail


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def outcome(fault: bool, detected: bool, localised: bool = False) -> ProbeOutcome:
    return ProbeOutcome(
        probe_id=f"p{fault}{detected}{localised}",
        fault_class="mesh" if fault else "none",
        fault_present=fault,
        expected_detector="assess_mesh_quality",
        tool_detectable=True,
        detected=detected,
        localised=localised,
    )


def test_recall_never_travels_without_the_false_alarm_rate() -> None:
    s = score([outcome(True, True), outcome(False, True)])
    assert s["recall"]["point"] == 1.0
    # An assessor that flags everything scores perfect recall. The pair is
    # the only honest summary.
    assert s["false_alarm_rate"]["point"] == 1.0


def test_rates_carry_intervals() -> None:
    s = score([outcome(True, True) for _ in range(3)] + [outcome(False, False)])
    ci = s["recall"]
    assert ci["low"] < ci["point"] <= ci["high"]
    # Three for three is not proof.
    assert ci["low"] < 1.0


def test_missed_faults_are_named() -> None:
    s = score([outcome(True, False), outcome(True, True)])
    assert len(s["missed"]) == 1


def test_localisation_is_stricter_than_detection() -> None:
    s = score([outcome(True, True, localised=False)])
    assert s["recall"]["point"] == 1.0
    assert s["localisation_rate"]["point"] == 0.0


def test_scoring_with_no_clean_controls_reports_absence() -> None:
    s = score([outcome(True, True)])
    # No negatives means no false-alarm rate — reported as absent, not zero.
    assert s["false_alarm_rate"] is None


def test_the_shipped_corpus_runs_end_to_end() -> None:
    result = run_all()
    s = result["summary"]
    assert s["n_run"] >= 15
    assert s["recall"] is not None
    assert s["false_alarm_rate"] is not None
    # Recall of 1.0 on this corpus is a real result, but the interval keeps
    # it honest at this sample size.
    assert s["recall"]["low"] < 1.0


@pytest.mark.parametrize("probe", ALL_PROBES, ids=lambda p: p.probe_id)
def test_every_probe_materialises(probe, tmp_path: Path) -> None:
    directory = probe.write(tmp_path / probe.probe_id)
    assert (directory / probe.artefact).is_file()
