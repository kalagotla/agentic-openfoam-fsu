"""Cross-server integration: the build-from-runs corpus loop.

The headline loop crosses two servers. ``openfoam.record_step`` WRITES the
REPORT.md entry format; ``consultant.draft_annotation_from_report`` READS it;
a human then promotes ``<name>.draft.md`` -> ``<name>.md`` and
``get_tutorial_annotation`` returns it. The writer and reader carry duplicated,
unshared parse contracts, so the per-server tests (which use hand-authored
REPORT fixtures) cannot catch drift between them. These tests feed REAL
``record_step`` output through the draft + promote path so a future change to
record_step's markdown shape that silently breaks the draft parser fails here.

``openfoam_mcp`` is imported lazily and the test skips if it is not installed
(the two servers are separate workspace packages; the shared dev venv has both).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from consultant_mcp.annotations import ENV_ROOT_OVERRIDE
from consultant_mcp.tools import (
    draft_annotation_from_report,
    get_tutorial_annotation,
)

TUTORIAL = "incompressible/icoFoam/cavity/cavity"


@pytest.fixture
def corpus_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp repo root with an empty corpus/, pointed at via the env override."""
    root = tmp_path / "repo"
    (root / "corpus").mkdir(parents=True)
    monkeypatch.setenv(ENV_ROOT_OVERRIDE, str(root))
    return root


def _record_real_entries(case: Path) -> None:
    """Two real record_step decision entries — the actual writer output."""
    of = pytest.importorskip("openfoam_mcp.tools")
    case.mkdir(parents=True, exist_ok=True)
    of.record_step(
        str(case),
        phase="solver_config",
        status="ok",
        title="Steady solver",
        decision="Swap transient icoFoam to steady simpleFoam.",
        why="The Re=400 cavity is a steady-laminar benchmark.",
        alternatives="Transient pisoFoam marched to steady state.",
        when_it_breaks="High Re where the cavity becomes time-periodic.",
        citations=["Ghia, Ghia & Shin (1982)"],
    )
    of.record_step(
        str(case),
        phase="mesh_quality",
        status="ok",
        title="Mesh accepted",
        decision="Accept the 100x100 grid.",
        why="checkMesh reports an orthogonal grid.",
        citations=["of_check_mesh_src"],
    )


def test_record_step_output_drafts_with_decisions(
    tmp_path: Path, corpus_root: Path
) -> None:
    case = tmp_path / "case"
    _record_real_entries(case)

    res = draft_annotation_from_report(
        str(case),
        TUTORIAL,
        solver="simpleFoam",
        physics="steady laminar lid-driven cavity",
    )
    assert res["success"] is True
    # Both real decision entries survived the writer -> reader parse contract.
    assert res["n_decisions"] == 2

    draft = Path(res["draft_path"])
    assert draft.is_file()
    assert draft.name.endswith(".draft.md")
    body = draft.read_text(encoding="utf-8")
    assert "Swap transient icoFoam to steady simpleFoam" in body
    assert "Accept the 100x100 grid" in body

    # The draft is staging only — get_tutorial_annotation must still miss until
    # it is promoted.
    assert get_tutorial_annotation(TUTORIAL)["success"] is False


def test_promote_roundtrip_makes_annotation_live(
    tmp_path: Path, corpus_root: Path
) -> None:
    case = tmp_path / "case"
    _record_real_entries(case)

    res = draft_annotation_from_report(str(case), TUTORIAL, solver="simpleFoam")
    draft = Path(res["draft_path"])

    # The human promotion step: rename <name>.draft.md -> <name>.md.
    live = draft.with_name(draft.name[: -len(".draft.md")] + ".md")
    draft.rename(live)

    got = get_tutorial_annotation(TUTORIAL)
    assert got["success"] is True
    assert got["annotation_path"].endswith("cavity.md")
    # The promoted file parses (valid frontmatter + body) and carries the run's
    # decisions — the reuse payoff a later run inherits.
    assert "Swap transient icoFoam to steady simpleFoam" in got["body"]
