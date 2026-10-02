"""Tool implementations for the Consultant MCP server.

Same rules as the OpenFOAM and Validation servers
(see ``docs/architecture.md``):

1. Every tool returns ``{"success": bool, ...}``. Never raise.
2. Output is small and structured — these tools feed the consultant
   schema fields on ``record_step`` and should not blow context budget.
3. No hallucinated CFD wisdom. Thresholds and recommendations cite the
   sources defined in ``assessments.CITATION_SOURCES``; tutorial
   rationale comes from the hand-authored annotations corpus.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from consultant_mcp.annotations import (
    AnnotationNotFoundError,
    annotation_path_for,
    find_repo_root,
    read_annotation,
)
from consultant_mcp.assessments import (
    CITATION_SOURCES,
    MetricVerdict,
    ResidualVerdict,
    YPlusVerdict,
    aggregate_verdict,
    DEFAULT_MESH_THRESHOLDS,
    DEFAULT_RESIDUAL_THRESHOLDS,
    MeshThresholds,
    ResidualThresholds,
    assess_aspect_ratio,
    assess_non_orthogonality,
    assess_residual_pattern,
    assess_severe_non_orthogonal,
    assess_skewness,
    classify_turbulence_model,
)
from consultant_mcp.assessments import (
    assess_y_plus as _assess_y_plus_band,
)

ToolResult = dict[str, Any]


# Patterns to extract checkMesh numbers from log.checkMesh. These mirror
# the ones used by the OpenFOAM server's _parse_check_mesh — duplicated
# here so the consultant tool doesn't import the OpenFOAM package.
_NCELLS = re.compile(r"\bcells:\s+(\d+)")
_AR = re.compile(r"Max aspect ratio = ([0-9.eE+\-]+)")
_NONORTHO = re.compile(
    r"Mesh non-orthogonality Max: ([0-9.eE+\-]+) average: ([0-9.eE+\-]+)"
)
_SKEWNESS = re.compile(r"Max skewness = ([0-9.eE+\-]+)")
_SEVERE = re.compile(
    r"\*Number of severely non-orthogonal \(> ?70 ?degrees\) faces:\s*(\d+)"
)
_MESH_OK = re.compile(r"^\s*Mesh OK\.\s*$", re.MULTILINE)
_FAILED_CHECKS = re.compile(r"Failed\s+(\d+)\s+mesh checks", re.IGNORECASE)


def _parse_check_mesh_log(log_text: str) -> dict[str, Any]:
    """Pull the numeric metrics + pass/fail flag out of a checkMesh log.

    Note on severe_non_orthogonal_faces: checkMesh OMITS the "Number of
    severely non-orthogonal..." line when there are zero such faces.
    We start the field at None so we can distinguish "not parsed" from
    "parsed as 0", then if non-orthogonality was successfully read but
    the severe-faces line was absent, we set it to 0.
    """
    metrics: dict[str, Any] = {
        "n_cells": None,
        "max_aspect_ratio": None,
        "max_non_orthogonality": None,
        "average_non_orthogonality": None,
        "max_skewness": None,
        "severe_non_orthogonal_faces": None,
    }
    for line in log_text.splitlines():
        if metrics["n_cells"] is None:
            m = _NCELLS.search(line)
            if m:
                metrics["n_cells"] = int(m.group(1))
        m = _AR.search(line)
        if m:
            metrics["max_aspect_ratio"] = float(m.group(1))
        m = _NONORTHO.search(line)
        if m:
            metrics["max_non_orthogonality"] = float(m.group(1))
            metrics["average_non_orthogonality"] = float(m.group(2))
        m = _SKEWNESS.search(line)
        if m:
            metrics["max_skewness"] = float(m.group(1))
        m = _SEVERE.search(line)
        if m:
            metrics["severe_non_orthogonal_faces"] = int(m.group(1))

    # If checkMesh successfully reported non-orthogonality but the
    # severe-faces line was absent, the absence means zero severe faces.
    if (
        metrics["max_non_orthogonality"] is not None
        and metrics["severe_non_orthogonal_faces"] is None
    ):
        metrics["severe_non_orthogonal_faces"] = 0

    quality_pass = bool(_MESH_OK.search(log_text)) and not _FAILED_CHECKS.search(
        log_text
    )
    metrics["quality_pass"] = quality_pass
    return metrics


def assess_mesh_quality(
    case_path: str, thresholds: MeshThresholds | None = None
) -> ToolResult:
    """Interpret checkMesh metrics in CFD-domain language.

    Reads ``<case_path>/log.checkMesh`` (written by the OpenFOAM
    server's ``check_mesh`` tool), extracts the standard metrics, and
    returns a per-metric verdict plus an overall verdict. Each metric
    carries a verdict band, a recommendation, and short citation tags
    that point into ``citation_sources``.

    Use this immediately after ``check_mesh`` to fill the consultant
    fields on ``record_step``:

    - ``decision`` = "accept mesh" or "re-mesh / compensate"
    - ``why`` = a short summary built from the per-metric verdicts
    - ``alternatives`` = what to change if the verdict is marginal/poor
    - ``when_it_breaks`` = the threshold band the metric sits in

    Args:
        case_path: Absolute path to the OpenFOAM case directory. Must
            contain ``log.checkMesh`` (from a prior ``check_mesh``
            call).

    Returns:
        On success: ``{"success": True, "overall_verdict": str,
        "metrics": [...], "citation_sources": {...},
        "summary": str}``. ``metrics`` is a list of per-metric verdict
        dicts (``metric``, ``value``, ``verdict``, ``threshold_band``,
        ``recommendation``, ``cites``). ``overall_verdict`` is the
        worst per-metric verdict. ``summary`` is a one-paragraph
        natural-language synthesis suitable for the ``why`` field.

        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of ``"invalid_case_path"``,
        ``"checkmesh_log_missing"``, ``"checkmesh_log_unreadable"``,
        ``"checkmesh_log_empty"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory.",
        }

    log_file = case / "log.checkMesh"
    if not log_file.is_file():
        return {
            "success": False,
            "reason": "checkmesh_log_missing",
            "detail": (
                f"{log_file} does not exist. Run check_mesh (openfoam "
                f"server) before assessing quality."
            ),
        }

    try:
        log_text = log_file.read_text(errors="replace")
    except OSError as exc:
        return {
            "success": False,
            "reason": "checkmesh_log_unreadable",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    if not log_text.strip():
        return {
            "success": False,
            "reason": "checkmesh_log_empty",
            "detail": f"{log_file} is empty.",
        }

    parsed = _parse_check_mesh_log(log_text)
    n_cells = parsed["n_cells"]
    # `thresholds` is not part of the MCP surface an agent sees — it stays
    # at the shipped defaults for every ordinary call. It exists so a study
    # can move the operating point and still get its verdicts from this
    # function rather than from a copy of it.
    bands = thresholds or DEFAULT_MESH_THRESHOLDS
    verdicts: list[MetricVerdict] = [
        assess_non_orthogonality(parsed["max_non_orthogonality"], bands),
        assess_skewness(parsed["max_skewness"], bands),
        assess_aspect_ratio(parsed["max_aspect_ratio"], bands),
        assess_severe_non_orthogonal(
            parsed["severe_non_orthogonal_faces"], n_cells, bands
        ),
    ]
    overall = aggregate_verdict(verdicts)

    # Build a short natural-language summary for the consultant `why` field.
    parts: list[str] = []
    parts.append(
        f"Mesh quality verdict: {overall}"
        f"{' (checkMesh reported failures)' if not parsed['quality_pass'] else ''}."
    )
    for v in verdicts:
        if v.verdict == "unknown":
            continue
        verb = "is" if v.verdict in {"good", "acceptable"} else "sits at"
        val = f"{v.value:.3g}" if v.value is not None else "?"
        parts.append(
            f"{v.metric}={val} {verb} {v.verdict} ({v.threshold_band})."
        )
    summary = " ".join(parts)

    # Subset citation_sources to only the keys actually used.
    used_cites: set[str] = set()
    for v in verdicts:
        used_cites.update(v.cites)
    citation_sources = {k: CITATION_SOURCES[k] for k in sorted(used_cites)}

    return {
        "success": True,
        "case_path": str(case),
        "n_cells": n_cells,
        "checkmesh_quality_pass": parsed["quality_pass"],
        "overall_verdict": overall,
        "metrics": [v.to_dict() for v in verdicts],
        "citation_sources": citation_sources,
        "summary": summary,
    }


def get_tutorial_annotation(tutorial_path: str) -> ToolResult:
    """Fetch a hand-authored annotation for an ``$FOAM_TUTORIALS`` entry.

    Corpus entries live under ``corpus/<solver>/<case>.md`` in the
    repo. When the agent picks a tutorial as a structural
    template, call this tool and use the returned ``body`` to fill the
    consultant fields on ``openfoam.record_step``. If no annotation
    exists, the tool returns ``success=False`` with reason
    ``"no_annotation"`` — DO NOT invent rationale; record the gap on
    the audit trail by passing the consultant fields empty (or with a
    "no annotation available at <path>" note).

    Args:
        tutorial_path: Tutorial location relative to ``$FOAM_TUTORIALS``,
            e.g. ``"incompressible/icoFoam/cavity/cavity"``. The same
            string you'd pass to the OpenFOAM server's
            ``read_tutorial_file``.

    Returns:
        On success: ``{"success": True, "tutorial_path": str,
        "annotation_path": str, "metadata": dict, "body": str}``.
        ``metadata`` is the YAML frontmatter parsed to a mapping (with
        keys like ``solver``, ``physics``, ``suitable_for_template``,
        ``not_suitable_for``, ``references``). ``body`` is the
        markdown body suitable for quoting verbatim into ``record_step``.

        On failure: ``{"success": False, "reason": str, "detail": str,
        "expected_path": str}``. ``reason`` is one of ``"no_annotation"``,
        ``"invalid_tutorial_path"``, ``"malformed_annotation"``,
        ``"annotations_root_not_found"``.
    """
    try:
        ann = read_annotation(tutorial_path)
    except AnnotationNotFoundError:
        try:
            expected = annotation_path_for(tutorial_path)
        except (ValueError, FileNotFoundError) as exc:
            return {
                "success": False,
                "reason": "annotations_root_not_found",
                "detail": str(exc),
                "expected_path": "",
            }
        return {
            "success": False,
            "reason": "no_annotation",
            "detail": (
                f"No annotation at {expected}. Record this as an uncited "
                f"choice on the audit trail rather than inventing rationale."
            ),
            "expected_path": str(expected),
        }
    except ValueError as exc:
        try:
            expected = annotation_path_for(tutorial_path)
        except Exception:
            expected_str = ""
        else:
            expected_str = str(expected)
        return {
            "success": False,
            "reason": "malformed_annotation",
            "detail": str(exc),
            "expected_path": expected_str,
        }
    except FileNotFoundError as exc:
        return {
            "success": False,
            "reason": "annotations_root_not_found",
            "detail": str(exc),
            "expected_path": "",
        }

    return {
        "success": True,
        "tutorial_path": ann.tutorial_path,
        "annotation_path": str(ann.file_path),
        "metadata": ann.metadata,
        "body": ann.body,
    }


def list_tutorial_annotations() -> ToolResult:
    """List every tutorial that has a hand-authored annotation.

    Useful when the agent is exploring what's available before picking a
    template. Returns the tutorial path (relative to ``$FOAM_TUTORIALS``)
    and the annotation file path for each.

    Returns:
        ``{"success": True, "annotations": [{"tutorial_path": str,
        "annotation_path": str}, ...]}`` — sorted by tutorial path.

        On failure: ``{"success": False, "reason":
        "annotations_root_not_found", "detail": str}``.
    """
    try:
        root = find_repo_root()
    except FileNotFoundError as exc:
        return {
            "success": False,
            "reason": "annotations_root_not_found",
            "detail": str(exc),
        }
    base = root / "corpus"
    entries: list[dict[str, str]] = []
    for md in base.rglob("*.md"):
        if md.name.lower() == "readme.md":
            continue
        # Drafts are staging, not promoted annotations — never enumerate them.
        if md.name.endswith(".draft.md"):
            continue
        rel = md.relative_to(base).with_suffix("")
        entries.append(
            {
                "tutorial_path": str(rel).replace("\\", "/"),
                "annotation_path": str(md),
            }
        )
    entries.sort(key=lambda e: e["tutorial_path"])
    return {"success": True, "annotations": entries}


# ---------------------------------------------------------------------------
# assess_residuals — convergence-pattern classification.
# ---------------------------------------------------------------------------

# "Solving for Ux, Initial residual = 1.23e-04, Final residual = ..."
# OpenFOAM prints one of these per field per outer iteration. The value
# group also matches nan/inf (printed verbatim by OpenFOAM when a solve
# blows up) so the residual classifier sees the divergence instead of
# silently dropping those lines and reading the run as still-dropping.
_RESIDUAL_LINE = re.compile(
    r"Solving for (\S+),\s*Initial residual\s*=\s*([0-9.eE+\-]+|[-+]?nan|[-+]?inf),"
)
# "Time = 100" — outer iteration marker (steady solvers) or time (transient).
_TIME_LINE = re.compile(r"^Time = ([0-9.eE+\-]+)\s*$", re.MULTILINE)

# Match common solver log names. controlDict.application drives the name,
# but agents may produce idiosyncratic ones.
_LOG_GLOB_PATTERNS = ("log.simpleFoam", "log.pimpleFoam", "log.icoFoam",
                      "log.pisoFoam", "log.foamRun", "log.*Foam")


def _find_solver_log(case: Path, explicit: str | None) -> Path | None:
    """Locate the solver log file inside a case directory."""
    if explicit:
        candidate = Path(explicit) if Path(explicit).is_absolute() else case / explicit
        return candidate if candidate.is_file() else None
    for pattern in _LOG_GLOB_PATTERNS:
        matches = list(case.glob(pattern))
        # Skip the auxiliary logs like log.blockMesh / log.checkMesh.
        matches = [
            m for m in matches
            if m.name not in {"log.blockMesh", "log.checkMesh",
                              "log.decomposePar", "log.reconstructPar"}
        ]
        if matches:
            # If multiple solver logs (rare), use the most recently modified.
            return max(matches, key=lambda p: p.stat().st_mtime)
    return None


def _parse_residual_log(log_text: str) -> dict[str, list[float]]:
    """Pull per-field initial-residual histories out of a solver log."""
    histories: dict[str, list[float]] = {}
    for line in log_text.splitlines():
        m = _RESIDUAL_LINE.search(line)
        if m:
            field = m.group(1)
            try:
                value = float(m.group(2))
            except ValueError:
                continue
            histories.setdefault(field, []).append(value)
    return histories


def assess_residuals(
    case_path: str,
    threshold: float = 1e-5,
    window: int = 50,
    log_path: str | None = None,
    bands: ResidualThresholds | None = None,
) -> ToolResult:
    """Classify the convergence pattern of each field's residual history.

    Reads the solver log under ``case_path``, extracts per-field
    **initial residuals** (the value OpenFOAM prints as ``Initial
    residual = ...``), and classifies the last ``window`` iterations
    of each field as one of:

    - ``converged`` — last value and whole window ≤ threshold (good).
    - ``still_running`` — dropping but above threshold (acceptable).
    - ``stalled`` — low variance, above threshold (marginal).
    - ``oscillating`` — high variance, non-monotonic (marginal).
    - ``diverging`` — last ≥ 2x first over window (poor).
    - ``insufficient_data`` — fewer than 5 iterations recorded.

    Each classification carries a CFD-domain recommendation citing
    ``of_user_guide_urf`` / ``cfd_online`` / ``versteeg``.

    Args:
        case_path: Absolute path to the OpenFOAM case directory.
        threshold: Residual level taken to mean "converged" (default
            ``1e-5``, matching typical SIMPLE residualControl).
        window: How many trailing iterations to look at (default 50).
        log_path: Optional explicit log filename or absolute path.
            When omitted, the tool searches ``case_path`` for a
            ``log.<solver>`` matching common solver names.

    Returns:
        On success: ``{"success": True, "overall_verdict": str,
        "fields": [{...}], "log_path": str, "n_iterations":
        {field: int}, "citation_sources": {...}, "summary": str}``.
        ``fields`` is a list of per-field verdict dicts. Use
        ``summary`` directly as the ``why`` argument on
        ``openfoam.record_step``.

        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of ``"invalid_case_path"``,
        ``"solver_log_missing"``, ``"solver_log_empty"``,
        ``"no_residuals_found"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory.",
        }

    log_file = _find_solver_log(case, log_path)
    if log_file is None:
        return {
            "success": False,
            "reason": "solver_log_missing",
            "detail": (
                f"No solver log found in {case}. Run a solver first, "
                f"or pass an explicit ``log_path``."
            ),
        }

    log_text = log_file.read_text(errors="replace")
    if not log_text.strip():
        return {
            "success": False,
            "reason": "solver_log_empty",
            "detail": f"{log_file} is empty.",
        }

    histories = _parse_residual_log(log_text)
    if not histories:
        return {
            "success": False,
            "reason": "no_residuals_found",
            "detail": (
                f"{log_file} contains no 'Solving for <field>, Initial "
                f"residual = ...' lines. Is this actually a solver log?"
            ),
        }

    # Not part of the MCP surface an agent sees — it stays at the shipped
    # bands for every ordinary call, and exists so a study can move the
    # operating point without re-implementing the classifier.
    verdicts: list[ResidualVerdict] = [
        assess_residual_pattern(
            field, history, threshold, window,
            bands or DEFAULT_RESIDUAL_THRESHOLDS,
        )
        for field, history in sorted(histories.items())
    ]
    overall = aggregate_verdict(verdicts)

    parts: list[str] = [f"Convergence verdict: {overall}."]
    for v in verdicts:
        if v.verdict == "unknown":
            continue
        if v.last_value is None:
            continue
        parts.append(
            f"{v.field} {v.pattern} (last={v.last_value:.2e})."
        )
    summary = " ".join(parts)

    used_cites: set[str] = set()
    for v in verdicts:
        used_cites.update(v.cites)
    citation_sources = {k: CITATION_SOURCES[k] for k in sorted(used_cites)}

    return {
        "success": True,
        "case_path": str(case),
        "log_path": str(log_file),
        "overall_verdict": overall,
        "threshold": threshold,
        "window": window,
        "fields": [v.to_dict() for v in verdicts],
        "n_iterations": {f: len(h) for f, h in sorted(histories.items())},
        "citation_sources": citation_sources,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# assess_y_plus — wall-treatment + y+ band classification.
# ---------------------------------------------------------------------------

_YPLUS_DAT_HEADER = re.compile(r"^#\s*(?:Time\s+)?patch", re.IGNORECASE)
_YPLUS_DATA_LINE = re.compile(
    r"^\s*([0-9.eE+\-]+)\s+(\S+)\s+([0-9.eE+\-]+)\s+([0-9.eE+\-]+)\s+([0-9.eE+\-]+)"
)

# Read turbulenceProperties via simple regex — avoids pulling in a full
# OpenFOAM dict parser.
_RAS_MODEL = re.compile(r"^\s*(?:RASModel|model)\s+([A-Za-z][\w]*)\s*;", re.MULTILINE)
_LES_MODEL = re.compile(r"^\s*(?:LESModel|model)\s+([A-Za-z][\w]*)\s*;", re.MULTILINE)
_SIMTYPE = re.compile(
    r"^\s*simulationType\s+(\w+)\s*;", re.MULTILINE
)


def _read_turbulence_properties(case: Path) -> dict[str, str | None]:
    """Extract simulationType + model name from constant/turbulenceProperties."""
    tp = case / "constant" / "turbulenceProperties"
    if not tp.is_file():
        return {"simulation_type": None, "ras_model": None, "les_model": None}
    text = tp.read_text(errors="replace")
    st = _SIMTYPE.search(text)
    ras = _RAS_MODEL.search(text)
    les = _LES_MODEL.search(text)
    return {
        "simulation_type": st.group(1) if st else None,
        "ras_model": ras.group(1) if ras else None,
        "les_model": les.group(1) if les else None,
    }


def _parse_y_plus_dat(text: str) -> list[dict[str, Any]]:
    """Parse a postProcessing yPlus.dat file into per-patch records."""
    records: list[dict[str, Any]] = []
    last_time: float | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _YPLUS_DATA_LINE.match(line)
        if not m:
            continue
        try:
            last_time = float(m.group(1))
        except ValueError:
            last_time = None
        records.append(
            {
                "time": last_time,
                "patch": m.group(2),
                "y_plus_min": float(m.group(3)),
                "y_plus_max": float(m.group(4)),
                "y_plus_avg": float(m.group(5)),
            }
        )
    return records


def _find_latest_yplus_file(case: Path, time: str) -> Path | None:
    """Locate postProcessing/yPlus/<time>/yPlus.dat."""
    base = case / "postProcessing" / "yPlus"
    if not base.is_dir():
        return None
    if time == "latest":
        # Time-directory names parse as floats; this includes scientific
        # notation like "1e-05" / "2.5e-3" (common for small-deltaT
        # transient runs), which a digit-only check would wrongly reject.
        def _as_time(name: str) -> float | None:
            try:
                return float(name)
            except ValueError:
                return None

        timed = [
            (t, d)
            for d in base.iterdir()
            if d.is_dir() and (t := _as_time(d.name)) is not None
        ]
        if not timed:
            return None
        target_dir = max(timed, key=lambda pair: pair[0])[1]
    else:
        target_dir = base / time
        if not target_dir.is_dir():
            return None
    dat = target_dir / "yPlus.dat"
    return dat if dat.is_file() else None


def assess_y_plus(case_path: str, time: str = "latest") -> ToolResult:
    """Verdict on wall-patch y+ values against the turbulence-model assumption.

    Reads ``<case>/postProcessing/yPlus/<time>/yPlus.dat`` (produced
    by OpenFOAM's ``yPlus`` function object) and
    ``<case>/constant/turbulenceProperties`` to classify each wall
    patch's max y+ against the model's wall-treatment requirements:

    - Laminar: y+ does not apply.
    - High-Re wall function (k-epsilon family): need y+ ∈ [30, 300].
    - kOmegaSST (hybrid): best at y+ < 1, acceptable < 5.
    - Spalart-Allmaras / low-Re: y+ < 1 required.

    If yPlus.dat doesn't exist yet, returns ``reason="y_plus_data_missing"``
    with a hint: run ``<solver> -postProcess -func yPlus -time <time>``.
    This server intentionally does not invoke OpenFOAM itself.

    Args:
        case_path: Absolute path to the OpenFOAM case directory.
        time: Time directory name to read, or ``"latest"`` (default)
            to pick the highest numeric subdirectory under
            ``postProcessing/yPlus/``.

    Returns:
        On success: ``{"success": True, "overall_verdict": str,
        "model_class": str, "patches": [{...}],
        "citation_sources": {...}, "summary": str}``.

        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of ``"invalid_case_path"``,
        ``"y_plus_data_missing"``, ``"turbulence_properties_missing"``,
        ``"y_plus_data_empty"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory.",
        }

    tp = _read_turbulence_properties(case)
    if tp["simulation_type"] is None:
        return {
            "success": False,
            "reason": "turbulence_properties_missing",
            "detail": (
                f"Could not parse simulationType from "
                f"{case}/constant/turbulenceProperties."
            ),
        }

    model_class = classify_turbulence_model(
        tp["simulation_type"],
        ras_model=tp["ras_model"],
        les_model=tp["les_model"],
    )

    # Laminar — short-circuit; no y+ work to do.
    if model_class == "laminar":
        return {
            "success": True,
            "case_path": str(case),
            "model_class": model_class,
            "overall_verdict": "unknown",
            "patches": [],
            "citation_sources": {},
            "summary": (
                "Laminar simulation — y+ check does not apply (no "
                "turbulent boundary layer to characterise)."
            ),
            "simulation_type": tp["simulation_type"],
            "model_name": tp["ras_model"] or tp["les_model"],
        }

    y_plus_file = _find_latest_yplus_file(case, time)
    if y_plus_file is None:
        return {
            "success": False,
            "reason": "y_plus_data_missing",
            "detail": (
                f"No yPlus.dat found under {case}/postProcessing/yPlus/. "
                f"Run the yPlus function object first, e.g. "
                f"``<solver> -postProcess -func yPlus -time {time}``."
            ),
        }

    text = y_plus_file.read_text(errors="replace")
    records = _parse_y_plus_dat(text)
    if not records:
        return {
            "success": False,
            "reason": "y_plus_data_empty",
            "detail": (
                f"{y_plus_file} had no parseable patch rows."
            ),
        }

    verdicts: list[YPlusVerdict] = [
        _assess_y_plus_band(
            patch=r["patch"],
            y_plus_min=r["y_plus_min"],
            y_plus_max=r["y_plus_max"],
            y_plus_avg=r["y_plus_avg"],
            model_class=model_class,
        )
        for r in records
    ]
    overall = aggregate_verdict(verdicts)

    parts: list[str] = [
        f"y+ verdict: {overall} (model class: {model_class}, model: "
        f"{tp['ras_model'] or tp['les_model']})."
    ]
    for v in verdicts:
        if v.y_plus_max is not None:
            parts.append(
                f"{v.patch}: max y+ = {v.y_plus_max:.2g} → {v.verdict} ({v.band})."
            )
    summary = " ".join(parts)

    used_cites: set[str] = set()
    for v in verdicts:
        used_cites.update(v.cites)
    citation_sources = {k: CITATION_SOURCES[k] for k in sorted(used_cites)}

    return {
        "success": True,
        "case_path": str(case),
        "y_plus_path": str(y_plus_file),
        "simulation_type": tp["simulation_type"],
        "model_name": tp["ras_model"] or tp["les_model"],
        "model_class": model_class,
        "overall_verdict": overall,
        "patches": [v.to_dict() for v in verdicts],
        "citation_sources": citation_sources,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Draft annotation from a case's REPORT.md.
#
# The agent runs a case end-to-end and narrates each decision via
# openfoam.record_step, which writes a per-step entry carrying the full
# consultant schema (decision / why / alternatives / when-it-breaks +
# citations). This tool reads those entries directly — not the compact
# Decisions index at the bottom of REPORT.md — so the drafted annotation
# captures the full reasoning regardless of how the report is summarised
# for human reading. The human then reviews the draft, edits it (adding
# citations, experience-based comments, generalising scenario-specific
# language to tutorial-template language), and promotes it into the
# corpus by removing the ``.draft`` suffix.

# Gap sentinels — must match the strings openfoam.record_step renders, so
# a field left empty in the run round-trips into the draft as a visible
# gap rather than silently vanishing.
_GAP_WHY = "_uncited choice — no annotation, reference, or paper cited._"
_GAP_ALTS = "_no alternatives surfaced._"
_GAP_BREAKS = "_failure modes not characterized._"

# Mirror of the record_step entry shape: `## [HH:MM:SS] phase / status —
# title` headers, then `- **Field:** value` lines (which live inside a
# <details> block in the rendered report, but parse the same line-by-line).
_ENTRY_HEADER_RE = re.compile(
    r"^##\s+\[(?P<ts>\d{2}:\d{2}:\d{2})\]"
    r"\s+(?P<phase>[^/]+?)"
    r"\s+/\s+(?P<status>[^—]+?)"
    r"\s+—\s+(?P<title>.+?)"
    r"(?:\s+\*\*\[PENDING REVIEW\]\*\*)?$"
)
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


def _parse_report_entries(report_text: str) -> list[dict[str, str]]:
    """Extract decision entries from REPORT.md's per-step narration.

    Returns one dict per entry that carried at least one consultant field.
    Info-only entries are skipped. The compact Decisions index and verdict
    banner are ignored (their lines match neither the header nor the field
    regex).
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

    for line in report_text.splitlines():
        header_m = _ENTRY_HEADER_RE.match(line)
        if header_m:
            commit(current)
            current = {
                "phase": header_m.group("phase").strip(),
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
        if key == "why":
            cite_m = _INLINE_CITES_RE.search(value)
            if cite_m:
                current["citations"] = cite_m.group(1).strip()
                value = _INLINE_CITES_RE.sub("", value).rstrip()
        current[key] = value

    commit(current)
    return entries


def _escape_cell(s: str) -> str:
    """Make a string safe for a single markdown-table cell."""
    return s.replace("|", "\\|").replace("\n", "; ").strip()


def _annotation_table_from_entries(
    entries: list[dict[str, str]],
) -> tuple[str, int]:
    """Build the annotation-form table from parsed report entries.

    Columns are the corpus annotation shape documented in
    ``corpus/README.md``: ``Choice | Decision | Why | Alternatives |
    When it breaks``. Citations fold into the Why cell; fields left empty
    in the run render as visible gap sentinels. Returns
    ``(table_markdown, n_rows)``.
    """
    if not entries:
        return "", 0
    rows = [
        "| Choice | Decision | Why | Alternatives | When it breaks |",
        "|---|---|---|---|---|",
    ]
    for e in entries:
        why_cell = _escape_cell(e["why"]) or _escape_cell(_GAP_WHY)
        if e["citations"]:
            why_cell = f"{why_cell} _(cites: {_escape_cell(e['citations'])})_"
        alts_cell = _escape_cell(e["alternatives"]) or _escape_cell(_GAP_ALTS)
        breaks_cell = _escape_cell(e["when_it_breaks"]) or _escape_cell(_GAP_BREAKS)
        rows.append(
            f"| {_escape_cell(e['phase'])} "
            f"| {_escape_cell(e['decision'])} "
            f"| {why_cell} "
            f"| {alts_cell} "
            f"| {breaks_cell} |"
        )
    return "\n".join(rows), len(entries)


def _yaml_scalar(value: str | None, placeholder: str) -> str:
    """A YAML-safe double-quoted scalar — the supplied value, or a placeholder.

    Uses ``json.dumps`` so colons/quotes inside the value can't break the
    frontmatter (a plain ``key: <fill in: x>`` would be invalid YAML).
    """
    return json.dumps(value) if value else json.dumps(placeholder)


def _yaml_list(values: list[str] | None, placeholder: str) -> str:
    """Render a YAML block list — supplied items, or a single placeholder."""
    items = [v for v in (values or []) if v]
    if not items:
        items = [placeholder]
    return "".join(f"  - {json.dumps(v)}\n" for v in items)


def _validated_setup_section(
    validated_setup: list[str] | None, entries: list[dict[str, str]]
) -> str:
    """The recipe a later run should start from, above the chronological table.

    The decision table is chronological, so a first attempt (e.g. a coarse
    grid that later failed) appears before the fix that passed; a reader in
    a hurry, or a small model, takes the first row. This section states the
    final, validated choices up front: as supplied by the agent that ran the
    case, else the last recorded decision for each phase.
    """
    items = [v for v in (validated_setup or []) if v and v.strip()]
    source = "as recorded by the run"
    if not items:
        last: dict[str, str] = {}
        for e in entries:
            if e.get("decision", "").strip():
                last[e["phase"]] = e["decision"].strip()
        items = [f"{phase}: {dec}" for phase, dec in last.items()]
        source = "last recorded decision per phase (auto-derived; confirm on review)"
    if not items:
        return ""
    lines = "".join(f"- {_escape_cell(i)}\n" for i in items)
    return (f"## Validated setup (start here)\n\n"
            f"The final choices that passed validation, {source}. Later rows of the "
            f"table below explain how each was reached.\n\n{lines}\n")


def _render_draft_annotation(
    tutorial_path: str,
    case_path: str,
    table_markdown: str,
    *,
    solver: str | None = None,
    physics: str | None = None,
    geometry: str | None = None,
    suitable_for: list[str] | None = None,
    not_suitable_for: list[str] | None = None,
    references: list[str] | None = None,
    validated_setup: list[str] | None = None,
    entries: list[dict[str, str]] | None = None,
) -> str:
    """Render the .draft.md content for promotion review.

    Frontmatter fields the agent supplies (it ran the case and knows them)
    are written in; the rest stay as quoted ``<fill in: ...>`` placeholders
    for the human. All values are emitted YAML-safely.
    """
    return (
        f"---\n"
        f"tutorial_path: {tutorial_path}\n"
        f"solver: {_yaml_scalar(solver, '<fill in: solver name (e.g. simpleFoam, icoFoam)>')}\n"
        f"physics: {_yaml_scalar(physics, '<fill in: regime, steady/transient, turbulence, Re or other dimensionless number>')}\n"
        f"geometry: {_yaml_scalar(geometry, '<fill in: one-line geometry summary>')}\n"
        f"suitable_for_template:\n"
        f"{_yaml_list(suitable_for, '<fill in (agent-proposed, confirm): when this tutorial is a good structural starting point>')}"
        f"not_suitable_for:\n"
        f"{_yaml_list(not_suitable_for, '<fill in (agent-proposed, confirm): when this tutorial is the wrong choice>')}"
        f"references:\n"
        f"{_yaml_list(references, '<fill in: paper or doc citation>')}"
        f"derived_from: {case_path}\n"
        f"draft_status: |\n"
        f"  Auto-generated by consultant.draft_annotation_from_report.\n"
        f"  The agent filled the metadata it knows from the run; on review,\n"
        f"  confirm the suitable_for / not_suitable_for proposals, generalise\n"
        f"  scenario-specific language to tutorial-template language, and add\n"
        f"  any missing citations. Promote by renaming this file to remove\n"
        f"  the .draft suffix.\n"
        f"---\n"
        f"\n"
        f"# `{tutorial_path}`\n"
        f"\n"
        f"<One-paragraph framing — what this tutorial is and what role "
        f"it plays as a template. Replace this line.>\n"
        f"\n"
        f"{_validated_setup_section(validated_setup, entries or [])}"
        f"## Decisions, in the order they were made\n"
        f"\n"
        f"{table_markdown}\n"
        f"\n"
        f"## Notes\n"
        f"\n"
        f"<Add experience-based commentary, edge cases, scenario-specific "
        f"guidance, links to related annotations.>\n"
    )


def draft_annotation_from_report(
    case_path: str,
    tutorial_path: str,
    overwrite: bool = False,
    corpus_subpath: str | None = None,
    solver: str | None = None,
    physics: str | None = None,
    geometry: str | None = None,
    suitable_for: list[str] | None = None,
    not_suitable_for: list[str] | None = None,
    references: list[str] | None = None,
    validated_setup: list[str] | None = None,
) -> ToolResult:
    """Draft a candidate tutorial annotation from a case's REPORT.md.

    Parses the per-step decision entries in ``<case_path>/REPORT.md``
    (the full decision / why / alternatives / when-it-breaks + citations
    that ``record_step`` records, not the compact bottom index) and
    writes a candidate annotation file as a ``.draft.md`` sibling of the
    live annotation path. Works straight off the narration — no
    ``finalize_report`` required first.

    You ran the case, so fill the frontmatter you know via the optional
    args below rather than leaving the human a blank scaffold: pass
    ``solver`` / ``physics`` / ``geometry`` (facts from the run),
    ``references`` (curated paper/doc citations), and your *proposed*
    ``suitable_for`` / ``not_suitable_for`` (generalised from your
    when-it-breaks reasoning — these are written with a "confirm" marker
    so the reviewer knows to check them). Any field you omit stays a
    ``<fill in: ...>`` placeholder. The human then confirms the
    proposals, generalises scenario-specific language to
    tutorial-template language, and promotes by renaming
    ``<name>.draft.md`` → ``<name>.md``.

    The draft path is constructed as
    ``<repo>/corpus/<tutorial_path>.draft.md`` by default. Pass
    ``corpus_subpath`` to file the draft elsewhere — e.g. under a
    case-family subfolder keyed by experiment — while ``tutorial_path``
    stays the real template recorded in the frontmatter. This decouples
    *where the entry lives* from *which tutorial it derived from*, which
    matters when several experiments share one template (a
    one-file-per-tutorial layout would otherwise collide). The
    ``.draft.md`` suffix means ``get_tutorial_annotation`` will not pick
    it up (it looks for ``<name>.md`` exactly), so partial work in the
    corpus directory is safe.

    Args:
        case_path: Absolute path to a case directory containing
            ``REPORT.md`` with at least one decision entry.
        tutorial_path: Path under ``$FOAM_TUTORIALS`` this case derived
            from, e.g. ``"incompressible/icoFoam/cavity/cavity"``.
            Determines where the draft is written.
        overwrite: When ``False`` (default), refuse to overwrite an
            existing draft. Set ``True`` to replace it.
        corpus_subpath: Optional path under ``corpus/`` (without the
            ``.md`` suffix) that overrides where the draft is written —
            e.g. ``"compressible/rhoCentralFoam/supersonic-half-cones/
            structured-body-fitted"`` to file an entry by experiment
            under a family subfolder. When omitted, the draft is filed at
            ``tutorial_path`` as before. ``tutorial_path`` is unaffected
            either way: it is the template recorded in the frontmatter.
        solver: One-line solver descriptor (e.g. the application used and
            any steady/transient swap). Generalise to the tutorial, not
            the specific run.
        physics: One-line regime descriptor (incompressible/compressible,
            steady/transient, turbulence, the Re/Ma range it's valid for).
        geometry: One-line geometry summary.
        suitable_for: List of conditions under which this tutorial is a
            good structural starting point (your proposal, for review).
        not_suitable_for: List of conditions under which it is the wrong
            choice (your proposal, for review).
        references: Curated list of paper/doc citations for the frontmatter.
        validated_setup: The final, validated setup as a short recipe a
            later run should start from, one item per choice (which
            tutorial each dictionary came from, mesh, key controls, the fix
            for each failure). Rendered as "Validated setup (start here)"
            above the chronological decision table; if omitted, the last
            recorded decision per phase is used.

    Returns:
        On success: ``{"success": True, "draft_path": str,
        "n_decisions": int, "annotation_exists": bool}``.
        ``annotation_exists`` is True when a live annotation already
        exists at the same tutorial_path — the draft is still written
        as a parallel file, so the human can merge if appropriate.
        On failure: ``{"success": False, "reason": str, "detail": str}``.
        ``reason`` is one of ``"invalid_case_path"``, ``"report_not_found"``,
        ``"invalid_tutorial_path"``, ``"invalid_corpus_subpath"``,
        ``"no_decisions_found"``, ``"draft_already_exists"``,
        ``"root_not_found"``, ``"write_failed"``.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory",
        }

    report = case / "REPORT.md"
    if not report.is_file():
        return {
            "success": False,
            "reason": "report_not_found",
            "detail": (
                f"No REPORT.md at {report}. Run the case and let "
                f"the agent narrate decisions via record_step first."
            ),
        }

    tutorial_clean = tutorial_path.strip().strip("/")
    if not tutorial_clean:
        return {
            "success": False,
            "reason": "invalid_tutorial_path",
            "detail": "tutorial_path must be a non-empty string",
        }

    # Where the draft is filed. Defaults to tutorial_clean (one file per
    # tutorial); corpus_subpath overrides it so a case family can be filed
    # by experiment while tutorial_clean stays the template in frontmatter.
    if corpus_subpath is not None:
        location_key = corpus_subpath.strip().strip("/")
        for suffix in (".draft.md", ".md"):
            if location_key.endswith(suffix):
                location_key = location_key[: -len(suffix)]
                break
        if not location_key or ".." in location_key.split("/"):
            return {
                "success": False,
                "reason": "invalid_corpus_subpath",
                "detail": (
                    "corpus_subpath must be a non-empty path under corpus/ "
                    "with no '..' segments, e.g. 'compressible/rhoCentralFoam/"
                    "supersonic-half-cones/structured-body-fitted'"
                ),
            }
    else:
        location_key = tutorial_clean

    report_text = report.read_text(encoding="utf-8", errors="replace")
    entries = _parse_report_entries(report_text)
    if not entries:
        return {
            "success": False,
            "reason": "no_decisions_found",
            "detail": (
                "REPORT.md has no decision entries to draft from — no "
                "record_step call filled the consultant-schema fields "
                "(decision / why / alternatives / when-it-breaks). Run the "
                "case again with decision narration."
            ),
        }

    table_markdown, n_decisions = _annotation_table_from_entries(entries)

    try:
        repo_root = find_repo_root()
    except FileNotFoundError as exc:
        return {
            "success": False,
            "reason": "root_not_found",
            "detail": str(exc),
        }

    live_path = annotation_path_for(location_key, root=repo_root)
    annotation_exists = live_path.is_file()
    draft_path = live_path.with_name(live_path.stem + ".draft.md")

    if draft_path.exists() and not overwrite:
        return {
            "success": False,
            "reason": "draft_already_exists",
            "detail": (
                f"{draft_path} already exists. Pass overwrite=True to "
                f"replace it, or rename/remove the existing draft first."
            ),
        }

    draft_text = _render_draft_annotation(
        tutorial_path=tutorial_clean,
        case_path=str(case),
        table_markdown=table_markdown,
        solver=solver,
        physics=physics,
        geometry=geometry,
        suitable_for=suitable_for,
        not_suitable_for=not_suitable_for,
        references=references,
        validated_setup=validated_setup,
        entries=entries,
    )

    try:
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(draft_text, encoding="utf-8")
    except OSError as exc:
        return {
            "success": False,
            "reason": "write_failed",
            "detail": f"{type(exc).__name__}: {exc}",
        }

    return {
        "success": True,
        "draft_path": str(draft_path),
        "n_decisions": n_decisions,
        "annotation_exists": annotation_exists,
    }


# ---------------------------------------------------------------------------
# flag_uncited_claims — end-of-run integrity audit.
# ---------------------------------------------------------------------------

# Appeals to outside authority that name no source. A claim carrying one of
# these but no citation must become a first-principles derivation or get a real
# citation added to corpus/references/.
_AUTHORITY_RE = re.compile(
    r"\bthe literature\b|\bstudies (?:show|have shown|find|suggest)\b"
    r"|\bit is (?:well[- ]?)?known\b|\bwell[- ]?known\b|\bwell[- ]?established\b"
    r"|\bcommonly (?:cited|used|accepted|reported)\b|\bgenerally (?:accepted|the case)\b"
    r"|\bas is standard\b|\bthe standard value\b|\brule of thumb\b|\bempirically\b"
    r"|\bknown from .{0,40}?literature\b|\bfrom (?:training|memory|recall)\b"
    r"|\b(?:typically|usually) (?:around|about|~)\b",
    re.IGNORECASE,
)

# Regime-boundary words that, paired with a number, are almost always an
# external result (a transition / critical value), not a run observation.
_REGIME_RE = re.compile(
    r"\bHopf\b|\bbifurcation\b|\btransition(?:s|al|ed)?\b|\bcritical\s+Re(?:ynolds)?\b"
    r"|\bonset\b|\blaminar[\s-].{0,8}?turbulent\b|\bbecomes?\s+(?:un)?steady\b"
    r"|\bloses?\s+steadiness\b",
    re.IGNORECASE,
)

# Honest admissions that a *claim* is uncited; under the no-uncited rule these
# must be resolved (derive or cite), not left in place. Kept narrow on purpose:
# bare words like "unsourced" / "no published benchmark" also appear in
# legitimate meta-discussion that *warns against* using an unsourced value, so
# they are not treated as self-admissions. The bare word "uncited" is excluded
# for the same reason: it is the gap sentinel record_step renders for an empty
# consultant field ("_uncited choice_") and shows up in contrastive prose
# ("cited to a prior run, not uncited") — neither is a claim. The phrase forms
# below still catch a genuine admission ("no citation", "not tied to a
# citation", "citation needed").
_SELF_ADMIT_RE = re.compile(
    r"\bno (?:specific )?citation\b"
    r"|\bnot (?:yet )?(?:tied to|backed by)[^.]{0,40}?citation\b"
    r"|\bcitation needed\b",
    re.IGNORECASE,
)

_HAS_NUMBER_RE = re.compile(r"\d")
_INLINE_CITE_MARKER_RE = re.compile(r"_\(cites:|\[\[|https?://", re.IGNORECASE)
# Author-year citation, e.g. "Ghia, Ghia & Shin (1982)" — used for the orphan
# check. The surname is anchored to a word boundary (so a camelCase fragment
# inside a solver/tool name — the "Foam" in icoFoam/simpleFoam/OpenFOAM — is
# not read as an author), the year must be PARENTHESISED, and only further
# author tokens (capitalised names, "&", ",", "and", "et al.") may sit between
# the surname and the year. That last rule stops an ordinary capitalised prose
# word ("Accept the ... vs Ghia (1982)") from being mis-read as the author when
# a real citation's year sits later in the same line/field — the surname picked
# is the one actually adjacent to the year.
_AUTHOR_YEAR_RE = re.compile(
    r"\b([A-Z][a-zA-Z]+)"
    r"(?:[,&]?\s+(?:[A-Z][a-zA-Z]+|et\s+al\.?|and|&))*"
    r"\s*\(((?:1[89]|20)\d\d)\)"
)

_AUDIT_NOTE = (
    "Heuristic lint, not a correctness judge: it surfaces candidate uncited "
    "claims for you to resolve — by a first-principles derivation or a real "
    "citation added to corpus/references/. False positives are expected; "
    "review each."
)
_AUDIT_FIX = (
    "Derive it from first principles, or cite a source and add that source to "
    "corpus/references/manifest.json."
)
_ORPHAN_FIX = (
    "Citation does not resolve to a corpus/references/ entry — add the source "
    "to corpus/references/manifest.json, or correct the citation."
)


def _load_reference_index() -> dict[str, Any] | None:
    """Catalogue of corpus/references/manifest.json: tags + lowercased blobs.

    Returns None when the repo root or the manifest can't be found, in which
    case the orphan-citation check is skipped (reported, not silently passed).
    """
    try:
        root = find_repo_root()
    except FileNotFoundError:
        return None
    manifest = root / "corpus" / "references" / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sources = data.get("sources", [])
    return {
        "tags": {s["consultant_tag"] for s in sources if s.get("consultant_tag")},
        "blobs": [json.dumps(s).lower() for s in sources],
    }


def _orphan_citations(citations_text: str, index: dict[str, Any] | None) -> list[str]:
    """Author-year citations in the text that don't resolve to the library."""
    if index is None or not citations_text.strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _AUTHOR_YEAR_RE.finditer(citations_text):
        surname, year = m.group(1).lower(), m.group(2)
        key = f"{surname} {year}"
        if key in seen:
            continue
        seen.add(key)
        if any(year in blob and surname in blob for blob in index["blobs"]):
            continue
        out.append(f"{m.group(1)} {year}")
    return out


def _regime_claim_with_number(text: str) -> bool:
    """True when a regime-boundary word sits within a few words of a number.

    Requiring the digit NEAR the regime keyword (not merely somewhere in the
    same entry) keeps real external boundaries — "transitions at Re 8000",
    "Hopf bifurcation near Re 7500" — while sparing the blessed first-principles
    form where an unrelated number (a mesh size, "Re=400" in the decision line)
    shares the entry with a number-free derivation ("a steady solve stalls once
    the cavity becomes time-periodic above a critical Reynolds number").
    """
    for m in _REGIME_RE.finditer(text):
        if _HAS_NUMBER_RE.search(text[max(0, m.start() - 25) : m.end() + 25]):
            return True
    return False


def _signals_for(text: str, has_citation: bool) -> list[str]:
    sigs: list[str] = []
    if _SELF_ADMIT_RE.search(text):
        sigs.append("self_admitted_uncited")
    if not has_citation:
        if _AUTHORITY_RE.search(text):
            sigs.append("authority_appeal")
        if _regime_claim_with_number(text):
            sigs.append("regime_claim")
    return sigs


def flag_uncited_claims(case_path: str, markdown_path: str | None = None) -> ToolResult:
    """Audit a REPORT.md (or a corpus entry) for uncited factual claims.

    The end-of-run integrity check. Two heuristic passes — it SURFACES
    candidates, it does not judge correctness:

    1. **Uncited assertion** — a decision entry (or line) appeals to outside
       authority ("the literature", "well-known"), states a regime boundary
       with a number (Hopf / transition / critical Re), or admits it is
       uncited, while carrying NO citation. Resolve by deriving from first
       principles or adding a real citation to ``corpus/references/``.
    2. **Orphan citation** — a citation names an external source (Author YYYY)
       that does not resolve to a ``corpus/references/`` manifest entry.
       Resolve by adding the source to the library.

    Run after ``finalize_report``. Default target is ``<case_path>/REPORT.md``;
    pass ``markdown_path`` (case-relative or absolute) to audit a corpus entry.

    Returns ``{"success": True, "target", "mode", "n_units", "flags",
    "orphan_citations", "n_flags", "verdict", "reference_library", "note"}`` or
    ``{"success": False, "reason": "target_not_found", "detail"}``.
    """
    case = Path(case_path)
    if markdown_path:
        target = Path(markdown_path)
        if not target.is_absolute():
            target = case / markdown_path
    else:
        target = case / "REPORT.md"
    if not target.is_file():
        return {
            "success": False,
            "reason": "target_not_found",
            "detail": f"No markdown to audit at {target}.",
        }

    text = target.read_text(encoding="utf-8", errors="replace")
    index = _load_reference_index()
    flags: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []

    entries = _parse_report_entries(text)
    if entries:
        mode = "entries"
        n_units = len(entries)
        for e in entries:
            body = " ".join(
                e.get(k, "")
                for k in ("decision", "why", "alternatives", "when_it_breaks")
            )
            has_cite = bool(e.get("citations", "").strip())
            sigs = _signals_for(body, has_cite)
            if sigs:
                flags.append({
                    "where": e.get("title") or e.get("phase", ""),
                    "phase": e.get("phase", ""),
                    "signals": sigs,
                    "snippet": body[:200],
                    "has_citation": has_cite,
                    "recommendation": _AUDIT_FIX,
                })
            for orphan in _orphan_citations(e.get("citations", ""), index):
                orphans.append({
                    "where": e.get("title") or e.get("phase", ""),
                    "citation": orphan,
                    "recommendation": _ORPHAN_FIX,
                })
    else:
        mode = "lines"
        n_units = 0
        for i, raw in enumerate(text.splitlines(), 1):
            s = raw.strip()
            if not s or s.startswith("#") or set(s) <= set("|-: "):
                continue
            n_units += 1
            has_cite = bool(_INLINE_CITE_MARKER_RE.search(s))
            sigs = _signals_for(s, has_cite)
            if sigs:
                flags.append({
                    "where": f"line {i}",
                    "signals": sigs,
                    "snippet": s[:200],
                    "has_citation": has_cite,
                    "recommendation": _AUDIT_FIX,
                })
            if has_cite:
                for orphan in _orphan_citations(s, index):
                    orphans.append({
                        "where": f"line {i}",
                        "citation": orphan,
                        "recommendation": _ORPHAN_FIX,
                    })

    n_flags = len(flags) + len(orphans)
    return {
        "success": True,
        "target": str(target),
        "mode": mode,
        "n_units": n_units,
        "flags": flags,
        "orphan_citations": orphans,
        "n_flags": n_flags,
        "verdict": "clean" if n_flags == 0 else f"{n_flags} item(s) to resolve",
        "reference_library": (
            "present" if index is not None else "missing (orphan check skipped)"
        ),
        "note": _AUDIT_NOTE,
    }
