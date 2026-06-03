"""Tests for OpenFOAM MCP tools.

These tests exercise the tools directly, without starting the MCP server.
That's the point of keeping ``tools.py`` free of decorators — we can unit
test every tool against the Pitz-Daily baseline case and know the server
will work once wired up.

Tests that shell out to OpenFOAM (run_blockmesh, run_solver) skip when
OpenFOAM isn't on PATH; pure-Python tests (write_dict) always run.

Run with: ``uv run pytest servers/openfoam/tests``
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from openfoam_mcp import tools as _tools
from openfoam_mcp.tools import (
    archive_case,
    check_mesh,
    decompose_par,
    export_field_image,
    finalize_report,
    get_residuals,
    list_tutorials,
    prepare_case,
    prepare_surface_mesh,
    read_tutorial_file,
    reconstruct_par,
    record_step,
    run_blockmesh,
    run_snappy_hex_mesh,
    run_solver,
    write_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_CASE = REPO_ROOT / "cases" / "examples" / "pitz-daily" / "baseline"

requires_openfoam = pytest.mark.skipif(
    shutil.which("blockMesh") is None,
    reason="OpenFOAM not found on PATH (source the OpenFOAM environment)",
)

requires_pvbatch = pytest.mark.skipif(
    shutil.which("pvbatch") is None,
    reason="pvbatch (ParaView) not found on PATH",
)


@pytest.fixture
def baseline_copy(tmp_path: Path) -> Path:
    """Copy the tracked baseline case into ``tmp_path`` so tests can mutate it.

    OpenFOAM utilities like ``foamDictionary`` rewrite the entire dictionary
    file when modifying any entry, so running the solver tools against the
    tracked case directly would reformat ``system/controlDict``. Tests that
    invoke run_solver / write_dict against a real case use this fixture to
    isolate the side effects.
    """
    dest = tmp_path / "case"
    shutil.copytree(BASELINE_CASE, dest)
    # constant/polyMesh exists if the user previously ran blockMesh in the
    # source tree; remove so each test starts mesh-less and explicit.
    polymesh = dest / "constant" / "polyMesh"
    if polymesh.exists():
        shutil.rmtree(polymesh)
    return dest


@requires_openfoam
class TestRunBlockmesh:
    def test_baseline_case_succeeds(self) -> None:
        """The baseline Pitz-Daily case should produce a valid mesh."""
        result = run_blockmesh(str(BASELINE_CASE))
        assert result["success"] is True
        assert "mesh_stats" in result
        assert result["mesh_stats"]["n_cells"] > 0

    def test_missing_dict_returns_structured_error(self, tmp_path: Path) -> None:
        """A case without blockMeshDict fails cleanly, not with an exception."""
        empty_case = tmp_path / "empty_case"
        (empty_case / "system").mkdir(parents=True)
        result = run_blockmesh(str(empty_case))
        assert result["success"] is False
        assert result["reason"] == "missing_dict"


class TestPrepareCase:
    def test_creates_fresh_dir(self, tmp_path: Path) -> None:
        case = tmp_path / "work" / "lid-cavity"  # parent doesn't exist yet
        result = prepare_case(str(case))
        assert result["success"] is True
        assert result["cleared"] is False
        assert case.is_dir()

    def test_empty_existing_dir_ok(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = prepare_case(str(case))
        assert result["success"] is True
        assert result["cleared"] is False

    def test_nonempty_refused_without_overwrite(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        (case / "system" / "controlDict").write_text("prior attempt")
        result = prepare_case(str(case))
        assert result["success"] is False
        assert result["reason"] == "case_exists"
        # Prior content is untouched.
        assert (case / "system" / "controlDict").read_text() == "prior attempt"

    def test_overwrite_clears_prior_case(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        (case / "system" / "controlDict").write_text("prior attempt")
        (case / "REPORT.md").write_text("old report")
        result = prepare_case(str(case), overwrite=True)
        assert result["success"] is True
        assert result["cleared"] is True
        assert case.is_dir()
        # The prior files are gone.
        assert not (case / "system").exists()
        assert not (case / "REPORT.md").exists()

    def test_path_is_a_file_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "not-a-dir"
        f.write_text("x")
        result = prepare_case(str(f))
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

    def test_prepared_dir_accepts_write_dict(self, tmp_path: Path) -> None:
        # prepare_case satisfies write_dict's pre-existing-case requirement.
        case = tmp_path / "work" / "demo"
        assert prepare_case(str(case))["success"] is True
        assert write_dict(str(case), "controlDict", "FoamFile{}")["success"] is True


class TestWriteDict:
    def test_writes_file_to_system_dir(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        result = write_dict(str(case), "controlDict", "FoamFile { object controlDict; }")
        assert result["success"] is True
        target = case / "system" / "controlDict"
        assert target.exists()
        assert target.read_text().startswith("FoamFile")

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        target = case / "system" / "fvSchemes"
        target.write_text("old content")
        result = write_dict(str(case), "fvSchemes", "new content")
        assert result["success"] is True
        assert target.read_text() == "new content"

    @pytest.mark.parametrize("bad_name", [
        "../escape",
        "subdir/file",
        "back\\slash",
        "",
        ".",
        "..",
        "with\x00null",
    ])
    def test_path_traversal_and_invalid_names_rejected(self, tmp_path: Path, bad_name: str) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        result = write_dict(str(case), bad_name, "content")
        assert result["success"] is False
        assert result["reason"] == "invalid_dict_name"
        # Critically, no file should have been written anywhere.
        assert list((case / "system").iterdir()) == []

    def test_missing_case_returns_structured_error(self, tmp_path: Path) -> None:
        result = write_dict(str(tmp_path / "does_not_exist"), "controlDict", "x")
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

    def test_auto_creates_missing_subdir(self, tmp_path: Path) -> None:
        """write_dict should create system/ if the case exists but subdir doesn't."""
        case = tmp_path / "case"
        case.mkdir()
        result = write_dict(str(case), "controlDict", "x")
        assert result["success"] is True
        assert (case / "system" / "controlDict").exists()

    def test_writes_to_constant_subdir(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = write_dict(
            str(case), "transportProperties", "nu 1.5e-5;", subdir="constant"
        )
        assert result["success"] is True
        assert (case / "constant" / "transportProperties").exists()

    def test_writes_to_zero_subdir(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = write_dict(str(case), "U", "FoamFile{}", subdir="0")
        assert result["success"] is True
        assert (case / "0" / "U").exists()

    def test_invalid_subdir_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = write_dict(str(case), "controlDict", "x", subdir="../etc")
        assert result["success"] is False
        assert result["reason"] == "invalid_subdir"


class TestRunSolverInputValidation:
    """Pure-Python validation paths — no OpenFOAM needed."""

    @pytest.mark.parametrize("bad_solver", ["", "with/slash", "with\\back", "x\x00y"])
    def test_invalid_solver_name_rejected(self, tmp_path: Path, bad_solver: str) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        (case / "system" / "controlDict").write_text("dummy")
        (case / "constant" / "polyMesh").mkdir(parents=True)
        result = run_solver(str(case), bad_solver)
        assert result["success"] is False
        assert result["reason"] == "invalid_solver"

    def test_missing_controldict_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "constant" / "polyMesh").mkdir(parents=True)
        result = run_solver(str(case), "simpleFoam")
        assert result["success"] is False
        assert result["reason"] == "invalid_case"
        assert "controlDict" in result["log_tail"]

    def test_missing_polymesh_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        (case / "system" / "controlDict").write_text("dummy")
        result = run_solver(str(case), "simpleFoam")
        assert result["success"] is False
        assert result["reason"] == "invalid_case"
        assert "polyMesh" in result["log_tail"]


@requires_openfoam
class TestRunSolverEndToEnd:
    """End-to-end run on a copy of the baseline case. Requires OpenFOAM sourced."""

    def test_simplefoam_on_baseline_converges(self, baseline_copy: Path) -> None:
        mesh = run_blockmesh(str(baseline_copy))
        assert mesh["success"] is True

        result = run_solver(str(baseline_copy), "simpleFoam")
        assert result["success"] is True, result.get("log_tail", "")
        assert result["converged"] is True
        assert "Ux" in result["final_residuals"]
        assert "p" in result["final_residuals"]
        for field, residual in result["final_residuals"].items():
            assert residual < 1.0, f"{field} final initial-residual is {residual}"
        assert result["walltime_s"] is not None and result["walltime_s"] > 0

    def test_unknown_solver_returns_solver_not_found(self, baseline_copy: Path) -> None:
        run_blockmesh(str(baseline_copy))
        result = run_solver(str(baseline_copy), "definitelyNotARealSolver")
        assert result["success"] is False
        assert result["reason"] == "solver_not_found"

    def test_end_time_override_round_trips(self, baseline_copy: Path) -> None:
        from openfoam_mcp.openfoam_utils import foam_dictionary_get

        run_blockmesh(str(baseline_copy))
        control_dict = baseline_copy / "system" / "controlDict"
        before_end_time = foam_dictionary_get(control_dict, "endTime")
        result = run_solver(str(baseline_copy), "simpleFoam", end_time=1.0)
        assert result["success"] is True, result.get("log_tail", "")
        assert foam_dictionary_get(control_dict, "endTime") == before_end_time


_SYNTHETIC_LOG = """\
Time = 1

smoothSolver:  Solving for Ux, Initial residual = 0.5, Final residual = 0.05, No Iterations 4
smoothSolver:  Solving for Uy, Initial residual = 0.4, Final residual = 0.04, No Iterations 3
GAMG:  Solving for p, Initial residual = 0.9, Final residual = 0.09, No Iterations 2
ExecutionTime = 1.0 s  ClockTime = 1 s

Time = 2

smoothSolver:  Solving for Ux, Initial residual = 0.05, Final residual = 0.005, No Iterations 4
smoothSolver:  Solving for Uy, Initial residual = 0.04, Final residual = 0.004, No Iterations 3
GAMG:  Solving for p, Initial residual = 0.09, Final residual = 0.009, No Iterations 2
ExecutionTime = 2.0 s  ClockTime = 2 s

End
"""


class TestGetResiduals:
    """Most coverage uses synthetic logs - no OpenFOAM needed."""

    def test_default_returns_summary(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.simpleFoam").write_text(_SYNTHETIC_LOG)
        result = get_residuals(str(case))
        assert result["success"] is True
        assert result["n_outer_iterations"] == 2
        assert "summary" in result
        assert "residuals" not in result  # full history not included by default
        ux = result["summary"]["Ux"]
        assert ux["first"] == 0.5
        assert ux["last"] == 0.05
        assert ux["min"] == 0.05
        assert ux["n_points"] == 2
        assert ux["orders_dropped"] == pytest.approx(1.0, rel=1e-4)

    def test_full_history_when_summary_false(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.simpleFoam").write_text(_SYNTHETIC_LOG)
        result = get_residuals(str(case), summary=False)
        assert result["success"] is True
        assert "residuals" in result
        assert set(result["residuals"]) == {"Ux", "Uy", "p"}
        assert result["residuals"]["Ux"][0] == {"iteration": 1, "initial": 0.5, "final": 0.05}
        assert result["residuals"]["p"][1] == {"iteration": 2, "initial": 0.09, "final": 0.009}

    def test_picks_latest_solver_log_when_multiple(self, tmp_path: Path) -> None:
        import os
        import time

        case = tmp_path / "case"
        case.mkdir()
        (case / "log.simpleFoam").write_text(_SYNTHETIC_LOG)
        # Sleep briefly so mtime is strictly later. mtime resolution on Linux
        # ext4 is ~ns so 0.01 s is plenty.
        time.sleep(0.01)
        winning_log = case / "log.pimpleFoam"
        winning_log.write_text(_SYNTHETIC_LOG.replace("0.5", "0.123"))
        os.utime(winning_log, None)  # bump mtime to now
        result = get_residuals(str(case))
        assert result["success"] is True
        assert result["log_file"].endswith("log.pimpleFoam")
        assert result["summary"]["Ux"]["first"] == 0.123

    def test_skips_utility_logs(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.blockMesh").write_text("blockMesh output, no residuals here")
        (case / "log.checkMesh").write_text("checkMesh output, no residuals here")
        result = get_residuals(str(case))
        assert result["success"] is False
        assert result["reason"] == "no_solver_log"

    def test_missing_case_returns_invalid_case_path(self, tmp_path: Path) -> None:
        result = get_residuals(str(tmp_path / "does_not_exist"))
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

    def test_solver_log_with_no_residual_lines(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        (case / "log.simpleFoam").write_text("Create mesh ...\nEnd\n")
        result = get_residuals(str(case))
        assert result["success"] is False
        assert result["reason"] == "no_residuals_in_log"


@requires_openfoam
class TestGetResidualsEndToEnd:
    def test_real_baseline_solver_log(self, baseline_copy: Path) -> None:
        run_blockmesh(str(baseline_copy))
        run_solver(str(baseline_copy), "simpleFoam")
        # summary mode (default) — sanity-check the per-field stats.
        result = get_residuals(str(baseline_copy))
        assert result["success"] is True
        assert "Ux" in result["summary"]
        assert "p" in result["summary"]
        assert result["n_outer_iterations"] > 50
        ux_summary = result["summary"]["Ux"]
        assert ux_summary["first"] > ux_summary["last"]
        assert ux_summary["orders_dropped"] > 0

        # Full history mode (opt-in) — back-compat sanity check.
        full = get_residuals(str(baseline_copy), summary=False)
        assert full["success"] is True
        ux = full["residuals"]["Ux"]
        assert ux[0]["initial"] > ux[-1]["initial"]


class TestExportFieldImageInputValidation:
    def test_missing_polymesh_returns_invalid_case(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        result = export_field_image(str(case), "U")
        assert result["success"] is False
        assert result["reason"] == "invalid_case"


@requires_openfoam
@requires_pvbatch
class TestExportFieldImageEndToEnd:
    """Render a real field on the populated baseline. Slow — opens ParaView."""

    def test_render_velocity_field(self, baseline_copy: Path) -> None:
        run_blockmesh(str(baseline_copy))
        # writeInterval is 100 timeSteps, so the solve must reach at least
        # t=100 to write a result directory the reader can render — t=10
        # leaves only 0/ and ParaView finds no fields.
        run_solver(str(baseline_copy), "simpleFoam", end_time=100.0)
        result = export_field_image(str(baseline_copy), "U")
        assert result["success"] is True, result
        image = Path(result["image_path"])
        assert image.exists()
        assert image.stat().st_size > 1024  # not a zero-byte file
        cmin, cmax = result["colorbar_range"]
        # Velocity magnitude is non-negative; at U_inlet=10 m/s the max is in
        # that ballpark (could overshoot in the contraction).
        assert cmin >= 0.0
        assert cmax > 0.0

    def test_unknown_field_returns_field_not_found(self, baseline_copy: Path) -> None:
        run_blockmesh(str(baseline_copy))
        # writeInterval is 100 timeSteps, so the solve must reach at least
        # t=100 to write a result directory the reader can render — t=10
        # leaves only 0/ and ParaView finds no fields.
        run_solver(str(baseline_copy), "simpleFoam", end_time=100.0)
        result = export_field_image(str(baseline_copy), "definitelyNotAField")
        assert result["success"] is False
        assert result["reason"] == "field_not_found"
        assert "U" in result["available_cell_arrays"]


@pytest.fixture
def fake_tutorials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Lay out a minimal $FOAM_TUTORIALS-shaped tree for the browse tools."""
    root = tmp_path / "tutorials"
    case = root / "incompressible" / "simpleFoam" / "myCase"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application simpleFoam;\n")
    (case / "0").mkdir()
    (case / "0" / "U").write_text("dimensions [0 1 -1 0 0 0 0];\n")
    monkeypatch.setenv("FOAM_TUTORIALS", str(root))
    return root


class TestListTutorials:
    def test_unsourced_returns_clean_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FOAM_TUTORIALS", raising=False)
        result = list_tutorials()
        assert result["success"] is False
        assert result["reason"] == "foam_tutorials_unset"

    def test_top_level_lists_categories(self, fake_tutorials: Path) -> None:
        result = list_tutorials()
        assert result["success"] is True
        names = [e["name"] for e in result["entries"]]
        assert "incompressible" in names

    def test_case_dir_marked_is_case(self, fake_tutorials: Path) -> None:
        result = list_tutorials("incompressible/simpleFoam")
        assert result["success"] is True
        my_case = next(e for e in result["entries"] if e["name"] == "myCase")
        assert my_case["is_case"] is True

    def test_path_escape_rejected(self, fake_tutorials: Path) -> None:
        result = list_tutorials("../etc")
        assert result["success"] is False
        assert result["reason"] == "path_escape"

    def test_not_a_directory(self, fake_tutorials: Path) -> None:
        result = list_tutorials("incompressible/simpleFoam/myCase/system/controlDict")
        assert result["success"] is False
        assert result["reason"] == "not_a_directory"


class TestReadTutorialFile:
    def test_reads_file_content(self, fake_tutorials: Path) -> None:
        result = read_tutorial_file("incompressible/simpleFoam/myCase/system/controlDict")
        assert result["success"] is True
        assert "simpleFoam" in result["content"]
        assert result["truncated"] is False

    def test_unsourced_returns_clean_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FOAM_TUTORIALS", raising=False)
        result = read_tutorial_file("anything")
        assert result["success"] is False
        assert result["reason"] == "foam_tutorials_unset"

    def test_path_escape_rejected(self, fake_tutorials: Path) -> None:
        result = read_tutorial_file("../etc/passwd")
        assert result["success"] is False
        assert result["reason"] == "path_escape"

    def test_directory_returns_not_a_file(self, fake_tutorials: Path) -> None:
        result = read_tutorial_file("incompressible/simpleFoam/myCase")
        assert result["success"] is False
        assert result["reason"] == "not_a_file"

    def test_large_file_truncates(self, fake_tutorials: Path, tmp_path: Path) -> None:
        big = fake_tutorials / "incompressible" / "simpleFoam" / "myCase" / "system" / "big"
        big.write_text("x" * 100_000)
        result = read_tutorial_file("incompressible/simpleFoam/myCase/system/big")
        assert result["success"] is True
        assert result["truncated"] is True
        assert len(result["content"]) <= 64_000
        assert result["size_bytes"] == 100_000


# A representative checkMesh log for a clean 2D mesh, used by the parser tests.
_CHECKMESH_OK_LOG = """\
Create mesh for time = 0
Time = 0

Mesh stats
    points:           5145
    faces:            10004
    internal faces:   4904
    cells:            2450
    boundary patches: 5

Checking geometry...
    Overall domain bounding box (0 0 -0.0005) (0.29 0.0508 0.0005)
    Max aspect ratio = 4.93 OK.
    Mesh non-orthogonality Max: 5.93 average: 1.40
    Non-orthogonality check OK.
    Max skewness = 0.51 OK.

Mesh OK.

End
"""

_CHECKMESH_FAIL_LOG = """\
Mesh stats
    cells:            18000

Checking geometry...
    Max aspect ratio = 1200.5 ***Large aspect ratio.
    Mesh non-orthogonality Max: 89.2 average: 38.4
 ***Number of severely non-orthogonal (> 70 degrees) faces: 412.
    Max skewness = 6.21 ***Bad skewness.

Failed 3 mesh checks.

End
"""


class TestCheckMeshParser:
    """Pure-Python tests for the checkMesh log parser — no OpenFOAM needed."""

    def test_clean_mesh_passes(self, tmp_path: Path) -> None:
        log = tmp_path / "log.checkMesh"
        log.write_text(_CHECKMESH_OK_LOG)
        result = _tools._parse_check_mesh(log, "tail")
        assert result["success"] is True
        assert result["quality_pass"] is True
        assert result["metrics"]["n_cells"] == 2450
        assert result["metrics"]["max_aspect_ratio"] == pytest.approx(4.93)
        assert result["metrics"]["max_non_orthogonality"] == pytest.approx(5.93)
        assert result["metrics"]["average_non_orthogonality"] == pytest.approx(1.40)
        assert result["metrics"]["max_skewness"] == pytest.approx(0.51)
        assert result["metrics"]["severe_non_orthogonal_faces"] == 0
        assert result["warnings"] == []

    def test_bad_mesh_fails_with_warnings(self, tmp_path: Path) -> None:
        log = tmp_path / "log.checkMesh"
        log.write_text(_CHECKMESH_FAIL_LOG)
        result = _tools._parse_check_mesh(log, "tail")
        assert result["success"] is True
        assert result["quality_pass"] is False
        assert result["metrics"]["max_non_orthogonality"] == pytest.approx(89.2)
        assert result["metrics"]["severe_non_orthogonal_faces"] == 412
        # Three lines with '***' should be captured as warnings.
        assert len(result["warnings"]) == 3
        assert any("severely non-orthogonal" in w for w in result["warnings"])


class TestCheckMesh:
    """check_mesh entry-point tests (no OpenFOAM shell-out)."""

    def test_missing_polymesh(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        result = check_mesh(str(case))
        assert result["success"] is False
        assert result["reason"] == "polymesh_missing"


@requires_openfoam
class TestCheckMeshEndToEnd:
    """Exercises check_mesh against the real Pitz-Daily baseline."""

    def test_baseline_mesh_passes(self, baseline_copy: Path) -> None:
        # Generate the mesh first.
        run_blockmesh(str(baseline_copy))
        result = check_mesh(str(baseline_copy))
        assert result["success"] is True
        assert result["quality_pass"] is True
        assert result["metrics"]["n_cells"] is not None
        assert result["metrics"]["max_non_orthogonality"] is not None


class TestRecordStep:
    def test_creates_report_with_header(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(
            str(case),
            phase="geometry",
            status="ok",
            title="Selected tutorial template",
            details="Picked `pitzDaily` as a structural template.",
        )
        assert result["success"] is True
        report = case / "REPORT.md"
        assert report.exists()
        text = report.read_text()
        assert "# Case setup report" in text
        # Compact entry header: `## [HH:MM:SS] phase / status — title`.
        assert "geometry / ok" in text
        assert re.search(r"## \[\d{2}:\d{2}:\d{2}\] geometry / ok — ", text)
        assert "Selected tutorial template" in text
        assert "Picked `pitzDaily`" in text
        assert result["n_entries"] == 1
        # Pure freeform entry — no consultant fields filled, not a decision
        # entry, so no gaps reported.
        assert result["consultant_gaps"] == []

    def test_appends_subsequent_entries(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        record_step(str(case), phase="mesh", status="ok", title="blockMesh OK")
        result = record_step(
            str(case), phase="mesh_quality", status="warning",
            title="High non-orthogonality",
            details="Max non-ortho 72; setting nNonOrthogonalCorrectors=2.",
        )
        assert result["success"] is True
        assert result["n_entries"] == 2
        text = (case / "REPORT.md").read_text()
        # Header only appears once.
        assert text.count("# Case setup report") == 1

    def test_retry_of_chains_entries(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        record_step(
            str(case), phase="convergence", status="error",
            title="Solver diverged at t=12",
        )
        result = record_step(
            str(case), phase="convergence", status="fixed",
            title="Reduced URFs and re-ran",
            retry_of="Solver diverged at t=12",
            details="Dropped p relaxation 0.7 -> 0.3; now stable.",
        )
        assert result["success"] is True
        text = (case / "REPORT.md").read_text()
        # retry_of renders via repr(), i.e. single-quoted.
        assert "retry of: 'Solver diverged at t=12'" in text
        assert "convergence / fixed" in text

    def test_invalid_status_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(str(case), phase="mesh", status="bogus", title="x")
        assert result["success"] is False
        assert result["reason"] == "invalid_status"

    def test_missing_case_path_rejected(self, tmp_path: Path) -> None:
        result = record_step(
            str(tmp_path / "nope"), phase="mesh", status="ok", title="x"
        )
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

    def test_empty_title_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(str(case), phase="mesh", status="ok", title="  ")
        assert result["success"] is False
        assert result["reason"] == "empty_title"

    def test_leaked_tool_markup_rejected(self, tmp_path: Path) -> None:
        # An over-long value can merge the next field's text plus its
        # '<parameter name=...>' / closing tag into 'decision', which then
        # renders 'why' as an empty-field gap. Refuse it loudly instead.
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(
            str(case),
            phase="solver_config",
            status="ok",
            title="Adopt template",
            decision=(
                'Swap to simpleFoam.</decision>\n'
                '<parameter name="why">A steady solver fits.'
            ),
        )
        assert result["success"] is False
        assert result["reason"] == "leaked_tool_markup"

    def test_literal_angle_brackets_in_prose_allowed(self, tmp_path: Path) -> None:
        # CLAUDE.md asks for literal <, >, & in prose; the guard targets only
        # the specific tool-call markup, not bare comparison operators.
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(
            str(case),
            phase="mesh_quality",
            status="ok",
            title="Mesh accepted",
            why="max non-orthogonality < 60 deg and skewness < 1 & aspect < 10.",
        )
        assert result["success"] is True

    def test_consultant_depth_is_collapsible(self, tmp_path: Path) -> None:
        # Decision stays visible; why/alternatives/when-it-breaks fold into a
        # <details> block so the live entry is scannable. The field lines
        # still render (inside the block) so they remain machine-extractable.
        case = tmp_path / "case"
        case.mkdir()
        record_step(
            str(case),
            phase="mesh",
            status="ok",
            title="40x40 cavity",
            decision="40x40 uniform mesh.",
            why="Coarse OK at Re=400.",
            alternatives="20x20 (under-resolved).",
            when_it_breaks="Re > 1000.",
        )
        text = (case / "REPORT.md").read_text()
        assert "<details><summary>why · alternatives · when it breaks</summary>" in text
        assert "</details>" in text
        # Decision is outside the collapsible block; the depth is inside it.
        idx_decision = text.index("- **Decision:**")
        idx_details = text.index("<details>")
        idx_why = text.index("- **Why:**")
        assert idx_decision < idx_details < idx_why

    def test_consultant_schema_fully_filled(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(
            str(case),
            phase="mesh",
            status="ok",
            title="Selected blockMesh template from cavity tutorial",
            decision="Use icoFoam/cavity blockMeshDict, 40x40 base mesh.",
            why="Lid-driven cavity at Re=400 matches Ghia 1982 reference setup.",
            alternatives=(
                "- 20x20 base: cheaper but Ghia profiles need >=40 to resolve\n"
                "- Stretched grid: overkill for Re=400 (laminar)"
            ),
            when_it_breaks=(
                "- Re > 1000 (transitional)\n"
                "- Non-square cavity (template assumes unit cube)"
            ),
            citations=[
                "corpus/incompressible/icoFoam/cavity.md",
                "Ghia 1982 JCP 48",
            ],
        )
        assert result["success"] is True
        assert result["consultant_gaps"] == []
        text = (case / "REPORT.md").read_text()
        assert "**Decision:**" in text
        assert "Use icoFoam/cavity blockMeshDict" in text
        assert "**Why:**" in text
        assert "Lid-driven cavity at Re=400" in text
        assert "**Alternatives:**" in text
        assert "**When it breaks:**" in text
        # Citations fold into the Why line as `_(cites: a, b)_`.
        assert "_(cites:" in text
        assert "Ghia 1982 JCP 48" in text

    def test_consultant_gaps_flagged_when_partial(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(
            str(case),
            phase="solver_config",
            status="ok",
            title="Chose simpleFoam",
            decision="Use simpleFoam (steady, incompressible).",
            # why / alternatives / when_it_breaks deliberately omitted.
        )
        assert result["success"] is True
        gaps = set(result["consultant_gaps"])
        assert gaps == {"uncited_why", "no_alternatives", "no_failure_modes"}
        text = (case / "REPORT.md").read_text()
        # Sentinels rendered as honest weakness.
        assert "uncited choice" in text
        assert "no alternatives surfaced" in text
        assert "failure modes not characterized" in text

    def test_citations_satisfy_why_gap(self, tmp_path: Path) -> None:
        # Citations without prose why are still a cited choice — the gap is
        # only "uncited_why" when BOTH why prose and citations are empty.
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(
            str(case),
            phase="mesh",
            status="ok",
            title="40x40 cavity mesh",
            decision="Use 40x40 base mesh.",
            citations=["corpus/incompressible/icoFoam/cavity.md"],
        )
        assert result["success"] is True
        assert "uncited_why" not in result["consultant_gaps"]
        # The other two are still missing.
        assert "no_alternatives" in result["consultant_gaps"]
        assert "no_failure_modes" in result["consultant_gaps"]

    def test_pending_review_status_renders_marker(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(
            str(case),
            phase="mesh",
            status="pending_review",
            title="Propose 40x40 cavity mesh",
            decision="Use icoFoam/cavity blockMeshDict, 40x40 base mesh.",
            why="Matches Ghia 1982 setup.",
            alternatives="20x20 (under-resolved); 80x80 (slower without payoff at Re=400).",
            when_it_breaks="Re > 1000.",
        )
        assert result["success"] is True
        text = (case / "REPORT.md").read_text()
        assert "mesh / pending_review" in text
        assert "**[PENDING REVIEW]**" in text
        # Pending-review is always a decision entry, so consultant block
        # must render even if the agent forgot fields.
        assert "**Decision:**" in text

    def test_pending_review_with_empty_fields_still_decision_entry(
        self, tmp_path: Path
    ) -> None:
        # Even with no consultant fields, a pending_review entry must be
        # treated as a decision so the gaps are loudly flagged.
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(
            str(case),
            phase="boundary_conditions",
            status="pending_review",
            title="Propose BC set",
        )
        assert result["success"] is True
        gaps = set(result["consultant_gaps"])
        assert gaps == {"uncited_why", "no_alternatives", "no_failure_modes"}
        text = (case / "REPORT.md").read_text()
        assert "uncited choice" in text

    def test_freeform_details_still_render_below_consultant(
        self, tmp_path: Path
    ) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = record_step(
            str(case),
            phase="convergence",
            status="ok",
            title="Solver converged at 240 iters",
            decision="Accept the converged solution.",
            why="All residuals < 1e-5 over last 50 iters.",
            alternatives="Could tighten to 1e-6 (marginal gain).",
            when_it_breaks="Doesn't apply to transient cases.",
            details="```\nIteration 240: Ux 8.2e-6, Uy 7.1e-6, p 9.4e-6\n```",
        )
        assert result["success"] is True
        text = (case / "REPORT.md").read_text()
        # Both blocks present, in order.
        idx_decision = text.find("**Decision:**")
        idx_details = text.find("Iteration 240")
        assert 0 < idx_decision < idx_details

class TestFinalizeReport:
    """finalize_report writes a top verdict banner and a compact Decisions
    index. record_step writes collapsible live entries and strips both, so
    the artifacts appear only after finalize_report and never go stale.
    """

    @staticmethod
    def _index_block(text: str) -> str:
        """The text between the DECISIONS markers (not the SUMMARY ones)."""
        return text.split("<!-- BEGIN DECISIONS TABLE", 1)[1].split(
            "<!-- END DECISIONS TABLE -->", 1
        )[0]

    def _record_decision(self, case: Path, **kw: object) -> None:
        defaults = dict(
            phase="mesh",
            status="ok",
            title="Selected blockMesh template from cavity tutorial",
            decision="icoFoam/cavity blockMeshDict, 40x40 base mesh.",
            why="Cavity at Re=400 matches Ghia 1982 setup.",
            alternatives="20x20 (under-resolved); 80x80 (slower).",
            when_it_breaks="Re > 1000 (transitional).",
        )
        defaults.update(kw)
        record_step(str(case), **defaults)  # type: ignore[arg-type]

    def test_no_artifacts_until_finalize(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        self._record_decision(case)
        text = (case / "REPORT.md").read_text()
        # Live narration only — neither banner nor index before finalize.
        assert "<!-- BEGIN SUMMARY" not in text
        assert "<!-- BEGIN DECISIONS TABLE" not in text
        assert "## Decisions" not in text

    def test_finalize_writes_banner_and_index(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        self._record_decision(case, citations=["corpus/incompressible/icoFoam/cavity.md"])
        result = finalize_report(str(case))
        assert result["success"] is True
        assert result["n_decisions"] == 1
        text = (case / "REPORT.md").read_text()
        # Verdict banner present.
        assert "<!-- BEGIN SUMMARY" in text
        assert "**VERDICT:" in text
        # Compact index header (NOT the old four-field prose table).
        assert "| Phase | Decision | Cites | Gaps |" in text
        assert "| Phase | Decision | Why | Alternatives | When it breaks |" not in text
        index = self._index_block(text)
        assert "| mesh | icoFoam/cavity blockMeshDict" in index
        assert "corpus/incompressible/icoFoam/cavity.md" in index
        # Index is at the very end of the file.
        assert text.rstrip().endswith("<!-- END DECISIONS TABLE -->")

    def test_banner_sits_above_first_entry(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        self._record_decision(case)
        finalize_report(str(case))
        text = (case / "REPORT.md").read_text()
        # The verdict banner is near the top, before the first step entry.
        assert text.index("<!-- BEGIN SUMMARY") < text.index("## [")

    def test_index_does_not_duplicate_full_prose(self, tmp_path: Path) -> None:
        # The whole point: the why/alternatives prose lives once (in the
        # collapsible entry), not copied verbatim into the index.
        case = tmp_path / "case"
        case.mkdir()
        self._record_decision(case)
        finalize_report(str(case))
        index = self._index_block((case / "REPORT.md").read_text())
        assert "Cavity at Re=400 matches Ghia 1982 setup." not in index
        assert "20x20 (under-resolved); 80x80 (slower)." not in index

    def test_verdict_pass_from_validation(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        self._record_decision(
            case, phase="validation", status="fixed",
            title="80x80 matches Ghia: u 0.4%, v 0.5%",
            decision="Accept the case.",
        )
        finalize_report(str(case))
        text = (case / "REPORT.md").read_text()
        assert "**VERDICT: PASS**" in text
        assert "80x80 matches Ghia: u 0.4%, v 0.5%" in text

    def test_verdict_fail_from_validation_error(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        self._record_decision(
            case, phase="validation", status="error",
            title="Profiles miss Ghia badly",
            decision="Reject.",
        )
        finalize_report(str(case))
        assert "**VERDICT: FAIL**" in (case / "REPORT.md").read_text()

    def test_verdict_incomplete_without_validation(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        self._record_decision(case)  # phase="mesh", no validation entry
        finalize_report(str(case))
        assert "**VERDICT: INCOMPLETE**" in (case / "REPORT.md").read_text()

    def test_index_reflects_multiple_entries_in_order(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        self._record_decision(
            case, phase="mesh", title="40x40 cavity", decision="40x40 uniform.",
        )
        self._record_decision(
            case, phase="solver_config", title="simpleFoam",
            decision="simpleFoam, laminar.",
        )
        result = finalize_report(str(case))
        assert result["n_decisions"] == 2
        text = (case / "REPORT.md").read_text()
        assert text.count("<!-- BEGIN DECISIONS TABLE") == 1
        index = self._index_block(text)
        assert "40x40 uniform." in index
        assert "simpleFoam, laminar." in index
        assert index.index("40x40 uniform") < index.index("simpleFoam, laminar")

    def test_finalize_refreshes_in_place(self, tmp_path: Path) -> None:
        # record_step after finalize strips the stale banner+index; a second
        # finalize rebuilds them. Net result is always exactly one of each.
        case = tmp_path / "case"
        case.mkdir()
        self._record_decision(
            case, phase="mesh", title="40x40 cavity", decision="40x40 uniform.",
        )
        finalize_report(str(case))
        self._record_decision(
            case, phase="validation", status="fixed", title="passes",
            decision="simpleFoam, laminar.",
        )
        result = finalize_report(str(case))
        assert result["n_decisions"] == 2
        text = (case / "REPORT.md").read_text()
        assert text.count("<!-- BEGIN SUMMARY") == 1
        assert text.count("<!-- BEGIN DECISIONS TABLE") == 1
        assert "40x40 uniform." in text
        assert "simpleFoam, laminar." in text

    def test_index_skips_info_only_entries(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        record_step(
            str(case), phase="geometry", status="ok",
            title="Read scenario YAML",
            details="Loaded cases/scenarios/lid-cavity.yaml.",
        )
        result = finalize_report(str(case))
        assert result["n_decisions"] == 0
        text = (case / "REPORT.md").read_text()
        index = self._index_block(text)
        assert "_no decisions recorded yet._" in index
        assert "Read scenario YAML" not in index

    def test_index_flags_gaps(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        record_step(
            str(case), phase="solver_config", status="ok",
            title="Chose simpleFoam", decision="simpleFoam.",
            # why / alternatives / when_it_breaks deliberately omitted.
        )
        finalize_report(str(case))
        text = (case / "REPORT.md").read_text()
        index = self._index_block(text)
        # The Gaps column flags every missing field...
        assert "why" in index and "alts" in index and "breaks" in index
        # ...but the verbose sentinel prose stays in the narration entry,
        # not copied into the compact index.
        assert "no alternatives surfaced" not in index
        assert "no alternatives surfaced" in text

    def test_index_escapes_pipes(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        record_step(
            str(case), phase="schemes", status="ok",
            title="Discretisation choice",
            decision="div(phi,U) | linearUpwind | grad(U)",
            why="Second-order, bounded.",
        )
        finalize_report(str(case))
        index = self._index_block((case / "REPORT.md").read_text())
        assert "linearUpwind \\| grad(U)" in index

    def test_finalize_no_report_fails(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = finalize_report(str(case))
        assert result["success"] is False
        assert result["reason"] == "no_report"

    def test_finalize_invalid_case_path_fails(self, tmp_path: Path) -> None:
        result = finalize_report(str(tmp_path / "nope"))
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

# Minimal ASCII STL — one closed triangle. surfaceCheck handles this; for
# the unit-test paths that don't call surfaceCheck, this is enough.
_TRIVIAL_ASCII_STL = """solid demo
facet normal 0 0 1
  outer loop
    vertex 0.0 0.0 0.0
    vertex 1.0 0.0 0.0
    vertex 0.0 1.0 0.0
  endloop
endfacet
endsolid demo
"""


class TestPrepareSurfaceMesh:
    """Validation paths for prepare_surface_mesh — no OpenFOAM call."""

    def test_copies_stl_into_trisurface(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        stl = tmp_path / "wing.stl"
        stl.write_text(_TRIVIAL_ASCII_STL)
        result = prepare_surface_mesh(str(case), str(stl), run_check=False)
        assert result["success"] is True
        dest = case / "constant" / "triSurface" / "wing.stl"
        assert dest.exists()
        assert dest.read_text() == _TRIVIAL_ASCII_STL
        assert result["surface_check"] is None  # run_check=False

    def test_custom_patch_name_renames(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        stl = tmp_path / "raw.stl"
        stl.write_text(_TRIVIAL_ASCII_STL)
        result = prepare_surface_mesh(
            str(case), str(stl), patch_name="aircraft", run_check=False
        )
        assert result["success"] is True
        assert (case / "constant" / "triSurface" / "aircraft.stl").exists()

    def test_missing_stl_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = prepare_surface_mesh(
            str(case), str(tmp_path / "nope.stl"), run_check=False
        )
        assert result["success"] is False
        assert result["reason"] == "stl_not_found"

    def test_missing_case_dir_rejected(self, tmp_path: Path) -> None:
        stl = tmp_path / "wing.stl"
        stl.write_text(_TRIVIAL_ASCII_STL)
        result = prepare_surface_mesh(
            str(tmp_path / "no-case"), str(stl), run_check=False
        )
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

    @pytest.mark.parametrize("bad_name", ["with/slash", "back\\slash", "", "with\x00null"])
    def test_invalid_patch_name_rejected(self, tmp_path: Path, bad_name: str) -> None:
        case = tmp_path / "case"
        case.mkdir()
        stl = tmp_path / "wing.stl"
        stl.write_text(_TRIVIAL_ASCII_STL)
        result = prepare_surface_mesh(
            str(case), str(stl), patch_name=bad_name, run_check=False
        )
        assert result["success"] is False
        assert result["reason"] == "invalid_patch_name"


class TestSnappyPhaseParser:
    """Pure-Python tests for the snappyHexMesh phase-parser — no OpenFOAM."""

    def test_three_phases_complete(self, tmp_path: Path) -> None:
        log = tmp_path / "log.snappyHexMesh"
        log.write_text(
            "Some preamble\n"
            "Time = 1\n"
            "Castellated mesh : Layer mesh OK\n"
            "Time = 2\n"
            "Snapping done\n"
            "Time = 3\n"
            "Added 100 % of the requested layers.\n"
            "Total number of cells = 50000\n"
            "End\n"
        )
        phases = _tools._parse_snappy_phases(log)
        assert phases["castellation"] == "ok"
        assert phases["snap"] == "ok"
        assert phases["layers"] == "ok"
        assert phases["layers_percent"] == 100.0
        assert _tools._parse_snappy_final_cells(log) == 50000

    def test_partial_layer_addition(self, tmp_path: Path) -> None:
        log = tmp_path / "log.snappyHexMesh"
        log.write_text(
            "Time = 1\n"
            "Castellated mesh : Mesh OK\n"
            "Time = 2\n"
            "Snapping done\n"
            "Time = 3\n"
            "Added 73.4 % of the requested layers.\n"
            "End\n"
        )
        phases = _tools._parse_snappy_phases(log)
        assert phases["layers"] == "partial"
        assert phases["layers_percent"] == pytest.approx(73.4)

    def test_castellation_only(self, tmp_path: Path) -> None:
        log = tmp_path / "log.snappyHexMesh"
        log.write_text("Time = 1\nCastellated mesh : OK\nEnd\n")
        phases = _tools._parse_snappy_phases(log)
        assert phases["castellation"] == "ok"
        assert phases["snap"] == "skipped"


class TestRunSnappyHexMesh:
    """Validation paths — no actual snappy run."""

    def test_missing_background_mesh(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        (case / "system" / "snappyHexMeshDict").write_text("// dummy")
        (case / "constant" / "triSurface").mkdir(parents=True)
        (case / "constant" / "triSurface" / "wing.stl").write_text(_TRIVIAL_ASCII_STL)
        result = run_snappy_hex_mesh(str(case))
        assert result["success"] is False
        assert result["reason"] == "missing_background_mesh"

    def test_missing_snappy_dict(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "constant" / "polyMesh").mkdir(parents=True)
        (case / "constant" / "triSurface").mkdir(parents=True)
        (case / "constant" / "triSurface" / "wing.stl").write_text(_TRIVIAL_ASCII_STL)
        result = run_snappy_hex_mesh(str(case))
        assert result["success"] is False
        assert result["reason"] == "missing_snappy_dict"

    def test_missing_trisurface(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "constant" / "polyMesh").mkdir(parents=True)
        (case / "system").mkdir(parents=True)
        (case / "system" / "snappyHexMeshDict").write_text("// dummy")
        result = run_snappy_hex_mesh(str(case))
        assert result["success"] is False
        assert result["reason"] == "missing_triSurface"


class TestDecomposePar:
    """Validation paths for decompose_par — no actual OpenFOAM call."""

    def test_missing_mesh_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = decompose_par(str(case), n_procs=4)
        assert result["success"] is False
        assert result["reason"] == "missing_mesh"

    @pytest.mark.parametrize("bad_n", [0, 1, -2, 3.5])
    def test_invalid_n_procs_rejected(self, tmp_path: Path, bad_n) -> None:
        case = tmp_path / "case"
        (case / "constant" / "polyMesh").mkdir(parents=True)
        result = decompose_par(str(case), n_procs=bad_n)
        assert result["success"] is False
        assert result["reason"] == "invalid_n_procs"

    def test_invalid_method_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "constant" / "polyMesh").mkdir(parents=True)
        result = decompose_par(str(case), n_procs=4, method="bogus")
        assert result["success"] is False
        assert result["reason"] == "invalid_method"

    def test_invalid_case_path_rejected(self, tmp_path: Path) -> None:
        result = decompose_par(str(tmp_path / "nope"), n_procs=4)
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"


class TestReconstructPar:
    """Validation paths for reconstruct_par — no actual OpenFOAM call."""

    def test_no_processor_dirs_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        case.mkdir()
        result = reconstruct_par(str(case))
        assert result["success"] is False
        assert result["reason"] == "no_processors"

    def test_invalid_case_path_rejected(self, tmp_path: Path) -> None:
        result = reconstruct_par(str(tmp_path / "nope"))
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"


class TestRunSolverParallelInputValidation:
    """Pure-Python validation paths for run_solver(n_procs > 1)."""

    @pytest.mark.parametrize("bad_n", [0, -1, 3.14, "4"])
    def test_invalid_n_procs_rejected(self, tmp_path: Path, bad_n) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        (case / "system" / "controlDict").write_text("dummy")
        (case / "constant" / "polyMesh").mkdir(parents=True)
        result = run_solver(str(case), "simpleFoam", n_procs=bad_n)
        assert result["success"] is False
        assert result["reason"] == "invalid_n_procs"

    def test_missing_decomposition_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        (case / "system" / "controlDict").write_text("dummy")
        (case / "constant" / "polyMesh").mkdir(parents=True)
        # Asked for 4 ranks but no processor*/ dirs exist.
        result = run_solver(str(case), "simpleFoam", n_procs=4)
        assert result["success"] is False
        assert result["reason"] == "missing_decomposition"

    def test_mismatched_decomposition_rejected(self, tmp_path: Path) -> None:
        case = tmp_path / "case"
        (case / "system").mkdir(parents=True)
        (case / "system" / "controlDict").write_text("dummy")
        (case / "constant" / "polyMesh").mkdir(parents=True)
        # Decomposed for 2, asked for 4.
        (case / "processor0").mkdir()
        (case / "processor1").mkdir()
        result = run_solver(str(case), "simpleFoam", n_procs=4)
        assert result["success"] is False
        assert result["reason"] == "missing_decomposition"


# ---------------------------------------------------------------------------
# archive_case
# ---------------------------------------------------------------------------


def _populate_full_case(case: Path) -> None:
    """Synthesise a case directory with both inputs and run-generated content.

    Inputs (should land in the archive):
      - system/{controlDict,fvSchemes,fvSolution,blockMeshDict}
      - constant/{transportProperties,turbulenceProperties}
      - constant/triSurface/geom.stl     (STL inputs are kept)
      - 0/{U,p}
      - REPORT.md
      - Allrun, Allclean
      - scenario.yaml

    Run-generated (should be skipped):
      - 100/{U,p}                          (time directory)
      - 1.5/{U}                            (time directory with decimal)
      - processor0/...                     (parallel decomposition)
      - postProcessing/sets/...
      - constant/polyMesh/{points,faces}   (generated mesh)
      - log.simpleFoam, log.blockMesh      (run logs)
      - lid-cavity.foam                    (ParaView marker)
    """
    case.mkdir(parents=True)

    # Inputs
    (case / "system").mkdir()
    for f in ("controlDict", "fvSchemes", "fvSolution", "blockMeshDict"):
        (case / "system" / f).write_text(f"// {f}\n")

    (case / "constant").mkdir()
    (case / "constant" / "transportProperties").write_text("nu 1e-5;\n")
    (case / "constant" / "turbulenceProperties").write_text("simulationType laminar;\n")
    (case / "constant" / "triSurface").mkdir()
    (case / "constant" / "triSurface" / "geom.stl").write_text("solid demo\n")

    (case / "0").mkdir()
    (case / "0" / "U").write_text("// U\n")
    (case / "0" / "p").write_text("// p\n")

    (case / "REPORT.md").write_text("# Case setup report\n")
    (case / "Allrun").write_text("#!/bin/sh\necho run\n")
    (case / "Allclean").write_text("#!/bin/sh\necho clean\n")
    (case / "scenario.yaml").write_text("name: demo\n")

    # Run-generated
    (case / "100").mkdir()
    (case / "100" / "U").write_text("garbage\n")
    (case / "100" / "p").write_text("garbage\n")
    (case / "1.5").mkdir()
    (case / "1.5" / "U").write_text("garbage\n")

    (case / "processor0").mkdir()
    (case / "processor0" / "0").mkdir()
    (case / "processor0" / "0" / "U").write_text("garbage\n")

    (case / "postProcessing").mkdir()
    (case / "postProcessing" / "sets").mkdir()
    (case / "postProcessing" / "sets" / "data.dat").write_text("garbage\n")
    # postProcessing/forceCoeffs: large run output, stays excluded even though
    # it is a sibling of the kept analysis/ carve-out.
    (case / "postProcessing" / "forceCoeffs").mkdir()
    (case / "postProcessing" / "forceCoeffs" / "0").mkdir()
    (case / "postProcessing" / "forceCoeffs" / "0" / "coefficient.dat").write_text(
        "garbage\n"
    )

    # Replay assets authored/produced by validation.run_analysis:
    #   - analysis/validate.py     : top-level, already kept by existing logic
    #   - postProcessing/analysis/ : carved out of the excluded postProcessing
    (case / "analysis").mkdir()
    (case / "analysis" / "validate.py").write_text("# validate\n")
    (case / "postProcessing" / "analysis").mkdir()
    (case / "postProcessing" / "analysis" / "u_centerline.png").write_text("PNG\n")
    (case / "postProcessing" / "analysis" / "v_centerline.png").write_text("PNG\n")
    (case / "postProcessing" / "analysis" / "metrics.json").write_text("{}\n")

    (case / "constant" / "polyMesh").mkdir()
    (case / "constant" / "polyMesh" / "points").write_text("garbage\n")
    (case / "constant" / "polyMesh" / "faces").write_text("garbage\n")

    (case / "log.simpleFoam").write_text("garbage\n")
    (case / "log.blockMesh").write_text("garbage\n")
    (case / "lid-cavity.foam").write_text("")


class TestArchiveCase:
    def test_happy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        case = root / "cases" / "work" / "lid-cavity"
        _populate_full_case(case)

        result = archive_case(str(case), "lid-cavity")
        assert result["success"] is True

        archive = (
            root / "cases" / "examples" / "lid-cavity" / "baseline"
        )
        assert Path(result["archive_path"]) == archive
        assert archive.is_dir()

        # Inputs were copied.
        assert (archive / "system" / "controlDict").is_file()
        assert (archive / "system" / "blockMeshDict").is_file()
        assert (archive / "constant" / "transportProperties").is_file()
        assert (archive / "constant" / "triSurface" / "geom.stl").is_file()
        assert (archive / "0" / "U").is_file()
        assert (archive / "0" / "p").is_file()
        assert (archive / "REPORT.md").is_file()
        assert (archive / "Allrun").is_file()
        assert (archive / "Allclean").is_file()
        assert (archive / "scenario.yaml").is_file()

        # Replay assets (analysis script + carved-out plots/metrics) WERE copied.
        assert (archive / "analysis" / "validate.py").is_file()
        assert (archive / "postProcessing" / "analysis" / "u_centerline.png").is_file()
        assert (archive / "postProcessing" / "analysis" / "v_centerline.png").is_file()
        assert (archive / "postProcessing" / "analysis" / "metrics.json").is_file()

        # Run-generated content was NOT copied.
        assert not (archive / "100").exists()
        assert not (archive / "1.5").exists()
        assert not (archive / "processor0").exists()
        # postProcessing itself only survives as the analysis/ carve-out; all
        # other run output under it (sets, forceCoeffs) is still dropped.
        assert not (archive / "postProcessing" / "sets").exists()
        assert not (archive / "postProcessing" / "forceCoeffs").exists()
        assert not (archive / "constant" / "polyMesh").exists()
        assert not (archive / "log.simpleFoam").exists()
        assert not (archive / "log.blockMesh").exists()
        assert not (archive / "lid-cavity.foam").exists()

        # File count is non-zero and matches what we copied (sanity check).
        assert result["n_files_copied"] >= 10

    def test_zero_dir_is_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The "0/" directory holds initial conditions and must be archived
        # even though it's a digit-named directory.
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        case = root / "cases" / "work" / "demo"
        case.mkdir(parents=True)
        (case / "0").mkdir()
        (case / "0" / "U").write_text("// initial U\n")
        (case / "system").mkdir()
        (case / "system" / "controlDict").write_text("// controlDict\n")

        result = archive_case(str(case), "demo")
        assert result["success"] is True
        archive = root / "cases" / "examples" / "demo" / "baseline"
        assert (archive / "0" / "U").is_file()

    def test_refuses_when_archive_already_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        case = root / "cases" / "work" / "demo"
        _populate_full_case(case)

        first = archive_case(str(case), "demo")
        assert first["success"] is True

        second = archive_case(str(case), "demo")
        assert second["success"] is False
        assert second["reason"] == "archive_already_exists"

    def test_overwrite_replaces_existing_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        case = root / "cases" / "work" / "demo"
        _populate_full_case(case)

        archive_case(str(case), "demo")

        archive = root / "cases" / "examples" / "demo" / "baseline"
        # Drop a stale file that shouldn't survive an overwrite.
        (archive / "system" / "stale.dict").write_text("stale\n")
        assert (archive / "system" / "stale.dict").is_file()

        result = archive_case(str(case), "demo", overwrite=True)
        assert result["success"] is True
        # Stale file is gone — overwrite means "wipe and replace", not merge.
        assert not (archive / "system" / "stale.dict").exists()
        # Real inputs are still present.
        assert (archive / "system" / "controlDict").is_file()

    def test_invalid_case_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        result = archive_case(str(tmp_path / "nope"), "demo")
        assert result["success"] is False
        assert result["reason"] == "invalid_case_path"

    def test_invalid_archive_name_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        case = root / "cases" / "work" / "demo"
        _populate_full_case(case)

        for bad_name in [
            "",
            "  ",
            "with/slash",
            "../escape",
            ".hidden",
            "name with spaces",
        ]:
            result = archive_case(str(case), bad_name)
            assert result["success"] is False, f"expected rejection for {bad_name!r}"
            assert result["reason"] == "invalid_archive_name"

    def test_repo_root_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Override points at a path with no cases/ subdir → failure.
        bad_root = tmp_path / "no-cases-here"
        bad_root.mkdir()
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(bad_root))

        case = tmp_path / "work" / "demo"
        case.mkdir(parents=True)
        (case / "system").mkdir()

        result = archive_case(str(case), "demo")
        assert result["success"] is False
        assert result["reason"] == "root_not_found"

    def test_symlinks_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Symlinks (e.g. to a shared mesh outside the case dir) are not
        # archived — they're typically pointing at something we don't want
        # to pull in.
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        case = root / "cases" / "work" / "demo"
        case.mkdir(parents=True)
        (case / "system").mkdir()
        (case / "system" / "controlDict").write_text("// controlDict\n")

        external = tmp_path / "outside" / "shared.dat"
        external.parent.mkdir(parents=True)
        external.write_text("shared data\n")
        (case / "system" / "shared.dat").symlink_to(external)

        result = archive_case(str(case), "demo")
        assert result["success"] is True
        archive = root / "cases" / "examples" / "demo" / "baseline"
        assert (archive / "system" / "controlDict").is_file()
        assert not (archive / "system" / "shared.dat").exists()

    def test_analysis_carveout_kept_but_rest_of_postprocessing_dropped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # postProcessing/ is excluded, but its analysis/ child (validation
        # plots + metrics produced by run_analysis) must be archived so the
        # validation replays. Every other postProcessing child stays dropped.
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        case = root / "cases" / "work" / "demo"
        case.mkdir(parents=True)
        (case / "system").mkdir()
        (case / "system" / "controlDict").write_text("// controlDict\n")
        (case / "analysis").mkdir()
        (case / "analysis" / "validate.py").write_text("# validate\n")

        pp = case / "postProcessing"
        (pp / "analysis").mkdir(parents=True)
        (pp / "analysis" / "u_centerline.png").write_text("PNG\n")
        (pp / "analysis" / "metrics.json").write_text('{"l2_error": 0.03}\n')
        # Sibling run output that must NOT travel into the archive.
        (pp / "forceCoeffs" / "0").mkdir(parents=True)
        (pp / "forceCoeffs" / "0" / "coefficient.dat").write_text("garbage\n")

        result = archive_case(str(case), "demo")
        assert result["success"] is True
        archive = root / "cases" / "examples" / "demo" / "baseline"

        # Carve-out and top-level script archived.
        assert (archive / "analysis" / "validate.py").is_file()
        assert (archive / "postProcessing" / "analysis" / "u_centerline.png").is_file()
        assert (
            archive / "postProcessing" / "analysis" / "metrics.json"
        ).read_text() == '{"l2_error": 0.03}\n'
        # Sibling run output dropped; only the analysis/ child of
        # postProcessing exists in the archive.
        assert not (archive / "postProcessing" / "forceCoeffs").exists()
        assert sorted(
            p.name for p in (archive / "postProcessing").iterdir()
        ) == ["analysis"]

    def test_no_empty_postprocessing_when_analysis_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # When postProcessing/ holds only run output (no analysis/ carve-out),
        # nothing under it is kept and no empty postProcessing/ dir is
        # materialised in the archive — preserving the old behaviour.
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        case = root / "cases" / "work" / "demo"
        case.mkdir(parents=True)
        (case / "system").mkdir()
        (case / "system" / "controlDict").write_text("// controlDict\n")
        (case / "postProcessing" / "sets").mkdir(parents=True)
        (case / "postProcessing" / "sets" / "data.dat").write_text("garbage\n")

        result = archive_case(str(case), "demo")
        assert result["success"] is True
        archive = root / "cases" / "examples" / "demo" / "baseline"
        assert (archive / "system" / "controlDict").is_file()
        assert not (archive / "postProcessing").exists()

    def test_polymesh_not_carved_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The carve-out is scoped to postProcessing/analysis only. An
        # accidentally-named analysis/ dir inside polyMesh/ (a different
        # excluded dir) is NOT rescued.
        root = tmp_path / "fake-repo"
        (root / "cases").mkdir(parents=True)
        monkeypatch.setenv("AGENTIC_OPENFOAM_ROOT", str(root))

        case = root / "cases" / "work" / "demo"
        case.mkdir(parents=True)
        (case / "system").mkdir()
        (case / "system" / "controlDict").write_text("// controlDict\n")
        (case / "constant" / "polyMesh" / "analysis").mkdir(parents=True)
        (case / "constant" / "polyMesh" / "analysis" / "x.png").write_text("PNG\n")
        (case / "constant" / "polyMesh" / "points").write_text("garbage\n")

        result = archive_case(str(case), "demo")
        assert result["success"] is True
        archive = root / "cases" / "examples" / "demo" / "baseline"
        assert not (archive / "constant" / "polyMesh").exists()


class TestSnappyPhaseParser:
    def _log(self, tmp_path: Path, text: str) -> Path:
        p = tmp_path / "log.snappyHexMesh"
        p.write_text(text, encoding="utf-8")
        return p

    def test_step_markers_tolerate_trailing_whitespace(self, tmp_path: Path) -> None:
        # A trailing space after "Time = N" used to defeat the raw-substring
        # match and report a completed mesh as not_run.
        out = _tools._parse_snappy_phases(
            self._log(tmp_path, "Time = 1 \nTime = 2 \nTime = 3 \n")
        )
        assert out["castellation"] == "ok"
        assert out["snap"] == "ok"
        assert out["layers"] == "ok"

    def test_two_phase_run_marks_layers_skipped(self, tmp_path: Path) -> None:
        out = _tools._parse_snappy_phases(self._log(tmp_path, "Time = 1\nTime = 2\n"))
        assert out["castellation"] == "ok"
        assert out["snap"] == "ok"
        assert out["layers"] == "skipped"

    def test_castellation_only_marks_snap_skipped(self, tmp_path: Path) -> None:
        out = _tools._parse_snappy_phases(self._log(tmp_path, "Time = 1\n"))
        assert out["castellation"] == "ok"
        assert out["snap"] == "skipped"
        assert out["layers"] == "not_run"

    def test_no_steps_is_not_run(self, tmp_path: Path) -> None:
        out = _tools._parse_snappy_phases(self._log(tmp_path, "Reading mesh ...\n"))
        assert out["castellation"] == "not_run"
        assert out["snap"] == "not_run"
        assert out["layers"] == "not_run"


class TestClassifySolverFailure:
    def _log(self, tmp_path: Path, text: str) -> Path:
        p = tmp_path / "log.simpleFoam"
        p.write_text(text, encoding="utf-8")
        return p

    def test_foam_fatal_is_solver_error(self, tmp_path: Path) -> None:
        log = self._log(tmp_path, "--> FOAM FATAL IO ERROR:\ncannot find file 0/U\n")
        assert _tools._classify_solver_failure(log) == "solver_error"

    def test_numerical_blowup_without_marker_is_diverged(self, tmp_path: Path) -> None:
        log = self._log(tmp_path, "Time = 5\nbounding k\nFloating point exception\n")
        assert _tools._classify_solver_failure(log) == "diverged"

    def test_missing_log_defaults_to_diverged(self, tmp_path: Path) -> None:
        assert _tools._classify_solver_failure(tmp_path / "nope.log") == "diverged"
