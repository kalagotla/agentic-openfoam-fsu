"""Validation of Re=1000 lid-driven cavity against Ghia et al. (1982).

Reads centerline samples written by the centerlineSample functionObject
(postProcessing/centerlineSample/<latest>/u_centerline_U.xy and
v_centerline_U.xy), scores u(y) at x=0.5 and v(x) at y=0.5 with
validation_mcp.compare_profiles against ghia_re_1000_u_centerline and
ghia_re_1000_v_centerline, and produces overlays in postProcessing/analysis/.
Tolerance is 5% relative L2 as specified in the reference.
"""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from validation_mcp.tools import compare_profiles, read_reference

CASE = Path.cwd()
OUT_DIR = CASE / "postProcessing" / "analysis"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sample_root = CASE / "postProcessing" / "centerlineSample"
# find latest time directory
times = [d for d in sample_root.iterdir() if d.is_dir()]
def time_key(d):
    try:
        return float(d.name)
    except ValueError:
        return -1.0
latest = max(times, key=time_key)

u_path = latest / "u_centerline_U.xy"
v_path = latest / "v_centerline_U.xy"

u_data = np.loadtxt(u_path)   # columns: coord, Ux, Uy, Uz
v_data = np.loadtxt(v_path)   # columns: coord, Ux, Uy, Uz

sim_u_coord = u_data[:, 0]
sim_u = u_data[:, 1]

sim_v_coord = v_data[:, 0]
sim_v = v_data[:, 2]

ref = read_reference("ghia_1982")
if not ref.get("success"):
    raise SystemExit(f"read_reference failed: {ref}")
datasets = ref["data"]["datasets"]

ref_u = datasets["ghia_re_1000_u_centerline"]
ref_v = datasets["ghia_re_1000_v_centerline"]

res_u = compare_profiles(
    sim_u_coord.tolist(),
    sim_u.tolist(),
    ref_u["axis_values"],
    ref_u["field_values"]
)
res_v = compare_profiles(
    sim_v_coord.tolist(),
    sim_v.tolist(),
    ref_v["axis_values"],
    ref_v["field_values"]
)

fig, axs = plt.subplots(1, 2, figsize=(10, 4.5))
ax = axs[0]
ax.plot(sim_u, sim_u_coord, "-", label="simpleFoam")
ax.plot(ref_u["field_values"], ref_u["axis_values"], "o", mfc="none", label="Ghia 1982")
ax.set_xlabel("u / U_lid")
ax.set_ylabel("y / L")
ax.set_title(f"u at x=0.5  L2={res_u.get('l2_error',0):.4f}")
ax.grid(alpha=0.3)
ax.legend()

ax = axs[1]
ax.plot(sim_v_coord, sim_v, "-", label="simpleFoam")
ax.plot(ref_v["axis_values"], ref_v["field_values"], "o", mfc="none", label="Ghia 1982")
ax.set_xlabel("x / L")
ax.set_ylabel("v / U_lid")
ax.set_title(f"v at y=0.5  L2={res_v.get('l2_error',0):.4f}")
ax.grid(alpha=0.3)
ax.legend()

fig.suptitle(f"Lid-driven cavity Re=1000, sample time {latest.name}")
fig.tight_layout()
plot_path = OUT_DIR / "centerlines_vs_ghia_re1000.png"
fig.savefig(plot_path, dpi=130)
plt.close(fig)

metrics = {
    "sample_time": str(latest.name),
    "u_centerline": res_u,
    "v_centerline": res_v,
    "tolerance_relative_L2": 0.05,
    "all_pass": bool(res_u.get("within_tolerance") and res_v.get("within_tolerance")),
    "provenance": {
        "reference": "ghia_1982",
        "reference_dataset_u": "ghia_re_1000_u_centerline",
        "reference_dataset_v": "ghia_re_1000_v_centerline",
    }
}

print("<<<ANALYSIS_RESULT>>>")
print(json.dumps({"metrics": metrics, "plots": [str(plot_path.relative_to(CASE))]}))
