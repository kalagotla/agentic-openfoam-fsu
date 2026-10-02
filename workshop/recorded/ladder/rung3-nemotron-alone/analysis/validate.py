#!/usr/bin/env python3
"""
Validation script for lid-driven cavity at Re=1000.
Extracts centerline velocity profiles and compares against Ghia et al. (1982).
"""

import numpy as np
import json
import sys
import os

sys.path.insert(0, '/home/kalagotla/agentic-openfoam-fsu')
from validation_mcp.tools import compare_profiles, read_reference


def read_openfoam_field(filepath):
    """Read an OpenFOAM volVectorField or volScalarField file."""
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    # Find the internalField line
    data_start = None
    for i, line in enumerate(lines):
        if 'internalField' in line and 'nonuniform' in line:
            data_start = i + 1
            break
    
    if data_start is None:
        raise ValueError("Could not find internalField in file")
    
    # Read the count
    count = int(lines[data_start].strip())
    data_start += 1
    
    # Skip the opening parenthesis
    if lines[data_start].strip() == '(':
        data_start += 1
    
    # Read the data
    values = []
    for i in range(data_start, data_start + count):
        line = lines[i].strip()
        if line == ')':
            break
        # Parse vector (x y z)
        parts = line.replace('(', '').replace(')', '').split()
        values.append([float(p) for p in parts])
    
    return np.array(values)


def get_cell_centers_2d(nx, ny):
    """Get cell centers for structured 2D mesh."""
    x = np.linspace(0.5/nx, 1 - 0.5/nx, nx)
    y = np.linspace(0.5/ny, 1 - 0.5/ny, ny)
    return x, y


def reshape_field(U, nx, ny):
    """Reshape flat field array to 2D (nx, ny, 3) assuming C-order (x varies fastest)."""
    # OpenFOAM writes in order: x varies fastest, then y, then z
    # For 2D (nx, ny, 1), the order is: for j in range(ny): for i in range(nx): cell(i,j)
    return U.reshape((ny, nx, 3)).transpose(1, 0, 2)  # Now (nx, ny, 3) with x first


def interpolate_centerline_u(U_2d, x_coords, y_coords, x_target=0.5):
    """Interpolate u-velocity at x=x_target for all y."""
    nx = U_2d.shape[0]
    
    # Find the two x-indices that bracket x_target
    idx_right = np.searchsorted(x_coords, x_target)
    idx_left = idx_right - 1
    
    if idx_left < 0:
        idx_left = 0
        idx_right = 1
    elif idx_right >= nx:
        idx_right = nx - 1
        idx_left = nx - 2
    
    x_left = x_coords[idx_left]
    x_right = x_coords[idx_right]
    
    # Linear interpolation weight
    if abs(x_right - x_left) < 1e-12:
        weight = 0.5
    else:
        weight = (x_target - x_left) / (x_right - x_left)
    
    # Interpolate u component (index 0) at each y
    u_left = U_2d[idx_left, :, 0]
    u_right = U_2d[idx_right, :, 0]
    u_interp = (1 - weight) * u_left + weight * u_right
    
    return y_coords, u_interp


def interpolate_centerline_v(U_2d, x_coords, y_coords, y_target=0.5):
    """Interpolate v-velocity at y=y_target for all x."""
    ny = U_2d.shape[1]
    
    # Find the two y-indices that bracket y_target
    idx_top = np.searchsorted(y_coords, y_target)
    idx_bottom = idx_top - 1
    
    if idx_bottom < 0:
        idx_bottom = 0
        idx_top = 1
    elif idx_top >= ny:
        idx_top = ny - 1
        idx_bottom = ny - 2
    
    y_bottom = y_coords[idx_bottom]
    y_top = y_coords[idx_top]
    
    # Linear interpolation weight
    if abs(y_top - y_bottom) < 1e-12:
        weight = 0.5
    else:
        weight = (y_target - y_bottom) / (y_top - y_bottom)
    
    # Interpolate v component (index 1) at each x
    v_bottom = U_2d[:, idx_bottom, 1]
    v_top = U_2d[:, idx_top, 1]
    v_interp = (1 - weight) * v_bottom + weight * v_top
    
    return x_coords, v_interp


def main():
    case_path = '/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000-r3'
    time_dir = '5000'
    
    # Read U field
    U_file = os.path.join(case_path, time_dir, 'U')
    U = read_openfoam_field(U_file)
    
    nx = ny = 80
    x_coords, y_coords = get_cell_centers_2d(nx, ny)
    
    # Reshape to 2D
    U_2d = reshape_field(U, nx, ny)
    
    # Interpolate centerline profiles at exact x=0.5 and y=0.5
    y_u, u_profile = interpolate_centerline_u(U_2d, x_coords, y_coords, x_target=0.5)
    x_v, v_profile = interpolate_centerline_v(U_2d, x_coords, y_coords, y_target=0.5)
    
    print(f"Extracted u-centerline: {len(y_u)} points at x=0.5 (interpolated)")
    print(f"Extracted v-centerline: {len(x_v)} points at y=0.5 (interpolated)")
    
    # Load reference data
    ref_data = read_reference('ghia_1982')
    u_ref = ref_data['data']['datasets']['ghia_re_1000_u_centerline']
    v_ref = ref_data['data']['datasets']['ghia_re_1000_v_centerline']
    
    ref_y = np.array(u_ref['axis_values'])
    ref_u = np.array(u_ref['field_values'])
    ref_x = np.array(v_ref['axis_values'])
    ref_v = np.array(v_ref['field_values'])
    
    print(f"Reference u: {len(ref_y)} points")
    print(f"Reference v: {len(ref_x)} points")
    
    # Compare profiles
    u_result = compare_profiles(
        sim_axis=y_u, sim_field=u_profile,
        ref_axis=ref_y, ref_field=ref_u,
        tolerance=None  # Use default 5% of reference range
    )
    
    v_result = compare_profiles(
        sim_axis=x_v, sim_field=v_profile,
        ref_axis=ref_x, ref_field=ref_v,
        tolerance=None
    )
    
    print(f"\nu-centerline (x=0.5):")
    print(f"  L2 error: {u_result['l2_error']:.6f}")
    print(f"  L_inf error: {u_result['linf_error']:.6f}")
    print(f"  Within tolerance: {u_result['within_tolerance']}")
    if 'tolerance' in u_result:
        print(f"  Tolerance: {u_result['tolerance']:.6f}")
    
    print(f"\nv-centerline (y=0.5):")
    print(f"  L2 error: {v_result['l2_error']:.6f}")
    print(f"  L_inf error: {v_result['linf_error']:.6f}")
    print(f"  Within tolerance: {v_result['within_tolerance']}")
    if 'tolerance' in v_result:
        print(f"  Tolerance: {v_result['tolerance']:.6f}")
    
    # Output metrics
    metrics = {
        'u_centerline': {
            'l2_error': float(u_result['l2_error']),
            'linf_error': float(u_result['linf_error']),
            'within_tolerance': bool(u_result['within_tolerance']),
            'tolerance': float(u_result.get('tolerance', 0.05))
        },
        'v_centerline': {
            'l2_error': float(v_result['l2_error']),
            'linf_error': float(v_result['linf_error']),
            'within_tolerance': bool(v_result['within_tolerance']),
            'tolerance': float(v_result.get('tolerance', 0.05))
        }
    }
    
    # Create plots
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    os.makedirs(os.path.join(case_path, 'postProcessing', 'analysis'), exist_ok=True)
    
    # Plot u centerline
    plt.figure(figsize=(10, 5))
    plt.subplot(1, 2, 1)
    plt.plot(ref_y, ref_u, 'ko-', label='Ghia Re=1000', markersize=4)
    plt.plot(y_u, u_profile, 'b-', label='OpenFOAM (80x80)', linewidth=2)
    plt.xlabel('y')
    plt.ylabel('u')
    plt.title('u-velocity at x=0.5')
    plt.legend()
    plt.grid(True)
    
    # Plot v centerline
    plt.subplot(1, 2, 2)
    plt.plot(ref_x, ref_v, 'ko-', label='Ghia Re=1000', markersize=4)
    plt.plot(x_v, v_profile, 'r-', label='OpenFOAM (80x80)', linewidth=2)
    plt.xlabel('x')
    plt.ylabel('v')
    plt.title('v-velocity at y=0.5')
    plt.legend()
    plt.grid(True)
    
    plt.tight_layout()
    plot_path = os.path.join(case_path, 'postProcessing', 'analysis', 'centerline_comparison.png')
    plt.savefig(plot_path, dpi=150)
    plt.close()
    
    print(f"\nPlot saved to: {plot_path}")
    
    # Print sentinel
    print(f"<<<ANALYSIS_RESULT>>>")
    print(json.dumps({"metrics": metrics, "plots": [plot_path]}))
    
    # Overall pass/fail
    overall_pass = metrics['u_centerline']['within_tolerance'] and metrics['v_centerline']['within_tolerance']
    sys.exit(0 if overall_pass else 1)


if __name__ == '__main__':
    main()