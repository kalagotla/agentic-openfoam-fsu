#!/usr/bin/env python3
"""
Validation script for Re=1000 lid-driven cavity case.
Compares centerline u(y) and v(x) profiles against Ghia et al. (1982) reference.
"""
import json
import numpy as np
import sys
from validation_mcp.tools import compare_profiles, read_reference

def read_xy_file(filepath):
    """Read OpenFOAM sets .xy file: each line has x y u v (or y x u v)."""
    data = np.loadtxt(filepath)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    # Columns: coordinate, u, v, w (for 2D, w is 0)
    coord = data[:, 0]
    u = data[:, 1]
    v = data[:, 2]
    return coord, u, v

def main():
    case_path = "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000-rec"
    
    # Read reference data - pass string name
    ref_data = read_reference("ghia_1982")
    ref = ref_data["data"]
    
    # Get Re=1000 reference datasets
    ref_u = ref["datasets"]["ghia_re_1000_u_centerline"]
    ref_v = ref["datasets"]["ghia_re_1000_v_centerline"]
    
    ref_u_y = np.array(ref_u["axis_values"])
    ref_u_vals = np.array(ref_u["field_values"])
    ref_v_x = np.array(ref_v["axis_values"])
    ref_v_vals = np.array(ref_v["field_values"])
    
    # Read simulation data (latest time = 420)
    sim_u_y, sim_u_u, _ = read_xy_file(f"{case_path}/postProcessing/centerline_u/420/u_centerline_U.xy")
    sim_v_x, _, sim_v_v = read_xy_file(f"{case_path}/postProcessing/centerline_v/420/v_centerline_U.xy")
    
    # Compare u centerline (u vs y at x=0.5)
    u_tol = 0.05 * (max(ref_u_vals) - min(ref_u_vals))
    u_result = compare_profiles(sim_u_y.tolist(), sim_u_u.tolist(), ref_u_y.tolist(), ref_u_vals.tolist(), u_tol)
    
    # Compare v centerline (v vs x at y=0.5)
    v_tol = 0.05 * (max(ref_v_vals) - min(ref_v_vals))
    v_result = compare_profiles(sim_v_x.tolist(), sim_v_v.tolist(), ref_v_x.tolist(), ref_v_vals.tolist(), v_tol)
    
    # Print results
    print(f"u_centerline L2 error: {u_result.get('l2_error', 'N/A')}, L_inf error: {u_result.get('linf_error', 'N/A')}, within_tol: {u_result.get('within_tolerance', 'N/A')}")
    print(f"v_centerline L2 error: {v_result.get('l2_error', 'N/A')}, L_inf error: {v_result.get('linf_error', 'N/A')}, within_tol: {v_result.get('within_tolerance', 'N/A')}")
    
    # Output sentinel for validation server
    metrics = {
        "u_centerline": {
            "l2_error": u_result.get("l2_error"),
            "linf_error": u_result.get("linf_error"),
            "within_tolerance": u_result.get("within_tolerance"),
            "reference_range": float(max(ref_u_vals) - min(ref_u_vals)),
            "tolerance_absolute": u_tol
        },
        "v_centerline": {
            "l2_error": v_result.get("l2_error"),
            "linf_error": v_result.get("linf_error"),
            "within_tolerance": v_result.get("within_tolerance"),
            "reference_range": float(max(ref_v_vals) - min(ref_v_vals)),
            "tolerance_absolute": v_tol
        }
    }
    
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    # Plot u centerline
    plt.figure(figsize=(8, 6))
    plt.plot(sim_u_y, sim_u_u, 'b-', label='Simulation (80x80)', linewidth=2)
    plt.plot(ref_u_y, ref_u_vals, 'ro', label='Ghia Re=1000', markersize=6)
    plt.xlabel('y')
    plt.ylabel('u / U_lid')
    plt.title('u-velocity along vertical centerline (x=0.5), Re=1000')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(f"{case_path}/postProcessing/analysis/u_centerline_re1000.png", dpi=150)
    plt.close()
    
    # Plot v centerline
    plt.figure(figsize=(8, 6))
    plt.plot(sim_v_x, sim_v_v, 'b-', label='Simulation (80x80)', linewidth=2)
    plt.plot(ref_v_x, ref_v_vals, 'ro', label='Ghia Re=1000', markersize=6)
    plt.xlabel('x')
    plt.ylabel('v / U_lid')
    plt.title('v-velocity along horizontal centerline (y=0.5), Re=1000')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(f"{case_path}/postProcessing/analysis/v_centerline_re1000.png", dpi=150)
    plt.close()
    
    plots = [
        "postProcessing/analysis/u_centerline_re1000.png",
        "postProcessing/analysis/v_centerline_re1000.png"
    ]
    
    print("<<<ANALYSIS_RESULT>>>")
    print(json.dumps({"metrics": metrics, "plots": plots}))

if __name__ == "__main__":
    main()