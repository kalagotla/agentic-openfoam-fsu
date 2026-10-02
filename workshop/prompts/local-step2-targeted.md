# Targeted prompt: Step 2 on a local model

This is **user input**, not agent instructions: what a researcher writes
after reading the promoted corpus entry for
`incompressible/icoFoam/cavity/cavity` (Step 1's output). It is deliberately
specific to this case. Every value in it comes from that entry and the
template tutorials; nothing is new knowledge. The point it makes: a local
model that cannot plan a case on its own executes a precise plan reliably.

Use it with Kilo's `cfd-local` agent after Step 1's entry is promoted:

```bash
kilo run --agent cfd-local --auto "$(sed -n '/^---$/,$p' workshop/prompts/local-step2-targeted.md | sed 1d)"
```

or paste everything below the line into `kilo` (Tab to `cfd-local`).

---

Execute this plan exactly. One tool call per numbered item, in order, with
the JSON shown as the arguments, copied as-is. Do not read tutorials and do
not add steps. Run straight through without pausing; I approve every phase.
If a call returns `success: false`, stop and report its `reason` and
`log_tail`.

1. `consultant_get_tutorial_annotation`
   `{"tutorial_path": "incompressible/icoFoam/cavity/cavity"}`
2. `openfoam_prepare_case`
   `{"case_path": "cases/work/lid-cavity-re1000"}`
3. `openfoam_copy_tutorial_dict`
   `{"case_path": "cases/work/lid-cavity-re1000", "tutorial_path": "incompressible/icoFoam/cavity/cavity/system/blockMeshDict", "dict_name": "blockMeshDict", "subdir": "system", "replacements": {"scale 0.1;": "scale 1;", "(20 20 1)": "(80 80 1)"}}`
4. `openfoam_copy_tutorial_dict`
   `{"case_path": "cases/work/lid-cavity-re1000", "tutorial_path": "incompressible/simpleFoam/pitzDaily/system/controlDict", "dict_name": "controlDict", "subdir": "system", "replacements": {"endTime 2000;": "endTime 5000;", "writeInterval 100;": "writeInterval 1000;", "#includeFunc streamlines": "#include \"centreline\""}}`
5. `write` the file `cases/work/lid-cavity-re1000/system/centreline` with this content:

   ```
   centreline
   {
       type            sets;
       libs            (sampling);
       writeControl    writeTime;
       interpolationScheme cellPoint;
       setFormat       raw;
       fields          (U);
       sets
       {
           uLine { type uniform; axis y; start (0.5 0 0.05); end (0.5 1 0.05); nPoints 129; }
           vLine { type uniform; axis x; start (0 0.5 0.05); end (1 0.5 0.05); nPoints 129; }
       }
   }
   ```
6. `openfoam_copy_tutorial_dict`
   `{"case_path": "cases/work/lid-cavity-re1000", "tutorial_path": "incompressible/simpleFoam/pitzDaily/system/fvSchemes", "dict_name": "fvSchemes", "subdir": "system"}`
7. `openfoam_copy_tutorial_dict`
   `{"case_path": "cases/work/lid-cavity-re1000", "tutorial_path": "incompressible/simpleFoam/pitzDaily/system/fvSolution", "dict_name": "fvSolution", "subdir": "system", "replacements": {"p 1e-2;": "p 1e-5;", "U 1e-3;": "U 1e-5;", "consistent yes;": "consistent yes; pRefCell 0; pRefValue 0;"}}`
8. `openfoam_copy_tutorial_dict`
   `{"case_path": "cases/work/lid-cavity-re1000", "tutorial_path": "incompressible/simpleFoam/pitzDaily/constant/transportProperties", "dict_name": "transportProperties", "subdir": "constant", "replacements": {"nu 1e-05;": "nu 0.001;"}}`
9. `openfoam_copy_tutorial_dict`
   `{"case_path": "cases/work/lid-cavity-re1000", "tutorial_path": "incompressible/simpleFoam/pitzDaily/constant/turbulenceProperties", "dict_name": "turbulenceProperties", "subdir": "constant", "replacements": {"simulationType RAS;": "simulationType laminar;"}}`
10. `openfoam_copy_tutorial_dict`
    `{"case_path": "cases/work/lid-cavity-re1000", "tutorial_path": "incompressible/icoFoam/cavity/cavity/0/U", "dict_name": "U", "subdir": "0"}`
11. `openfoam_copy_tutorial_dict`
    `{"case_path": "cases/work/lid-cavity-re1000", "tutorial_path": "incompressible/icoFoam/cavity/cavity/0/p", "dict_name": "p", "subdir": "0"}`
12. `openfoam_record_step`
    `{"case_path": "cases/work/lid-cavity-re1000", "phase": "geometry", "status": "ok", "title": "Setup from the corpus entry: icoFoam/cavity geometry, pitzDaily SIMPLE controls, 80x80, nu 0.001", "decision": "Apply the promoted corpus entry for incompressible/icoFoam/cavity/cavity at Re = 1000", "citations": ["corpus/incompressible/icoFoam/cavity/cavity.md"]}`
13. `openfoam_run_blockmesh` `{"case_path": "cases/work/lid-cavity-re1000"}`
14. `openfoam_check_mesh` `{"case_path": "cases/work/lid-cavity-re1000"}`
15. `openfoam_run_solver` `{"case_path": "cases/work/lid-cavity-re1000", "solver": "simpleFoam"}`
16. `openfoam_record_step`
    `{"case_path": "cases/work/lid-cavity-re1000", "phase": "convergence", "status": "ok", "title": "80x80 mesh, simpleFoam converged"}`
    and put the cell count (step 13) and final residuals (step 15) in `body`.
17. `write` the file `cases/work/lid-cavity-re1000/analysis/validate.py` with this content:

    ```python
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
    ```
18. `validation_run_analysis` `{"case_path": "cases/work/lid-cavity-re1000"}`
19. `openfoam_record_step`
    `{"case_path": "cases/work/lid-cavity-re1000", "phase": "validation", "status": "ok", "title": "Ghia Re=1000 centerlines vs the 5% band", "citations": ["ghia_1982", "corpus/incompressible/icoFoam/cavity/cavity.md"]}`
    with the two `l2_error` values from step 18 in `body`; use `"status": "error"` if either `within_tolerance` is false.
20. `openfoam_finalize_report` `{"case_path": "cases/work/lid-cavity-re1000"}`
    Then reply with the two L2 values and the verdict.
