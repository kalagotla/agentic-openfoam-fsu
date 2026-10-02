"""Tests for the REPORT.md parser.

Two kinds, deliberately. **Round-trip** tests drive the real
``record_step`` / ``finalize_report`` from the OpenFOAM server and parse
what they emit — so the parser cannot drift from the emitter without a
test going red. **Golden** tests parse a checked-in fixture, so a parser
regression is caught even if the emitter changes in lockstep.

The scorer's numbers are only as trustworthy as this parser, which is why
it is tested before anything is scored with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openfoam_mcp import tools as of_tools
from report_parse import (
    GAP_ALTS,
    GAP_BREAKS,
    GAP_WHY,
    parse_report,
    parse_report_text,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def case(tmp_path: Path) -> Path:
    d = tmp_path / "case"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Round-trip against the real emitter
# ---------------------------------------------------------------------------


def test_full_entry_round_trips(case: Path) -> None:
    of_tools.record_step(
        str(case),
        phase="solver_config",
        status="ok",
        title="Steady SIMPLE for a steady benchmark",
        decision="simpleFoam over icoFoam (agent's call)",
        why="Ghia 1982 tabulates a steady solution; SIMPLE reaches it directly",
        alternatives="icoFoam run to steady state — wastes iterations on transients",
        when_it_breaks="Above the steady-solution limit the solve stalls",
        citations=["ghia_1982", "corpus/incompressible/icoFoam/cavity/cavity.md"],
        details="Adopted the tutorial fvSolution and changed only the solver.",
    )

    report = parse_report(case)
    assert len(report.entries) == 1
    e = report.entries[0]
    assert e.phase == "solver_config"
    assert e.status == "ok"
    assert e.title == "Steady SIMPLE for a steady benchmark"
    assert e.decision == "simpleFoam over icoFoam (agent's call)"
    assert e.why.startswith("Ghia 1982 tabulates")
    assert "_(cites:" not in e.why
    assert e.citations == [
        "ghia_1982",
        "corpus/incompressible/icoFoam/cavity/cavity.md",
    ]
    assert e.alternatives.startswith("icoFoam run to steady state")
    assert e.when_it_breaks.startswith("Above the steady-solution limit")
    assert "Adopted the tutorial fvSolution" in e.details
    assert e.is_decision is True
    assert e.gaps == []


def test_empty_consultant_fields_round_trip_as_gaps(case: Path) -> None:
    of_tools.record_step(
        str(case),
        phase="mesh",
        status="ok",
        title="80x80 uniform grid",
        decision="Refined to 80x80",
    )

    e = parse_report(case).entries[0]
    # The rendered sentinels are absence, not content.
    assert e.why == ""
    assert e.alternatives == ""
    assert e.when_it_breaks == ""
    assert e.gaps == ["why", "alternatives", "when_it_breaks"]


def test_citations_alone_close_the_why_gap(case: Path) -> None:
    of_tools.record_step(
        str(case),
        phase="mesh",
        status="ok",
        title="Grid from the reference",
        decision="129x129 uniform",
        citations=["ghia_1982"],
    )

    e = parse_report(case).entries[0]
    assert e.citations == ["ghia_1982"]
    assert "why" not in e.gaps


def test_info_entry_is_not_a_decision(case: Path) -> None:
    of_tools.record_step(
        str(case),
        phase="setup",
        status="info",
        title="Case directory prepared",
        details="cases/work/lid-cavity created.",
    )

    report = parse_report(case)
    assert report.entries[0].is_decision is False
    assert report.decisions == []


def test_pending_review_is_flagged_and_counts_as_a_decision(case: Path) -> None:
    of_tools.record_step(
        str(case),
        phase="validation",
        status="pending_review",
        title="Awaiting sign-off on the comparison",
    )

    e = parse_report(case).entries[0]
    assert e.pending_review is True
    assert e.status == "pending_review"
    assert e.is_decision is True


def test_retry_chain_round_trips(case: Path) -> None:
    of_tools.record_step(
        str(case), phase="mesh_quality", status="error", title="Non-orthogonality 78 deg"
    )
    of_tools.record_step(
        str(case),
        phase="mesh_quality",
        status="fixed",
        title="Regraded the block",
        decision="Reduced expansion ratio to 4",
        retry_of="Non-orthogonality 78 deg",
    )

    report = parse_report(case)
    assert len(report.entries) == 2
    assert report.entries[1].retry_of == "Non-orthogonality 78 deg"
    assert len(report.retries) == 1


def test_tables_round_trip_with_escaped_pipes(case: Path) -> None:
    of_tools.record_step(
        str(case),
        phase="mesh_quality",
        status="ok",
        title="checkMesh clean",
        tables={
            "checkMesh metrics": [
                {"metric": "max_non_orthogonality", "value": "42.1", "verdict": "good"},
                {"metric": "max_skewness", "value": "0.8", "verdict": "good"},
            ],
            "Patches": [{"name": "movingWall", "type": "wall | patch", "faces": "80"}],
        },
    )

    e = parse_report(case).entries[0]
    assert set(e.tables) == {"checkMesh metrics", "Patches"}
    rows = e.tables["checkMesh metrics"]
    assert len(rows) == 2
    assert rows[0] == {
        "metric": "max_non_orthogonality",
        "value": "42.1",
        "verdict": "good",
    }
    # A pipe inside a cell is escaped on write and must come back intact.
    assert e.tables["Patches"][0]["type"] == "wall | patch"


def test_title_containing_an_em_dash_is_kept_whole(case: Path) -> None:
    of_tools.record_step(
        str(case),
        phase="validation",
        status="ok",
        title="u(y) matches — L2 = 0.0023",
    )

    e = parse_report(case).entries[0]
    assert e.title == "u(y) matches — L2 = 0.0023"
    assert e.status == "ok"


def test_banner_and_index_round_trip(case: Path) -> None:
    of_tools.record_step(
        str(case),
        phase="mesh",
        status="ok",
        title="80x80 grid",
        decision="Uniform 80x80",
        why="Resolves the secondary corner vortices",
        citations=["ghia_1982"],
    )
    of_tools.record_step(
        str(case),
        phase="validation",
        status="ok",
        title="Within the Ghia band",
        decision="Accept: u(y) L2 = 0.0023, v(x) L2 = 0.0106",
        why="Both profiles inside the 0.05 relative-L2 tolerance",
        alternatives="Refine to 129x129 — unnecessary once inside tolerance",
        when_it_breaks="A coarser grid misses the corner vortices",
        citations=["ghia_1982"],
    )
    # finalize_report checks a narrated PASS against the saved analysis.
    saved = case / "postProcessing/analysis/run_analysis_result.json"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text('{"metrics": {"u": {"within_tolerance": true}, "v": {"within_tolerance": true}}}')
    of_tools.finalize_report(str(case))

    report = parse_report(case)
    assert report.finalized is True
    assert report.banner is not None
    assert report.banner.verdict == "PASS"
    assert report.banner.outcome == "Within the Ghia band"
    assert report.banner.steps == 2
    assert report.banner.decisions == 2
    assert report.banner.retries == 0
    # The mesh entry is missing alternatives + when_it_breaks, so one gap entry.
    assert report.banner.gaps == 1

    # Entries still parse cleanly with the generated blocks present.
    assert len(report.entries) == 2
    assert len(report.decisions_index) == 2
    assert report.decisions_index[0]["decision"] == "Uniform 80x80"

    # Parser-derived counts agree with the banner the server rendered — the
    # two are computed independently, so agreement is a real cross-check.
    assert len(report.entries) == report.banner.steps
    assert len(report.decisions) == report.banner.decisions
    assert sum(1 for e in report.entries if e.gaps) == report.banner.gaps


def test_incomplete_run_banner_reads_incomplete(case: Path) -> None:
    of_tools.record_step(
        str(case), phase="mesh", status="ok", title="Meshed", decision="80x80"
    )
    of_tools.finalize_report(str(case))

    report = parse_report(case)
    assert report.banner is not None
    assert report.banner.verdict == "INCOMPLETE"


# ---------------------------------------------------------------------------
# Golden fixture — catches parser regressions independently of the emitter
# ---------------------------------------------------------------------------


def test_golden_fixture_counts() -> None:
    report = parse_report(FIXTURES / "report_golden.md")

    assert len(report.entries) == 6
    assert len(report.decisions) == 4
    assert len(report.retries) == 1
    assert [e.phase for e in report.entries] == [
        "setup",
        "geometry",
        "mesh",
        "mesh_quality",
        "mesh_quality",
        "validation",
    ]
    assert [e.status for e in report.entries] == [
        "info",
        "ok",
        "ok",
        "error",
        "fixed",
        "warning",
    ]

    gapped = [e for e in report.entries if e.gaps]
    assert len(gapped) == 2
    assert report.entries[2].gaps == ["alternatives", "when_it_breaks"]

    assert report.banner is not None
    assert report.banner.verdict == "REVIEW"
    assert report.entries[-1].tables["Comparison vs ghia_1982"][1]["verdict"] == "fail"


def test_missing_report_is_empty_not_an_error(tmp_path: Path) -> None:
    report = parse_report(tmp_path / "nope")
    assert report.entries == []
    assert report.banner is None
    assert report.finalized is False


def test_truncated_entry_keeps_what_it_can() -> None:
    text = (
        "## [10:00:00] mesh / ok — Truncated mid-entry\n"
        "\n"
        "- **Decision:** Started refining\n"
        "<details><summary>why · alternatives · when it breaks</summary>\n"
        "\n"
        "- **Why:** Corner vortices were unresolved\n"
    )
    report = parse_report_text(text)
    assert len(report.entries) == 1
    assert report.entries[0].decision == "Started refining"
    assert report.entries[0].why == "Corner vortices were unresolved"
    assert "when_it_breaks" in report.entries[0].gaps


def test_gap_sentinels_are_recognised_verbatim() -> None:
    text = (
        "## [10:00:00] mesh / ok — Sentinels\n"
        "\n"
        "- **Decision:** Something\n"
        f"- **Why:** {GAP_WHY}\n"
        f"- **Alternatives:** {GAP_ALTS}\n"
        f"- **When it breaks:** {GAP_BREAKS}\n"
    )
    e = parse_report_text(text).entries[0]
    assert (e.why, e.alternatives, e.when_it_breaks) == ("", "", "")
    assert e.gaps == ["why", "alternatives", "when_it_breaks"]


# ---------------------------------------------------------------------------
# Two parsers read the same file
# ---------------------------------------------------------------------------


def test_the_two_report_parsers_agree() -> None:
    """The scorer and the consultant server must read REPORT.md the same way.

    `draft_annotation_from_report` carries its own parser, so the corpus
    draft and the evaluation record are produced by different code reading
    the same file. If they drift, a decision could be scored here and
    dropped from the annotation there — or the reverse — and nothing would
    say so. The plan proposes merging them; until that happens this is the
    guard that would catch the drift.
    """
    from consultant_mcp.tools import _parse_report_entries

    text = (Path(__file__).parent / "fixtures" / "report_golden.md").read_text(
        encoding="utf-8"
    )
    scored = [
        e
        for e in parse_report_text(text).entries
        if any([e.decision, e.why, e.alternatives, e.when_it_breaks, e.citations])
    ]
    drafted = _parse_report_entries(text)

    assert [e.title for e in scored] == [e["title"] for e in drafted]
    assert [e.decision for e in scored] == [e["decision"] for e in drafted]
    assert [e.phase for e in scored] == [e["phase"] for e in drafted]
