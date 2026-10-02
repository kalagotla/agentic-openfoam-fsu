# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — PASS: u and v centrelines within 5% of range vs Ghia Re=400

8 steps · 7 decisions · 0 retries · 3 gaps
<!-- END SUMMARY -->

## [09:13:25] geometry / ok — Template: icoFoam/cavity geometry + simpleFoam/pitzDaily SIMPLE controls

- **Decision:** (scenario-specified) 2-D unit square cavity, Re = U_lid L / nu = 1*1/0.0025 = 400, steady laminar simpleFoam; geometry, patches and BCs from incompressible/icoFoam/cavity/cavity; SIMPLE-family fvSchemes/fvSolution structure from incompressible/simpleFoam/pitzDaily (agent's call — icoFoam/cavity is transient PISO and has no SIMPLE / relaxationFactors block)
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario names icoFoam/cavity as template and simpleFoam as application. The cavity tutorial supplies the movingWall / fixedWalls / frontAndBack patch layout matching the Ghia, Ghia & Shin (1982) problem. A steady solver needs steadyState ddt and a SIMPLE dictionary, which pitzDaily is the stock v2412 simpleFoam source for. Tutorial scale 0.1 and nu 0.01 (Re = 10) are replaced by L = 1 m and nu = 0.0025 so the case is directly non-dimensional, matching the reference normalisation. No corpus annotation exists for either tutorial. _(cites: $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily, Ghia, Ghia & Shin (1982) J. Comput. Phys. 48(3) 387-411)_
- **Alternatives:** Keep icoFoam and march to steady state (transient, scenario requires simpleFoam).
- **When it breaks:** A steady solver presumes a steady solution exists; if the cavity flow at the chosen Re were inherently unsteady, SIMPLE residuals would stall rather than converge, and that stall would be the diagnostic.

</details>

## [09:13:52] mesh / ok — blockMesh: 128x128x1 graded, 16 384 cells

- **Decision:** (scenario-specified) single block, 128x128x1, two-part multi-grading per in-plane direction with centre/wall cell-size ratio 4 (64 cells each half, expansion 4 and 0.25); scale 1 m (tutorial 0.1 replaced so L = 1)
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Scenario fixes resolution [128,128,1] and wall_normal_expansion 4 toward all four walls. blockMesh reports wall cell size 3.60e-3 m, so the centre cell is ~1.44e-2 m. Reference grid for comparison: Ghia et al. (1982) used a 129x129 uniform mesh (stated in the reference dataset's tolerance rationale). _(cites: $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict, cases/lid-cavity/reference/ghia_1982.json)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Mesh stats

| cells | points | faces | internal_faces |
|---|---|---|---|
| 16384 | 33282 | 65792 | 32512 |

### Patches

| name | type | faces |
|---|---|---|
| movingWall | wall | 128 |
| fixedWalls | wall | 384 |
| frontAndBack | empty | 32768 |

## [09:13:58] mesh_quality / ok — checkMesh: Mesh OK, overall verdict good

- **Decision:** Accept mesh; no non-orthogonal correctors needed
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality=0 (< 60 deg), max_skewness=1.69e-13 (< 1), max_aspect_ratio=4 (< 10, the 4:1 grading ratio), severe_non_orthogonal_faces=0. _(cites: of_check_mesh_src, versteeg)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0 | good |
| max_skewness | 1.69e-13 | good |
| max_aspect_ratio | 4 | good |
| severe_non_orthogonal_faces | 0 | good |

## [09:14:04] boundary_conditions / ok — BCs: lid U=(1 0 0), noSlip walls, zeroGradient p, empty front/back

- **Decision:** (scenario-specified) movingWall fixedValue (1 0 0); fixedWalls noSlip; frontAndBack empty; p zeroGradient on all walls with pRefCell 0 / pRefValue 0 (agent's call, taken from the cavity tutorial's PISO block into the SIMPLE block)
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** 0/U and 0/p copied verbatim from the cavity tutorial, which already matches the scenario's patch names and lid speed. In a fully enclosed domain p is defined only up to a constant (only grad p enters the incompressible momentum equation, and no patch fixes a p value), so a reference cell is required for the pressure equation to be non-singular; the tutorial's pRefCell 0 / pRefValue 0 is carried over. _(cites: $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/0/U, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/fvSolution)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** The lid-corner velocity singularity (U jumps from 1 to 0 at the top corners) is part of the Ghia benchmark definition; a regularised lid profile would be a different problem and would not match the reference.

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

## [09:14:10] solver_config / ok — simpleFoam laminar: linearUpwind, URF U 0.7 / p 0.3, residualControl 1e-6

- **Decision:** (scenario-specified) simpleFoam, simulationType laminar, nu 0.0025, div(phi,U) bounded Gauss linearUpwind grad(U), laplacian Gauss linear corrected, URF U 0.7 / p 0.3, residualControl p,U 1e-6, endTime 5000, writeInterval 1000. Kept at pitzDaily tutorial values (agent's call): steadyState ddt, GAMG p (relTol 0.1), smoothSolver U, SIMPLE consistent yes. Added a sets functionObject sampling U on x=0.5 and y=0.5 (257 points each, cellPoint) for validation.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scheme and laplacian strings in the scenario are identical to the pitzDaily simpleFoam tutorial's, so its fvSchemes is used with only turbulence-transport entries removed (laminar run). Relaxation and residual targets are the scenario's. The bounded variant subtracts the div(phi) term, which vanishes for a converged incompressible solution, so it does not alter the converged answer (Versteeg & Malalasekera Ch. 5 for upwind-biased 2nd-order schemes). _(cites: $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSchemes, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSolution, versteeg)_
- **Alternatives:** SIMPLE (consistent no) is the classic pairing with p URF 0.3; the tutorial's consistent yes (SIMPLEC) was retained since only the URF values were specified.
- **When it breaks:** residualControl 1e-6 is at the p linear-solver tolerance (1e-6); if initial residuals plateau near that floor the run will hit endTime 5000 instead of triggering residualControl.

</details>

## [09:15:01] convergence / warning — 5000 iterations: U converged < 1e-6, p plateau at 1.7e-6 (5.8 orders)

- **Decision:** Accept the solution for validation; residualControl 1e-6 not triggered, run ended at endTime 5000
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: marginal. Ux converged (last 4.94e-7), Uy converged (last 6.53e-7), p stalled at ~1.70e-6 (CoV 0.03 over last 50 iterations). The p plateau sits just above the GAMG absolute tolerance of 1e-6 inherited from the pitzDaily fvSolution: in the last iterations GAMG performs only 1-2 cycles and exits at the tolerance, so the initial residual of the next outer iteration cannot fall far below it. All fields dropped more than 4 orders, satisfying the scenario's qualitative check. Wall time 37 s. _(cites: of_user_guide_urf, versteeg)_
- **Alternatives:** Tighten p tolerance (e.g. 1e-8) and relTol so residualControl 1e-6 can trigger; not applied because centreline validation, not the residual target, decides the outcome and the U field is stationary to < 1e-6.
- **When it breaks:** If the centreline profiles were still drifting between the 4000 and 5000 writes, the plateau would be hiding an unconverged solution; validation would show it as a miss.

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 4.94e-7 | 6.31 |
| Uy | 0.99995 | 6.53e-7 | 6.19 |
| p | 1 | 1.70e-6 | 5.77 |

## [09:15:39] validation / ok — PASS: u and v centrelines within 5% of range vs Ghia Re=400

- **Decision:** Accept: both centreline profiles within tolerance (compare_profiles, RMS error at the 17 Ghia stations vs 5% of reference range); v passes with small margin (0.0366 vs 0.0376) because of one station
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** u(y) on x=0.5: L2 = 0.0011, L_inf = 0.0025 against tolerance 0.066. v(x) on y=0.5: L2 = 0.0366, L_inf = 0.150 against tolerance 0.0376. Pointwise, 16 of the 17 v stations agree within |dv| < 0.006; the single x = 0.9063 station (Ghia prints v = -0.23827, simulation -0.389) accounts for nearly all the v error, and RMS over the other 16 points is 0.0027. That station is the one the reference file flags as a suspected typo in Ghia's Table II (an outlier between -0.44993 at x = 0.8594 and -0.22847 at x = 0.9453); it is scored as printed, with no substitute value. Stationarity: the 4000 -> 5000 profile change is L2 2.2e-4 (u) and 1.9e-4 (v), an order of magnitude below the reference mismatch, so the p residual plateau is not masking drift. _(cites: Ghia, Ghia & Shin (1982) J. Comput. Phys. 48(3) 387-411, cases/lid-cavity/reference/ghia_1982.json)_
- **Alternatives:** Excluding the suspected-typo station would give a large v margin, but no published Re=400 re-tabulation exists to justify dropping or replacing it (per the reference provenance note), so the as-printed scoring is the reported verdict.
- **When it breaks:** The v verdict is sensitive to that single station: any discretisation change that moves the other 16 points by a few thousandths could flip it to FAIL even though agreement elsewhere is excellent. Reading the v verdict without the pointwise breakdown would misattribute the error.

</details>

### Comparison vs ghia_1982 (Re=400)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) at x=0.5 | 0.00112 | 0.00252 | 0.0664 | PASS |
| v(x) at y=0.5 | 0.0366 | 0.1505 | 0.0376 | PASS |

### v-centreline worst stations

| x | ghia | sim | diff |
|---|---|---|---|
| 0.8594 | -0.44993 | -0.45237 | -0.00244 |
| 0.9063 | -0.23827 | -0.38874 | -0.15047 |
| 0.9453 | -0.22847 | -0.23445 | -0.00598 |

Plots: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png`; metrics with provenance in `postProcessing/analysis/metrics.json`.

## [09:15:51] post_processing / info — |U| at t=5000: primary vortex near (0.54, 0.60); corner vortices not resolved in image

Rendered `postProcessing/images/U_tlatest.png` (|U|, 7.9e-7 to 0.98). The |U| minimum marking the primary vortex core sits right of and above the cavity centre, with the strong downflow jet along the right wall. Centreline zero-crossings (a proxy for the core position, exact only if the core lies on both lines): u = 0 on x = 0.5 at y = 0.599; v = 0 on y = 0.5 at x = 0.542 — consistent with the scenario's expected (x ~ 0.55, y ~ 0.60). The two lower-corner secondary vortices are low-speed regions that a linear |U| colour map does not separate from the wall layer; that qualitative check is not verified by this image (a streamline or stream-function plot would be needed).

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | (scenario-specified) 2-D unit square cavity, Re = U_lid L / nu = 1*1/0.0025 = 400, steady laminar simpleFoam; geometry, patches and BCs from incompressible/icoFoam/cavity/cavity; SIMPLE-family fvSchemes/fvSolution structure from incompressible/simpleFoam/pitzDaily (agent's call — icoFoam/cavity is transient PISO and has no SIMPLE / relaxationFactors block) | $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily, Ghia, Ghia & Shin (1982) J. Comput. Phys. 48(3) 387-411 | — |
| mesh | (scenario-specified) single block, 128x128x1, two-part multi-grading per in-plane direction with centre/wall cell-size ratio 4 (64 cells each half, expansion 4 and 0.25); scale 1 m (tutorial 0.1 replaced so L = 1) | $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict, cases/lid-cavity/reference/ghia_1982.json | alts, breaks |
| mesh_quality | Accept mesh; no non-orthogonal correctors needed | of_check_mesh_src, versteeg | alts, breaks |
| boundary_conditions | (scenario-specified) movingWall fixedValue (1 0 0); fixedWalls noSlip; frontAndBack empty; p zeroGradient on all walls with pRefCell 0 / pRefValue 0 (agent's call, taken from the cavity tutorial's PISO block into the SIMPLE block) | $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/0/U, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/fvSolution | alts |
| solver_config | (scenario-specified) simpleFoam, simulationType laminar, nu 0.0025, div(phi,U) bounded Gauss linearUpwind grad(U), laplacian Gauss linear corrected, URF U 0.7 / p 0.3, residualControl p,U 1e-6, endTime 5000, writeInterval 1000. Kept at pitzDaily tutorial values (agent's call): steadyState ddt, GAMG p (relTol 0.1), smoothSolver U, SIMPLE consistent yes. Added a sets functionObject sampling U on x=0.5 and y=0.5 (257 points each, cellPoint) for validation. | $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSchemes, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSolution, versteeg | — |
| convergence | Accept the solution for validation; residualControl 1e-6 not triggered, run ended at endTime 5000 | of_user_guide_urf, versteeg | — |
| validation | Accept: both centreline profiles within tolerance (compare_profiles, RMS error at the 17 Ghia stations vs 5% of reference range); v passes with small margin (0.0366 vs 0.0376) because of one station | Ghia, Ghia & Shin (1982) J. Comput. Phys. 48(3) 387-411, cases/lid-cavity/reference/ghia_1982.json | — |

<!-- END DECISIONS TABLE -->
