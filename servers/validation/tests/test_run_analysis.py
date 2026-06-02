"""Tests for validation.run_analysis — the agent-authored-script runner.

These exercise the tool directly with tiny stub scripts; no OpenFOAM needed.
The security-critical behaviours (process-group kill, resource caps, secret
stripping) have dedicated regression tests.

Run with: ``uv run pytest servers/validation/tests/test_run_analysis.py``
"""

from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from validation_mcp import tools as _tools
from validation_mcp.tools import run_analysis

POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="POSIX-only behaviour")


def _write_script(case: Path, body: str, name: str = "analysis/validate.py") -> None:
    path = case / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body))


def _case(tmp_path: Path) -> Path:
    case = tmp_path / "work-case"
    case.mkdir()
    return case


class TestHappyPath:
    def test_emits_sentinel_and_verifies_plot(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        _write_script(
            case,
            """
            import json, os
            os.makedirs("postProcessing/analysis", exist_ok=True)
            open("postProcessing/analysis/u.png", "w").write("PNG")
            print("narration the agent emitted")
            print("<<<ANALYSIS_RESULT>>>")
            print(json.dumps({"metrics": {"within_tolerance": True, "l2": 0.03},
                              "plots": ["postProcessing/analysis/u.png"]}))
            """,
        )
        r = run_analysis(str(case))
        assert r["success"] is True
        assert r["metrics"] == {"within_tolerance": True, "l2": 0.03}
        assert r["plots"] == ["postProcessing/analysis/u.png"]
        assert r["missing_plots"] == []
        assert "narration the agent emitted" in r["stdout_tail"]
        assert r["returncode"] == 0

    def test_cwd_is_case_dir(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        _write_script(
            case,
            """
            import json, os
            open("ran_here.txt", "w").write("yes")
            print("<<<ANALYSIS_RESULT>>>")
            print(json.dumps({"metrics": {}, "plots": []}))
            """,
        )
        assert run_analysis(str(case))["success"] is True
        assert (case / "ran_here.txt").read_text() == "yes"

    def test_last_sentinel_wins(self, tmp_path: Path) -> None:
        # A literal sentinel in earlier narration must not shadow the real one.
        case = _case(tmp_path)
        _write_script(
            case,
            """
            import json
            print("about to print <<<ANALYSIS_RESULT>>> as a literal token")
            print('{"metrics": {"decoy": true}, "plots": []}')
            print("<<<ANALYSIS_RESULT>>>")
            print(json.dumps({"metrics": {"real": True}, "plots": []}))
            """,
        )
        r = run_analysis(str(case))
        assert r["success"] is True
        assert r["metrics"] == {"real": True}


class TestPlotVerification:
    def test_declared_plot_not_written_is_dropped(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        _write_script(
            case,
            """
            import json
            print("<<<ANALYSIS_RESULT>>>")
            print(json.dumps({"metrics": {}, "plots": ["postProcessing/analysis/ghost.png"]}))
            """,
        )
        r = run_analysis(str(case))
        assert r["success"] is True
        assert r["plots"] == []
        assert r["missing_plots"] == ["postProcessing/analysis/ghost.png"]

    @POSIX_ONLY
    def test_plot_symlink_escape_dropped(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        outside = tmp_path / "outside.png"
        outside.write_text("PNG")
        (case / "analysis").mkdir(parents=True, exist_ok=True)
        os.symlink(outside, case / "analysis" / "escape.png")
        _write_script(
            case,
            """
            import json
            print("<<<ANALYSIS_RESULT>>>")
            print(json.dumps({"metrics": {}, "plots": ["analysis/escape.png"]}))
            """,
        )
        r = run_analysis(str(case))
        # The symlink resolves outside the case dir → dropped, not returned.
        assert r["plots"] == []
        assert "analysis/escape.png" in r["missing_plots"]


class TestScriptFailures:
    def test_nonzero_exit_reports_script_error_with_traceback(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        _write_script(case, "raise ValueError('extraction blew up')\n")
        r = run_analysis(str(case))
        assert r["success"] is False
        assert r["reason"] == "script_error"
        assert "ValueError: extraction blew up" in r["stderr_tail"]

    def test_exit_zero_without_sentinel_is_no_result_sentinel(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        _write_script(case, "print('did work but forgot the sentinel')\n")
        r = run_analysis(str(case))
        assert r["success"] is False
        assert r["reason"] == "no_result_sentinel"

    def test_unparseable_json_is_bad_result_json(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        _write_script(
            case,
            """
            print("<<<ANALYSIS_RESULT>>>")
            print("{this is not valid json")
            """,
        )
        r = run_analysis(str(case))
        assert r["success"] is False
        assert r["reason"] == "bad_result_json"

    def test_oversize_result_json_is_bad_result_json(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        _write_script(
            case,
            """
            import json
            print("<<<ANALYSIS_RESULT>>>")
            print(json.dumps({"metrics": {"blob": "x" * (300 * 1024)}, "plots": []}))
            """,
        )
        r = run_analysis(str(case))
        assert r["success"] is False
        assert r["reason"] == "bad_result_json"


class TestInputValidation:
    def test_invalid_case_path(self, tmp_path: Path) -> None:
        r = run_analysis(str(tmp_path / "nope"))
        assert r["success"] is False
        assert r["reason"] == "invalid_case_path"

    def test_missing_script_is_script_not_found(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        r = run_analysis(str(case))
        assert r["success"] is False
        assert r["reason"] == "script_not_found"

    @pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.py", "../../x.py", "a/../../b.py"])
    def test_path_escape_rejected(self, tmp_path: Path, bad: str) -> None:
        case = _case(tmp_path)
        r = run_analysis(str(case), script=bad)
        assert r["success"] is False
        assert r["reason"] == "path_escape"


class TestSandbox:
    @POSIX_ONLY
    def test_timeout_kills_process_group(self, tmp_path: Path) -> None:
        # Regression for the "subprocess.run(timeout) leaks grandchildren" bug:
        # the script forks a `sleep` grandchild; on timeout the whole group must
        # be killed, not just the direct child.
        case = _case(tmp_path)
        _write_script(
            case,
            """
            import subprocess, sys, time
            p = subprocess.Popen(["sleep", "60"])
            with open("grandchild.pid", "w") as f:
                f.write(str(p.pid))
            sys.stdout.flush()
            time.sleep(60)
            """,
        )
        r = run_analysis(str(case), timeout_s=3)
        assert r["success"] is False
        assert r["reason"] == "timeout"
        pid = int((case / "grandchild.pid").read_text())
        # The grandchild must die shortly after the group kill.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

    @POSIX_ONLY
    @pytest.mark.skipif(_tools.resource is None, reason="resource module unavailable")
    def test_rlimit_caps_memory(self, tmp_path: Path) -> None:
        case = _case(tmp_path)
        _write_script(
            case,
            """
            import numpy as np
            x = np.ones((2 * 1024**3,), dtype="f8")  # ~16 GiB > RLIMIT_AS
            print(x.sum())
            """,
        )
        r = run_analysis(str(case))
        assert r["success"] is False
        assert r["reason"] == "script_error"

    def test_minimal_env_strips_secrets_and_forces_agg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECRET_TOKEN", "hunter2")
        case = _case(tmp_path)
        _write_script(
            case,
            """
            import json, os
            print("SECRET=" + os.environ.get("SECRET_TOKEN", "ABSENT"))
            print("MPLBACKEND=" + os.environ.get("MPLBACKEND", "UNSET"))
            print("<<<ANALYSIS_RESULT>>>")
            print(json.dumps({"metrics": {}, "plots": []}))
            """,
        )
        r = run_analysis(str(case))
        assert r["success"] is True
        assert "SECRET=ABSENT" in r["stdout_tail"]
        assert "MPLBACKEND=Agg" in r["stdout_tail"]


class TestTrustHinge:
    def test_script_can_import_validation_primitives(self, tmp_path: Path) -> None:
        # The script must be able to load reference data + score via the
        # trusted primitive from a foreign cwd — this is the whole point.
        case = _case(tmp_path)
        _write_script(
            case,
            """
            import json
            from validation_mcp.tools import read_reference, compare_profiles
            ref = read_reference("ghia_1982")
            ok = ref["success"]
            cp = compare_profiles([0, 1], [0, 1], [0, 1], [0, 1.05])
            print("<<<ANALYSIS_RESULT>>>")
            print(json.dumps({"metrics": {"ref_ok": ok, "cp_ok": cp["success"]}, "plots": []}))
            """,
        )
        r = run_analysis(str(case))
        assert r["success"] is True
        assert r["metrics"]["ref_ok"] is True
        assert r["metrics"]["cp_ok"] is True
