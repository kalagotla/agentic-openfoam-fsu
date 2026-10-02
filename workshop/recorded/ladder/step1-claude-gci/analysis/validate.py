"""Validate the Re = 400 lid-driven cavity against Ghia, Ghia & Shin (1982).

Extracts u(y) at x = 0.5 and v(x) at y = 0.5 from the `centrelines` sets
function object, scores each with validation_mcp.tools.compare_profiles
(default tolerance: 5 % of the reference range = scenario's relative L2 0.05),
and plots overlays.

Optional GCI (Celik et al. 2008): pass `--grids N1:path1 N2:path2 N3:path3`
(case directories of three uniformly refined N x N grids, relative to this
case). Each grid's profile is interpolated onto the Ghia stations and handed
to validation_mcp.tools.grid_convergence_index with h = 1/N.
"""

import json
import platform
import subprocess
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from validation_mcp.analysis import emit, latest_set, read_set
from validation_mcp.tools import compare_profiles, grid_convergence_index, read_reference

REFERENCE = "ghia_1982"
CHECKS = {
    "u_centerline": ("vertical", "ghia_re_400_u_centerline", 0),    # Ux along y
    "v_centerline": ("horizontal", "ghia_re_400_v_centerline", 1),  # Uy along x
}
OUT = Path("postProcessing/analysis")


def profile(case, set_name, comp):
    path = latest_set(case, "centrelines", f"{set_name}_U")
    coord, U = read_set(path)
    return coord, U[:, comp], path


def parse_grids(argv):
    if "--grids" not in argv:
        return []
    out = []
    for tok in argv[argv.index("--grids") + 1:]:
        n, p = tok.split(":", 1)
        out.append((int(n), p))
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ref = read_reference(REFERENCE)["data"]["datasets"]
    grids = parse_grids(sys.argv[1:])

    metrics, plots, sample_files = {}, [], {}
    for q, (set_name, ds, comp) in CHECKS.items():
        r = ref[ds]
        coord, val, path = profile(".", set_name, comp)
        sample_files[q] = str(path)
        res = compare_profiles(coord.tolist(), val.tolist(), r["axis_values"], r["field_values"])
        res["relative_l2"] = res["l2_error"] / res["reference_range"]
        metrics[q] = res

        fig, ax = plt.subplots(figsize=(5, 4))
        axis_lbl, fld = r["axis"], r["field"]
        if fld == "u":
            ax.plot(val, coord, "-", label="simpleFoam (this case)")
            ax.plot(r["field_values"], r["axis_values"], "ko", mfc="none", label="Ghia et al. 1982")
            ax.set_xlabel("u / U_lid"); ax.set_ylabel("y / L")
        else:
            ax.plot(coord, val, "-", label="simpleFoam (this case)")
            ax.plot(r["axis_values"], r["field_values"], "ko", mfc="none", label="Ghia et al. 1982")
            ax.set_xlabel("x / L"); ax.set_ylabel("v / U_lid")
        for n, gp in grids:
            c, v, _ = profile(gp, set_name, comp)
            (ax.plot(v, c, "--", lw=1, label=f"{n}x{n}") if fld == "u"
             else ax.plot(c, v, "--", lw=1, label=f"{n}x{n}"))
        ax.set_title(f"Re = 400, {q}: rel. L2 = {res['relative_l2']:.3f}")
        ax.grid(alpha=0.3); ax.legend(fontsize=8)
        fig.tight_layout()
        png = OUT / f"{q}.png"
        fig.savefig(png, dpi=120); plt.close(fig)
        plots.append(str(png))

    if grids:
        gci = {}
        for q, (set_name, ds, comp) in CHECKS.items():
            r = ref[ds]
            stations = np.asarray(r["axis_values"], float)
            # interior stations only: wall values are fixed by the BC and carry no error
            stations = stations[(stations > 0) & (stations < 1)]
            vals = []
            for n, gp in grids:
                c, v, _ = profile(gp, set_name, comp)
                vals.append(np.interp(stations, c, v).tolist())
            res = grid_convergence_index([1.0 / n for n, _ in grids], vals)
            res["stations"] = stations.tolist()
            res["grids"] = [n for n, _ in grids]
            gci[q] = res
        metrics["gci"] = gci

    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                text=True, timeout=10).stdout.strip() or None
    except Exception:
        commit = None
    metrics["provenance"] = {
        "reference_dataset": REFERENCE,
        "sample_files": sample_files,
        "sample_time": Path(sample_files["u_centerline"]).parent.name,
        "numpy": np.__version__,
        "matplotlib": matplotlib.__version__,
        "python": platform.python_version(),
        "git_commit": commit,
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2, default=float))
    emit(metrics, plots)


if __name__ == "__main__":
    main()
