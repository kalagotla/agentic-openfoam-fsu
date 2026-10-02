# Plan: lid-driven cavity, Re = 1000 (simpleFoam, laminar)

Execute this plan exactly. One tool call per numbered step, in order, with the
arguments copied verbatim. Run straight through without pausing for approval:
do not stop between steps and do not ask questions. If a step fails, report its
`reason` and `log_tail` and stop.

Case directory: `/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000`

Sources: template tutorial `incompressible/icoFoam/cavity/cavity` (geometry,
patches, BCs) with the SIMPLE controls of `incompressible/simpleFoam/pitzDaily`,
as the promoted corpus entry
`corpus/incompressible/icoFoam/cavity/cavity.md` prescribes (pRefCell/pRefValue
in the SIMPLE block, residualControl 1e-5, grid refined well beyond 20x20).

## Setup

1. `openfoam_prepare_case` `{"case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "overwrite": true}`

2. `write` — path `/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000/system/sampleCenterlines`, content:

```
centerlines
{
    type                sets;
    libs                (sampling);
    writeControl        writeTime;
    interpolationScheme cellPoint;
    setFormat           raw;
    fields              (U);

    sets
    {
        vertical
        {
            type    uniform;
            axis    y;
            start   (0.5 0 0.05);
            end     (0.5 1 0.05);
            nPoints 201;
        }
        horizontal
        {
            type    uniform;
            axis    x;
            start   (0 0.5 0.05);
            end     (1 0.5 0.05);
            nPoints 201;
        }
    }
}
```

3. `openfoam_copy_tutorial_dict` `{"tutorial_path": "incompressible/simpleFoam/pitzDaily/system/controlDict", "case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "dict_name": "controlDict", "subdir": "system", "replacements": {"endTime         2000;": "endTime         5000;", "writeInterval   100;": "writeInterval   1000;", "#includeFunc streamlines": "#include \"sampleCenterlines\""}}`

4. `openfoam_copy_tutorial_dict` `{"tutorial_path": "incompressible/simpleFoam/pitzDaily/system/fvSchemes", "case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "dict_name": "fvSchemes", "subdir": "system"}`

5. `openfoam_copy_tutorial_dict` `{"tutorial_path": "incompressible/simpleFoam/pitzDaily/system/fvSolution", "case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "dict_name": "fvSolution", "subdir": "system", "replacements": {"consistent      yes;": "consistent      yes; pRefCell 0; pRefValue 0;", "p               1e-2;": "p               1e-5;", "U               1e-3;": "U               1e-5;"}}`

6. `openfoam_copy_tutorial_dict` `{"tutorial_path": "incompressible/icoFoam/cavity/cavity/system/blockMeshDict", "case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "dict_name": "blockMeshDict", "subdir": "system", "replacements": {"scale   0.1;": "scale   1;", "(20 20 1)": "(80 80 1)"}}`

7. `openfoam_copy_tutorial_dict` `{"tutorial_path": "incompressible/icoFoam/cavity/cavity/constant/transportProperties", "case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "dict_name": "transportProperties", "subdir": "constant", "replacements": {"nu              0.01;": "transportModel  Newtonian; nu              0.001;"}}`

8. `openfoam_copy_tutorial_dict` `{"tutorial_path": "incompressible/simpleFoam/pitzDaily/constant/turbulenceProperties", "case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "dict_name": "turbulenceProperties", "subdir": "constant", "replacements": {"simulationType      RAS;": "simulationType      laminar;"}}`

9. `openfoam_copy_tutorial_dict` `{"tutorial_path": "incompressible/icoFoam/cavity/cavity/0/U", "case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "dict_name": "U", "subdir": "0"}`

10. `openfoam_copy_tutorial_dict` `{"tutorial_path": "incompressible/icoFoam/cavity/cavity/0/p", "case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "dict_name": "p", "subdir": "0"}`

11. `write` — path `/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000/analysis/validate.py`, content:

```python
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
```

12. `openfoam_record_step` `{"case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "phase": "solver_config", "status": "ok", "title": "Case set up: cavity geometry, simpleFoam with pitzDaily SIMPLE controls, 80x80 grid", "decision": "Unit square cavity (scale 0.1 -> 1) from incompressible/icoFoam/cavity/cavity (scenario-specified template); simpleFoam laminar (scenario-specified) with fvSchemes/fvSolution/controlDict from incompressible/simpleFoam/pitzDaily, pRefCell 0 / pRefValue 0 in SIMPLE, residualControl p 1e-5 / U 1e-5 (corpus entry); nu = 0.001 so Re = 1*1/0.001 = 1000 (scenario-specified), with transportModel Newtonian added because simpleFoam's singlePhaseTransportModel requires it and icoFoam's transportProperties omits it (a first attempt stopped with 'transportModel not found'); uniform 80x80x1 grid (agent's call, from the corpus entry).", "why": "The corpus entry for this template swaps in pitzDaily's SIMPLE controls for simpleFoam, carries pRefCell/pRefValue into the SIMPLE block because a closed all-wall domain with zeroGradient p fixes pressure only up to a constant, and replaces pitzDaily's residualControl (p 1e-2, U 1e-3), which stopped the cavity solve after about 3 orders, with 1e-5 to meet a 4-order drop. It lists the tutorial's 20x20 grid as not suitable for quantitative validation; 40x40 and 80x80 passed at Re = 400. Re = 1000 has thinner wall layers than Re = 400, so the finest validated grid is used. L = U_lid = 1 makes the solution directly comparable with Ghia's non-dimensional profiles.", "citations": ["corpus/incompressible/icoFoam/cavity/cavity.md", "ghia_1982", "of_user_guide_urf"], "alternatives": "The tutorial's 20x20 grid (rejected by the corpus entry for quantitative validation). The template's own transient icoFoam (the scenario fixes simpleFoam).", "when_it_breaks": "A steady solver presumes a steady solution exists; if the cavity flow at this Re were unsteady, SIMPLE would stall or oscillate instead of converging. The 80x80 grid is validated only at Re = 400; at Re = 1000 the validation below decides whether it is fine enough.", "tables": {"Boundary conditions": [{"patch": "movingWall", "U": "fixedValue (1 0 0)", "p": "zeroGradient"}, {"patch": "fixedWalls", "U": "noSlip", "p": "zeroGradient"}, {"patch": "frontAndBack", "U": "empty", "p": "empty"}]}}`

## Mesh

13. `openfoam_run_blockmesh` `{"case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000"}`

14. `openfoam_check_mesh` `{"case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000"}`

15. `openfoam_record_step` with `case_path` `/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000`, `phase` `"mesh_quality"`, `status` `"ok"` if step 14 reported the mesh OK, otherwise `"warning"`, `title` `"checkMesh on the 80x80x1 grid"`, and a `tables` entry `"checkMesh metrics"` with one row each (`metric`, `value`) for the cell count, max non-orthogonality, max skewness and max aspect ratio, using the numbers step 14 returned.

## Solve

16. `openfoam_run_solver` `{"case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000", "solver": "simpleFoam", "timeout_s": 900}`

17. `openfoam_record_step` with `case_path` `/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000`, `phase` `"convergence"`, `status` `"ok"` if step 16 succeeded, otherwise `"error"`, `title` `"simpleFoam run"`, and `details` stating the final iteration and the final residuals of Ux, Uy and p as step 16 returned them (include its `log_tail` if it failed).

## Validate

18. `validation_run_analysis` `{"case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000"}`

19. `openfoam_record_step` with these arguments:
    - `case_path`: `/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000`
    - `phase`: `"validation"`
    - `status`: `"ok"` if both `u_centerline.within_tolerance` and `v_centerline.within_tolerance` from step 18 are true, otherwise `"error"`
    - `title`: `"Centerline u(y), v(x) vs Ghia et al. (1982), Re = 1000"`
    - `decision`: `"Score the centerline profiles against ghia_re_1000_u_centerline and ghia_re_1000_v_centerline with a 5% relative-L2 tolerance (scenario-specified)."`
    - `why`: `"Ghia, Ghia & Shin (1982) tabulate u(y) at x = 0.5 and v(x) at y = 0.5 for Re = 1000; the corpus entry validated the same template and sampling against the Re = 400 columns."`
    - `citations`: `["ghia_1982", "corpus/incompressible/icoFoam/cavity/cavity.md"]`
    - `tables`: `{"Comparison vs ghia_1982": [{"profile": "u_centerline", "L2": <u_centerline.l2_error>, "L_inf": <u_centerline.linf_error>, "relative_L2": <u_centerline.relative_L2>, "tolerance": <u_centerline.tolerance_threshold>, "verdict": "pass" or "fail"}, {"profile": "v_centerline", "L2": <v_centerline.l2_error>, "L_inf": <v_centerline.linf_error>, "relative_L2": <v_centerline.relative_L2>, "tolerance": <v_centerline.tolerance_threshold>, "verdict": "pass" or "fail"}]}` with every value filled in from step 18's metrics (verdict is "pass" when `within_tolerance` is true).
    - `details`: `"Overlays: postProcessing/analysis/u_centerline.png, postProcessing/analysis/v_centerline.png"`

20. `openfoam_finalize_report` `{"case_path": "/home/kalagotla/agentic-openfoam-fsu/cases/work/lid-cavity-re1000"}`

Then reply with a short summary: the validation verdict and the relative-L2 of each profile.
