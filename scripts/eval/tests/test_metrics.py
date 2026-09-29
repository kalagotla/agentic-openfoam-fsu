"""Tests for the per-run metric functions.

Every metric that appears in a results table is tested here, including its
degenerate case (no decisions, no citations, no banner) — an aggregate
built on a metric that silently returns 0 instead of None for "not
measured" would read as a finding when it is an absence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from metrics import (
    ReferenceIndex,
    citation_stats,
    decision_coverage,
    field_completeness,
    gap_stats,
    hitl_stats,
    origin_tag_stats,
    phase_stats,
    resolve_citation,
    retry_stats,
    verdict_stats,
)
from report_parse import parse_report, parse_report_text

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def golden():
    return parse_report(FIXTURES / "report_golden.md")


@pytest.fixture
def index() -> ReferenceIndex:
    return ReferenceIndex.load(REPO_ROOT)


def entry_report(*blocks: str):
    return parse_report_text("\n".join(blocks))


def decision_block(
    phase: str = "mesh",
    status: str = "ok",
    title: str = "T",
    decision: str = "D",
    why: str = "",
    alternatives: str = "",
    when_it_breaks: str = "",
    cites: str = "",
) -> str:
    why_line = why + (f" _(cites: {cites})_" if cites else "")
    return (
        f"## [10:00:00] {phase} / {status} — {title}\n"
        "\n"
        f"- **Decision:** {decision}\n"
        f"- **Why:** {why_line}\n"
        f"- **Alternatives:** {alternatives}\n"
        f"- **When it breaks:** {when_it_breaks}\n"
    )


# ---------------------------------------------------------------------------
# Citation resolution
# ---------------------------------------------------------------------------


def test_manifest_id_resolves(index: ReferenceIndex) -> None:
    r = resolve_citation("of_check_mesh_src", index)
    assert r["resolved"] is True
    assert r["kind"] == "manifest_id"


def test_cached_file_name_resolves(index: ReferenceIndex) -> None:
    r = resolve_citation("of_check_mesh_src__primitiveMeshCheck.C", index)
    assert r["resolved"] is True
    assert r["kind"] == "manifest_file"


# The workshop repo ships the cavity corpus entry empty: step 1 of the demo
# earns it live. These tests need it present to resolve the citation.
_CAVITY_ENTRY = REPO_ROOT / "corpus/incompressible/icoFoam/cavity/cavity.md"
needs_cavity_entry = pytest.mark.skipif(
    not _CAVITY_ENTRY.is_file(),
    reason="cavity corpus entry not present (earned live in the workshop demo)",
)


@needs_cavity_entry
def test_corpus_annotation_path_resolves(index: ReferenceIndex) -> None:
    r = resolve_citation("corpus/incompressible/icoFoam/cavity/cavity.md", index)
    assert r["resolved"] is True
    assert r["kind"] == "corpus_annotation"


def test_author_year_citation_resolves_strongly(index: ReferenceIndex) -> None:
    # How a human writes it, not how the manifest keys it.
    r = resolve_citation("Ghia & Shin (1982)", index)
    assert r["resolved"] is True
    assert r["kind"] == "manifest_author_year"
    assert r["strength"] == "strong"


def test_reworded_citation_of_a_held_source_resolves_weakly(
    index: ReferenceIndex,
) -> None:
    # The library holds "OpenFOAM v2412 User Guide, 6.3 'Solution and
    # algorithm control'". Exact matching would call this fabricated, which
    # would be a fact about the matcher, not about the run.
    r = resolve_citation("OpenFOAM User Guide 6.3 (Solution and algorithm control)", index)
    assert r["resolved"] is True
    assert r["kind"] == "manifest_fuzzy"
    # Fuzzy hits are never strong, so they cannot inflate the headline rate.
    assert r["strength"] == "weak"


def test_tutorial_path_resolves_weakly(index: ReferenceIndex) -> None:
    r = resolve_citation("incompressible/simpleFoam/pitzDaily", index)
    assert r["resolved"] is True
    assert r["kind"] == "tutorial_path"
    assert r["strength"] == "weak"


def test_declared_absence_is_not_scored_as_a_failed_citation(
    index: ReferenceIndex,
) -> None:
    r = resolve_citation(
        "incompressible/icoFoam/cavity/cavity (no corpus annotation)", index
    )
    assert r["kind"] == "declared_absent"
    report = entry_report(
        decision_block(cites="incompressible/icoFoam/cavity/cavity (no corpus annotation)")
    )
    stats = citation_stats(report, index)
    assert stats["n_citations"] == 1
    assert stats["n_declared_absent"] == 1
    # Held out of the denominator: recording that no annotation exists is the
    # honesty the gap rule asks for, not a miss.
    assert stats["n_scored"] == 0
    assert stats["citation_resolution_rate"] is None


def test_unlibraried_url_does_not_resolve(index: ReferenceIndex) -> None:
    r = resolve_citation("https://example.com/some-blog-post", index)
    assert r["resolved"] is False
    # Named distinctly: pulling a source and citing it without adding it to
    # the library is a specific, fixable failure, not a generic miss.
    assert r["kind"] == "unlibraried_url"


def test_invented_citation_does_not_resolve(index: ReferenceIndex) -> None:
    r = resolve_citation("Smith 2031, Journal of Imaginary Fluids", index)
    assert r["resolved"] is False
    assert r["kind"] == "unresolved"


def test_missing_manifest_is_reported_not_assumed(tmp_path: Path) -> None:
    idx = ReferenceIndex.load(tmp_path)
    assert idx.available is False
    report = entry_report(decision_block(cites="ghia_1982"))
    stats = citation_stats(report, idx)
    # With no library, nothing can resolve — and the caller must be able to
    # tell that apart from a run that genuinely cited nothing real.
    assert stats["reference_library_available"] is False


@needs_cavity_entry
def test_citation_stats_on_the_golden_report(golden, index: ReferenceIndex) -> None:
    stats = citation_stats(golden, index)
    assert stats["n_citations"] == 4
    assert stats["n_resolved"] == 4
    assert stats["n_strong"] == 4
    assert stats["citation_resolution_rate"] == 1.0
    assert stats["strong_citation_rate"] == 1.0
    assert stats["cited_decision_rate"] == 1.0


def test_weak_resolutions_are_reported_apart_from_strong(
    index: ReferenceIndex,
) -> None:
    report = entry_report(
        decision_block(title="A", cites="ghia_1982"),
        decision_block(title="B", cites="incompressible/simpleFoam/pitzDaily"),
    )
    stats = citation_stats(report, index)
    assert stats["citation_resolution_rate"] == 1.0
    assert stats["strong_citation_rate"] == 0.5


def test_citation_stats_with_no_citations_returns_none_not_zero() -> None:
    report = entry_report(decision_block())
    stats = citation_stats(report, ReferenceIndex(set(), set(), set(), [], set()))
    assert stats["n_citations"] == 0
    assert stats["citation_resolution_rate"] is None


# ---------------------------------------------------------------------------
# Decision coverage
# ---------------------------------------------------------------------------


def test_decision_coverage_matches_on_any_keyword(golden) -> None:
    expected = [
        {"key": "template", "any_of": ["tutorial", "template"]},
        {"key": "mesh_resolution", "any_of": ["80x80", "grid", "cells"]},
        {"key": "turbulence_model", "any_of": ["kOmega", "kEpsilon", "laminar"]},
    ]
    cov = decision_coverage(golden, expected)
    assert cov["n_matched"] == 2
    assert cov["missing"] == ["turbulence_model"]
    assert cov["decision_coverage"] == pytest.approx(2 / 3)


def test_decision_coverage_with_empty_checklist_is_none() -> None:
    cov = decision_coverage(entry_report(decision_block()), [])
    assert cov["decision_coverage"] is None


def test_coverage_ignores_non_decision_entries() -> None:
    # An info entry mentioning the keyword must not count as a narrated choice.
    report = entry_report(
        "## [10:00:00] setup / info — Chose the kOmegaSST turbulence model\n"
    )
    cov = decision_coverage(report, [{"key": "turbulence", "any_of": ["komegasst"]}])
    assert cov["missing"] == ["turbulence"]


# ---------------------------------------------------------------------------
# Field completeness and gaps
# ---------------------------------------------------------------------------


def test_field_completeness_on_the_golden_report(golden) -> None:
    fc = field_completeness(golden)
    assert fc["n_decisions"] == 4
    assert fc["n_complete"] == 2
    assert fc["complete_rate"] == 0.5
    assert fc["per_field"]["decision"] == 4
    assert fc["per_field"]["when_it_breaks"] == 2


def test_citation_alone_counts_as_a_filled_why() -> None:
    report = entry_report(decision_block(why="", cites="ghia_1982"))
    fc = field_completeness(report)
    assert fc["per_field"]["why"] == 1


def test_gap_stats_on_the_golden_report(golden) -> None:
    g = gap_stats(golden)
    assert g["n_gapped_decisions"] == 2
    assert g["per_field"] == {"why": 0, "alternatives": 1, "when_it_breaks": 2}
    assert g["gapped_decision_rate"] == 0.5


def test_gap_stats_with_no_decisions_returns_none() -> None:
    report = entry_report("## [10:00:00] setup / info — Nothing decided\n")
    g = gap_stats(report)
    assert g["n_decisions"] == 0
    assert g["gapped_decision_rate"] is None


# ---------------------------------------------------------------------------
# Origin tags, retries, HITL, phases, verdict
# ---------------------------------------------------------------------------


def test_origin_tags_counted_by_kind() -> None:
    report = entry_report(
        decision_block(title="A", decision="simpleFoam (scenario-specified)"),
        decision_block(title="B", decision="80x80 grid (agent's call)"),
        decision_block(title="C", decision="Curly apostrophe (agent\u2019s call)"),
        decision_block(title="D", decision="Uniform spacing (deviation from scenario)"),
        decision_block(title="E", decision="Untagged choice"),
    )
    o = origin_tag_stats(report)
    assert o["counts"]["scenario_specified"] == 1
    assert o["counts"]["agent_call"] == 2
    assert o["counts"]["deviation"] == 1
    assert o["counts"]["untagged"] == 1
    assert o["untagged_titles"] == ["E"]
    assert o["tagged_rate"] == 0.8


def test_retry_stats_on_the_golden_report(golden) -> None:
    r = retry_stats(golden)
    assert r["n_retries"] == 1
    assert r["n_failures"] == 1
    assert r["n_failures_resolved"] == 1
    assert r["unresolved_failures"] == []
    assert r["dangling_retry_targets"] == []


def test_dangling_retry_target_is_flagged() -> None:
    report = parse_report_text(
        "## [10:00:00] mesh / fixed — Fixed something\n"
        "_retry of: 'An entry that was never recorded'_\n"
        "\n"
        "- **Decision:** Patched it\n"
    )
    r = retry_stats(report)
    assert r["dangling_retry_targets"] == ["An entry that was never recorded"]


def test_unresolved_failure_is_flagged() -> None:
    report = entry_report("## [10:00:00] mesh / error — blockMesh failed\n")
    r = retry_stats(report)
    assert r["unresolved_failures"] == ["blockMesh failed"]


def test_hitl_stats_counts_pending_review() -> None:
    report = parse_report_text(
        "## [10:00:00] validation / pending_review — Awaiting sign-off"
        "  **[PENDING REVIEW]**\n"
    )
    h = hitl_stats(report)
    assert h["n_pending_review"] == 1
    assert h["phases_paused"] == ["validation"]


def test_phase_stats_reports_missing_canonical_phases(golden) -> None:
    p = phase_stats(golden)
    assert p["n_steps"] == 6
    assert p["phases"]["mesh_quality"] == 2
    assert p["statuses"]["error"] == 1
    assert "convergence" in p["canonical_missing"]
    assert "mesh" not in p["canonical_missing"]


def test_verdict_stats_reads_the_banner(golden) -> None:
    v = verdict_stats(golden)
    assert v["finalized"] is True
    assert v["verdict"] == "REVIEW"
    assert all(v["banner_agrees_with_parse"].values())


def test_verdict_stats_on_an_unfinalized_run() -> None:
    v = verdict_stats(entry_report(decision_block()))
    assert v["finalized"] is False
    assert v["verdict"] is None


def test_banner_disagreement_is_surfaced() -> None:
    # A hand-edited banner claiming more steps than the narration holds.
    text = (
        "<!-- BEGIN SUMMARY - auto-generated, do not edit -->\n"
        "**VERDICT: PASS** — all good\n"
        "\n"
        "9 steps · 9 decisions · 0 retries · 0 gaps\n"
        "<!-- END SUMMARY -->\n"
        "\n" + decision_block()
    )
    v = verdict_stats(parse_report_text(text))
    assert v["banner_agrees_with_parse"]["steps"] is False


def test_every_metric_is_json_serialisable(golden, index: ReferenceIndex) -> None:
    payload = {
        "citations": citation_stats(golden, index),
        "coverage": decision_coverage(golden, [{"key": "k", "any_of": ["grid"]}]),
        "fields": field_completeness(golden),
        "gaps": gap_stats(golden),
        "origin": origin_tag_stats(golden),
        "retries": retry_stats(golden),
        "hitl": hitl_stats(golden),
        "phases": phase_stats(golden),
        "verdict": verdict_stats(golden),
    }
    assert json.loads(json.dumps(payload))["fields"]["n_decisions"] == 4
