"""Headless validation of a Pitz-Daily simulation against Armaly 1983.

Reads sampled data from ``<case>/postProcessing/`` (written by the function
objects in ``baseline/system/controlDict``), computes the reattachment length,
loads Armaly's reference data, and prints a comparison table. Exits 0 if all
checks pass, 1 otherwise.

The reattachment computation is inlined below — it is case-specific
(backward-facing step physics: deepest negative wall shear, then first
zero-crossing downstream) and so lives next to the case rather than in the
validation MCP server, which is reserved for case-agnostic tools.

Profile validation against Armaly is intentionally not run for the baseline
case at Re ≈ 50,800 — Armaly has no velocity profile data in the turbulent
regime. Reattachment length alone validates the headline metric (the
high-Re plateau ≈ 6 step heights). See ``reference/README.md``.

Usage:
    uv run python cases/examples/pitz-daily/validation.py [CASE_DIR]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_CASE = REPO_ROOT / "cases" / "examples" / "pitz-daily" / "baseline"

# Geometry constants for the v2412 pitzDaily tutorial. The straight section of
# the BFS floor (where reattachment physics is well-defined) ends at the
# contraction inlet at x = 206 mm. Sampling in the contraction reflects
# accelerating-channel flow, not BFS reattachment.
STEP_HEIGHT_M = 0.0254
BFS_FLOOR_Y_M = -0.0254
BFS_STRAIGHT_X_MAX_M = 0.206


def _latest_time_dir(parent: Path) -> Path | None:
    """Return the postProcessing/<func>/<time> directory with the largest int time."""
    if not parent.is_dir():
        return None
    candidates = []
    for child in parent.iterdir():
        if not child.is_dir():
            continue
        try:
            candidates.append((int(child.name), child))
        except ValueError:
            continue
    if not candidates:
        return None
    return max(candidates)[1]


def _read_wall_shear(case_dir: Path) -> dict[str, list[float]] | str:
    """Load (x, tau_wx) pairs along the BFS floor from the latest sample.

    Filters to the straight downstream section (y ≈ -h, 0 < x < 0.206 m) so
    the corner artifacts at the step face and the contraction floor don't
    pollute the reattachment search.

    Sign convention: OpenFOAM's wallShearStress on a lower wall returns
    *negative* tau_x for attached forward flow and *positive* for backflow.
    We negate to give the textbook skin-friction convention used by the
    reattachment computation below (negative inside the bubble, positive
    once attached).

    Returns a ``{"x": [...], "tau_wx": [...]}`` dict on success or a string
    error message describing what was missing.
    """
    sample_root = case_dir / "postProcessing" / "bottomWallShear"
    latest = _latest_time_dir(sample_root)
    if latest is None:
        return f"no postProcessing/bottomWallShear/<time> directory under {case_dir}"

    raw_file = latest / "wallShearStress_lowerWall.raw"
    if not raw_file.exists():
        return f"missing {raw_file}"

    xs: list[float] = []
    taus: list[float] = []
    with raw_file.open() as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            x, y = float(parts[0]), float(parts[1])
            tau_x = float(parts[3])
            if abs(y - BFS_FLOOR_Y_M) > 1e-4:
                continue
            if not (0.0 < x < BFS_STRAIGHT_X_MAX_M):
                continue
            xs.append(x)
            # Negate to convert OpenFOAM's wallShearStress sign on a lower wall
            # to the textbook skin-friction convention.
            taus.append(-tau_x)

    if len(xs) < 2:
        return f"only {len(xs)} BFS-floor samples found in {raw_file}"

    return {"x": xs, "tau_wx": taus}


def _compute_reattachment_xrh(
    xs: list[float], taus: list[float], step_height: float
) -> dict[str, object]:
    """Find x_r/h from a (x, tau_wx) trace along the BFS floor.

    BFS-specific physics: the deepest negative wall shear sits in the
    recirculation bubble; the first sign change downstream of it marks
    reattachment. Linear interpolation between the bracketing samples
    gives the crossing point.

    Returns ``{"success": bool, ...}`` consistent with the MCP tool
    convention so the print-out logic above stays unchanged.
    """
    if step_height <= 0:
        return {"success": False, "reason": "step_height_must_be_positive"}
    n = len(xs)
    if n < 2 or n != len(taus):
        return {"success": False, "reason": "input_arrays_too_short_or_mismatched"}

    # Sort by x (the upstream reader filters then appends in file order;
    # sorting is cheap and defensive).
    paired = sorted(zip(xs, taus))
    x_sorted = [p[0] for p in paired]
    tau_sorted = [p[1] for p in paired]

    i_min = min(range(n), key=lambda i: tau_sorted[i])
    if tau_sorted[i_min] >= 0:
        return {
            "success": False,
            "reason": "no_recirculation_detected",
            "min_tau_wx": tau_sorted[i_min],
        }

    for i in range(i_min, n - 1):
        if tau_sorted[i] < 0 <= tau_sorted[i + 1]:
            t_i, t_ip1 = tau_sorted[i], tau_sorted[i + 1]
            x_i, x_ip1 = x_sorted[i], x_sorted[i + 1]
            x_r = x_i + (-t_i) * (x_ip1 - x_i) / (t_ip1 - t_i)
            return {
                "success": True,
                "x_reattachment": x_r,
                "x_r_over_h": x_r / step_height,
            }

    return {
        "success": False,
        "reason": "no_reattachment_in_sampled_window",
        "last_x": x_sorted[-1],
        "last_tau_wx": tau_sorted[-1],
    }


def _load_armaly_reference() -> dict[str, object]:
    """Read the digitized Armaly reattachment-length JSON from the case directory."""
    ref_path = (
        Path(__file__).resolve().parent / "reference" / "reattachment_length.json"
    )
    if not ref_path.exists():
        return {"success": False, "reason": f"missing {ref_path}"}
    with ref_path.open() as fh:
        return {"success": True, "data": json.load(fh)}


def _format_pass_fail(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def main(case_dir: Path) -> int:
    print(f"Validating case: {case_dir}")
    print(f"Step height h = {STEP_HEIGHT_M} m")
    print()

    overall_ok = True

    # --- Reattachment length ------------------------------------------------
    wall = _read_wall_shear(case_dir)
    if isinstance(wall, str):
        print(f"[reattachment] FAIL — could not read wall shear: {wall}")
        return 1

    sim = _compute_reattachment_xrh(wall["x"], wall["tau_wx"], STEP_HEIGHT_M)
    if not sim["success"]:
        print(f"[reattachment] FAIL — {sim['reason']}")
        return 1

    ref = _load_armaly_reference()
    if not ref["success"]:
        print(f"[reattachment] FAIL — could not load reference: {ref['reason']}")
        return 1

    ref_xrh = ref["data"]["high_re_plateau"]["x_r_over_h"]
    tol = ref["data"]["tolerance"]["absolute_x_r_over_h"]
    sim_xrh = sim["x_r_over_h"]
    abs_err = abs(sim_xrh - ref_xrh)
    within = abs_err <= tol
    overall_ok = overall_ok and within

    print("Quantity                  reference   simulated    abs error    tol     status")
    print("-" * 80)
    print(
        f"x_r/h (Armaly plateau)    {ref_xrh:9.3f}   {sim_xrh:9.3f}   {abs_err:9.3f}   "
        f"{tol:5.2f}    {_format_pass_fail(within)}"
    )
    print()
    print(
        "Reference: "
        + ref["data"]["high_re_plateau"]["notes"].split('.')[0]
        + f". x_r/h = {ref_xrh} ± {ref['data']['high_re_plateau']['uncertainty']}."
    )
    print(f"Citation: {ref['data']['primary_citation']}")
    print()

    # --- Velocity profiles --------------------------------------------------
    # Intentionally skipped at this Re. Logged so anyone running the script
    # sees the deferred check rather than thinking it silently passed.
    print(
        "[profiles] SKIP — Armaly has no velocity profile data in the "
        "turbulent regime. Profile validation deferred until either the "
        "baseline Re drops into Armaly's range or a turbulent profile "
        "reference (e.g. Driver–Seegmiller 1985) is registered."
    )
    print()

    print("=" * 80)
    print(f"Overall: {_format_pass_fail(overall_ok)}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    case = Path(sys.argv[1]) if len(sys.argv) > 1 else BASELINE_CASE
    sys.exit(main(case))
