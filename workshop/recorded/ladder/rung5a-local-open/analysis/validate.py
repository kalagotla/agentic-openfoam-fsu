#!/usr/bin/env python3
import os
import numpy as np
from validation_mcp.analysis import latest_set, read_set, emit
from validation_mcp.tools import read_reference, compare_profiles

case_path = os.getcwd()

ref = read_reference("ghia_1982")
u_ref_axis = np.array(ref["data"]["datasets"]["ghia_re_1000_u_centerline"]["axis_values"])
u_ref_vals = np.array(ref["data"]["datasets"]["ghia_re_1000_u_centerline"]["field_values"])
v_ref_axis = np.array(ref["data"]["datasets"]["ghia_re_1000_v_centerline"]["axis_values"])
v_ref_vals = np.array(ref["data"]["datasets"]["ghia_re_1000_v_centerline"]["field_values"])

# Find sample files
u_path = latest_set(case_path, "sampleU", "U_centerline_U.xy")
v_path = latest_set(case_path, "sampleV", "V_centerline_U.xy")

metrics = {}
plots = []

if u_path and v_path:
    # read_set returns (coord, values) for the sampled set
    u_coord, u_vals = read_set(u_path)
    v_coord, v_vals = read_set(v_path)
    # u_coord is y, v_coord is x
    u_sim = np.interp(u_ref_axis, u_coord, u_vals)
    v_sim = np.interp(v_ref_axis, v_coord, v_vals)
    u_cmp = compare_profiles(u_ref_axis, u_sim, u_ref_axis, u_ref_vals)
    v_cmp = compare_profiles(v_ref_axis, v_sim, v_ref_axis, v_ref_vals)
    metrics["u_centerline_L2"] = float(u_cmp["L2"])
    metrics["v_centerline_L2"] = float(v_cmp["L2"])
    metrics["u_centerline_pass"] = u_cmp["L2"] <= 0.05
    metrics["v_centerline_pass"] = v_cmp["L2"] <= 0.05
else:
    metrics["u_centerline_L2"] = None
    metrics["v_centerline_L2"] = None
    metrics["u_centerline_pass"] = False
    metrics["v_centerline_pass"] = False

emit(metrics, plots)
