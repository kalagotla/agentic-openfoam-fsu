import os
import matplotlib.pyplot as plt
from validation_mcp.analysis import latest_set, read_set, emit
from validation_mcp.tools import read_reference, compare_profiles

ref = read_reference("ghia_1982")["data"]["datasets"]
y, U1 = read_set(latest_set(".", "uLine", "U"))
x, U2 = read_set(latest_set(".", "vLine", "U"))
ru, rv = ref["ghia_re_1000_u_centerline"], ref["ghia_re_1000_v_centerline"]
u = compare_profiles(y.tolist(), U1[:, 0].tolist(), ru["axis_values"], ru["field_values"], tolerance=0.05)
v = compare_profiles(x.tolist(), U2[:, 1].tolist(), rv["axis_values"], rv["field_values"], tolerance=0.05)
fig, ax = plt.subplots(1, 2, figsize=(9, 4))
ax[0].plot(U1[:, 0], y, label="OpenFOAM"); ax[0].plot(ru["field_values"], ru["axis_values"], "o", label="Ghia 1982")
ax[1].plot(x, U2[:, 1], label="OpenFOAM"); ax[1].plot(rv["axis_values"], rv["field_values"], "o", label="Ghia 1982")
ax[0].set_title("u(y) at x = 0.5"); ax[1].set_title("v(x) at y = 0.5"); ax[0].legend()
os.makedirs("postProcessing/analysis", exist_ok=True)
fig.savefig("postProcessing/analysis/centerlines.png", dpi=120)
emit({"u_centerline": u, "v_centerline": v}, plots=["postProcessing/analysis/centerlines.png"])
