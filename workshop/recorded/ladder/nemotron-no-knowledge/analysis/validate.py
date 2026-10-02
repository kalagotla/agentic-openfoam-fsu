#!/usr/bin/env python3
"""
Validation script for lid-driven cavity at Re=1000.
Reads sampled centerline velocity profiles and compares with Ghia et al. (1982).
"""
import numpy as np
from pathlib import Path
from validation_mcp.tools import compare_profiles, read_reference
from validation_mcp.analysis import latest_set, read_set, emit

def main():
    case_dir = Path(".")
    
    # Find latest sampled data - function object name is "sampleCenterlines"
    post_dir = case_dir / "postProcessing" / "sampleCenterlines"
    if not post_dir.exists():
        print(f"ERROR: No {post_dir} directory found")
        return
    
    time_dirs = sorted([d for d in post_dir.iterdir() if d.is_dir()], 
                       key=lambda x: float(x.name))
    if not time_dirs:
        print("ERROR: No time directories in postProcessing/sampleCenterlines")
        return
    
    latest_time = time_dirs[-1]
    print(f"Reading sampled data from time {latest_time.name}...")
    
    # Read vertical centerline (u at x=0.5)
    u_file = latest_time / "centerlineVertical_U.xy"
    # Read horizontal centerline (v at y=0.5)
    v_file = latest_time / "centerlineHorizontal_U.xy"
    
    if not u_file.exists() or not v_file.exists():
        print(f"ERROR: Sample files not found in {latest_time}")
        print(f"  Looking for: {u_file}, {v_file}")
        return
    
    u_data = np.loadtxt(u_file)
    v_data = np.loadtxt(v_file)
    
    # u_data: y, Ux, Uy, Uz
    # v_data: x, Ux, Uy, Uz
    
    u_y = u_data[:, 0]
    u_u = u_data[:, 1]  # Ux component
    
    v_x = v_data[:, 0]
    v_v = v_data[:, 2]  # Uy component
    
    # Read reference data
    ref = read_reference("ghia_1982")
    ref_u = ref["data"]["datasets"]["ghia_re_1000_u_centerline"]
    ref_v = ref["data"]["datasets"]["ghia_re_1000_v_centerline"]
    
    ref_u_y = np.array(ref_u["axis_values"])
    ref_u_u = np.array(ref_u["field_values"])
    ref_v_x = np.array(ref_v["axis_values"])
    ref_v_v = np.array(ref_v["field_values"])
    
    # Compare u centerline
    print("\nComparing u centerline (x=0.5)...")
    result_u = compare_profiles(
        sim_axis=u_y.tolist(),
        sim_field=u_u.tolist(),
        ref_axis=ref_u_y.tolist(),
        ref_field=ref_u_u.tolist(),
        tolerance=0.05
    )
    
    # Compare v centerline
    print("\nComparing v centerline (y=0.5)...")
    result_v = compare_profiles(
        sim_axis=v_x.tolist(),
        sim_field=v_v.tolist(),
        ref_axis=ref_v_x.tolist(),
        ref_field=ref_v_v.tolist(),
        tolerance=0.05
    )
    
    # Print results
    print(f"\nu centerline: L2 error = {result_u['l2_error']:.6f}, L_inf error = {result_u['linf_error']:.6f}")
    print(f"  Within tolerance: {result_u['within_tolerance']}")
    print(f"v centerline: L2 error = {result_v['l2_error']:.6f}, L_inf error = {result_v['linf_error']:.6f}")
    print(f"  Within tolerance: {result_v['within_tolerance']}")
    
    # Overall verdict
    overall_pass = result_u['within_tolerance'] and result_v['within_tolerance']
    print(f"\nOverall validation: {'PASS' if overall_pass else 'FAIL'}")
    
    # Emit result for validation server
    metrics = {
        "u_centerline": {
            "l2_error": result_u['l2_error'],
            "linf_error": result_u['linf_error'],
            "within_tolerance": result_u['within_tolerance']
        },
        "v_centerline": {
            "l2_error": result_v['l2_error'],
            "linf_error": result_v['linf_error'],
            "within_tolerance": result_v['within_tolerance']
        },
        "overall_pass": overall_pass
    }
    emit(metrics, [])

if __name__ == "__main__":
    main()