"""Validate the Re=400 lid-driven cavity against Ghia, Ghia & Shin (1982).

Reads the centerline samples written by the `sampleLines` functionObject
(postProcessing/sampleLines/<latest>/{vertical,horizontal}Centerline_U.xy),
scores u(y) at x=0.5 and v(x) at y=0.5 with validation_mcp.compare_profiles
(tolerance = 5% of the reference range, the dataset's relative-L2 convention),
and draws overlays into postProcessing/analysis/.
"""

import json
import platform
import subprocess
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from validation_mcp.tools import compare_profiles, read_reference

CASE = Path(".").resolve()
OUT = CASE / "postProcessing" / "analysis"
OUT.mkdir(parents=True, exist_ok=True)

REFERENCE = "ghia_1982"
CHECKS = [
    # (quantity, sample file, axis column, field column, dataset, label)
    ("u_centerline", "verticalCenterline_U.xy", 0, 1, "ghia_re_400_u_centerline", ("y", "u")),
    ("v_centerline", "horizontalCenterline_U.xy", 0, 2, "ghia_re_400_v_centerline", ("x", "v")),
]
REL_TOL = 0.05


def latest_sample_dir() -> Path:
    root = CASE / "postProcessing" / "sampleLines"
    times = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: float(d.name))
    return times[-1]


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=CASE, timeout=10
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


ref = read_reference(REFERENCE)
if not ref.get("success"):
    raise SystemExit(f"read_reference failed: {ref}")
datasets = ref["data"]["datasets"]

sample_dir = latest_sample_dir()
metrics = {"checks": {}}
plots = []
all_pass = True

for quantity, fname, ax_col, f_col, dset, (ax_name, f_name) in CHECKS:
    data = np.loadtxt(sample_dir / fname)
    sim_x, sim_f = data[:, ax_col], data[:, f_col]
    r = datasets[dset]
    ref_x, ref_f = r["axis_values"], r["field_values"]

    result = compare_profiles(list(sim_x), list(sim_f), ref_x, ref_f)
    if not result.get("success"):
        raise SystemExit(f"compare_profiles failed for {quantity}: {result}")
    result["relative_l2"] = result["l2_error"] / result["reference_range"]
    result["tolerance_relative_L2"] = REL_TOL
    result["reference_dataset"] = dset
    metrics["checks"][quantity] = result
    all_pass &= bool(result["within_tolerance"])

    if dset == "ghia_re_400_v_centerline":
        # Diagnostic only (not a pass criterion): the reference provenance
        # flags Ghia's printed v at x=0.9063 as a suspected typo. Score the
        # profile without that point to separate it from discretization error.
        keep = [i for i, x in enumerate(ref_x) if abs(x - 0.9063) > 1e-6]
        diag = compare_profiles(
            list(sim_x), list(sim_f), [ref_x[i] for i in keep], [ref_f[i] for i in keep]
        )
        diag["relative_l2"] = diag["l2_error"] / diag["reference_range"]
        diag["sim_v_at_x0.9063"] = float(np.interp(0.9063, sim_x, sim_f))
        metrics["diagnostics"] = {"v_centerline_excl_x0.9063": diag}

    fig, ax = plt.subplots(figsize=(5, 4))
    if ax_name == "y":
        ax.plot(sim_f, sim_x, "-", label="simpleFoam")
        ax.plot(ref_f, ref_x, "o", mfc="none", label="Ghia et al. (1982)")
        ax.set_xlabel(f"{f_name} / U_lid")
        ax.set_ylabel(f"{ax_name} / L")
    else:
        ax.plot(sim_x, sim_f, "-", label="simpleFoam")
        ax.plot(ref_x, ref_f, "o", mfc="none", label="Ghia et al. (1982)")
        ax.set_xlabel(f"{ax_name} / L")
        ax.set_ylabel(f"{f_name} / U_lid")
    ax.set_title(f"Re=400 {quantity}: rel. L2 = {result['relative_l2']:.3f}")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    png = OUT / f"{quantity}.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    plots.append(str(png.relative_to(CASE)))

metrics["all_pass"] = all_pass
metrics["provenance"] = {
    "reference": REFERENCE,
    "sample_time": sample_dir.name,
    "numpy": np.__version__,
    "matplotlib": matplotlib.__version__,
    "python": platform.python_version(),
    "git_commit": git_commit(),
}
(OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))

print("<<<ANALYSIS_RESULT>>>")
print(json.dumps({"metrics": metrics, "plots": plots}))
