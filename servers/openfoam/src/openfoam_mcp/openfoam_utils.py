"""Lower-level OpenFOAM utilities — log parsing, dictionary helpers.

Kept separate from ``tools.py`` so these helpers are testable without
involving the MCP server.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

# Regex for lines like: "  nPoints: 12345"
_MESH_STAT_LINE = re.compile(r"\s*([A-Za-z]+):\s*([0-9.]+)")

# Keys of interest from `blockMesh` / `checkMesh` output
_MESH_STAT_KEYS = {
    "nPoints": "n_points",
    "nCells": "n_cells",
    "nFaces": "n_faces",
    "nInternalFaces": "n_internal_faces",
    "nBoundaryFaces": "n_boundary_faces",
}

# A SIMPLE/PIMPLE solver log line we care about looks like:
#   smoothSolver:  Solving for Ux, Initial residual = 0.000110215, Final residual = 1.02392e-05, No Iterations 4
#   GAMG:  Solving for p, Initial residual = 0.00461919, Final residual = 0.000325975, No Iterations 2
_RESIDUAL_LINE = re.compile(
    r"Solving for (\w+),\s*Initial residual\s*=\s*([\deE+\-.]+),"
    r"\s*Final residual\s*=\s*([\deE+\-.]+),\s*No Iterations\s*(\d+)"
)

# Time stamp lines in a transient/SIMPLE log: "Time = 321"
_TIME_LINE = re.compile(r"^Time\s*=\s*([\deE+\-.]+)\s*$")

# Walltime line at the bottom of each iteration's output block:
#   "ExecutionTime = 3.46 s  ClockTime = 3 s"
_WALLTIME_LINE = re.compile(
    r"ExecutionTime\s*=\s*([\deE+\-.]+)\s*s\s*ClockTime\s*=\s*([\deE+\-.]+)\s*s"
)

# Convergence sentinels emitted by simpleFoam / pimpleFoam.
_CONVERGED_MARKERS = (
    "SIMPLE solution converged",
    "PIMPLE: converged",
)


def tail_log(log_file: Path, n_lines: int) -> str:
    """Return the last ``n_lines`` of a log file, or an explanatory message."""
    if not log_file.exists():
        return f"(no log at {log_file})"
    try:
        lines = log_file.read_text(errors="replace").splitlines()
    except OSError as exc:
        return f"(could not read {log_file}: {exc})"
    return "\n".join(lines[-n_lines:])


def parse_mesh_stats(log_file: Path) -> dict[str, Any]:
    """Extract mesh statistics from a ``blockMesh`` or ``checkMesh`` log.

    This is deliberately forgiving — if a field is missing we just omit it
    rather than raising. The agent will see whatever we managed to parse.
    """
    stats: dict[str, Any] = {}
    if not log_file.exists():
        return stats

    for line in log_file.read_text(errors="replace").splitlines():
        match = _MESH_STAT_LINE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if key in _MESH_STAT_KEYS:
            try:
                stats[_MESH_STAT_KEYS[key]] = int(value)
            except ValueError:
                stats[_MESH_STAT_KEYS[key]] = float(value)

    return stats


def parse_residual_history(log_file: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse a solver log into a per-field residual history.

    Returns a dict keyed by field name (``"Ux"``, ``"Uy"``, ``"p"``, ``"k"``,
    ``"epsilon"``, ...) where each value is a list of
    ``{"iteration": int, "initial": float, "final": float, "n_iter_inner": int}``
    entries — one per outer SIMPLE / PIMPLE iteration. Iteration numbers come
    from the ``Time = N`` markers.

    Forgiving: lines that don't match are skipped. Empty dict if the log is
    absent or has no recognisable solver output.
    """
    history: dict[str, list[dict[str, Any]]] = {}
    if not log_file.exists():
        return history

    current_iter = 0
    for line in log_file.read_text(errors="replace").splitlines():
        time_match = _TIME_LINE.match(line)
        if time_match:
            try:
                current_iter = int(float(time_match.group(1)))
            except ValueError:
                pass
            continue

        match = _RESIDUAL_LINE.search(line)
        if not match:
            continue
        field = match.group(1)
        try:
            initial = float(match.group(2))
            final = float(match.group(3))
            n_inner = int(match.group(4))
        except ValueError:
            continue
        history.setdefault(field, []).append({
            "iteration": current_iter,
            "initial": initial,
            "final": final,
            "n_iter_inner": n_inner,
        })

    return history


def final_residuals(history: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    """Pick out the last initial-residual per field from a parsed history.

    The "initial" residual on the last outer iteration is the value compared
    against ``residualControl`` thresholds, so it's the one to report.
    """
    return {field: entries[-1]["initial"] for field, entries in history.items() if entries}


def parse_walltime_seconds(log_file: Path) -> float | None:
    """Return the final ClockTime (s) reported in the log, or None."""
    if not log_file.exists():
        return None
    last: float | None = None
    for line in log_file.read_text(errors="replace").splitlines():
        match = _WALLTIME_LINE.search(line)
        if match:
            try:
                last = float(match.group(2))
            except ValueError:
                continue
    return last


def is_converged(log_file: Path) -> bool:
    """Return True if the log emits a SIMPLE/PIMPLE convergence sentinel.

    Convergence here means "residualControl thresholds met"; a solver that
    runs to ``endTime`` without hitting them is considered not-converged
    even if its final residuals are small.
    """
    if not log_file.exists():
        return False
    text = log_file.read_text(errors="replace")
    return any(marker in text for marker in _CONVERGED_MARKERS)


def foam_dictionary_get(dict_path: Path, entry: str) -> str:
    """Read an OpenFOAM dictionary entry via ``foamDictionary -value``.

    Raises ``subprocess.CalledProcessError`` if foamDictionary fails or is
    not on PATH; callers in ``tools.py`` translate to structured errors.
    """
    result = subprocess.run(
        ["foamDictionary", "-entry", entry, "-value", str(dict_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def foam_dictionary_set(dict_path: Path, entry: str, value: str) -> None:
    """Set an OpenFOAM dictionary entry via ``foamDictionary -set``."""
    subprocess.run(
        ["foamDictionary", "-entry", entry, "-set", value, str(dict_path)],
        check=True,
        capture_output=True,
        text=True,
    )
