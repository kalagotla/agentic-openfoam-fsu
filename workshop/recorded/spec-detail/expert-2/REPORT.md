# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — PASS vs Ghia Re=400: u rel-L2 0.0009, v rel-L2 0.0487 (tol 0.05)

10 steps · 8 decisions · 1 retry · 4 gaps
<!-- END SUMMARY -->

## [09:18:21] geometry / ok — Template: icoFoam/cavity, unit square cavity, Re = 400 (simpleFoam)

- **Decision:** Structural template incompressible/icoFoam/cavity/cavity (scenario-specified); 2-D unit square cavity L = 1 m, lid U = 1 m/s, nu = 0.0025 m²/s giving Re = U L / nu = 400 (scenario-specified); steady simpleFoam replaces transient icoFoam (scenario-specified).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The cavity tutorial already has the target topology: a single hex block with patches movingWall / fixedWalls / frontAndBack, which matches the scenario's patch names exactly. Re = U_lid L / nu = 1·1/0.0025 = 400, the Ghia et al. (1982) Re = 400 column used for validation. The steady SIMPLE structure (SIMPLE dict, residualControl, relaxationFactors, steadyState ddt) comes from the simpleFoam tutorial incompressible/simpleFoam/pitzDaily, because icoFoam/cavity is a PISO case with no SIMPLE block. No corpus annotation exists for incompressible/icoFoam/cavity/cavity. _(cites: ghia_1982, incompressible/icoFoam/cavity/cavity, incompressible/simpleFoam/pitzDaily)_
- **Alternatives:** Running transient icoFoam to a steady state would also reach the steady solution, but the scenario fixes simpleFoam.
- **When it breaks:** A steady solver assumes a steady solution exists. If the flow at the chosen Re were inherently unsteady, SIMPLE residuals would stall or oscillate instead of decaying, and that stall would be the diagnostic.

</details>

### Case parameters

| quantity | value |
|---|---|
| L | 1.0 m |
| U_lid | 1.0 m/s |
| nu | 0.0025 m²/s |
| Re | 400 |

## [09:19:18] solver_config / ok — simpleFoam laminar: linearUpwind, URF U 0.7 / p 0.3, residualControl 1e-6

- **Decision:** Schemes: steadyState ddt, bounded Gauss linearUpwind grad(U) for div(phi,U), Gauss linear corrected laplacian (scenario-specified); snGrad corrected to match the laplacian (agent's call); URF U 0.7 (equation), p 0.3 (field) under standard SIMPLE without `consistent` (scenario-specified URFs; dropping SIMPLEC is the agent's call); residualControl U, p 1e-6 (scenario-specified); linear-solver absolute tolerances tightened from the tutorial's 1e-6 (p) and 1e-5 (U) to 1e-7 (agent's call); laminar turbulenceProperties.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The steady-state SIMPLE block layout (residualControl, relaxationFactors, steadyState ddt, bounded linearUpwind form) follows incompressible/simpleFoam/pitzDaily. A p-field URF of 0.3 with U 0.7 is the classic SIMPLE pairing, where the pressure correction is under-relaxed explicitly (Versteeg & Malalasekera 2007, ch. 6). pitzDaily's `consistent yes` (SIMPLEC) is built to need little or no explicit p relaxation, so it is not combined with the scenario's p = 0.3. Solver tolerance, from first principles: residualControl tests the *initial* residual of each outer iteration. Once that residual falls below the linear solver's absolute tolerance, the solver performs zero sweeps. A U tolerance of 1e-5 therefore cannot drive the U residual to the 1e-6 target, so both tolerances are set an order below the target. On this orthogonal block mesh, corrected and orthogonal snGrad are numerically identical, so the snGrad choice only keeps the dictionary self-consistent. The 0.1 m depth and empty front/back patches make the case 2-D; laminar turbulenceProperties is taken from incompressible/pimpleFoam/laminar/cylinder2D. _(cites: incompressible/simpleFoam/pitzDaily, incompressible/icoFoam/cavity/cavity, versteeg_2007, of_user_guide_urf, incompressible/pimpleFoam/laminar/cylinder2D)_
- **Alternatives:** SIMPLEC (`consistent yes`, as in pitzDaily) with higher URFs would likely converge in fewer iterations, but it departs from the scenario's p = 0.3. First-order upwind for div(phi,U) is more robust but adds numerical diffusion, and the scenario fixes linearUpwind.
- **When it breaks:** If 5000 iterations at U 0.7 / p 0.3 are not enough to reach 1e-6, the run stops at endTime without meeting residualControl, and convergence has to be judged from the residual drop. linearUpwind on a strongly skewed or non-orthogonal mesh would need nNonOrthogonalCorrectors > 0, which does not apply to this block mesh.

</details>

### Solver settings

| item | value | origin |
|---|---|---|
| div(phi,U) | bounded Gauss linearUpwind grad(U) | scenario |
| laplacian | Gauss linear corrected | scenario |
| URF U / p | 0.7 / 0.3 | scenario |
| residualControl U / p | 1e-6 / 1e-6 | scenario |
| p solver | PCG/DIC, tol 1e-7, relTol 0.05 | tutorial (tol tightened) |
| U solver | smoothSolver symGaussSeidel, tol 1e-7, relTol 0 | tutorial (tol tightened) |
| endTime / writeInterval | 5000 / 1000 | scenario |

## [09:19:49] mesh / ok — blockMesh 128×128×1, wall-clustered multi-grading (ratio 4)

- **Decision:** Single hex block, 128×128×1 cells, two-section multi-grading ((0.5 0.5 4) (0.5 0.5 0.25)) in x and y so cells are smallest at all four walls (scenario-specified resolution and grading; the two-section form is the agent's encoding of "cluster toward all walls").
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Each half of the side holds 64 cells and expands 4× from the wall to the centreline. blockMesh reports a wall cell size of 0.00360 m, so the centre cells are about 0.0144 m. Ghia et al. (1982) solved on a 129×129 uniform grid, so this mesh resolves the walls more finely than the reference and the centre about half as finely. The tutorial's scale 0.1 is changed to 1 so that L = 1 m. _(cites: ghia_1982, incompressible/icoFoam/cavity/cavity)_
- **Alternatives:** A uniform 128² grid would match Ghia's topology more closely but spend fewer cells in the wall shear layers.
- **When it breaks:** Coarser centre cells could under-resolve the corner-vortex extent if those were compared quantitatively. Only centreline profiles are scored here.

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

## [09:19:53] mesh_quality / ok — checkMesh: Mesh OK, overall verdict good

- **Decision:** Accept mesh; nNonOrthogonalCorrectors stays 0.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality=0 is good (< 60 deg). max_skewness=1.69e-13 is good (< 1). max_aspect_ratio=4 is good (< 10), arising where a 0.0036 m wall-normal spacing meets a 0.0144 m tangential spacing at mid-wall. severe_non_orthogonal_faces=0. _(cites: of_check_mesh_src, versteeg_2007)_
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

## [09:19:59] boundary_conditions / ok — BCs: lid fixedValue (1 0 0), noSlip walls, zeroGradient p, empty front/back

- **Decision:** 0/U and 0/p copied verbatim from icoFoam/cavity (scenario-specified BCs match the tutorial's exactly); p reference pRefCell 0 / pRefValue 0 in the SIMPLE dict (tutorial value).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The tutorial's patch names and BC types already match the scenario. In a closed cavity every boundary has zeroGradient p, so the pressure level is set only up to a constant. pRefCell/pRefValue pins that constant, otherwise the pressure equation is singular (first principles: a pure-Neumann Poisson problem has a one-parameter family of solutions). _(cites: incompressible/icoFoam/cavity/cavity)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** The lid's fixedValue (1 0 0) meets the noSlip side walls at the two top corners, where the velocity is discontinuous. This singularity is inherent to the benchmark and is shared by the reference solution.

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

## [09:20:08] solver_config / error — simpleFoam aborted: div((nuEff*dev2(T(grad(U))))) missing in fvSchemes

FOAM FATAL IO ERROR at Time = 1: `Entry 'div((nuEff*dev2(T(grad(U)))))' not found in dictionary "system/fvSchemes/divSchemes"`. icoFoam solves with a constant-viscosity Laplacian only, so its fvSchemes has no entry for the deviatoric transpose-stress term that simpleFoam's laminar (Stokes) model assembles.

## [09:20:16] solver_config / fixed — Added div((nuEff*dev2(T(grad(U))))) Gauss linear from pitzDaily
_retry of: 'simpleFoam aborted: div((nuEff*dev2(T(grad(U))))) missing in fvSchemes'_

- **Decision:** Add `div((nuEff*dev2(T(grad(U))))) Gauss linear;` to divSchemes (agent's call, forced by the solver error).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The entry and its scheme are taken verbatim from the simpleFoam template incompressible/simpleFoam/pitzDaily/system/fvSchemes. For constant nu in incompressible flow, div(nu·dev2(T(grad U))) is analytically zero, because div(T(grad U)) = grad(div U) = 0. Its discretisation therefore has a negligible effect on the solution. _(cites: incompressible/simpleFoam/pitzDaily)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

## [09:21:14] convergence / ok — SIMPLE converged in 3120 iterations (residualControl 1e-6 met), 46 s

<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: good. Ux converged (last=1.70e-07). Uy converged (last=2.26e-07). p converged (last=9.89e-07). All three initial residuals dropped at least 6 orders of magnitude, exceeding the scenario's ≥ 4-order qualitative check. The run stopped on residualControl before the 5000-iteration endTime. Continuity errors are about 2e-9 (sum local). _(cites: of_user_guide_urf)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1.0 | 1.70e-07 | 6.77 |
| Uy | 1.0 | 2.26e-07 | 6.65 |
| p | 1.0 | 9.89e-07 | 6 |

## [09:22:35] validation / ok — PASS vs Ghia Re=400: u rel-L2 0.0009, v rel-L2 0.0487 (tol 0.05)

- **Decision:** Accept: both centreline profiles are within the scenario's 5 % relative-L2 tolerance, scored by compare_profiles over all 17 printed Ghia stations.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** u(y) on x = 0.5 matches closely (L_inf 0.0026). The v(x) margin is narrow (0.0487 vs 0.05), and it is almost entirely one station. At x = 0.9063, Ghia's Table II prints v = -0.23827, while the solution gives -0.389. The ghia_1982 reference file's provenance flags this printed value as a suspected typo: it is an outlier between -0.44993 (x = 0.8594) and -0.22847 (x = 0.9453). Excluding that station as a diagnostic only, v relative-L2 falls to 0.0037 and L_inf to 0.0061, the same level as u. The shipped value is kept in the scored verdict, following the reference file's instruction not to substitute it. Qualitative checks: the streamfunction minimum (primary vortex) is at (0.549, 0.601), against the scenario's expected (≈0.55, ≈0.60). Counter-rotating (ψ > 0) secondary vortices sit in both lower corners, centred near (0.88, 0.12) on the right (ψ = 6.5e-4) and (0.05, 0.05) on the left (ψ = 1.5e-5). Residuals dropped ≥ 6 orders. _(cites: ghia_1982, cases/lid-cavity/reference/ghia_1982.json (data_provenance))_
- **Alternatives:** Scoring v without the x = 0.9063 station would give a wide margin, but it would mean editing the reference set. That is reported only as a diagnostic. A grid-refinement study would establish mesh independence directly, but this scenario does not request one.
- **When it breaks:** The pass on v depends on a single suspect reference point consuming about 97 % of the error budget. A small change in the solution near x = 0.9 (for example a coarser mesh) could flip the scored verdict without any real loss of agreement with the rest of the profile. Vortex centres are located at cell-centre resolution (about 0.004–0.014 m), and the streamfunction is integrated from cell-centred u with cell centres reconstructed from the blockMesh grading.

</details>

### Comparison vs ghia_1982

| profile | L2 | L_inf | rel_L2 | tolerance | verdict |
|---|---|---|---|---|---|
| u_centerline (x=0.5) | 0.00113 | 0.00258 | 0.0009 | 0.0664 (5% of range) | pass |
| v_centerline (y=0.5) | 0.0366 | 0.151 | 0.0487 | 0.0376 (5% of range) | pass (narrow) |
| v_centerline excl. x=0.9063 (diagnostic) | 0.00282 | 0.00608 | 0.0037 | 0.0376 | informational |

### Vortex structure

| vortex | x | y | psi | expected |
|---|---|---|---|---|
| primary | 0.549 | 0.601 | -0.114 | (~0.55, ~0.60) |
| lower-right | 0.884 | 0.122 | +6.5e-4 | present |
| lower-left | 0.051 | 0.047 | +1.5e-5 | present |

Plots: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png`, `postProcessing/analysis/streamfunction.png`. Metrics with provenance (sample time 3120, numpy 2.4.4, matplotlib 3.10.9, commit aecc137): `postProcessing/analysis/metrics.json`.

## [09:22:47] post_processing / ok — |U| field at t = 3120 rendered

![U magnitude](postProcessing/images/U_tlatest.png)

The thin lid shear layer is visible, along with the high-speed wall jet driven down the right (downstream) wall. The low-speed core sits at about (0.55, 0.6), coinciding with the streamfunction minimum, and the near-stagnant lower corners are where the counter-rotating secondary vortices sit. Peak cell-centred |U| = 0.983 is just below the lid speed, as expected for cell centres half a wall cell (0.0018 m) below the lid.

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | Structural template incompressible/icoFoam/cavity/cavity (scenario-specified); 2-D unit square cavity L = 1 m, lid U = 1 m/s, nu = 0.0025 m²/s giving Re = U L / nu = 400 (scenario-specified); steady simpleFoam replaces transient icoFoam (scenario-specified). | ghia_1982, incompressible/icoFoam/cavity/cavity, incompressible/simpleFoam/pitzDaily | — |
| solver_config | Schemes: steadyState ddt, bounded Gauss linearUpwind grad(U) for div(phi,U), Gauss linear corrected laplacian (scenario-specified); snGrad corrected to match the laplacian (agent's call); URF U 0.7 (equation), p 0.3 (field) under standard SIMPLE without `consistent` (scenario-specified URFs; dropping SIMPLEC is the agent's call); residualControl U, p 1e-6 (scenario-specified); linear-solver absolute tolerances tightened from the tutorial's 1e-6 (p) and 1e-5 (U) to 1e-7 (agent's call); laminar turbulenceProperties. | incompressible/simpleFoam/pitzDaily, incompressible/icoFoam/cavity/cavity, versteeg_2007, of_user_guide_urf, incompressible/pimpleFoam/laminar/cylinder2D | — |
| mesh | Single hex block, 128×128×1 cells, two-section multi-grading ((0.5 0.5 4) (0.5 0.5 0.25)) in x and y so cells are smallest at all four walls (scenario-specified resolution and grading; the two-section form is the agent's encoding of "cluster toward all walls"). | ghia_1982, incompressible/icoFoam/cavity/cavity | — |
| mesh_quality | Accept mesh; nNonOrthogonalCorrectors stays 0. | of_check_mesh_src, versteeg_2007 | alts, breaks |
| boundary_conditions | 0/U and 0/p copied verbatim from icoFoam/cavity (scenario-specified BCs match the tutorial's exactly); p reference pRefCell 0 / pRefValue 0 in the SIMPLE dict (tutorial value). | incompressible/icoFoam/cavity/cavity | alts |
| solver_config | Add `div((nuEff*dev2(T(grad(U))))) Gauss linear;` to divSchemes (agent's call, forced by the solver error). | incompressible/simpleFoam/pitzDaily | alts, breaks |
| convergence |  | of_user_guide_urf | alts, breaks |
| validation | Accept: both centreline profiles are within the scenario's 5 % relative-L2 tolerance, scored by compare_profiles over all 17 printed Ghia stations. | ghia_1982, cases/lid-cavity/reference/ghia_1982.json (data_provenance) | — |

<!-- END DECISIONS TABLE -->
