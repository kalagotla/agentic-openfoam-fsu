"""Tool implementations for the OpenFOAM MCP server.

Design rules (see ``docs/architecture.md``):

1. **Every tool returns a dict with ``success: bool``.** Never raise.
   The agent needs to reason about failures — a traceback is not useful.
2. **Logs are tailed, never dumped.** OpenFOAM logs are often thousands of
   lines. We return the last ~50 lines so the agent has context without
   blowing its token budget.
3. **Tool docstrings are the agent's documentation.** Keep them tight and
   accurate — the LLM reads them to decide which tool to call.

Status: ``run_blockmesh`` is fully implemented as a reference. The rest
are signatures + docstrings with ``NotImplementedError`` bodies. Fill them
in during the Week of 11 May (see ``docs/build-plan.md``).
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openfoam_mcp.openfoam_utils import (
    final_residuals,
    foam_dictionary_get,
    foam_dictionary_set,
    is_converged,
    parse_mesh_stats,
    parse_residual_history,
    parse_walltime_seconds,
    tail_log,
)

ToolResult = dict[str, Any]

LOG_TAIL_LINES = 50
DEFAULT_SOLVER_TIMEOUT_S = 600

# log.<name> files written by mesh / case-prep utilities, not by solvers. Used
# by get_residuals to skip them when discovering the latest solver log.
_UTILITY_LOG_SUFFIXES = frozenset({
    "blockMesh",
    "checkMesh",
    "snappyHexMesh",
    "foamDictionary",
    "decomposePar",
    "reconstructPar",
    "renumberMesh",
    "topoSet",
    "createPatch",
    "transformPoints",
    "extrudeMesh",
    "setFields",
    "potentialFoam",
})


def _find_latest_solver_log(case: Path) -> Path | None:
    """Return the most-recent ``log.<solver>`` file, or None if none exist."""
    candidates: list[Path] = []
    for path in case.glob("log.*"):
        if not path.is_file():
            continue
        # path.suffix on "log.simpleFoam" is ".simpleFoam"; strip the dot.
        suffix = path.suffix.lstrip(".")
        if suffix in _UTILITY_LOG_SUFFIXES:
            continue
        candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run_blockmesh(case_path: str) -> ToolResult:
    """Generate the mesh for an OpenFOAM case using ``blockMesh``.

    Args:
        case_path: Absolute path to the OpenFOAM case directory. Must contain
            ``system/blockMeshDict``.

    Returns:
        On success: ``{"success": True, "mesh_stats": {...}, "log_tail": str}``.
        The ``mesh_stats`` dict has ``n_points``, ``n_cells``, ``n_faces``,
        ``n_boundary_patches``, and ``max_aspect_ratio``.

        On failure: ``{"success": False, "reason": str, "log_tail": str}``.
        ``reason`` is a short classification (``"missing_dict"``,
        ``"mesh_generation_failed"``, ``"timeout"``) that the agent can
        pattern-match on.
    """
    case = Path(case_path)
    dict_path = case / "system" / "blockMeshDict"
    if not dict_path.exists():
        return {
            "success": False,
            "reason": "missing_dict",
            "log_tail": f"Expected {dict_path} to exist.",
        }

    log_file = case / "log.blockMesh"
    try:
        with log_file.open("w") as log:
            result = subprocess.run(
                ["blockMesh", "-case", str(case)],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "reason": "timeout",
            "log_tail": tail_log(log_file, LOG_TAIL_LINES),
        }
    except FileNotFoundError:
        return {
            "success": False,
            "reason": "blockmesh_not_on_path",
            "log_tail": "blockMesh CLI not found. Is OpenFOAM sourced?",
        }

    log_tail = tail_log(log_file, LOG_TAIL_LINES)
    if result.returncode != 0:
        return {
            "success": False,
            "reason": "mesh_generation_failed",
            "log_tail": log_tail,
        }

    return {
        "success": True,
        "mesh_stats": parse_mesh_stats(log_file),
        "log_tail": log_tail,
    }


# checkMesh output patterns. The format has been stable across OpenFOAM
# releases; tested against v2412 output. Lines look like:
#   "    Max aspect ratio = 4.93 OK."
#   "    Mesh non-orthogonality Max: 5.93 average: 1.40"
#   "    Max skewness = 0.51 OK."
#   " ***Number of severely non-orthogonal (> 70 degrees) faces: 42."
#   "Mesh OK." or "Failed 2 mesh checks."
_CHECKMESH_AR = re.compile(r"Max aspect ratio\s*=\s*([\deE+\-.]+)")
_CHECKMESH_NONORTHO = re.compile(
    r"Mesh non-orthogonality Max:\s*([\deE+\-.]+)\s+average:\s*([\deE+\-.]+)"
)
_CHECKMESH_SKEWNESS = re.compile(r"Max skewness\s*=\s*([\deE+\-.]+)")
_CHECKMESH_NCELLS = re.compile(r"^\s*cells:\s*(\d+)")
_CHECKMESH_SEVERE = re.compile(
    r"severely non-orthogonal[^:]*:\s*(\d+)", re.IGNORECASE
)
_CHECKMESH_OK = re.compile(r"^Mesh OK\.")
_CHECKMESH_FAILED = re.compile(r"^Failed\s+(\d+)\s+mesh checks?\.")


def check_mesh(case_path: str) -> ToolResult:
    """Run OpenFOAM's ``checkMesh`` and return parsed quality metrics.

    Always run this after generating a mesh. A converged solver on a bad
    mesh is still wrong — non-orthogonality and skewness are the two
    metrics that bite first.

    Args:
        case_path: Absolute path to the OpenFOAM case directory. Must
            contain a generated mesh at ``constant/polyMesh/``.

    Returns:
        On success: ``{"success": True, "quality_pass": bool, "metrics": {...},
        "warnings": [str, ...], "log_tail": str}``. ``metrics`` includes
        ``n_cells``, ``max_aspect_ratio``, ``max_non_orthogonality``,
        ``average_non_orthogonality``, ``max_skewness``, and
        ``severe_non_orthogonal_faces``. ``quality_pass`` is True only when
        ``checkMesh`` prints ``Mesh OK.``. ``warnings`` collects every line
        ``checkMesh`` marked with ``***`` (the standard failure marker).

        On failure: ``{"success": False, "reason": str, "log_tail": str}``.
        ``reason`` is one of ``"polymesh_missing"``,
        ``"checkmesh_not_on_path"``, ``"timeout"``, ``"checkmesh_failed"``.
    """
    case = Path(case_path)
    polymesh = case / "constant" / "polyMesh"
    if not polymesh.is_dir():
        return {
            "success": False,
            "reason": "polymesh_missing",
            "log_tail": f"Expected {polymesh} to exist. Run blockMesh first.",
        }

    log_file = case / "log.checkMesh"
    try:
        with log_file.open("w") as log:
            result = subprocess.run(
                ["checkMesh", "-case", str(case)],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "reason": "timeout",
            "log_tail": tail_log(log_file, LOG_TAIL_LINES),
        }
    except FileNotFoundError:
        return {
            "success": False,
            "reason": "checkmesh_not_on_path",
            "log_tail": "checkMesh CLI not found. Is OpenFOAM sourced?",
        }

    log_tail = tail_log(log_file, LOG_TAIL_LINES)
    # checkMesh returns 0 even when the mesh has failures — it only non-zero
    # exits on infrastructure errors (missing files, can't read polyMesh).
    if result.returncode != 0:
        return {
            "success": False,
            "reason": "checkmesh_failed",
            "log_tail": log_tail,
        }

    return _parse_check_mesh(log_file, log_tail)


def _parse_check_mesh(log_file: Path, log_tail: str) -> ToolResult:
    """Extract quality metrics from a ``log.checkMesh`` file."""
    metrics: dict[str, Any] = {
        "n_cells": None,
        "max_aspect_ratio": None,
        "max_non_orthogonality": None,
        "average_non_orthogonality": None,
        "max_skewness": None,
        "severe_non_orthogonal_faces": 0,
    }
    warnings: list[str] = []
    quality_pass = False
    explicit_failure = False

    for line in log_file.read_text(errors="replace").splitlines():
        stripped = line.strip()

        if "***" in line:
            warnings.append(stripped)

        if _CHECKMESH_OK.match(stripped):
            quality_pass = True
            continue
        if _CHECKMESH_FAILED.match(stripped):
            explicit_failure = True
            continue

        if metrics["n_cells"] is None:
            m = _CHECKMESH_NCELLS.match(line)
            if m:
                metrics["n_cells"] = int(m.group(1))
                continue

        m = _CHECKMESH_AR.search(line)
        if m:
            metrics["max_aspect_ratio"] = float(m.group(1))
            continue

        m = _CHECKMESH_NONORTHO.search(line)
        if m:
            metrics["max_non_orthogonality"] = float(m.group(1))
            metrics["average_non_orthogonality"] = float(m.group(2))
            continue

        m = _CHECKMESH_SKEWNESS.search(line)
        if m:
            metrics["max_skewness"] = float(m.group(1))
            continue

        m = _CHECKMESH_SEVERE.search(line)
        if m:
            metrics["severe_non_orthogonal_faces"] = int(m.group(1))
            continue

    # If checkMesh printed neither "Mesh OK." nor "Failed N mesh checks.",
    # treat it as a failure with the warnings we collected.
    if explicit_failure:
        quality_pass = False

    return {
        "success": True,
        "quality_pass": quality_pass,
        "metrics": metrics,
        "warnings": warnings,
        "log_tail": log_tail,
    }


# surfaceCheck output patterns. Stable across OpenFOAM v2412.
#   "Triangles            : 12345"
#   "Triangle area        : min..max = ..."
#   "Number of open edges (incomplete surface) : 0"
#   "Surface is closed."
#   "Surface is open."
_SURFCHECK_NTRI = re.compile(r"Triangles\s*:\s*(\d+)")
_SURFCHECK_NOPEN = re.compile(r"Number of open edges[^:]*:\s*(\d+)")
_SURFCHECK_CLOSED = re.compile(r"Surface is closed\.")
_SURFCHECK_OPEN = re.compile(r"Surface is open\.")


def prepare_surface_mesh(
    case_path: str,
    stl_path: str,
    patch_name: str | None = None,
    run_check: bool = True,
) -> ToolResult:
    """Drop an STL into a case's ``constant/triSurface/`` directory.

    Use this before ``run_snappy_hex_mesh``. The STL is copied (not moved)
    so the source file is preserved. By default, ``surfaceCheck`` runs on
    the copied file and the parsed result (triangle count, open-edge
    count, closed/open verdict) is returned so the agent can decide
    whether the geometry is mesh-ready.

    Args:
        case_path: Absolute path to the OpenFOAM case directory.
        stl_path: Absolute path to the source STL file.
        patch_name: Optional new basename (without ``.stl``). If None, the
            source filename is used. Must not contain path separators.
        run_check: If True (default), run ``surfaceCheck`` after copying
            and include parsed results in the response.

    Returns:
        On success: ``{"success": True, "dest_path": str,
        "surface_check": {...}, "log_tail": str}``. The ``surface_check``
        dict has ``n_triangles``, ``n_open_edges``, ``is_closed`` (bool),
        and ``raw_log_tail``. If ``run_check=False``, ``surface_check``
        is None.

        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of ``"invalid_case_path"``, ``"stl_not_found"``,
        ``"invalid_patch_name"``, ``"copy_failed"``,
        ``"surfacecheck_not_on_path"``, ``"surfacecheck_failed"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} is not a directory",
        }

    src = Path(stl_path)
    if not src.is_file():
        return {
            "success": False,
            "reason": "stl_not_found",
            "detail": f"{src} does not exist or is not a file",
        }

    if patch_name is not None:
        if not patch_name or any(sep in patch_name for sep in ("/", "\\", "\x00")):
            return {
                "success": False,
                "reason": "invalid_patch_name",
                "detail": f"patch_name must be a bare name, got {patch_name!r}",
            }
        dest_name = patch_name + ".stl"
    else:
        dest_name = src.name

    surf_dir = case / "constant" / "triSurface"
    try:
        surf_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "success": False,
            "reason": "copy_failed",
            "detail": f"could not create {surf_dir}: {type(exc).__name__}: {exc}",
        }

    dest = surf_dir / dest_name
    try:
        # Read+write rather than shutil.copy so we don't pull in another import
        # and so we control text-vs-binary mode predictably across STL types.
        dest.write_bytes(src.read_bytes())
    except OSError as exc:
        return {
            "success": False,
            "reason": "copy_failed",
            "detail": f"could not write {dest}: {type(exc).__name__}: {exc}",
        }

    payload: ToolResult = {
        "success": True,
        "dest_path": str(dest),
        "surface_check": None,
        "log_tail": "",
    }

    if not run_check:
        return payload

    log_file = case / f"log.surfaceCheck.{dest.stem}"
    try:
        with log_file.open("w") as log:
            result = subprocess.run(
                ["surfaceCheck", str(dest)],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "reason": "surfacecheck_timeout",
            "log_tail": tail_log(log_file, LOG_TAIL_LINES),
        }
    except FileNotFoundError:
        return {
            "success": False,
            "reason": "surfacecheck_not_on_path",
            "log_tail": "surfaceCheck CLI not found. Is OpenFOAM sourced?",
        }

    log_tail = tail_log(log_file, LOG_TAIL_LINES)
    if result.returncode != 0:
        return {
            "success": False,
            "reason": "surfacecheck_failed",
            "log_tail": log_tail,
        }

    payload["surface_check"] = _parse_surface_check(log_file)
    payload["log_tail"] = log_tail
    return payload


def _parse_surface_check(log_file: Path) -> dict[str, Any]:
    """Extract triangle count, open-edge count, and closed-ness from a log."""
    stats: dict[str, Any] = {
        "n_triangles": None,
        "n_open_edges": None,
        "is_closed": None,
    }
    if not log_file.exists():
        return stats
    for line in log_file.read_text(errors="replace").splitlines():
        m = _SURFCHECK_NTRI.search(line)
        if m and stats["n_triangles"] is None:
            stats["n_triangles"] = int(m.group(1))
            continue
        m = _SURFCHECK_NOPEN.search(line)
        if m and stats["n_open_edges"] is None:
            stats["n_open_edges"] = int(m.group(1))
            continue
        if _SURFCHECK_CLOSED.search(line):
            stats["is_closed"] = True
        elif _SURFCHECK_OPEN.search(line):
            stats["is_closed"] = False
    return stats


# snappyHexMesh phase markers. Three phases run in sequence:
#   1. castellation — refine background mesh around the geometry
#   2. snap — pull cell vertices onto the geometry surface
#   3. addLayers — extrude prism layers off the surface
_SNAPPY_PHASE_CASTELL = re.compile(r"Castellated mesh : (?:Layer mesh|Mesh)?(?:OK)?")
_SNAPPY_DONE_CASTELL = re.compile(r"^Time\s*=\s*1\s*$|Castellated mesh\s*=\s*OK", re.IGNORECASE)
_SNAPPY_DONE_SNAP = re.compile(r"Snapped mesh\s*=\s*OK|Snapping done", re.IGNORECASE)
_SNAPPY_LAYER_ADDED = re.compile(
    r"Added\s+([\d.]+)\s+%\s+of the requested layers", re.IGNORECASE
)
_SNAPPY_LAYER_REPORT = re.compile(
    r"patch\s+\d+\s+(\S+)\s+(\d+)\s+(\d+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)"
)
_SNAPPY_NCELLS = re.compile(r"Total number of cells\s*=\s*(\d+)|cells:\s*(\d+)")
_SNAPPY_FINISHED = re.compile(r"^End$", re.MULTILINE)


def run_snappy_hex_mesh(
    case_path: str,
    extract_features: bool = True,
) -> ToolResult:
    """Run snappyHexMesh on a case prepared with prepare_surface_mesh.

    The case must already have:
    - A background mesh in ``constant/polyMesh/`` (from ``run_blockmesh``).
    - One or more STL files in ``constant/triSurface/`` (from
      ``prepare_surface_mesh``).
    - ``system/snappyHexMeshDict`` describing the castellation / snap /
      add-layers configuration.
    - ``system/surfaceFeatureExtractDict`` if ``extract_features`` is True
      (the default; needed when snappyHexMeshDict references ``.eMesh``
      feature files).

    snappyHexMesh runs in three phases (castellation, snap, addLayers).
    The wrapper parses the log for per-phase outcomes and returns a
    structured summary so the agent can diagnose mid-pipeline failures
    without reading the whole log.

    Args:
        case_path: Absolute path to the OpenFOAM case directory.
        extract_features: When True (default), runs
            ``surfaceFeatureExtract`` first to produce ``.eMesh`` files
            from the STLs. Set False if features were extracted earlier
            or the snappyHexMeshDict does not use features.

    Returns:
        On success: ``{"success": True, "mesh_stats": {...},
        "phases": {...}, "log_tail": str}``.

        ``mesh_stats`` carries the final ``n_cells`` (parsed from the
        snappyHexMesh log). ``phases`` reports each phase outcome:
        ``{"castellation": "ok"|"failed", "snap": "ok"|"failed"|"skipped",
        "layers": "ok"|"partial"|"failed"|"skipped",
        "layers_percent": float|None}``.

        On failure: ``{"success": False, "reason": str,
        "phases": {...}, "log_tail": str}``. ``reason`` is one of
        ``"missing_background_mesh"``, ``"missing_snappy_dict"``,
        ``"missing_surface_dict"``, ``"missing_triSurface"``,
        ``"snappy_not_on_path"``, ``"surface_features_failed"``,
        ``"snappy_failed"``, ``"timeout"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "log_tail": f"{case} is not a directory",
        }

    polymesh = case / "constant" / "polyMesh"
    if not polymesh.is_dir():
        return {
            "success": False,
            "reason": "missing_background_mesh",
            "log_tail": (
                f"Expected {polymesh} to exist. Run blockMesh first to "
                f"generate the background mesh."
            ),
        }

    snappy_dict = case / "system" / "snappyHexMeshDict"
    if not snappy_dict.exists():
        return {
            "success": False,
            "reason": "missing_snappy_dict",
            "log_tail": f"Expected {snappy_dict} to exist.",
        }

    surf_dir = case / "constant" / "triSurface"
    if not surf_dir.is_dir() or not any(surf_dir.glob("*.stl")):
        return {
            "success": False,
            "reason": "missing_triSurface",
            "log_tail": (
                f"Expected {surf_dir} to contain at least one .stl. Use "
                f"prepare_surface_mesh to drop one in."
            ),
        }

    if extract_features:
        sfx_dict = case / "system" / "surfaceFeatureExtractDict"
        if not sfx_dict.exists():
            return {
                "success": False,
                "reason": "missing_surface_dict",
                "log_tail": (
                    f"Expected {sfx_dict} to exist (or pass "
                    f"extract_features=False)."
                ),
            }
        sfx_log = case / "log.surfaceFeatureExtract"
        try:
            with sfx_log.open("w") as log:
                result = subprocess.run(
                    ["surfaceFeatureExtract", "-case", str(case)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=120,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "reason": "surface_features_timeout",
                "log_tail": tail_log(sfx_log, LOG_TAIL_LINES),
            }
        except FileNotFoundError:
            return {
                "success": False,
                "reason": "snappy_not_on_path",
                "log_tail": "surfaceFeatureExtract CLI not found. Is OpenFOAM sourced?",
            }
        if result.returncode != 0:
            return {
                "success": False,
                "reason": "surface_features_failed",
                "log_tail": tail_log(sfx_log, LOG_TAIL_LINES),
            }

    snappy_log = case / "log.snappyHexMesh"
    try:
        with snappy_log.open("w") as log:
            result = subprocess.run(
                ["snappyHexMesh", "-overwrite", "-case", str(case)],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1800,  # 30 min — snappy can be slow on real geometry
                check=False,
            )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "reason": "timeout",
            "phases": _parse_snappy_phases(snappy_log),
            "log_tail": tail_log(snappy_log, LOG_TAIL_LINES),
        }
    except FileNotFoundError:
        return {
            "success": False,
            "reason": "snappy_not_on_path",
            "log_tail": "snappyHexMesh CLI not found. Is OpenFOAM sourced?",
        }

    log_tail = tail_log(snappy_log, LOG_TAIL_LINES)
    phases = _parse_snappy_phases(snappy_log)
    mesh_stats = {"n_cells": _parse_snappy_final_cells(snappy_log)}

    if result.returncode != 0:
        return {
            "success": False,
            "reason": "snappy_failed",
            "phases": phases,
            "mesh_stats": mesh_stats,
            "log_tail": log_tail,
        }

    return {
        "success": True,
        "mesh_stats": mesh_stats,
        "phases": phases,
        "log_tail": log_tail,
    }


# snappyHexMesh advances one pseudo-time step per phase: Time = 1 after
# castellation, Time = 2 after snapping, Time = 3 after layer addition. Match
# the step markers with an anchored regex that tolerates surrounding whitespace
# — a raw "Time = N\n" substring is defeated by a single trailing space, which
# would report a completed mesh as "not_run".
_SNAPPY_STEP_RE = {
    n: re.compile(rf"^\s*Time\s*=\s*{n}\s*$", re.MULTILINE) for n in (1, 2, 3)
}


def _has_snappy_step(text: str, n: int) -> bool:
    return bool(_SNAPPY_STEP_RE[n].search(text))


def _parse_snappy_phases(log_file: Path) -> dict[str, Any]:
    """Identify which of the three snappyHexMesh phases ran to completion."""
    out: dict[str, Any] = {
        "castellation": "not_run",
        "snap": "not_run",
        "layers": "not_run",
        "layers_percent": None,
    }
    if not log_file.exists():
        return out
    text = log_file.read_text(errors="replace")
    step1 = _has_snappy_step(text, 1)
    step2 = _has_snappy_step(text, 2)
    step3 = _has_snappy_step(text, 3)

    # Castellation completes at Time = 1 (the step marker alone is sufficient;
    # the old name-marker AND-condition was brittle across OpenFOAM versions).
    if step1:
        out["castellation"] = "ok"

    # Snap completes at Time = 2; if only castellation ran, snap was skipped.
    if step2:
        out["snap"] = "ok"
    elif step1:
        out["snap"] = "skipped"

    # Layer addition: prefer the "Added X % of the requested layers" report
    # (the most common partial-failure signal); fall back to the Time = 3 step.
    layer_match = _SNAPPY_LAYER_ADDED.search(text)
    if layer_match:
        try:
            percent = float(layer_match.group(1))
            out["layers_percent"] = percent
            out["layers"] = "ok" if percent >= 95.0 else "partial"
        except ValueError:
            pass
    elif step3:
        out["layers"] = "ok"
    elif step2:
        out["layers"] = "skipped"

    return out


def _parse_snappy_final_cells(log_file: Path) -> int | None:
    """Return the final cell count parsed from the snappyHexMesh log."""
    if not log_file.exists():
        return None
    last: int | None = None
    for line in log_file.read_text(errors="replace").splitlines():
        m = _SNAPPY_NCELLS.search(line)
        if m:
            try:
                last = int(m.group(1) or m.group(2))
            except (TypeError, ValueError):
                continue
    return last


REPORT_FILENAME = "REPORT.md"
_VALID_STATUSES = frozenset(
    {"ok", "warning", "error", "fixed", "info", "pending_review"}
)
_REPORT_HEADER = (
    "# Case setup report\n"
    "\n"
    "`tail -f` to watch the run unfold. A verdict banner and a compact\n"
    "decisions index appear once the agent calls `finalize_report`.\n"
    "\n"
    "---\n"
)

# Sentinels rendered when a consultant field is empty on a decision entry.
# The phrasing is deliberate — these are gaps the researcher should see, not
# hidden absences.
_GAP_WHY = "_uncited choice — no annotation, reference, or paper cited._"
_GAP_ALTS = "_no alternatives surfaced._"
_GAP_BREAKS = "_failure modes not characterized._"

# Markers bracketing the rolled-up Decisions index at the end of REPORT.md
# and the verdict banner near the top. Both are emitted by finalize_report
# and stripped by record_step so live narration never carries a stale copy.
_DECISIONS_BEGIN = "<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->"
_DECISIONS_END = "<!-- END DECISIONS TABLE -->"
_SUMMARY_BEGIN = "<!-- BEGIN SUMMARY - auto-generated, do not edit -->"
_SUMMARY_END = "<!-- END SUMMARY -->"

# Maps the status of the last validation entry to a banner verdict label.
_VERDICT_FROM_STATUS = {
    "ok": "PASS",
    "fixed": "PASS",
    "error": "FAIL",
    "warning": "REVIEW",
    "pending_review": "REVIEW",
    "info": "REVIEW",
}

_ENTRY_HEADER_RE = re.compile(
    r"^##\s+\[(?P<ts>\d{2}:\d{2}:\d{2})\]"
    r"\s+(?P<phase>[^/]+?)"
    r"\s+/\s+(?P<status>[^—]+?)"
    r"\s+—\s+(?P<title>.+?)"
    r"(?:\s+\*\*\[PENDING REVIEW\]\*\*)?$"
)
# Consultant fields render as `- **Field:** value` in the compact format.
# Inline citations land in the Why line as `_(cites: a, b, c)_`.
_CONSULTANT_FIELD_RE = re.compile(
    r"^-\s+\*\*(Decision|Why|Alternatives|When it breaks):\*\*\s*(.*)$"
)
_INLINE_CITES_RE = re.compile(r"\s*_\(cites:\s*(.*?)\)_\s*$")

_FIELD_NAME_TO_KEY = {
    "Decision": "decision",
    "Why": "why",
    "Alternatives": "alternatives",
    "When it breaks": "when_it_breaks",
}


def _parse_decision_entries(body: str) -> list[dict[str, str]]:
    """Walk REPORT.md body and extract entries with consultant fields.

    Returns one dict per *decision* entry — entries where at least one
    consultant field (decision / why / alternatives / when-it-breaks /
    citations) is non-empty. Info-only entries are skipped. Multi-line
    field values are flattened into one cell-safe string per field.
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    def commit(entry: dict[str, str] | None) -> None:
        if entry is None:
            return
        if any(
            entry.get(k, "").strip()
            for k in ("decision", "why", "alternatives", "when_it_breaks", "citations")
        ):
            entries.append(entry)

    for line in body.splitlines():
        header_m = _ENTRY_HEADER_RE.match(line)
        if header_m:
            commit(current)
            current = {
                "timestamp": header_m.group("ts"),
                "phase": header_m.group("phase").strip(),
                "status": header_m.group("status").strip(),
                "title": header_m.group("title").strip(),
                "decision": "",
                "why": "",
                "alternatives": "",
                "when_it_breaks": "",
                "citations": "",
            }
            continue

        if current is None:
            continue

        field_m = _CONSULTANT_FIELD_RE.match(line)
        if not field_m:
            continue
        key = _FIELD_NAME_TO_KEY[field_m.group(1)]
        value = field_m.group(2).strip()
        # Pull any inline `_(cites: ...)_` suffix off the Why line into
        # the entry's citations slot.
        if key == "why":
            cite_m = _INLINE_CITES_RE.search(value)
            if cite_m:
                current["citations"] = cite_m.group(1).strip()
                value = _INLINE_CITES_RE.sub("", value).rstrip()
        current[key] = value

    commit(current)
    return entries


def _escape_table_cell(s: str) -> str:
    """Make a string safe for a single markdown-table cell."""
    return s.replace("|", "\\|").replace("\n", "; ").strip()


def _render_tables_block(
    tables: dict[str, list[dict[str, Any]]] | None,
) -> list[str]:
    """Render the optional ``tables`` payload as markdown tables.

    Each (title, rows) pair becomes a ``### title`` heading followed by a
    pipe table. Column order is the insertion order of the first row's
    keys; rows that introduce new keys append them to the right with
    blank cells in earlier rows.
    """
    if not tables:
        return []
    lines: list[str] = []
    for title, rows in tables.items():
        if not isinstance(rows, list) or not rows:
            continue
        # Determine column order: first row's keys, then any new keys
        # introduced by later rows (appended).
        columns: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for k in row.keys():
                if k not in columns:
                    columns.append(k)
        if not columns:
            continue
        lines.append("")
        lines.append(f"### {title.strip()}")
        lines.append("")
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("|" + "|".join(["---"] * len(columns)) + "|")
        for row in rows:
            if not isinstance(row, dict):
                continue
            cells = [_escape_table_cell(str(row.get(c, ""))) for c in columns]
            lines.append("| " + " | ".join(cells) + " |")
    return lines


def _entry_gaps(e: dict[str, str]) -> list[str]:
    """Return short tokens for the consultant fields missing on an entry.

    Mirrors record_step's gap logic, reading the parsed (round-tripped)
    values: a sentinel value counts as a gap. Citations satisfy the why
    gap even when the why prose is empty.
    """
    gaps: list[str] = []
    if (not e["why"] or e["why"] == _GAP_WHY) and not e["citations"]:
        gaps.append("why")
    if not e["alternatives"] or e["alternatives"] == _GAP_ALTS:
        gaps.append("alts")
    if not e["when_it_breaks"] or e["when_it_breaks"] == _GAP_BREAKS:
        gaps.append("breaks")
    return gaps


def _render_decisions_index(entries: list[dict[str, str]]) -> str:
    """Render the compact Decisions index for the end of REPORT.md.

    One scannable line per decision: phase, the decision one-liner, its
    citations, and any consultant gaps. The full why / alternatives /
    when-it-breaks reasoning stays in each entry's collapsible block
    above — this index is a map into it, not a second copy.
    """
    lines = [
        _DECISIONS_BEGIN,
        "## Decisions",
        "",
        "One line per decision above; open an entry's *why · alternatives · "
        "when it breaks* block for the full reasoning. Generated on "
        "`finalize_report`.",
        "",
    ]
    if not entries:
        lines.append("_no decisions recorded yet._")
    else:
        lines.append("| Phase | Decision | Cites | Gaps |")
        lines.append("|---|---|---|---|")
        for e in entries:
            cites_cell = _escape_table_cell(e["citations"]) or "—"
            gaps = _entry_gaps(e)
            gaps_cell = ", ".join(gaps) if gaps else "—"
            lines.append(
                f"| {_escape_table_cell(e['phase'])} "
                f"| {_escape_table_cell(e['decision'])} "
                f"| {cites_cell} "
                f"| {gaps_cell} |"
            )
    lines.append("")
    lines.append(_DECISIONS_END)
    return "\n".join(lines) + "\n"


ANALYSIS_RESULT_FILE = "postProcessing/analysis/run_analysis_result.json"


def _metrics_support(case: Path | None) -> tuple[str, str]:
    """Do the last ``validation.run_analysis`` metrics back a PASS?

    Returns ``(state, detail)``: ``verified`` (every pass flag true),
    ``contradicted`` (a flag false, or a NaN/inf metric), ``unchecked`` (no
    pass flags to read) or ``missing`` (no saved result). Pass flags are
    ``within_tolerance`` (what ``compare_profiles`` / ``compare_scalar``
    return) and any key named ``pass``/``passed`` or ending in ``_pass``.
    """
    if case is None:
        return "unchecked", ""
    path = case / ANALYSIS_RESULT_FILE
    if not path.is_file():
        return "missing", "no validation.run_analysis result saved in this case"
    try:
        metrics = json.loads(path.read_text(errors="replace")).get("metrics", {})
    except (OSError, ValueError):
        return "missing", "the saved run_analysis result is unreadable"
    flags: list[tuple[str, bool]] = []
    bad_numbers: list[str] = []

    def walk(obj: Any, key: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{key}.{k}" if key else str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{key}[{i}]")
        elif isinstance(obj, bool):
            leaf = key.rsplit(".", 1)[-1].lower()
            if leaf == "within_tolerance" or leaf in ("pass", "passed") or leaf.endswith("_pass"):
                flags.append((key, obj))
        elif obj is None and re.search(r"(l2|linf|error)", key.lower()):
            bad_numbers.append(key)
        elif isinstance(obj, float) and not math.isfinite(obj):
            bad_numbers.append(key)

    walk(metrics)
    failed = [k for k, v in flags if not v]
    if bad_numbers or failed:
        why = ", ".join((failed + [f"{k} is not a number" for k in bad_numbers])[:4])
        return "contradicted", why
    if not flags:
        return "unchecked", "the analysis metrics carry no pass/within_tolerance field"
    return "verified", ""


def _render_summary_block(
    body: str, entries: list[dict[str, str]], case: Path | None = None
) -> str:
    """Render the top-of-report verdict banner from the narration body.

    Verdict is read off the last ``validation`` entry's status; counts are
    derived by scanning entry headers, retry lines, and parsed decisions. A
    PASS is checked against the metrics ``validation.run_analysis`` saved in
    the case: a PASS those numbers do not support is shown as REVIEW, so a
    narrated claim never outranks the tested comparison.
    """
    headers: list[dict[str, str]] = []
    n_retries = 0
    for ln in body.splitlines():
        m = _ENTRY_HEADER_RE.match(ln)
        if m:
            headers.append(m.groupdict())
        elif ln.strip().startswith("_retry of:"):
            n_retries += 1

    validation = [h for h in headers if "validation" in h["phase"].strip().lower()]
    if validation:
        last = validation[-1]
        verdict = _VERDICT_FROM_STATUS.get(last["status"].strip(), "REVIEW")
        outcome = last["title"].strip()
        if verdict == "PASS":
            state, detail = _metrics_support(case)
            if state in ("contradicted", "missing"):
                verdict = "REVIEW"
                outcome = (f"narrated as passing, but not backed by the validation metrics "
                           f"({detail}). Narration: {outcome}")
            elif state == "unchecked" and case is not None:
                outcome = f"{outcome} (not machine-checked: {detail})"
    else:
        verdict = "INCOMPLETE"
        outcome = "no validation step recorded"

    n_steps = len(headers)
    n_dec = len(entries)
    n_gaps = sum(1 for e in entries if _entry_gaps(e))
    counts = (
        f"{n_steps} steps · {n_dec} decisions · "
        f"{n_retries} retr{'y' if n_retries == 1 else 'ies'} · "
        f"{n_gaps} gap{'' if n_gaps == 1 else 's'}"
    )
    lines = [
        _SUMMARY_BEGIN,
        f"**VERDICT: {verdict}** — {outcome}",
        "",
        counts,
        _SUMMARY_END,
    ]
    return "\n".join(lines) + "\n"


def _strip_decisions_table(text: str) -> str:
    """Remove any existing decisions-index block from REPORT.md text.

    Returns the body (everything before the index marker), ending with a
    single trailing newline. If no index is present, the text is returned
    as-is (normalised to a single trailing newline).
    """
    if _DECISIONS_BEGIN in text:
        body = text.split(_DECISIONS_BEGIN, 1)[0]
        return body.rstrip() + "\n"
    return text if text.endswith("\n") else text + "\n"


def _strip_summary_block(text: str) -> str:
    """Remove any existing verdict-banner block, rejoining head and body."""
    if _SUMMARY_BEGIN in text and _SUMMARY_END in text:
        before = text.split(_SUMMARY_BEGIN, 1)[0]
        after = text.split(_SUMMARY_END, 1)[1]
        joined = before.rstrip() + "\n\n" + after.lstrip("\n")
        return joined.rstrip() + "\n"
    return text if text.endswith("\n") else text + "\n"


def _insert_summary_after_header(body: str, summary_block: str) -> str:
    """Place the verdict banner just after the report's ``---`` header rule."""
    sep = "\n---\n"
    idx = body.find(sep)
    if idx == -1:
        return summary_block.rstrip() + "\n\n" + body.lstrip("\n")
    head = body[: idx + len(sep)]
    rest = body[idx + len(sep) :]
    return (
        head.rstrip("\n")
        + "\n\n"
        + summary_block.rstrip()
        + "\n\n"
        + rest.lstrip("\n")
    )


# The function-call encoding can, on an over-long field value, merge the next
# parameter's text (and its literal '<parameter name=...>' / '</field>' markup)
# into the current field — observed on multi-clause `decision` values, which
# the schema expects to be one line. Detect that leaked markup and refuse,
# turning a silently-corrupt entry (a decision that swallowed its `why`, with
# `why` then rendering as an empty-field gap) into a loud, recoverable error.
_LEAKED_TOOL_MARKUP_RE = re.compile(
    r"<parameter\s+name=|</(?:decision|why|alternatives|when_it_breaks|title|details)>",
    re.IGNORECASE,
)


def record_step(
    case_path: str,
    phase: str,
    status: str,
    title: str,
    decision: str = "",
    why: str = "",
    alternatives: str = "",
    when_it_breaks: str = "",
    citations: list[str] | None = None,
    details: str = "",
    retry_of: str | None = None,
    tables: dict[str, list[dict[str, Any]]] | None = None,
) -> ToolResult:
    """Append a structured progress entry to the case's ``REPORT.md``.

    Call this after each meaningful step — tutorial selection, geometry
    sanity check, mesh generation, mesh quality (``checkMesh``) result,
    boundary-condition setup, solver configuration, convergence outcome,
    validation comparison, post-processing image. The file is human-readable
    markdown — ``tail -f`` it to watch the run unfold.

    **Consultant schema.** When the entry records a *decision* (mesh
    template, scheme, BC, turbulence model, ...) fill the four consultant
    fields: ``decision`` (one line on what was chosen), ``why`` (the
    rationale, must cite an annotation or reference), ``alternatives``
    (what else was considered + tradeoffs), and ``when_it_breaks`` (regimes
    where this choice would be wrong). Empty fields render explicitly as
    "_uncited choice_" / "_no alternatives surfaced_" / "_failure modes not
    characterized_" — this is intentional. Honest weakness creates pull to
    grow the corpus; silent omission hides it. The return includes a
    ``consultant_gaps`` list naming the missing fields so you can notice.

    **Human-in-the-loop.** Use ``status="pending_review"`` when you are
    proposing a decision and need the researcher to approve before
    executing the next phase. The entry renders with a ``[PENDING REVIEW]``
    marker so the human knows action is required.

    When you retry after a failure, record the fix as ``status="fixed"``
    and pass the failing entry's title via ``retry_of`` — the retry chain
    becomes a visible audit trail that "we tried X, hit Y, applied Z".

    Args:
        case_path: Absolute path to the case directory. Must already exist
            as a directory.
        phase: Short pipeline phase. Recommended values: ``"geometry"``,
            ``"mesh"``, ``"mesh_quality"``, ``"boundary_conditions"``,
            ``"solver_config"``, ``"convergence"``, ``"validation"``,
            ``"post_processing"``. Free-form so the agent can extend.
        status: One of ``"ok"``, ``"warning"``, ``"error"``, ``"fixed"``,
            ``"info"``, ``"pending_review"``.
        title: One-line entry header. Keep under ~80 characters.
        decision: One-line summary of what was chosen (consultant schema).
        why: Rationale for the decision; should cite an annotation,
            reference, or paper (consultant schema).
        alternatives: Other options considered and why they were rejected
            (consultant schema).
        when_it_breaks: Regimes / assumptions under which this decision
            would be wrong (consultant schema).
        citations: Optional list of citation strings (annotation paths,
            DOIs, URLs). Rendered as a "Cites:" line below ``why``.
        details: Freeform markdown body for additional context (log
            excerpts, image paths, error messages) that doesn't fit the
            consultant schema. Rendered below the consultant block.
        retry_of: When ``status="fixed"``, the ``title`` of the prior
            failing entry this resolves. Surfaced as ``retry of: …``.
        tables: Optional structured payload, rendered as markdown
            tables under the entry. Shape:
            ``{table_title: [{col_name: value, ...}, {col_name: value, ...}], ...}``.
            Use this for any data the reader needs to scan rather than
            read — BC patch types, mesh metrics, residual drops, validation
            comparisons. The first row's key insertion order determines
            column order; later rows can add new columns (appended to the
            right). Values are stringified; pipes are escaped. See the
            workflow contract for canonical table shapes per phase.

    Returns:
        On success: ``{"success": True, "path": str, "n_entries": int,
        "consultant_gaps": list[str]}``. ``consultant_gaps`` lists which
        consultant fields were left empty on a decision entry — values from
        ``{"uncited_why", "no_alternatives", "no_failure_modes"}``. Empty
        list means the entry was fully characterized (or wasn't a decision
        entry to begin with).
        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of ``"invalid_case_path"``, ``"invalid_status"``,
        ``"empty_title"``, ``"leaked_tool_markup"``, ``"write_failed"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory",
        }

    if status not in _VALID_STATUSES:
        return {
            "success": False,
            "reason": "invalid_status",
            "detail": f"status must be one of {sorted(_VALID_STATUSES)}, got {status!r}",
        }

    title_clean = title.strip()
    if not title_clean:
        return {
            "success": False,
            "reason": "empty_title",
            "detail": "title must be a non-empty string",
        }

    for fname, fval in (
        ("title", title),
        ("decision", decision),
        ("why", why),
        ("alternatives", alternatives),
        ("when_it_breaks", when_it_breaks),
        ("details", details),
    ):
        if fval and _LEAKED_TOOL_MARKUP_RE.search(fval):
            return {
                "success": False,
                "reason": "leaked_tool_markup",
                "detail": (
                    f"The {fname!r} value contains literal tool-call markup "
                    f"('<parameter name=...>' or a '</{fname}>' tag) — an "
                    "adjacent field's text was merged into it, usually from an "
                    "over-long value. Keep 'decision' to one line, move the "
                    "detail into 'why', and re-record."
                ),
            }

    decision_clean = decision.strip()
    why_clean = why.strip()
    alternatives_clean = alternatives.strip()
    when_it_breaks_clean = when_it_breaks.strip()
    citation_list = [c.strip() for c in (citations or []) if c and c.strip()]

    # A "decision entry" is one where the agent recorded a choice. Trigger
    # the consultant rendering if any consultant field is filled, or if the
    # entry is a pending review (which is always a proposed decision).
    is_decision_entry = bool(
        decision_clean
        or why_clean
        or alternatives_clean
        or when_it_breaks_clean
        or citation_list
        or status == "pending_review"
    )

    consultant_gaps: list[str] = []
    if is_decision_entry:
        if not why_clean and not citation_list:
            consultant_gaps.append("uncited_why")
        if not alternatives_clean:
            consultant_gaps.append("no_alternatives")
        if not when_it_breaks_clean:
            consultant_gaps.append("no_failure_modes")

    report = case / REPORT_FILENAME
    timestamp = _dt.datetime.now().strftime("%H:%M:%S")
    phase_clean = (phase.strip() or "info").replace("[", "(").replace("]", ")")

    header = f"## [{timestamp}] {phase_clean} / {status} — {title_clean}"
    if status == "pending_review":
        header += "  **[PENDING REVIEW]**"
    lines = [header]
    if retry_of:
        lines.append(f"_retry of: {retry_of.strip()!r}_")

    if is_decision_entry:
        # Decision stays visible; the depth (why / alternatives / when-it-
        # breaks) folds into a <details> so the live entry is scannable but
        # the full reasoning is one click away. The field lines keep the
        # `- **Field:** value` shape inside the block so they remain
        # machine-extractable (corpus drafting parses them).
        why_line = why_clean if why_clean else _GAP_WHY
        if citation_list:
            why_line = f"{why_line} _(cites: {', '.join(citation_list)})_"
        lines.append("")
        if decision_clean:
            lines.append(f"- **Decision:** {decision_clean}")
        lines.append(
            "<details><summary>why · alternatives · when it breaks</summary>"
        )
        lines.append("")
        lines.append(f"- **Why:** {why_line}")
        lines.append(f"- **Alternatives:** {alternatives_clean or _GAP_ALTS}")
        lines.append(f"- **When it breaks:** {when_it_breaks_clean or _GAP_BREAKS}")
        lines.append("")
        lines.append("</details>")

    lines.extend(_render_tables_block(tables))

    if details.strip():
        lines.append("")
        lines.append(details.rstrip())
    lines.append("")
    entry = "\n".join(lines) + "\n"

    try:
        if not report.exists() or report.stat().st_size == 0:
            existing_body = _REPORT_HEADER + "\n"
        else:
            # Strip any previously-rendered verdict banner and decisions
            # index — both are only emitted on finalize_report. Stripping
            # mid-run handles the case where someone calls finalize_report
            # and then records more steps.
            existing_body = report.read_text(errors="replace")
            existing_body = _strip_summary_block(existing_body)
            existing_body = _strip_decisions_table(existing_body)

        # Always separate entries with a blank line. existing_body may
        # have been trimmed by a prior write_text(rstrip()+'\n'); re-add
        # the gap so each new header lands cleanly under its own break.
        new_body = existing_body.rstrip() + "\n\n" + entry
        report.write_text(new_body.rstrip() + "\n")
    except OSError as exc:
        return {
            "success": False,
            "reason": "write_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    # Count entries by scanning header lines in the narration body. Cheap —
    # the file is small.
    n_entries = sum(
        1 for ln in new_body.splitlines() if ln.startswith("## [")
    )

    return {
        "success": True,
        "path": str(report),
        "n_entries": n_entries,
        "consultant_gaps": consultant_gaps,
    }


def finalize_report(case_path: str) -> ToolResult:
    """Add a verdict banner and a compact decisions index to ``REPORT.md``.

    Call this once at the end of a run — after validation has returned
    its verdict and any post-processing image has been rendered. It adds
    two skim aids without disturbing the live narration:

    - a **verdict banner** near the top: PASS / FAIL / REVIEW (read off
      the last ``validation`` entry's status) or INCOMPLETE, plus step /
      decision / retry / gap counts.
    - a **compact Decisions index** at the end: one line per decision
      entry — phase, the decision one-liner, its citations, and which
      consultant fields are gaps. The full why / alternatives /
      when-it-breaks reasoning stays in each step's collapsible
      ``<details>`` block; the index is a map into it, not a copy.

    Calling this again later refreshes both in place — useful if the
    agent records additional ``status="fixed"`` entries after a
    researcher review and wants the banner/index to reflect them.

    Args:
        case_path: Absolute path to the case directory. ``REPORT.md``
            must already exist (i.e. at least one prior ``record_step``).

    Returns:
        ``{"success": True, "path": str, "n_decisions": int}`` on
        success, or ``{"success": False, "reason": str, "detail": str}``
        on a missing-report or write failure. ``reason`` is one of
        ``"invalid_case_path"``, ``"no_report"``, ``"write_failed"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory",
        }
    report = case / REPORT_FILENAME
    if not report.exists() or report.stat().st_size == 0:
        return {
            "success": False,
            "reason": "no_report",
            "detail": (
                f"{report} does not exist. Call record_step at least once "
                f"before finalize_report."
            ),
        }
    try:
        text = _strip_summary_block(report.read_text(errors="replace"))
        body = _strip_decisions_table(text)
        entries = _parse_decision_entries(body)
        summary = _render_summary_block(body, entries, case=report.parent)
        index = _render_decisions_index(entries)
        with_summary = _insert_summary_after_header(body, summary)
        report.write_text(with_summary.rstrip() + "\n\n" + index)
    except OSError as exc:
        return {
            "success": False,
            "reason": "write_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    return {
        "success": True,
        "path": str(report),
        "n_decisions": len(entries),
    }


_VALID_WRITE_SUBDIRS = frozenset({"system", "constant", "0"})


def prepare_case(case_path: str, overwrite: bool = False) -> ToolResult:
    """Create a fresh case directory for authoring, refusing to clobber a prior run.

    Call this ONCE at the start, before authoring any dictionaries
    (``write_dict`` / ``copy_tutorial_dict`` require the case directory to
    already exist). It creates ``case_path`` if absent. If the directory
    already exists and is **non-empty** — i.e. it holds a previous attempt's
    files — it refuses with ``reason="case_exists"`` unless ``overwrite=True``,
    which clears it first. This mirrors ``archive_case`` and
    ``draft_annotation_from_report``: existing work is never silently
    overwritten.

    The guard lives only here, so it does not interfere with the normal
    author → mesh → solve → re-author iterate loop within a single run: once
    the directory exists, subsequent ``write_dict`` calls (including dict
    re-writes after a failed check) proceed freely.

    Args:
        case_path: Absolute or repo-relative path to the case directory,
            e.g. ``cases/work/lid-cavity``. Parent directories are created.
        overwrite: When ``False`` (default), refuse a non-empty existing
            directory. ``True`` removes it and recreates a clean one.

    Returns:
        On success: ``{"success": True, "path": str, "cleared": bool}`` —
        ``cleared`` is True when a non-empty prior case was removed.
        On failure: ``{"success": False, "reason": str, "detail": str}``,
        where ``reason`` is one of ``"case_exists"``, ``"invalid_case_path"``
        (the path exists but is not a directory), or ``"prepare_failed"``.
    """
    case = Path(case_path)
    if case.exists() and not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} exists but is not a directory.",
        }

    non_empty = case.is_dir() and any(case.iterdir())
    if non_empty and not overwrite:
        return {
            "success": False,
            "reason": "case_exists",
            "detail": (
                f"{case} already exists and is not empty — it holds a prior "
                f"attempt. Pass overwrite=True to discard and replace it, or "
                f"choose a different case name. Ask the researcher before "
                f"discarding prior work."
            ),
        }

    cleared = False
    try:
        if non_empty:  # overwrite is True here
            shutil.rmtree(case)
            cleared = True
        case.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "success": False,
            "reason": "prepare_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    return {"success": True, "path": str(case), "cleared": cleared}


def write_dict(
    case_path: str,
    dict_name: str,
    content: str,
    subdir: str = "system",
) -> ToolResult:
    """Write an OpenFOAM dictionary or field file into a case directory.

    A complete OpenFOAM case has three writable subdirectories:
    - ``system/`` — solver control (controlDict, fvSchemes, fvSolution,
      blockMeshDict, ...)
    - ``constant/`` — physical/turbulence properties (transportProperties,
      turbulenceProperties, ...)
    - ``0/`` — initial and boundary fields (U, p, k, omega, nut, ...)

    Use this tool for all three. Pick the subdir explicitly via the
    ``subdir`` argument; ``"system"`` is the default for backwards
    compatibility.

    Args:
        case_path: Absolute path to the OpenFOAM case directory.
        dict_name: Filename (e.g. ``"controlDict"``, ``"U"``,
            ``"transportProperties"``). Must not contain path separators.
        content: Full text of the file, including the FoamFile header.
        subdir: Target subdirectory under the case. One of ``"system"``,
            ``"constant"``, ``"0"``. Created if it does not already exist
            (no parents-of-the-case are ever created).

    Returns:
        ``{"success": True, "path": str}`` if written, or
        ``{"success": False, "reason": str, "detail": str}`` on a validation
        or filesystem failure. ``reason`` is one of ``"invalid_dict_name"``,
        ``"invalid_subdir"``, ``"invalid_case_path"``, ``"write_failed"``.

    Note:
        This tool does NOT validate the file syntax — it only writes. Use
        ``run_blockmesh`` / ``run_solver`` to surface any syntax errors
        through the normal OpenFOAM pipeline.
    """
    if not dict_name or dict_name in {".", ".."} or any(sep in dict_name for sep in ("/", "\\", "\x00")):
        return {
            "success": False,
            "reason": "invalid_dict_name",
            "detail": f"dict_name must be a bare filename, got {dict_name!r}",
        }

    if subdir not in _VALID_WRITE_SUBDIRS:
        return {
            "success": False,
            "reason": "invalid_subdir",
            "detail": (
                f"subdir must be one of {sorted(_VALID_WRITE_SUBDIRS)}, "
                f"got {subdir!r}"
            ),
        }

    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory",
        }

    target_dir = case / subdir
    try:
        target_dir.mkdir(exist_ok=True)
    except OSError as exc:
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"could not create {target_dir}: {type(exc).__name__}: {exc}",
        }

    target = target_dir / dict_name
    try:
        target.write_text(content)
    except OSError as exc:
        return {
            "success": False,
            "reason": "write_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    return {"success": True, "path": str(target)}


def _whitespace_insensitive_matches(content: str, target: str) -> list[tuple[int, int]]:
    """Spans of ``content`` equal to ``target`` up to whitespace-run width."""
    parts = target.split()
    if not parts:
        return []
    pattern = r"\s+".join(re.escape(p) for p in parts)
    return [m.span() for m in re.finditer(pattern, content)]


def copy_tutorial_dict(
    tutorial_path: str,
    case_path: str,
    dict_name: str,
    subdir: str = "system",
    replacements: dict | None = None,
) -> ToolResult:
    """Copy a tutorial dictionary verbatim into a case, optionally patching
    a few string tokens.

    The bytes-on-disk transfer fixes the failure mode where smaller local
    models hallucinate or truncate dict content when asked to *generate*
    a valid OpenFOAM file. They only need to (a) pick the right tutorial
    path and (b) supply the patches the scenario actually requires — the
    FoamFile header, banner, and trailing separator survive intact.

    Args:
        tutorial_path: Path under ``$FOAM_TUTORIALS`` (same syntax as
            ``read_tutorial_file``), e.g.
            ``"incompressible/icoFoam/cavity/cavity/system/controlDict"``.
        case_path: Absolute or repo-relative path to the case directory.
        dict_name: Output filename in the case (e.g. ``"controlDict"``).
        subdir: Target subdirectory. One of ``"system"``, ``"constant"``,
            ``"0"``.
        replacements: Optional ``{old_string: new_string}`` map applied
            after the read. Each old_string must appear exactly once in
            the tutorial content or the call fails (so the agent doesn't
            silently no-op when the source has changed).

    Returns:
        On success: ``{"success": True, "path": str, "source": str,
        "patches_applied": int}``.

        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of the existing read / write reasons, plus
        ``"patch_not_found"`` (an ``old_string`` was not in the tutorial)
        and ``"patch_ambiguous"`` (an ``old_string`` matched more than once).
    """
    if not dict_name or dict_name in {".", ".."} or any(sep in dict_name for sep in ("/", "\\", "\x00")):
        return {
            "success": False,
            "reason": "invalid_dict_name",
            "detail": f"dict_name must be a bare filename, got {dict_name!r}",
        }
    if subdir not in _VALID_WRITE_SUBDIRS:
        return {
            "success": False,
            "reason": "invalid_subdir",
            "detail": (
                f"subdir must be one of {sorted(_VALID_WRITE_SUBDIRS)}, got {subdir!r}"
            ),
        }

    root = _resolve_tutorials_root()
    if root is None:
        return {
            "success": False,
            "reason": "foam_tutorials_unset",
            "detail": "$FOAM_TUTORIALS is not set or does not exist. Source OpenFOAM first.",
        }
    source = _safe_join_under(root, tutorial_path)
    if source is None or not source.is_file():
        return {
            "success": False,
            "reason": "tutorial_not_found",
            "detail": f"no such tutorial file: {tutorial_path}",
        }
    try:
        content = source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "success": False,
            "reason": "read_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    patches_applied = 0
    if replacements:
        for old, new in replacements.items():
            occurrences = content.count(old)
            span = None
            if occurrences == 0:
                # Dictionaries align values with runs of spaces that models
                # rarely reproduce exactly ("endTime 2000;" for
                # "endTime         2000;"). Fall back to a match that treats
                # any whitespace run as equal, still requiring one hit.
                matches = _whitespace_insensitive_matches(content, old)
                occurrences = len(matches)
                if occurrences == 1:
                    span = matches[0]
            if occurrences == 0:
                return {
                    "success": False,
                    "reason": "patch_not_found",
                    "detail": f"replacement target not found in tutorial content: {old!r}",
                }
            if occurrences > 1:
                return {
                    "success": False,
                    "reason": "patch_ambiguous",
                    "detail": (
                        f"replacement target appears {occurrences} times "
                        f"in {tutorial_path} — give a longer, unique snippet: {old!r}"
                    ),
                }
            if span is None:
                content = content.replace(old, new, 1)
            else:
                content = content[: span[0]] + new + content[span[1] :]
            patches_applied += 1

    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory",
        }
    target_dir = case / subdir
    try:
        target_dir.mkdir(exist_ok=True)
    except OSError as exc:
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"could not create {target_dir}: {type(exc).__name__}: {exc}",
        }
    target = target_dir / dict_name
    try:
        target.write_text(content)
    except OSError as exc:
        return {
            "success": False,
            "reason": "write_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    return {
        "success": True,
        "path": str(target),
        "source": str(source),
        "patches_applied": patches_applied,
    }


_VALID_DECOMP_METHODS = frozenset({"scotch", "simple", "hierarchical", "metis"})


def decompose_par(
    case_path: str,
    n_procs: int,
    method: str = "scotch",
) -> ToolResult:
    """Decompose a case for parallel execution.

    Writes ``system/decomposeParDict`` with the requested method and
    subdomain count, then runs ``decomposePar`` to split the mesh and
    fields into per-processor directories.

    Args:
        case_path: Absolute path to the OpenFOAM case directory. Must
            have a generated mesh (``constant/polyMesh/``).
        n_procs: Number of subdomains. The case's solver will need to run
            with the same count.
        method: Decomposition method. ``"scotch"`` (default) is automatic
            and works for arbitrary meshes; ``"simple"`` is grid-aligned
            and useful for structured meshes; ``"hierarchical"`` and
            ``"metis"`` are also accepted.

    Returns:
        On success: ``{"success": True, "n_procs": int, "n_cells_total":
        int | None, "log_tail": str}``.

        On failure: ``{"success": False, "reason": str, "log_tail": str}``.
        ``reason`` is one of ``"invalid_case_path"``, ``"missing_mesh"``,
        ``"invalid_n_procs"``, ``"invalid_method"``,
        ``"decomposepar_not_on_path"``, ``"decomposition_failed"``,
        ``"timeout"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "log_tail": f"{case} is not a directory",
        }
    polymesh = case / "constant" / "polyMesh"
    if not polymesh.is_dir():
        return {
            "success": False,
            "reason": "missing_mesh",
            "log_tail": f"missing {polymesh}; mesh the case first",
        }
    if not isinstance(n_procs, int) or n_procs < 2:
        return {
            "success": False,
            "reason": "invalid_n_procs",
            "log_tail": f"n_procs must be an integer >= 2, got {n_procs!r}",
        }
    if method not in _VALID_DECOMP_METHODS:
        return {
            "success": False,
            "reason": "invalid_method",
            "log_tail": (
                f"method must be one of {sorted(_VALID_DECOMP_METHODS)}, "
                f"got {method!r}"
            ),
        }

    decomp_dict = case / "system" / "decomposeParDict"
    decomp_dict.parent.mkdir(parents=True, exist_ok=True)
    decomp_dict.write_text(_decompose_par_dict_text(n_procs, method))

    log_file = case / "log.decomposePar"
    try:
        with log_file.open("w") as log:
            result = subprocess.run(
                ["decomposePar", "-force", "-case", str(case)],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "reason": "timeout",
            "log_tail": tail_log(log_file, LOG_TAIL_LINES),
        }
    except FileNotFoundError:
        return {
            "success": False,
            "reason": "decomposepar_not_on_path",
            "log_tail": "decomposePar CLI not found. Is OpenFOAM sourced?",
        }

    log_tail = tail_log(log_file, LOG_TAIL_LINES)
    if result.returncode != 0:
        return {
            "success": False,
            "reason": "decomposition_failed",
            "log_tail": log_tail,
        }

    return {
        "success": True,
        "n_procs": n_procs,
        "n_cells_total": _parse_decompose_cells(log_file),
        "log_tail": log_tail,
    }


def _decompose_par_dict_text(n_procs: int, method: str) -> str:
    """Render a minimal decomposeParDict for the chosen method."""
    return (
        "/*--------------------------------*- C++ -*----------------------------------*\\\n"
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        "    class       dictionary;\n"
        "    object      decomposeParDict;\n"
        "}\n"
        f"numberOfSubdomains  {n_procs};\n"
        f"method              {method};\n"
        "// ************************************************************************* //\n"
    )


def _parse_decompose_cells(log_file: Path) -> int | None:
    """Parse 'Number of cells = N' from a decomposePar log."""
    if not log_file.exists():
        return None
    pattern = re.compile(r"Number of cells\s*=\s*(\d+)")
    for line in log_file.read_text(errors="replace").splitlines():
        m = pattern.search(line)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def reconstruct_par(
    case_path: str,
    time: str = "latestTime",
) -> ToolResult:
    """Reconstruct a parallel-decomposed case back to a single mesh.

    Args:
        case_path: Absolute path to the OpenFOAM case directory. Must
            contain ``processor*/`` subdirectories from a previous
            ``decompose_par`` + parallel solver run.
        time: Which simulation time(s) to reconstruct. ``"latestTime"``
            (default) reconstructs only the final time. Pass ``"all"`` to
            reconstruct every time directory, or a numeric value for one
            specific time.

    Returns:
        On success: ``{"success": True, "reconstructed_times": [str, ...],
        "log_tail": str}``.

        On failure: ``{"success": False, "reason": str, "log_tail": str}``.
        ``reason`` is one of ``"invalid_case_path"``, ``"no_processors"``,
        ``"reconstructpar_not_on_path"``, ``"reconstruction_failed"``,
        ``"timeout"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "log_tail": f"{case} is not a directory",
        }
    if not any(case.glob("processor*")):
        return {
            "success": False,
            "reason": "no_processors",
            "log_tail": (
                f"no processor*/ directories in {case}; run decompose_par "
                f"and a parallel solver first."
            ),
        }

    cmd = ["reconstructPar", "-case", str(case)]
    if time == "all":
        # Default behaviour is "all" when no -time / -latestTime flag is given.
        pass
    elif time == "latestTime":
        cmd.append("-latestTime")
    else:
        cmd.extend(["-time", time])

    log_file = case / "log.reconstructPar"
    try:
        with log_file.open("w") as log:
            result = subprocess.run(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "reason": "timeout",
            "log_tail": tail_log(log_file, LOG_TAIL_LINES),
        }
    except FileNotFoundError:
        return {
            "success": False,
            "reason": "reconstructpar_not_on_path",
            "log_tail": "reconstructPar CLI not found. Is OpenFOAM sourced?",
        }

    log_tail = tail_log(log_file, LOG_TAIL_LINES)
    if result.returncode != 0:
        return {
            "success": False,
            "reason": "reconstruction_failed",
            "log_tail": log_tail,
        }

    times = _parse_reconstructed_times(log_file)
    return {
        "success": True,
        "reconstructed_times": times,
        "log_tail": log_tail,
    }


def _parse_reconstructed_times(log_file: Path) -> list[str]:
    """Extract the simulation times reconstructPar wrote out."""
    if not log_file.exists():
        return []
    pattern = re.compile(r"^Time\s*=\s*(\S+)\s*$")
    out: list[str] = []
    for line in log_file.read_text(errors="replace").splitlines():
        m = pattern.match(line)
        if m:
            t = m.group(1)
            if t not in out:
                out.append(t)
    return out


# A FOAM FATAL (IO) ERROR is a setup/config problem (missing field, bad
# keyword, unknown patch), not numerical divergence. Distinguishing the two
# matters for recovery: "solver_error" points the agent at a dictionary/field
# fix; "diverged" at URF / scheme / mesh-quality tuning.
_FOAM_FATAL_RE = re.compile(r"FOAM FATAL (?:IO )?ERROR", re.IGNORECASE)


def _classify_solver_failure(log_file: Path) -> str:
    """Return "solver_error" if the log carries a FOAM FATAL marker, else "diverged".

    A numerical blow-up exits non-zero without a fatal-error banner, so the
    absence of the marker defaults to "diverged".
    """
    try:
        text = log_file.read_text(errors="replace")
    except OSError:
        return "diverged"
    return "solver_error" if _FOAM_FATAL_RE.search(text) else "diverged"


def run_solver(
    case_path: str,
    solver: str,
    end_time: float | None = None,
    timeout_s: int = DEFAULT_SOLVER_TIMEOUT_S,
    n_procs: int = 1,
) -> ToolResult:
    """Run an OpenFOAM solver on the given case.

    Args:
        case_path: Absolute path to the OpenFOAM case directory. Must already
            have a valid mesh (``constant/polyMesh/``) and a ``system/controlDict``.
        solver: Solver executable name, e.g. ``"simpleFoam"``, ``"pisoFoam"``,
            ``"pimpleFoam"``. Must be a bare command name with no path
            separators — the tool relies on PATH lookup.
        end_time: If set, override ``controlDict.endTime`` before running and
            restore it afterwards. The override happens via ``foamDictionary``,
            so OpenFOAM must be sourced.
        timeout_s: Hard wall-clock timeout. The solver is killed if it runs
            longer than this.
        n_procs: Number of MPI ranks. Default 1 = serial. If > 1, the case
            must already be decomposed via ``decompose_par`` to the same
            count, and the solver is launched as
            ``mpirun -np <n_procs> <solver> -parallel``.

    Returns:
        On success: ``{"success": True, "final_residuals": {...}, "walltime_s":
        float, "converged": bool, "log_tail": str}``.

        On failure: ``{"success": False, "reason": str, "log_tail": str}``,
        where ``reason`` is one of ``"invalid_solver"``, ``"invalid_case"``,
        ``"invalid_n_procs"``, ``"missing_decomposition"``,
        ``"end_time_override_failed"``, ``"solver_not_found"``,
        ``"mpirun_not_on_path"``, ``"timeout"``, ``"solver_error"`` (the log
        carries a FOAM FATAL ERROR — a setup/dictionary/field problem to fix),
        or ``"diverged"`` (non-zero exit with no fatal marker — a numerical
        blow-up to address with relaxation / scheme / mesh-quality changes).
    """
    if not solver or any(sep in solver for sep in ("/", "\\", "\x00")):
        return {
            "success": False,
            "reason": "invalid_solver",
            "log_tail": f"solver must be a bare command name, got {solver!r}",
        }
    if not isinstance(n_procs, int) or n_procs < 1:
        return {
            "success": False,
            "reason": "invalid_n_procs",
            "log_tail": f"n_procs must be an integer >= 1, got {n_procs!r}",
        }

    case = Path(case_path)
    control_dict = case / "system" / "controlDict"
    polymesh = case / "constant" / "polyMesh"
    if not control_dict.is_file():
        return {
            "success": False,
            "reason": "invalid_case",
            "log_tail": f"missing {control_dict}",
        }
    if not polymesh.is_dir():
        return {
            "success": False,
            "reason": "invalid_case",
            "log_tail": f"missing {polymesh}; run blockMesh first",
        }

    if n_procs > 1:
        proc_dirs = sorted(case.glob("processor*"))
        if len(proc_dirs) != n_procs:
            return {
                "success": False,
                "reason": "missing_decomposition",
                "log_tail": (
                    f"asked for {n_procs} ranks but found {len(proc_dirs)} "
                    f"processor*/ directories in {case}. Run decompose_par "
                    f"with n_procs={n_procs} first."
                ),
            }

    saved_end_time: str | None = None
    if end_time is not None:
        try:
            saved_end_time = foam_dictionary_get(control_dict, "endTime")
            foam_dictionary_set(control_dict, "endTime", str(end_time))
        except FileNotFoundError:
            return {
                "success": False,
                "reason": "end_time_override_failed",
                "log_tail": "foamDictionary not on PATH; is OpenFOAM sourced?",
            }
        except subprocess.CalledProcessError as exc:
            return {
                "success": False,
                "reason": "end_time_override_failed",
                "log_tail": (exc.stderr or "") + (exc.stdout or ""),
            }

    log_file = case / f"log.{solver}"
    cmd: list[str]
    if n_procs > 1:
        cmd = ["mpirun", "-np", str(n_procs), solver, "-case", str(case), "-parallel"]
    else:
        cmd = [solver, "-case", str(case)]

    try:
        try:
            with log_file.open("w") as fh:
                result = subprocess.run(
                    cmd,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    timeout=timeout_s,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "reason": "timeout",
                "log_tail": tail_log(log_file, LOG_TAIL_LINES),
            }
        except FileNotFoundError:
            missing = "mpirun" if n_procs > 1 else solver
            return {
                "success": False,
                "reason": (
                    "mpirun_not_on_path" if n_procs > 1 else "solver_not_found"
                ),
                "log_tail": f"{missing} CLI not found. Is OpenFOAM sourced?",
            }

        log_tail = tail_log(log_file, LOG_TAIL_LINES)
        if result.returncode != 0:
            return {
                "success": False,
                "reason": _classify_solver_failure(log_file),
                "log_tail": log_tail,
            }

        history = parse_residual_history(log_file)
        return {
            "success": True,
            "final_residuals": final_residuals(history),
            "walltime_s": parse_walltime_seconds(log_file),
            "converged": is_converged(log_file),
            "log_tail": log_tail,
        }
    finally:
        if saved_end_time is not None:
            try:
                foam_dictionary_set(control_dict, "endTime", saved_end_time)
            except (FileNotFoundError, subprocess.CalledProcessError):
                # Best-effort restore. If foamDictionary is gone, the user has
                # bigger problems than a stale endTime.
                pass


def get_residuals(case_path: str, summary: bool = True) -> ToolResult:
    """Read residual data from a case's solver log.

    Picks the most recently modified ``log.<solver>`` file in the case
    directory, ignoring mesh / case-prep utilities (blockMesh, snappyHexMesh,
    foamDictionary, etc.). If multiple solver logs exist, the newest wins.

    Args:
        case_path: Absolute path to the OpenFOAM case directory.
        summary: When True (default), return a compact per-field summary
            with first/last/min initial residual and orders-of-magnitude
            drop — small payload, safe for the agent's context. When False,
            return the full per-iteration history. Long solver runs can
            produce histories of 10s-100s of KB; only request the full
            history if you need to look at the trajectory.

    Returns:
        On success, with ``summary=True``:
            ``{"success": True, "log_file": str, "n_outer_iterations": int,
            "summary": {field: {"first": float, "last": float, "min": float,
            "orders_dropped": float, "n_points": int}}}``.

        On success, with ``summary=False``:
            ``{"success": True, "log_file": str, "n_outer_iterations": int,
            "residuals": {field: [{"iteration": int, "initial": float,
            "final": float}, ...]}}``.

        ``{"success": False, "reason": str, "detail": str}`` on failure.
        ``reason`` is one of ``"invalid_case_path"``, ``"no_solver_log"``,
        ``"no_residuals_in_log"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} is not a directory",
        }

    log = _find_latest_solver_log(case)
    if log is None:
        return {
            "success": False,
            "reason": "no_solver_log",
            "detail": f"no log.<solver> file found in {case}",
        }

    history = parse_residual_history(log)
    if not history:
        return {
            "success": False,
            "reason": "no_residuals_in_log",
            "detail": f"{log} has no parseable 'Solving for ...' lines",
        }

    n_outer = max((len(e) for e in history.values()), default=0)

    if summary:
        return {
            "success": True,
            "log_file": str(log),
            "n_outer_iterations": n_outer,
            "summary": _summarize_residuals(history),
        }

    # Project parser output onto the public contract (drop n_iter_inner).
    residuals = {
        field: [
            {"iteration": e["iteration"], "initial": e["initial"], "final": e["final"]}
            for e in entries
        ]
        for field, entries in history.items()
    }
    return {
        "success": True,
        "log_file": str(log),
        "n_outer_iterations": n_outer,
        "residuals": residuals,
    }


def _summarize_residuals(
    history: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Compact per-field stats: first, last, min, orders_dropped."""
    out: dict[str, dict[str, Any]] = {}
    for field, entries in history.items():
        if not entries:
            continue
        initials = [e["initial"] for e in entries if e["initial"] > 0]
        first = entries[0]["initial"]
        last = entries[-1]["initial"]
        minimum = min(initials) if initials else last
        orders: float | None
        if first > 0 and last > 0:
            orders = math.log10(first / last)
        else:
            orders = None
        out[field] = {
            "n_points": len(entries),
            "first": first,
            "last": last,
            "min": minimum,
            "orders_dropped": orders,
        }
    return out


PVBATCH_TIMEOUT_S = 120
_PVBATCH_RENDER_SCRIPT = Path(__file__).resolve().parent / "pvbatch_render.py"
_RESULT_SENTINEL = "<<<RENDER_RESULT>>>"


def export_field_image(
    case_path: str,
    field: str,
    time: str | float = "latestTime",
    slice_plane: Mapping[str, Any] | None = None,
) -> ToolResult:
    """Render a field at a given time to a PNG, return the path.

    Drives ParaView's ``pvbatch`` headlessly via the bundled
    ``pvbatch_render.py`` script. The agent can describe the image (frontier
    agents) or hand it to a vision-capable local model (Demo 2).

    Args:
        case_path: Absolute path to the OpenFOAM case directory. Must have a
            mesh in ``constant/polyMesh/`` and at least one numeric time
            directory.
        field: Field name, e.g. ``"U"``, ``"p"``, ``"k"``. Must exist in the
            case at the chosen time.
        time: Simulation time to render. ``"latestTime"`` uses the final step;
            a numeric value is snapped to the nearest available time.
        slice_plane: Reserved. Currently ignored — the renderer auto-detects
            single-layer 2D cases (like pitzDaily) and uses a top-down
            parallel-projection view; full 3D cases get a default ResetCamera
            view. Slice support is a Week-of-18-May extension.

    Returns:
        On success: ``{"success": True, "image_path": str,
        "colorbar_range": [float, float], "rendered_time": float}``.

        On failure: ``{"success": False, "reason": str, ...}``. ``reason`` is
        one of ``"invalid_case"``, ``"pvbatch_not_found"``, ``"timeout"``,
        ``"no_time_directories"``, ``"field_not_found"``, ``"render_failed"``.
    """
    case = Path(case_path)
    polymesh = case / "constant" / "polyMesh"
    if not polymesh.is_dir():
        return {
            "success": False,
            "reason": "invalid_case",
            "detail": f"missing {polymesh}; run blockMesh first",
        }

    images_dir = case / "postProcessing" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    safe_time = "latest" if time == "latestTime" else str(time).replace(".", "p")
    output_path = images_dir / f"{field}_t{safe_time}.png"

    # ParaView's OpenFOAMReader needs a foam-marker file to anchor the case.
    # Re-use one if it already exists; otherwise drop one (idempotent).
    existing_markers = list(case.glob("*.foam"))
    case_marker = existing_markers[0] if existing_markers else case / "case.foam"
    if not case_marker.exists():
        case_marker.touch()

    opts = {
        "case_marker": str(case_marker),
        "field": field,
        "time": time,
        "output_path": str(output_path),
    }

    try:
        result = subprocess.run(
            [
                "pvbatch",
                # A single-image render needs no MPI; initialising it anyway
                # hangs pvbatch on hosts where MPI cannot start (seen on
                # WSL2 with mirrored networking), until the timeout fires.
                "--no-mpi",
                "--force-offscreen-rendering",
                str(_PVBATCH_RENDER_SCRIPT),
                json.dumps(opts),
            ],
            capture_output=True,
            text=True,
            timeout=PVBATCH_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return {
            "success": False,
            "reason": "pvbatch_not_found",
            "detail": "pvbatch is not on PATH (install ParaView)",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "reason": "timeout",
            "detail": f"pvbatch did not finish within {PVBATCH_TIMEOUT_S}s",
        }

    payload = _parse_pvbatch_payload(result.stdout)
    if payload is None:
        return {
            "success": False,
            "reason": "render_failed",
            "detail": (
                "pvbatch produced no result sentinel. "
                f"stderr_tail: {result.stderr.splitlines()[-5:]} "
                f"stdout_tail: {result.stdout.splitlines()[-5:]}"
            ),
        }
    return payload


TUTORIAL_LIST_LIMIT = 200
TUTORIAL_READ_BYTES_LIMIT = 64_000
_TUTORIAL_CASE_MARKERS = ("system",)


def _resolve_tutorials_root() -> Path | None:
    """Return ``$FOAM_TUTORIALS`` as a Path if set and existing, else None."""
    raw = os.environ.get("FOAM_TUTORIALS")
    if not raw:
        return None
    root = Path(raw).resolve()
    return root if root.is_dir() else None


def _safe_join_under(root: Path, rel: str) -> Path | None:
    """Join ``rel`` under ``root``; return None if it escapes ``root``."""
    if not rel:
        return root
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def list_tutorials(subpath: str = "") -> ToolResult:
    """List entries under the OpenFOAM tutorials library at ``$FOAM_TUTORIALS``.

    The OpenFOAM tutorials are the canonical source for case templates. Use
    this tool to browse the tree before authoring a new case — pick a tutorial
    that matches your physics, then read its dictionaries with
    ``read_tutorial_file``.

    Args:
        subpath: Path under ``$FOAM_TUTORIALS`` to list. Empty string lists the
            top-level categories (incompressible, compressible, multiphase, …).
            Use forward slashes; ``..`` and absolute paths are rejected.

    Returns:
        On success: ``{"success": True, "root": str, "subpath": str,
        "entries": [{"name": str, "kind": "dir"|"file", "is_case": bool}, ...],
        "truncated": bool}``. ``is_case`` is True when an entry is a directory
        that looks like a runnable OpenFOAM case (contains a ``system/`` dir).
        ``truncated`` is True if the listing was capped at the entry limit.

        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of ``"foam_tutorials_unset"``, ``"path_escape"``,
        ``"not_a_directory"``.
    """
    root = _resolve_tutorials_root()
    if root is None:
        return {
            "success": False,
            "reason": "foam_tutorials_unset",
            "detail": "$FOAM_TUTORIALS is not set or does not exist. Source OpenFOAM first.",
        }

    target = _safe_join_under(root, subpath)
    if target is None:
        return {
            "success": False,
            "reason": "path_escape",
            "detail": f"{subpath!r} resolves outside $FOAM_TUTORIALS",
        }
    if not target.is_dir():
        return {
            "success": False,
            "reason": "not_a_directory",
            "detail": f"{target} is not a directory",
        }

    entries: list[dict[str, Any]] = []
    truncated = False
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if len(entries) >= TUTORIAL_LIST_LIMIT:
            truncated = True
            break
        is_dir = child.is_dir()
        is_case = is_dir and all((child / m).exists() for m in _TUTORIAL_CASE_MARKERS)
        entries.append({
            "name": child.name,
            "kind": "dir" if is_dir else "file",
            "is_case": is_case,
        })

    return {
        "success": True,
        "root": str(root),
        "subpath": subpath,
        "entries": entries,
        "truncated": truncated,
    }


def read_tutorial_file(relative_path: str) -> ToolResult:
    """Read a single file from the OpenFOAM tutorials library.

    Use this after ``list_tutorials`` to inspect a tutorial's dictionaries
    (``system/blockMeshDict``, ``0/U``, etc.) when authoring a new case.

    Args:
        relative_path: Path under ``$FOAM_TUTORIALS``, e.g.
            ``"incompressible/simpleFoam/pitzDaily/system/controlDict"``.
            Forward slashes only; ``..`` and absolute paths are rejected.

    Returns:
        On success: ``{"success": True, "path": str, "content": str,
        "truncated": bool, "size_bytes": int}``. The content is capped at
        ~64 KB; ``truncated`` is True when the file was longer.

        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of ``"foam_tutorials_unset"``, ``"path_escape"``,
        ``"not_a_file"``, ``"read_failed"``.
    """
    root = _resolve_tutorials_root()
    if root is None:
        return {
            "success": False,
            "reason": "foam_tutorials_unset",
            "detail": "$FOAM_TUTORIALS is not set or does not exist. Source OpenFOAM first.",
        }

    target = _safe_join_under(root, relative_path)
    if target is None:
        return {
            "success": False,
            "reason": "path_escape",
            "detail": f"{relative_path!r} resolves outside $FOAM_TUTORIALS",
        }
    if not target.is_file():
        return {
            "success": False,
            "reason": "not_a_file",
            "detail": f"{target} is not a regular file",
        }

    try:
        size = target.stat().st_size
        with target.open("rb") as fh:
            raw = fh.read(TUTORIAL_READ_BYTES_LIMIT + 1)
    except OSError as exc:
        return {
            "success": False,
            "reason": "read_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    truncated = len(raw) > TUTORIAL_READ_BYTES_LIMIT
    content = raw[:TUTORIAL_READ_BYTES_LIMIT].decode("utf-8", errors="replace")
    return {
        "success": True,
        "path": str(target),
        "content": content,
        "truncated": truncated,
        "size_bytes": size,
    }


def _parse_pvbatch_payload(stdout: str) -> ToolResult | None:
    """Find ``_RESULT_SENTINEL`` in pvbatch stdout and return the JSON below it.

    pvbatch is chatty on startup; the script prints the sentinel right before
    its result so we can split cleanly regardless of preceding noise.
    """
    lines = stdout.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == _RESULT_SENTINEL and idx + 1 < len(lines):
            try:
                return json.loads(lines[idx + 1])
            except json.JSONDecodeError:
                return None
    return None


# ---------------------------------------------------------------------------
# archive_case: promote a completed case from cases/work/<name>/ into the
# tracked cases/examples/<name>/baseline/ library, after explicit user OK.
#
# Skips run-generated content (time directories, parallel decomposition,
# postProcessing output, polyMesh, logs, .foam markers) so the archive
# contains only the case *inputs* the agent authored — same shape as the
# existing cases/examples/pitz-daily/baseline/ layout.

_REPO_ROOT_ENV = "AGENTIC_OPENFOAM_ROOT"
_CASES_DIRNAME = "cases"
_EXAMPLES_SUBDIR = "examples"
_BASELINE_SUBDIR = "baseline"

# Directory names that represent run-generated content and should never be
# copied into the archive.
#  - Time directories: any directory whose name parses to a positive number
#    (e.g. "1", "1.5", "100"). The "0/" directory is the committed initial
#    conditions and IS kept.
#  - processor*: parallel decomposition outputs.
#  - postProcessing: function-object output.
#  - polyMesh (under constant/): generated mesh.
_TIME_DIR_RE = re.compile(r"^[1-9]\d*(?:\.\d+)?$")
_PROCESSOR_DIR_RE = re.compile(r"^processor\d+$")
_EXCLUDED_DIR_EXACT = frozenset({"postProcessing", "polyMesh"})

# Carve-outs that override the directory exclusions above: subtrees that sit
# *inside* an excluded directory but must still be archived so the validation
# replays. Each entry is the case-relative path (as a tuple of components) of a
# directory to keep. ``postProcessing/analysis/`` holds the agent-authored
# validation plots + metrics.json produced by ``validation.run_analysis``;
# everything else under ``postProcessing/`` (forceCoeffs, probes, sampled sets)
# is large run output and stays excluded.
_ARCHIVE_INCLUDE_SUBPATHS = frozenset({("postProcessing", "analysis")})

# Files that represent run output and shouldn't be archived.
_EXCLUDED_FILE_PREFIXES = ("log.",)
_EXCLUDED_FILE_SUFFIXES = (".foam",)
# An archive-name validator: single path component, no separators, not
# starting with a dot.
_ARCHIVE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")


def _find_repo_root_for_archive() -> Path:
    """Locate the repo root that holds ``cases/``.

    Honours ``AGENTIC_OPENFOAM_ROOT`` env override (useful for tests).
    Otherwise walks up from this module's location looking for a child
    ``cases/`` directory.
    """
    override = os.environ.get(_REPO_ROOT_ENV)
    if override:
        root = Path(override).resolve()
        if (root / _CASES_DIRNAME).is_dir():
            return root
        raise FileNotFoundError(
            f"{_REPO_ROOT_ENV}={override} is set but "
            f"{root / _CASES_DIRNAME} does not exist."
        )
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / _CASES_DIRNAME).is_dir():
            return parent
    raise FileNotFoundError(
        f"Could not locate the {_CASES_DIRNAME}/ directory by walking up "
        f"from {here}. Set {_REPO_ROOT_ENV} to override."
    )


def _is_excluded_dir(name: str) -> bool:
    if name in _EXCLUDED_DIR_EXACT:
        return True
    if _TIME_DIR_RE.match(name):
        return True
    if _PROCESSOR_DIR_RE.match(name):
        return True
    return False


def _is_included_subpath(rel: tuple[str, ...]) -> bool:
    """True if ``rel`` is an allowlisted subtree to keep despite exclusion."""
    return rel in _ARCHIVE_INCLUDE_SUBPATHS


def _is_include_prefix(rel: tuple[str, ...]) -> bool:
    """True if ``rel`` is a strict ancestor of some allowlisted subtree.

    An excluded directory (e.g. ``postProcessing``) must still be *descended
    into* — rather than skipped wholesale — when one of its descendants is an
    allowlisted carve-out (e.g. ``postProcessing/analysis``). Only the
    carve-out child is then copied; the rest of the excluded dir is dropped.
    """
    n = len(rel)
    return any(inc[:n] == rel for inc in _ARCHIVE_INCLUDE_SUBPATHS if len(inc) > n)


def _has_included_descendant(src: Path, rel: tuple[str, ...]) -> bool:
    """True if any allowlisted carve-out subtree exists on disk under ``src``.

    Guards against materialising an empty excluded directory in the archive:
    we only descend into (and thus ``mkdir``) an excluded dir when the
    carve-out it gates is actually present.
    """
    n = len(rel)
    for inc in _ARCHIVE_INCLUDE_SUBPATHS:
        if len(inc) > n and inc[:n] == rel:
            if (src / Path(*inc[n:])).is_dir():
                return True
    return False


def _is_excluded_file(name: str) -> bool:
    if any(name.startswith(p) for p in _EXCLUDED_FILE_PREFIXES):
        return True
    if any(name.endswith(s) for s in _EXCLUDED_FILE_SUFFIXES):
        return True
    return False


def _copy_case_inputs(
    src: Path,
    dst: Path,
    rel: tuple[str, ...] = (),
    in_exclusion: bool = False,
) -> int:
    """Recursively copy src into dst, skipping run-generated artifacts.

    ``rel`` is the path of ``src`` relative to the case root, as a tuple of
    directory-name components — used to honour the ``_ARCHIVE_INCLUDE_SUBPATHS``
    carve-outs (subtrees kept even though their parent dir is excluded).

    ``in_exclusion`` is True once we have descended *below* an excluded
    directory purely to reach an allowlisted carve-out. In that context the
    normal "keep everything not explicitly excluded" rule no longer applies —
    only paths on the way to (or inside) a carve-out are kept; every sibling
    run-output dir is dropped.

    Returns the number of regular files copied.
    """
    dst.mkdir(parents=True, exist_ok=True)
    n_copied = 0
    for entry in sorted(src.iterdir()):
        if entry.is_symlink():
            # Skip symlinks: they often point outside the case (e.g. to
            # a shared mesh) and copying as files can pull in megabytes.
            continue
        child_rel = (*rel, entry.name)
        if entry.is_dir():
            # Inside an exclusion context, only descend toward a carve-out.
            if in_exclusion:
                if _is_included_subpath(child_rel):
                    # The carve-out itself: copy its whole subtree verbatim.
                    n_copied += _copy_case_inputs(entry, dst / entry.name, child_rel)
                elif _is_include_prefix(child_rel) and _has_included_descendant(
                    entry, child_rel
                ):
                    n_copied += _copy_case_inputs(
                        entry, dst / entry.name, child_rel, in_exclusion=True
                    )
                # else: sibling run output below an excluded dir — dropped.
                continue
            if _is_excluded_dir(entry.name):
                # Keep an allowlisted carve-out living inside an excluded dir
                # (e.g. postProcessing/analysis); descend only if the carve-out
                # actually exists so we never materialise an empty excluded dir
                # (e.g. a bare postProcessing/ holding only run output). Every
                # non-carve-out child of the excluded dir is still dropped.
                if _is_include_prefix(child_rel) and _has_included_descendant(
                    entry, child_rel
                ):
                    n_copied += _copy_case_inputs(
                        entry, dst / entry.name, child_rel, in_exclusion=True
                    )
                continue
            n_copied += _copy_case_inputs(entry, dst / entry.name, child_rel)
        elif entry.is_file():
            # Files directly under an excluded dir (not inside a carve-out)
            # are run output: drop them. Files inside the carve-out subtree
            # are reached via the _is_included_subpath branch above with
            # in_exclusion reset, so they land here with in_exclusion False.
            if in_exclusion:
                continue
            if _is_excluded_file(entry.name):
                continue
            shutil.copy2(entry, dst / entry.name)
            n_copied += 1
    return n_copied


def archive_case(
    case_path: str,
    archive_name: str,
    overwrite: bool = False,
) -> ToolResult:
    """Archive a completed case to ``cases/examples/<archive_name>/baseline/``.

    Copies the case *inputs* the agent authored — dictionaries under
    ``system/``, ``constant/`` (excluding ``polyMesh/``), the committed
    initial-conditions ``0/`` directory, ``REPORT.md``, ``Allrun`` /
    ``Allclean`` scripts, and any top-level YAML scenario the user
    placed in the case directory. Skips run-generated content: time
    directories (``1/``, ``1.5/``, ``100/``, ...), ``processor*/``,
    ``postProcessing/``, ``polyMesh/``, ``log.*`` files, and ``.foam``
    markers.

    The result lands at ``<repo>/cases/examples/<archive_name>/baseline/``
    — the same shape as the existing ``cases/examples/pitz-daily/baseline/``
    archive. The agent must obtain explicit user approval before calling
    this tool; see ``CLAUDE.md`` for the end-of-run handoff.

    Args:
        case_path: Absolute path to the case directory to archive.
        archive_name: Directory name under ``cases/examples/``. Must be a
            single path component (no slashes), beginning with an
            alphanumeric, containing only ``[A-Za-z0-9._-]``.
        overwrite: If False (default), refuse to overwrite an existing
            ``cases/examples/<archive_name>/baseline/``. Pass True to
            replace.

    Returns:
        On success: ``{"success": True, "archive_path": str,
        "n_files_copied": int}``.
        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of ``"invalid_case_path"``,
        ``"invalid_archive_name"``, ``"root_not_found"``,
        ``"archive_already_exists"``, ``"copy_failed"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory",
        }

    name_clean = archive_name.strip()
    if not name_clean or not _ARCHIVE_NAME_RE.match(name_clean):
        return {
            "success": False,
            "reason": "invalid_archive_name",
            "detail": (
                f"archive_name must be a single path component matching "
                f"[A-Za-z0-9][A-Za-z0-9._-]*, got {archive_name!r}."
            ),
        }

    try:
        repo_root = _find_repo_root_for_archive()
    except FileNotFoundError as exc:
        return {
            "success": False,
            "reason": "root_not_found",
            "detail": str(exc),
        }

    archive_path = (
        repo_root / _CASES_DIRNAME / _EXAMPLES_SUBDIR / name_clean / _BASELINE_SUBDIR
    )

    if archive_path.exists():
        if not overwrite:
            return {
                "success": False,
                "reason": "archive_already_exists",
                "detail": (
                    f"{archive_path} already exists. Pass overwrite=True "
                    f"to replace it, or pick a different archive_name."
                ),
            }
        # Wipe so the new archive is exactly what's in src, not a merge.
        try:
            shutil.rmtree(archive_path)
        except OSError as exc:
            return {
                "success": False,
                "reason": "copy_failed",
                "detail": f"Failed to remove existing archive: {exc}",
            }

    try:
        n_copied = _copy_case_inputs(case, archive_path)
    except OSError as exc:
        return {
            "success": False,
            "reason": "copy_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    return {
        "success": True,
        "archive_path": str(archive_path),
        "n_files_copied": n_copied,
    }
