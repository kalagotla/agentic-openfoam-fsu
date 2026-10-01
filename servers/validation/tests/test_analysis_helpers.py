"""Tests for validation_mcp.analysis (helpers for agent-authored scripts)."""

import json

import numpy as np
import pytest

from validation_mcp.analysis import emit, latest_set, read_set
from validation_mcp.tools import _parse_analysis_sentinel


def _write_set(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# distance U_x U_y U_z\n" + "\n".join(" ".join(map(str, r)) for r in rows) + "\n")


def test_latest_set_picks_newest_time(tmp_path):
    _write_set(tmp_path / "postProcessing/line/100/line_U.xy", [[0, 1, 2, 0]])
    _write_set(tmp_path / "postProcessing/line/250/line_U.xy", [[0, 3, 4, 0]])
    _write_set(tmp_path / "postProcessing/line/250/line_p.xy", [[0, 5]])
    assert latest_set(tmp_path, "line", "U").parts[-2:] == ("250", "line_U.xy")
    assert latest_set(tmp_path, "line", "p").name == "line_p.xy"


def test_latest_set_falls_back_to_name_match(tmp_path):
    # e.g. a function object named "sets" writing <setName>_U.xy files
    _write_set(tmp_path / "postProcessing/sets/500/centreline_U.xy", [[0, 1, 0, 0]])
    assert latest_set(tmp_path, "centreline", "U").name == "centreline_U.xy"


def test_latest_set_error_lists_files(tmp_path):
    _write_set(tmp_path / "postProcessing/other/1/other_U.xy", [[0, 1, 0, 0]])
    with pytest.raises(FileNotFoundError, match="other_U.xy"):
        latest_set(tmp_path, "missing", "U")


def test_read_set_vector_and_scalar(tmp_path):
    vec = tmp_path / "v.xy"
    _write_set(vec, [[0.0, 1.0, 2.0, 0.0], [0.5, 3.0, 4.0, 0.0]])
    coord, U = read_set(vec)
    assert coord.tolist() == [0.0, 0.5]
    assert U.shape == (2, 3) and U[1, 1] == 4.0
    sca = tmp_path / "s.xy"
    sca.write_text("0 1\n1 2\n")
    coord, p = read_set(sca)
    assert p.shape == (2,) and p.tolist() == [1.0, 2.0]


def test_emit_round_trips_through_run_analysis_parser(capsys):
    emit({"u": {"l2_error": np.float64(0.01), "within_tolerance": np.bool_(True), "x": np.arange(2)}},
         plots=["postProcessing/analysis/u.png"])
    payload, err = _parse_analysis_sentinel(capsys.readouterr().out)
    assert err is None
    assert payload["metrics"]["u"] == {"l2_error": 0.01, "within_tolerance": True, "x": [0, 1]}
    assert payload["plots"] == ["postProcessing/analysis/u.png"]
    json.dumps(payload)
