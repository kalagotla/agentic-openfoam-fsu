"""Centerline validation of the Re=400 lid-driven cavity against Ghia et al. (1982).

Extracts u(y) at x=0.5 and v(x) at y=0.5 from the `centerlines` sets
functionObject output, scores both with validation_mcp.compare_profiles
(default tolerance: 5% of the reference range), overlays them on Ghia's
Table I/II data, and stamps metrics.json with provenance.
"""
import json
import platform
import re
import subprocess
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from validation_mcp.tools import compare_profiles, read_reference

CASE = Path.cwd()
SETS_DIR = CASE / "postProcessing" / "centerlines"
OUT_DIR = CASE / "postProcessing" / "analysis"
REFERENCE = "ghia_1982"
RE = 400
# Ghia Table II prints v=-0.23827 at x=0.9063 for Re=400; the reference JSON
# ships it as printed and flags it as a suspected typo. The verdict uses the
# full dataset; the exclusion below is reported for information only.
SUSPECT_X = 0.9063


def latest_time_dir(root):
    times = [d for d in root.iterdir() if d.is_dir() and re.fullmatch(r"[0-9.eE+-]+", d.name)]
    return max(times, key=lambda d: float(d.name))


def n_cells():
    owner = CASE / "constant" / "polyMesh" / "owner"
    m = re.search(r"nCells:\s*(\d+)", owner.read_text(errors="ignore")[:2000]) if owner.exists() else None
    return int(m.group(1)) if m else None


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=CASE,
                              capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def main():
    tdir = latest_time_dir(SETS_DIR)
    vert = np.loadtxt(tdir / "vertical_U.xy")      # y Ux Uy Uz
    horiz = np.loadtxt(tdir / "horizontal_U.xy")   # x Ux Uy Uz

    ref = read_reference(REFERENCE)
    assert ref["success"], ref
    ds = ref["data"]["datasets"]
    ref_u = ds[f"ghia_re_{RE}_u_centerline"]
    ref_v = ds[f"ghia_re_{RE}_v_centerline"]

    res_u = compare_profiles(vert[:, 0].tolist(), vert[:, 1].tolist(),
                             ref_u["axis_values"], ref_u["field_values"])
    res_v = compare_profiles(horiz[:, 0].tolist(), horiz[:, 2].tolist(),
                             ref_v["axis_values"], ref_v["field_values"])

    keep = [i for i, x in enumerate(ref_v["axis_values"]) if abs(x - SUSPECT_X) > 1e-6]
    res_v_info = compare_profiles(horiz[:, 0].tolist(), horiz[:, 2].tolist(),
                                  [ref_v["axis_values"][i] for i in keep],
                                  [ref_v["field_values"][i] for i in keep])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    ax = axes[0]
    ax.plot(vert[:, 1], vert[:, 0], "-", label="simpleFoam")
    ax.plot(ref_u["field_values"], ref_u["axis_values"], "o", mfc="none", label="Ghia et al. 1982")
    ax.set_xlabel("u / U_lid"); ax.set_ylabel("y / L")
    ax.set_title(f"u at x = 0.5 (L2 = {res_u['l2_error']:.4f}, tol {res_u['tolerance_threshold']:.4f})")
    ax.grid(alpha=0.3); ax.legend()
    ax = axes[1]
    ax.plot(horiz[:, 0], horiz[:, 2], "-", label="simpleFoam")
    ax.plot(ref_v["axis_values"], ref_v["field_values"], "o", mfc="none", label="Ghia et al. 1982")
    ax.set_xlabel("x / L"); ax.set_ylabel("v / U_lid")
    ax.set_title(f"v at y = 0.5 (L2 = {res_v['l2_error']:.4f}, tol {res_v['tolerance_threshold']:.4f})")
    ax.grid(alpha=0.3); ax.legend()
    fig.suptitle(f"Lid-driven cavity Re = {RE}, {n_cells()} cells, iteration {tdir.name}")
    fig.tight_layout()
    plot = OUT_DIR / "centerlines_vs_ghia.png"
    fig.savefig(plot, dpi=130)

    metrics = {
        "u_centerline": res_u,
        "v_centerline": res_v,
        "v_centerline_excluding_suspect_x0.9063_info_only": res_v_info,
        "pass": bool(res_u["within_tolerance"] and res_v["within_tolerance"]),
        "n_cells": n_cells(),
        "sample_time": tdir.name,
        "provenance": {
            "reference_dataset": REFERENCE,
            "reference_path": ref.get("path"),
            "numpy": np.__version__,
            "matplotlib": matplotlib.__version__,
            "python": platform.python_version(),
            "git_commit": git_commit(),
        },
    }
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print("<<<ANALYSIS_RESULT>>>")
    print(json.dumps({"metrics": metrics, "plots": [str(plot.relative_to(CASE))]}))


if __name__ == "__main__":
    main()
