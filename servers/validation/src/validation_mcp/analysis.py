"""Helpers for agent-authored ``analysis/validate.py`` scripts.

The validation contract (see ``run_analysis``) leaves extraction to the
script, but two parts of it are the same for every case and easy to get
wrong: finding and parsing the files an OpenFOAM ``sets`` function object
writes, and printing the result in the form ``run_analysis`` parses. These
helpers do exactly that and nothing case-specific::

    from validation_mcp.analysis import latest_set, read_set, emit
    from validation_mcp.tools import read_reference, compare_profiles

    coord, U = read_set(latest_set(".", "centreline", "U"))
    ...
    emit({"u_centerline": result}, plots=["postProcessing/analysis/u.png"])
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from validation_mcp.tools import _ANALYSIS_SENTINEL


def _time_key(p: Path) -> float:
    try:
        return float(p.name)
    except ValueError:
        return float("-inf")


def latest_set(case: str | Path, name: str, field: str | None = None) -> Path:
    """Path of the newest sampled file a ``sets`` function object wrote.

    Looks under ``<case>/postProcessing/<name>/<time>/`` (the layout of a
    function object called ``name``) and, failing that, anywhere below
    ``postProcessing/`` for a file whose name contains ``name``. With
    ``field`` given, the file name must also contain it (``line_U.xy``).
    Raises ``FileNotFoundError`` listing what exists, so a wrong name is
    obvious from the error alone.
    """
    root = Path(case) / "postProcessing"
    if not root.is_dir():
        raise FileNotFoundError(f"{root} does not exist — did the solver run with the sets function object?")

    def wanted(f: Path) -> bool:
        return f.is_file() and (field is None or field in f.name)

    candidates: list[Path] = []
    fo_dir = root / name
    if fo_dir.is_dir():
        for tdir in sorted((d for d in fo_dir.iterdir() if d.is_dir()), key=_time_key, reverse=True):
            files = sorted(f for f in tdir.iterdir() if wanted(f))
            if files:
                candidates = files
                break
    if not candidates:
        hits = [f for f in root.rglob("*") if wanted(f) and name in f.name]
        hits.sort(key=lambda f: _time_key(f.parent), reverse=True)
        candidates = hits[:1]
    if not candidates:
        existing = sorted(str(f.relative_to(root)) for f in root.rglob("*") if f.is_file())[:30]
        raise FileNotFoundError(
            f"no sampled file for set {name!r}" + (f" field {field!r}" if field else "")
            + f" under {root}. Files present: {existing}"
        )
    return candidates[0]


def read_set(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Load an OpenFOAM ``raw`` (``.xy``) sampled set.

    Returns ``(coord, values)``: ``coord`` is the first column (distance or
    the axis coordinate, as the set was configured) and ``values`` the
    remaining columns, shape ``(n,)`` for a scalar field or ``(n, k)`` for a
    vector/tensor field (``U`` gives columns Ux, Uy, Uz). Comment lines
    starting with ``#`` are skipped.
    """
    data = np.loadtxt(path, comments="#", ndmin=2)
    if data.shape[1] < 2:
        raise ValueError(f"{path}: expected a coordinate column plus at least one value column")
    values = data[:, 1:]
    return data[:, 0], (values[:, 0] if values.shape[1] == 1 else values)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def emit(metrics: dict[str, Any], plots: list[str] | tuple[str, ...] = ()) -> None:
    """Print the result block ``run_analysis`` reads, as the script's last output.

    ``metrics`` is typically ``{"<quantity>": <compare_profiles result>}``;
    ``plots`` are case-relative paths of the figures the script saved.
    """
    sys.stdout.flush()
    print(_ANALYSIS_SENTINEL)
    print(json.dumps({"metrics": _jsonable(metrics), "plots": list(plots)}))
    sys.stdout.flush()
