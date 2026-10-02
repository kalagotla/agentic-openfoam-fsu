"""Centerline u(y), v(x) at Re=1000 vs Ghia, Ghia & Shin (1982)."""
import json
import subprocess
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from validation_mcp.analysis import emit, latest_set, read_set
from validation_mcp.tools import compare_profiles, read_reference

ref = read_reference("ghia_1982")["data"]["datasets"]
out = Path("postProcessing/analysis")
out.mkdir(parents=True, exist_ok=True)

checks = [
    ("u_centerline", "vertical", "ghia_re_1000_u_centerline", 0, "y", "u"),
    ("v_centerline", "horizontal", "ghia_re_1000_v_centerline", 1, "x", "v"),
]
metrics, plots, sample_time = {}, [], None
for quantity, set_name, ds_name, comp, axis, field in checks:
    path = latest_set(".", "centerlines", set_name)
    sample_time = path.parent.name
    coord, U = read_set(path)
    sim = U[:, comp]
    ds = ref[ds_name]
    res = compare_profiles(coord.tolist(), sim.tolist(), ds["axis_values"], ds["field_values"])
    res["relative_L2"] = res["l2_error"] / res["reference_range"]
    res["reference_dataset"] = ds_name
    metrics[quantity] = res

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(coord, sim, "-", label="simpleFoam 80x80")
    ax.plot(ds["axis_values"], ds["field_values"], "o", mfc="none", label="Ghia et al. 1982")
    ax.set_xlabel(axis)
    ax.set_ylabel(field)
    ax.set_title(f"{quantity}, Re=1000: rel. L2 = {res['relative_L2']:.3%}")
    ax.legend()
    ax.grid(alpha=0.3)
    png = out / f"{quantity}.png"
    fig.tight_layout()
    fig.savefig(png, dpi=120)
    plt.close(fig)
    plots.append(str(png))

try:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
except OSError:
    commit = ""
metrics["provenance"] = {
    "numpy": np.__version__,
    "matplotlib": matplotlib.__version__,
    "git_commit": commit,
    "sample_time": sample_time,
    "reference": "ghia_1982",
}
(out / "metrics.json").write_text(json.dumps(metrics, indent=2))
emit(metrics, plots)
