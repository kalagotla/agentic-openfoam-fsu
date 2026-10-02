"""Tool implementations for the Validation MCP server.

Same rules as the OpenFOAM server (see ``docs/architecture.md``):

1. Every tool returns ``{"success": bool, ...}``. Never raise.
2. Data arrays are summarized, not dumped. No raw field returns.
3. Docstrings are the agent's documentation — keep them tight.
4. **Nothing physics-specific.** Tools here must be case-agnostic. If a
   tool's docstring needs to name a flow type or geometry to be
   intelligible (e.g. "reattachment length", "Strouhal number"), it
   belongs in the agent's inline reasoning, not here.
"""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

try:
    import resource  # POSIX only; used to cap the analysis subprocess.
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None  # type: ignore[assignment]

from validation_mcp.reference_data import (
    MalformedReferenceError,
    ReferenceNotFoundError,
    discover_references,
    read_reference_json,
)

ToolResult = dict[str, Any]

# Default tolerance (fraction of reference value range) used by
# ``compare_profiles`` when the caller doesn't specify one. 5% is the
# standard acceptance threshold for benchmark comparisons.
_DEFAULT_PROFILE_TOL_FRACTION = 0.05


def list_references() -> ToolResult:
    """List all reference datasets discoverable under ``cases/*/reference/``.

    Reference data is just JSON files dropped into the right directory; no
    registration step is needed. Each JSON file's basename (without the
    ``.json`` extension) is the reference name the agent passes to
    ``read_reference``.

    Returns:
        ``{"success": True, "references": [{"name": str, "case": str,
        "path": str}, ...]}``. Sorted by case then name.
    """
    entries = discover_references()
    return {
        "success": True,
        "references": [
            {"name": e.name, "case": e.case, "path": str(e.path)}
            for e in entries
        ],
    }


def read_reference(name: str) -> ToolResult:
    """Read a reference dataset by name.

    The reference name is the JSON file's basename, e.g.
    ``"reattachment_length"`` for ``cases/examples/pitz-daily/reference/reattachment_length.json``
    or ``"ghia_1982"`` for ``cases/lid-cavity/reference/ghia_1982.json``.
    The returned ``data`` is whatever JSON shape the file uses — the agent
    is responsible for understanding it (citations and units are typically
    embedded in the JSON, by convention).

    Args:
        name: Reference name (filename stem). Use ``list_references`` to
            discover available names.

    Returns:
        ``{"success": True, "name": str, "case": str, "path": str,
        "data": ...}`` on success. ``data`` is the full parsed JSON.

        ``{"success": False, "reason": str, "available": [...]}`` if the
        name is not found.
    """
    try:
        data = read_reference_json(name)
    except ReferenceNotFoundError as exc:
        return {
            "success": False,
            "reason": str(exc),
            "available": sorted({e.name for e in discover_references()}),
        }
    except MalformedReferenceError as exc:
        return {
            "success": False,
            "reason": "malformed_reference_json",
            "detail": str(exc),
        }

    # Find the entry again to populate metadata. Cheap relative to JSON load.
    entries = [e for e in discover_references() if e.name == name]
    entry = entries[0] if entries else None

    return {
        "success": True,
        "name": name,
        "case": entry.case if entry else None,
        "path": str(entry.path) if entry else None,
        "data": data,
    }


def compare_profiles(
    sim_axis: list[float],
    sim_field: list[float],
    ref_axis: list[float],
    ref_field: list[float],
    tolerance: float | None = None,
) -> ToolResult:
    """Compare a simulated profile to a reference profile on a shared axis.

    Takes raw arrays — no knowledge of what the axis or field represents.
    Linearly interpolates the simulation onto the reference's axis points
    over the overlap window, computes L2 and L_inf errors of the difference,
    and reports whether the L2 is below the tolerance (default: 5% of the
    reference's value range, the standard benchmark threshold).

    Args:
        sim_axis: Independent variable values from the simulation
            (e.g. y-coordinates of a velocity-profile sample).
        sim_field: Field values from the simulation, same length as
            ``sim_axis``.
        ref_axis: Independent variable values from the reference dataset.
        ref_field: Field values from the reference, same length as
            ``ref_axis``.
        tolerance: Absolute L2 threshold below which the comparison is
            judged "within tolerance". If omitted, defaults to 5% of the
            reference value range over the overlap window. Pass an explicit
            value if you want the threshold relative to something else
            (e.g. the lid velocity in a cavity case).

    Returns:
        ``{"success": True, "l2_error": float, "linf_error": float,
        "tolerance_threshold": float, "within_tolerance": bool,
        "n_compared": int, "reference_range": float}``.

        ``{"success": False, "reason": str}`` on shape mismatch, too few
        points, NaN/Inf in the simulation, or no axis overlap.
    """
    sim_x = np.asarray(sim_axis, dtype=float)
    sim_y = np.asarray(sim_field, dtype=float)
    ref_x = np.asarray(ref_axis, dtype=float)
    ref_y = np.asarray(ref_field, dtype=float)

    if sim_x.shape != sim_y.shape or ref_x.shape != ref_y.shape:
        return {"success": False, "reason": "shape_mismatch_within_one_side"}
    if sim_x.size < 2 or ref_x.size < 2:
        return {"success": False, "reason": "too_few_points"}
    if not np.all(np.isfinite(sim_y)):
        return {"success": False, "reason": "nan_or_inf_in_simulation"}

    sim_order = np.argsort(sim_x)
    sim_x, sim_y = sim_x[sim_order], sim_y[sim_order]
    ref_order = np.argsort(ref_x)
    ref_x, ref_y = ref_x[ref_order], ref_y[ref_order]

    x_lo = max(sim_x[0], ref_x[0])
    x_hi = min(sim_x[-1], ref_x[-1])
    mask = (ref_x >= x_lo) & (ref_x <= x_hi)
    if mask.sum() < 2:
        return {
            "success": False,
            "reason": "no_overlap_in_axis",
            "sim_range": [float(sim_x[0]), float(sim_x[-1])],
            "ref_range": [float(ref_x[0]), float(ref_x[-1])],
        }

    ref_x_o, ref_y_o = ref_x[mask], ref_y[mask]
    sim_y_at_ref = np.interp(ref_x_o, sim_x, sim_y)

    diff = sim_y_at_ref - ref_y_o
    ref_range = float(ref_y_o.max() - ref_y_o.min())
    if ref_range <= 0:
        ref_range = max(float(np.abs(ref_y_o).max()), 1.0)

    l2 = float(np.sqrt(np.mean(diff**2)))
    linf = float(np.max(np.abs(diff)))
    threshold = (
        float(tolerance)
        if tolerance is not None
        else _DEFAULT_PROFILE_TOL_FRACTION * ref_range
    )

    return {
        "success": True,
        "l2_error": l2,
        "linf_error": linf,
        "tolerance_threshold": threshold,
        "within_tolerance": l2 < threshold,
        "n_compared": int(mask.sum()),
        "reference_range": ref_range,
    }


# Default relative tolerance for compare_scalar — 5%, matching the profile
# default and the coefficient bands the example scenarios declare.
_DEFAULT_SCALAR_TOL_RELATIVE = 0.05
# Below this |ref|, a relative error is meaningless; the tool refuses rather
# than misgrade, and asks for an absolute tolerance instead.
_SCALAR_ZERO_EPS = 1e-12


def compare_scalar(
    sim_value: float,
    ref_value: float,
    tolerance_relative: float | None = None,
    tolerance_absolute: float | None = None,
) -> ToolResult:
    """Compare a single simulated scalar against a reference scalar.

    The companion to ``compare_profiles`` for coefficient-style validation —
    one lift/drag coefficient, a reattachment length, a peak value — where
    there is no profile to interpolate. ``compare_profiles`` needs >= 2 points
    per side and rejects a lone scalar with ``too_few_points``; routing such a
    metric through this tool keeps the pass/fail on tested code instead of the
    agent's own inline arithmetic.

    By default the verdict is the relative error ``|sim - ref| / |ref|`` against
    ``tolerance_relative`` (default 0.05 = 5%). To compare the raw difference
    instead (or when the reference is ~0, where a relative error is undefined),
    pass ``tolerance_absolute``; it takes precedence and the verdict becomes
    ``|sim - ref| <= tolerance_absolute``.

    Args:
        sim_value: The simulated scalar.
        ref_value: The reference scalar.
        tolerance_relative: Relative-error threshold (fraction). Default 0.05.
            Ignored when ``tolerance_absolute`` is given.
        tolerance_absolute: Absolute-difference threshold. When set, the verdict
            is absolute, not relative.

    Returns:
        ``{"success": True, "abs_error": float, "rel_error": float | None,
        "tolerance": float, "tolerance_basis": "relative" | "absolute",
        "within_tolerance": bool}``.

        ``{"success": False, "reason": str, ...}`` on non-numeric / non-finite
        input, or ``reason="reference_near_zero"`` when a relative comparison is
        requested against a reference of ~0 (pass ``tolerance_absolute``).
    """
    try:
        sim = float(sim_value)
        ref = float(ref_value)
    except (TypeError, ValueError):
        return {"success": False, "reason": "non_numeric_input"}
    if not (math.isfinite(sim) and math.isfinite(ref)):
        return {"success": False, "reason": "nan_or_inf_input"}

    abs_error = abs(sim - ref)

    if tolerance_absolute is not None:
        threshold = float(tolerance_absolute)
        rel = abs_error / abs(ref) if abs(ref) > _SCALAR_ZERO_EPS else None
        return {
            "success": True,
            "abs_error": abs_error,
            "rel_error": rel,
            "tolerance": threshold,
            "tolerance_basis": "absolute",
            "within_tolerance": abs_error <= threshold,
        }

    if abs(ref) <= _SCALAR_ZERO_EPS:
        return {
            "success": False,
            "reason": "reference_near_zero",
            "detail": (
                "Relative error is undefined when |ref_value| ~ 0; pass "
                "tolerance_absolute to compare the raw difference instead."
            ),
            "abs_error": abs_error,
        }

    tol = (
        _DEFAULT_SCALAR_TOL_RELATIVE
        if tolerance_relative is None
        else float(tolerance_relative)
    )
    rel_error = abs_error / abs(ref)
    return {
        "success": True,
        "abs_error": abs_error,
        "rel_error": rel_error,
        "tolerance": tol,
        "tolerance_basis": "relative",
        "within_tolerance": rel_error <= tol,
    }


def grid_convergence_index(
    h: list[float],
    values: list[Any],
    safety_factor: float = 1.25,
) -> ToolResult:
    """Grid Convergence Index (GCI) from three systematically refined grids.

    Implements the procedure of Celik et al. (2008), "Procedure for
    estimation and reporting of uncertainty due to discretization in CFD
    applications", J. Fluids Eng. 130(7) 078001 (doi:10.1115/1.2960953),
    based on Roache's GCI. Cite it as ``celik_2008``.

    Args:
        h: Representative cell size of each grid, e.g. ``[1/20, 1/40, 1/80]``
            (any order; sorted fine to coarse internally). For a uniform 2-D
            grid, ``h = L / N``.
        values: The solution on each grid, in the same order as ``h``: either
            one scalar per grid (a coefficient, a peak value) or one list per
            grid holding a profile sampled at the SAME stations on every
            grid (e.g. the simulation interpolated onto the reference
            stations).
        safety_factor: Fs; 1.25 for three-grid studies.

    Returns:
        ``{success, refinement_ratios {r21, r32}, apparent_order p,
        convergence (monotonic | oscillatory | divergent | mixed),
        extrapolated (phi_ext), relative_error_fine e_a21, gci_fine
        (GCI_21, the fine-grid uncertainty), gci_medium (GCI_32),
        asymptotic_ratio (GCI_32 / (r21^p GCI_21), ~1 when in the
        asymptotic range)}``. For profiles every field is per station plus
        ``summary`` (mean p used, max and mean GCI_fine). Grid 1 is the
        finest.
    """
    try:
        hs = [float(x) for x in h]
    except (TypeError, ValueError):
        return {"success": False, "reason": "invalid_input", "detail": "h must be three numbers"}
    if len(hs) != 3 or len(values) != 3 or min(hs) <= 0:
        return {"success": False, "reason": "invalid_input",
                "detail": "need exactly three positive cell sizes and three solutions"}
    order = sorted(range(3), key=lambda i: hs[i])
    h1, h2, h3 = (hs[i] for i in order)
    try:
        sols = [np.atleast_1d(np.asarray(values[i], dtype=float)) for i in order]
    except (TypeError, ValueError):
        return {"success": False, "reason": "invalid_input", "detail": "values must be numbers or equal-length lists"}
    if len({v.shape for v in sols}) != 1:
        return {"success": False, "reason": "invalid_input",
                "detail": "profiles must be sampled at the same stations on every grid"}
    phi1, phi2, phi3 = sols
    r21, r32 = h2 / h1, h3 / h2
    if r21 <= 1.0 or r32 <= 1.0:
        return {"success": False, "reason": "invalid_input", "detail": "grids must be distinct (refinement ratio > 1)"}

    # ratio = eps32 / eps21 = 1 / R in Celik's notation: monotonic convergence
    # when the coarse-pair change exceeds the fine-pair change (ratio > 1).
    eps21, eps32 = phi2 - phi1, phi3 - phi2
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(eps21 != 0, eps32 / eps21, np.nan)

    def apparent_order(rt: float) -> float:
        if not np.isfinite(rt) or rt == 0:
            return float("nan")
        s = 1.0 if rt > 0 else -1.0
        p = abs(np.log(abs(rt))) / np.log(r21)
        for _ in range(100):  # fixed-point iteration (Celik eq. 3)
            q = np.log((r21 ** p - s) / (r32 ** p - s))
            p_new = abs(np.log(abs(rt)) + q) / np.log(r21)
            if not np.isfinite(p_new):
                return float("nan")
            if abs(p_new - p) < 1e-10:
                return float(p_new)
            p = max(p_new, 1e-6)
        return float(p)

    p_local = np.array([apparent_order(float(x)) for x in ratio])
    kinds = np.where(np.isnan(ratio), "converged",
                     np.where(ratio > 0, np.where(ratio > 1, "monotonic", "divergent"), "oscillatory"))
    finite = p_local[np.isfinite(p_local)]
    p_used = float(np.mean(finite)) if finite.size else float("nan")

    def at(pv: float) -> dict[str, Any]:
        rp = r21 ** pv
        with np.errstate(divide="ignore", invalid="ignore"):
            ext = (rp * phi1 - phi2) / (rp - 1.0)
            e_a = np.abs((phi1 - phi2) / phi1)
            gci21 = safety_factor * e_a / (rp - 1.0)
            e_a32 = np.abs((phi2 - phi3) / phi2)
            gci32 = safety_factor * e_a32 / (r32 ** pv - 1.0)
            asym = gci32 / (rp * gci21)
        return {"extrapolated": ext, "relative_error_fine": e_a, "gci_fine": gci21,
                "gci_medium": gci32, "asymptotic_ratio": asym}

    def clean(a: Any) -> Any:
        a = np.asarray(a, dtype=float) if not isinstance(a, np.ndarray) or a.dtype.kind != "U" else a
        if a.dtype.kind == "U":
            return a.tolist()
        return [None if not np.isfinite(x) else float(x) for x in a]

    if phi1.size == 1:
        kind = str(kinds[0])
        if not np.isfinite(p_local[0]):
            return {"success": True, "convergence": kind, "apparent_order": None,
                    "refinement_ratios": {"r21": r21, "r32": r32},
                    "detail": "no change between grids or no usable order; GCI undefined"}
        res = at(float(p_local[0]))
        return {"success": True, "refinement_ratios": {"r21": r21, "r32": r32},
                "apparent_order": float(p_local[0]), "convergence": kind,
                **{k: clean(v)[0] for k, v in res.items()}}

    res = at(p_used)
    gci = np.asarray(res["gci_fine"], dtype=float)
    ok = gci[np.isfinite(gci)]
    counts = {k: int(np.sum(kinds == k)) for k in ("monotonic", "oscillatory", "divergent", "converged")}
    return {
        "success": True,
        "refinement_ratios": {"r21": r21, "r32": r32},
        "apparent_order_local": clean(p_local),
        "convergence_local": kinds.tolist(),
        **{k: clean(v) for k, v in res.items()},
        "summary": {
            "apparent_order_mean": None if not np.isfinite(p_used) else p_used,
            "gci_fine_max": float(ok.max()) if ok.size else None,
            "gci_fine_mean": float(ok.mean()) if ok.size else None,
            "convergence_counts": counts,
            "note": "per-station GCI uses the mean apparent order (Celik et al. 2008); "
                    "stations where the solution is near zero give large relative GCI",
        },
    }


def check_convergence(
    residuals: dict[str, list[float]],
    threshold: float = 1e-4,
    stall_window: int = 50,
) -> ToolResult:
    """Classify convergence behavior from a residual history.

    Per-field rules applied to the initial-residual time series:
    - ``diverged`` if the series contains NaN/Inf, or the latest value is more
      than 100x the first value (orders-of-magnitude blow-up).
    - ``converged`` if the latest value is below ``threshold``.
    - ``stalled`` if the latest value is within 5% of the minimum of the last
      ``stall_window`` values — i.e. no meaningful progress recently.
    - ``still_running`` otherwise (residuals still trending down toward
      threshold).

    Overall status priority: diverged > stalled > still_running > converged.

    Args:
        residuals: Mapping from field name to its initial-residual time series,
            e.g. ``{"Ux": [...], "p": [...]}``.
        threshold: Residual value below which we consider a field converged.
        stall_window: Number of iterations to look back when checking for a
            stalled (non-decreasing) residual.

    Returns:
        ``{"success": True, "status": str, "per_field": {...}, "recommendation":
        str}`` where ``status`` is one of ``"converged"``, ``"diverged"``,
        ``"stalled"``, ``"still_running"``. ``recommendation`` is a short
        action the agent can take.

        ``{"success": False, "reason": str}`` on malformed input.
    """
    if not isinstance(residuals, dict) or not residuals:
        return {"success": False, "reason": "empty_residuals"}
    if threshold <= 0:
        return {"success": False, "reason": "threshold_must_be_positive"}
    if stall_window < 2:
        return {"success": False, "reason": "stall_window_must_be_at_least_2"}

    per_field: dict[str, str] = {}
    any_diverged = False
    any_stalled = False
    all_converged = True

    for field, series in residuals.items():
        if not isinstance(series, list) or not series:
            return {"success": False, "reason": f"empty_series_for_field: {field}"}

        if any(not math.isfinite(float(v)) for v in series):
            per_field[field] = "diverged"
            any_diverged = True
            all_converged = False
            continue

        first = float(series[0])
        latest = float(series[-1])

        if first > 0 and latest > 100 * first:
            per_field[field] = "diverged"
            any_diverged = True
            all_converged = False
            continue

        if latest < threshold:
            per_field[field] = "converged"
            continue

        all_converged = False
        window = series[-stall_window:] if len(series) >= stall_window else series
        window_start = float(window[0])
        # Stalled if the latest value is no meaningfully lower than the
        # window-start value (5% bar). Comparing to the start of the window
        # rather than its minimum so a series that just hit a new low isn't
        # mis-classified as stalled.
        if latest >= window_start * 0.95:
            per_field[field] = "stalled"
            any_stalled = True
        else:
            per_field[field] = "still_running"

    if any_diverged:
        status = "diverged"
        diverged_fields = sorted(f for f, s in per_field.items() if s == "diverged")
        recommendation = (
            f"Reduce relaxation factors and verify inlet boundary conditions; "
            f"diverged on {diverged_fields}."
        )
    elif all_converged:
        status = "converged"
        recommendation = "No action needed; all fields below the convergence threshold."
    elif any_stalled:
        status = "stalled"
        stalled_fields = sorted(f for f, s in per_field.items() if s == "stalled")
        recommendation = (
            f"Stalled on {stalled_fields}: tighten linear-solver tolerance, "
            f"refine the mesh near recirculation zones, or relax momentum."
        )
    else:
        status = "still_running"
        recommendation = "Continue running; residuals are still trending down."

    return {
        "success": True,
        "status": status,
        "per_field": per_field,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# run_analysis — execute an agent-authored validation script.
#
# A fixed set of comparison primitives cannot span every CFD metric (Cd/Cl,
# Cp, Cf, reattachment, Strouhal, Nusselt, shock angle, spectra). So the
# agent WRITES a per-case Python script that extracts the case-specific
# quantity from the solver's output and plots it, then scores the result by
# calling the trusted ``compare_profiles`` primitive — the pass/fail number
# stays on tested code while the open-ended extraction + visuals are
# agent-authored. This tool runs that script the SAME way in Claude Code and
# the bare harness, so the archived artifact (script + plots) is identical
# and the validation replays. It executes semi-trusted code, so it is
# hardened (process-group kill, resource limits, minimal env) — best-effort
# soft isolation, not a jail; see the docstring.
# ---------------------------------------------------------------------------

_ANALYSIS_SENTINEL = "<<<ANALYSIS_RESULT>>>"
_ANALYSIS_DEFAULT_TIMEOUT_S = 120
_ANALYSIS_TAIL_BYTES = 512 * 1024  # bound how much of each stream we read back
_ANALYSIS_TAIL_LINES = 50
_MAX_RESULT_JSON_BYTES = 256 * 1024
_RLIMIT_AS_BYTES = 4 * 1024**3  # 4 GiB address space — generous for numpy/mpl
_RLIMIT_FSIZE_BYTES = 256 * 1024**2  # 256 MiB max single-file write
_KILL_GRACE_S = 2.0


def _analysis_join_under(root: Path, rel: str) -> Path | None:
    """Join ``rel`` under ``root`` (resolved); None if it escapes ``root``."""
    if not rel:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _analysis_child_env() -> dict[str, str]:
    """Minimal allow-listed env for the subprocess — no secret pass-through.

    The full server environment is NOT inherited: only the variables the
    interpreter needs to run plus ``MPLBACKEND=Agg`` (forces headless
    matplotlib regardless of what the script does). OpenFOAM ``FOAM_*`` /
    ``WM_*`` are forwarded only if actually present (the validation server is
    normally launched without sourcing OpenFOAM, so they will be absent —
    the analysis script must read solver output files directly, not shell out
    to ``postProcess``).
    """
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "TMPDIR")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    for k, v in os.environ.items():
        if k.startswith(("FOAM_", "WM_")):
            env[k] = v
    env.setdefault("PATH", "/usr/bin:/bin")
    env["MPLBACKEND"] = "Agg"  # headless matplotlib regardless of the script
    # Single-threaded BLAS/OMP: a profile comparison needs no thread pool, it
    # keeps the run deterministic (a reproducibility win), and it avoids the
    # OpenBLAS thread explosion that would otherwise trip resource limits.
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[var] = "1"
    return env


def _make_rlimit_preexec(cpu_seconds: int):
    """Return a preexec_fn that caps child resources, or None if unavailable.

    Best-effort: each limit is set independently and a failure (e.g. an
    unsupported limit) is swallowed so the launch still proceeds. Combined
    with ``start_new_session`` (separate process group, set in C) this is
    soft isolation — not a container.
    """
    if resource is None:
        return None

    def _preexec() -> None:
        # NB: RLIMIT_NPROC is deliberately NOT set — it is per-UID (counts all
        # the user's processes/threads), so any usable value still lets a fork
        # bomb through while a tight one breaks numpy's own thread pool. Fork
        # runaways are instead bounded by the CPU/wall limit + process-group
        # kill. This is soft isolation, not a jail.
        for what, soft in (
            (resource.RLIMIT_AS, _RLIMIT_AS_BYTES),
            (resource.RLIMIT_CPU, cpu_seconds),
            (resource.RLIMIT_FSIZE, _RLIMIT_FSIZE_BYTES),
        ):
            try:
                resource.setrlimit(what, (soft, soft))
            except (ValueError, OSError, AttributeError):
                pass

    return _preexec


def _kill_process_group(proc: subprocess.Popen) -> None:
    """SIGTERM then SIGKILL the child's whole process group, and reap it.

    A bare ``subprocess`` timeout only kills the direct child, leaving any
    grandchild (e.g. a forked worker) running forever. Killing the group
    catches them.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=_KILL_GRACE_S)
            return
        except subprocess.TimeoutExpired:
            continue


def _read_tail(f: Any, n_bytes: int) -> str:
    """Read at most the last ``n_bytes`` of a binary temp file as text."""
    try:
        f.flush()
    except (OSError, ValueError):
        pass
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(max(0, size - n_bytes))
    return f.read().decode("utf-8", errors="replace")


def _tail_lines(text: str, n: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _parse_analysis_sentinel(stdout: str) -> tuple[dict | None, str | None]:
    """Extract the JSON payload after the LAST sentinel line.

    Scanning for the last occurrence (not the first) means a literal sentinel
    token in earlier human-narration can't shadow the real result, which the
    contract requires to be the script's final output.
    """
    lines = stdout.splitlines()
    sentinel_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == _ANALYSIS_SENTINEL:
            sentinel_idx = i
            break
    if sentinel_idx is None:
        return None, "no_result_sentinel"
    json_line = None
    for j in range(sentinel_idx + 1, len(lines)):
        if lines[j].strip():
            json_line = lines[j].strip()
            break
    if json_line is None:
        return None, "no_result_sentinel"
    if len(json_line.encode("utf-8")) > _MAX_RESULT_JSON_BYTES:
        return None, "bad_result_json"
    try:
        payload = json.loads(json_line)
    except (json.JSONDecodeError, ValueError):
        return None, "bad_result_json"
    if not isinstance(payload, dict):
        return None, "bad_result_json"
    return payload, None


def _verify_plots(case: Path, declared: Any) -> tuple[list[str], list[str]]:
    """Split declared plot paths into (exist-under-case, missing/escaping)."""
    plots: list[str] = []
    missing: list[str] = []
    if not isinstance(declared, list):
        return plots, missing
    for p in declared:
        if not isinstance(p, str) or not p:
            continue
        resolved = _analysis_join_under(case, p)
        if resolved is not None and resolved.is_file():
            plots.append(p)
        else:
            missing.append(p)
    return plots, missing


def run_analysis(
    case_path: str,
    script: str = "analysis/validate.py",
    args: list[str] | None = None,
    timeout_s: int = _ANALYSIS_DEFAULT_TIMEOUT_S,
) -> ToolResult:
    """Run an agent-authored validation script and capture its metrics + plots.

    The agent writes a Python script (default ``analysis/validate.py``,
    relative to the case dir) that: reads the solver's output, loads reference
    arrays via ``read_reference``, scores them with the trusted
    ``compare_profiles`` primitive (do NOT re-implement the error norm), draws
    matplotlib overlays into ``postProcessing/analysis/``, and as its LAST
    stdout prints the sentinel line ``<<<ANALYSIS_RESULT>>>`` followed by one
    line of compact JSON ``{"metrics": {...}, "plots": ["postProcessing/analysis/x.png", ...]}``.
    ``metrics`` is free-form (embed the ``compare_profiles`` verdict per
    check); this tool does NOT interpret it and never decides pass/fail — that
    stays on the tested primitive the script called.

    The script runs under the validation server's own interpreter with
    ``cwd = case_path``, so it can ``from validation_mcp.tools import
    compare_profiles, read_reference``. Allowed imports: stdlib + numpy +
    matplotlib (Agg backend is forced via env) + validation_mcp. The
    validation server is launched WITHOUT OpenFOAM sourced, so the script must
    read solver output files directly (e.g. a sampled ``postProcessing/sets``
    ``.xy`` file the solver wrote) — it cannot shell out to ``postProcess``.

    Helpers for the generic parts, in ``validation_mcp.analysis``:
    ``latest_set(".", name, field)`` finds the newest file a ``sets`` function
    object called ``name`` wrote, ``read_set(path)`` returns ``(coord,
    values)`` from a raw ``.xy`` set, and ``emit(metrics, plots)`` prints the
    result block above as the script's last output.

    Execution is hardened but NOT a sandbox/jail: the child runs in its own
    process group (the whole group is killed on timeout, catching forked
    grandchildren), with best-effort RLIMIT caps on address space / CPU /
    file size / process count, and a minimal allow-listed environment (server
    secrets are not passed through). Network access is NOT blocked at the OS
    level — the contract requires scripts not use it, and you are trusting the
    script you authored. Plot paths are verified to be real files under the
    case dir; missing/escaping ones are dropped and listed in ``missing_plots``.

    Args:
        case_path: Absolute path to the case directory.
        script: Path to the analysis script, RELATIVE to ``case_path``.
            Rejected if absolute, containing ``..``, or escaping the case dir.
        args: Optional extra argv forwarded to the script.
        timeout_s: Wall-clock cap (default 120s); the process group is killed
            on overrun.

    Returns:
        On success: ``{"success": True, "script": str, "metrics": dict,
        "plots": [str], "missing_plots": [str], "returncode": 0,
        "walltime_s": float, "stdout_tail": str}``.
        On failure: ``{"success": False, "reason": str, ...}`` where reason is
        one of ``"invalid_case_path"``, ``"path_escape"``,
        ``"script_not_found"``, ``"timeout"``, ``"script_error"``,
        ``"no_result_sentinel"``, ``"bad_result_json"``, ``"python_not_found"``
        — with ``stdout_tail`` / ``stderr_tail`` (the traceback) where useful.
    """
    case = Path(case_path)
    if not case.is_dir():
        return {
            "success": False,
            "reason": "invalid_case_path",
            "detail": f"{case} does not exist or is not a directory",
        }
    case = case.resolve()

    target = _analysis_join_under(case, script)
    if target is None:
        return {
            "success": False,
            "reason": "path_escape",
            "detail": f"script {script!r} is absolute or escapes the case directory",
        }
    if not target.is_file():
        return {
            "success": False,
            "reason": "script_not_found",
            "detail": f"no analysis script at {target}",
        }

    argv = [sys.executable, str(target)] + [str(a) for a in (args or [])]
    env = _analysis_child_env()
    preexec = _make_rlimit_preexec(int(timeout_s) + 5)

    timed_out = False
    start = time.monotonic()
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(case),
                env=env,
                stdout=out_f,
                stderr=err_f,
                start_new_session=True,  # own process group, killed as a unit
                preexec_fn=preexec,
            )
        except (OSError, ValueError) as exc:
            return {
                "success": False,
                "reason": "python_not_found",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_group(proc)
        walltime = time.monotonic() - start
        returncode = proc.returncode
        stdout = _read_tail(out_f, _ANALYSIS_TAIL_BYTES)
        stderr = _read_tail(err_f, _ANALYSIS_TAIL_BYTES)

    stdout_tail = _tail_lines(stdout, _ANALYSIS_TAIL_LINES)
    stderr_tail = _tail_lines(stderr, _ANALYSIS_TAIL_LINES)

    if timed_out:
        return {
            "success": False,
            "reason": "timeout",
            "detail": f"exceeded {timeout_s}s wall-clock; process group killed",
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "script": script,
        }
    if returncode != 0:
        return {
            "success": False,
            "reason": "script_error",
            "returncode": returncode,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "script": script,
        }

    payload, parse_err = _parse_analysis_sentinel(stdout)
    if parse_err is not None:
        return {
            "success": False,
            "reason": parse_err,
            "returncode": returncode,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "script": script,
        }

    plots, missing = _verify_plots(case, payload.get("plots", []))
    # Saved for openfoam.finalize_report, which checks a narrated PASS
    # against these numbers.
    try:
        out = case / "postProcessing" / "analysis" / "run_analysis_result.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"script": script, "metrics": payload.get("metrics", {})},
                                  indent=2, default=str))
    except (OSError, TypeError, ValueError):
        pass
    return {
        "success": True,
        "script": script,
        "metrics": payload.get("metrics", {}),
        "plots": plots,
        "missing_plots": missing,
        "returncode": returncode,
        "walltime_s": round(walltime, 3),
        "stdout_tail": stdout_tail,
    }
