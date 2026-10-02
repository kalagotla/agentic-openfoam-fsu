"""Centerline validation of the Re = 1000 lid-driven cavity against Ghia et al. (1982).

Extracts u(y) at x = 0.5 and v(x) at y = 0.5 from the `centerlines` sets
function object, scores both with the tested `compare_profiles` primitive
(default tolerance = 5% of the reference range, i.e. relative L2 <= 0.05),
and locates the primary / corner vortices from a stream function integrated
from the cell-centre U field (uniform N x N blockMesh, x-fastest ordering).
"""

import json
import platform
import re
import subprocess
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from validation_mcp.analysis import emit, latest_set, read_set
from validation_mcp.tools import compare_profiles, read_reference

REF_NAME = "ghia_1982"
OUT = Path("postProcessing/analysis")
OUT.mkdir(parents=True, exist_ok=True)

ref = read_reference(REF_NAME)["data"]["datasets"]
ref_u = ref["ghia_re_1000_u_centerline"]
ref_v = ref["ghia_re_1000_v_centerline"]

u_path = latest_set(".", "centerlines", "uCenterline")
v_path = latest_set(".", "centerlines", "vCenterline")
sample_time = u_path.parent.name
y, Uu = read_set(u_path)
x, Uv = read_set(v_path)
u_sim, v_sim = Uu[:, 0], Uv[:, 1]

metrics = {}
for key, axis, field, r in (
    ("u_centerline", y, u_sim, ref_u),
    ("v_centerline", x, v_sim, ref_v),
):
    res = compare_profiles(axis.tolist(), field.tolist(), r["axis_values"], r["field_values"])
    res["relative_L2"] = res["l2_error"] / res["reference_range"]
    res["relative_Linf"] = res["linf_error"] / res["reference_range"]
    metrics[key] = res

# ---- stream function from the cell-centre field --------------------------
def read_internal_vectors(path):
    text = Path(path).read_text()
    m = re.search(r"internalField\s+nonuniform\s+List<vector>\s*(\d+)\s*\(", text)
    n = int(m.group(1))
    body = text[m.end():]
    vals = re.findall(r"\(([^()]+)\)", body)[:n]
    return np.array([[float(t) for t in v.split()] for v in vals])

Uc = read_internal_vectors(Path(sample_time) / "U")
N = int(round(np.sqrt(len(Uc))))
h = 1.0 / N
uc = Uc[:, 0].reshape(N, N)  # [j (y), i (x)]
vc = Uc[:, 1].reshape(N, N)
xc = (np.arange(N) + 0.5) * h
# psi(x, y) = integral_0^y u dy' (psi = 0 on the bottom wall), cell-centre midpoint rule
psi = np.cumsum(uc, axis=0) * h - 0.5 * uc * h
jmin, imin = np.unravel_index(np.argmin(psi), psi.shape)
primary = {"x": float(xc[imin]), "y": float(xc[jmin]), "psi_min": float(psi.min())}

def corner_eddy(mask_x):
    sub = np.where(mask_x[None, :] & (xc[:, None] < 0.5), psi, -np.inf)
    j, i = np.unravel_index(np.argmax(sub), sub.shape)
    return {"x": float(xc[i]), "y": float(xc[j]), "psi_max": float(sub[j, i]),
            "present": bool(sub[j, i] > 0)}

eddies = {"bottom_left": corner_eddy(xc < 0.5), "bottom_right": corner_eddy(xc > 0.5)}
metrics["vortices"] = {"primary": primary, **eddies}

# ---- plots ---------------------------------------------------------------
plots = []
fig, ax = plt.subplots(figsize=(4.5, 5))
ax.plot(u_sim, y, "-", label=f"simpleFoam {N}x{N}")
ax.plot(ref_u["field_values"], ref_u["axis_values"], "o", mfc="none", label="Ghia et al. (1982)")
ax.set_xlabel("u / U_lid"); ax.set_ylabel("y / L")
ax.set_title(f"u at x = 0.5, Re = 1000 (rel. L2 = {metrics['u_centerline']['relative_L2']:.3f})")
ax.legend(); ax.grid(alpha=0.3); fig.tight_layout()
p = OUT / "u_centerline.png"; fig.savefig(p, dpi=130); plt.close(fig); plots.append(str(p))

fig, ax = plt.subplots(figsize=(5.5, 4))
ax.plot(x, v_sim, "-", label=f"simpleFoam {N}x{N}")
ax.plot(ref_v["axis_values"], ref_v["field_values"], "o", mfc="none", label="Ghia et al. (1982)")
ax.set_xlabel("x / L"); ax.set_ylabel("v / U_lid")
ax.set_title(f"v at y = 0.5, Re = 1000 (rel. L2 = {metrics['v_centerline']['relative_L2']:.3f})")
ax.legend(); ax.grid(alpha=0.3); fig.tight_layout()
p = OUT / "v_centerline.png"; fig.savefig(p, dpi=130); plt.close(fig); plots.append(str(p))

fig, ax = plt.subplots(figsize=(5, 5))
X, Y = np.meshgrid(xc, xc)
neg = np.linspace(psi.min(), 0, 15)[:-1]
pos = np.geomspace(1e-7, max(psi.max(), 2e-7), 6)
ax.contour(X, Y, psi, levels=neg, colors="k", linewidths=0.7)
ax.contour(X, Y, psi, levels=pos, colors="tab:red", linewidths=0.7)
ax.plot(primary["x"], primary["y"], "b+", ms=10)
ax.set_aspect("equal"); ax.set_xlabel("x / L"); ax.set_ylabel("y / L")
ax.set_title("Stream function (black: primary, red: corner eddies)")
fig.tight_layout()
p = OUT / "streamfunction.png"; fig.savefig(p, dpi=130); plt.close(fig); plots.append(str(p))

# ---- provenance-stamped metrics.json ------------------------------------
try:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            timeout=10).stdout.strip() or None
except Exception:
    commit = None
provenance = {
    "reference_dataset": REF_NAME,
    "reference_columns": ["ghia_re_1000_u_centerline", "ghia_re_1000_v_centerline"],
    "sample_time": sample_time,
    "grid": f"{N}x{N}",
    "numpy": np.__version__,
    "matplotlib": matplotlib.__version__,
    "python": platform.python_version(),
    "git_commit": commit,
}
(OUT / "metrics.json").write_text(json.dumps({"metrics": metrics, "provenance": provenance}, indent=2))

emit(metrics, plots)
