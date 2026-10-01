# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — PASS on 80×80: u L2 0.0022, v L2 0.0349 vs Ghia (grid-converged)

15 steps · 14 decisions · 2 retries · 2 gaps
<!-- END SUMMARY -->

## [10:19:20] geometry / ok — Unit square cavity from icoFoam/cavity, scale 0.1 → 1

- **Decision:** (scenario-specified) Adopt incompressible/icoFoam/cavity/cavity as the structural template (single hex block, patches movingWall / fixedWalls / frontAndBack) with `scale 1` so L = 1 m; nu = 0.0025 m²/s gives Re = U_lid·L/nu = 1·1/0.0025 = 400.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** With L = 1 and U_lid = 1 the dimensional u, v equal Ghia's normalised u/U_lid, v/U_lid, and Re = U·L/nu reproduces Ghia's convention exactly, so no rescaling enters the comparison. The tutorial carries the same square geometry and patch layout at L = 0.1; only the scale changes. No corpus annotation exists for this tutorial (corpus/incompressible/icoFoam/cavity/cavity.md absent). _(cites: ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict)_
- **Alternatives:** Keep L = 0.1 with nu = 0.00025 (same Re) and rescale coordinates in the analysis; rejected because it adds a rescaling step to validation with no physical benefit.
- **When it breaks:** Any comparison that assumes a different Re definition (e.g. based on cavity depth for a non-square cavity) or a 3-D cavity where end-wall effects matter; the empty front/back patches impose strict two-dimensionality.

</details>

## [10:19:28] solver_config / ok — simpleFoam (laminar) with pitzDaily SIMPLE dictionaries

- **Decision:** (scenario-specified) simpleFoam, laminar; fvSchemes and fvSolution copied verbatim from incompressible/simpleFoam/pitzDaily (steadyState, bounded Gauss linearUpwind for div(phi,U), SIMPLEC `consistent yes`, URF 0.9, residualControl p 1e-2 / U 1e-3). (agent's call) Added pRefCell 0 / pRefValue 0, endTime 5000 iterations, writeInterval 1000, and a `sets` functionObject sampling U on x = 0.5 and y = 0.5.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario fixes steady physics and simpleFoam; icoFoam's fvSchemes (Euler ddt) and PISO fvSolution do not apply to a SIMPLE loop, so the algorithm-specific dictionaries come from pitzDaily, the canonical simpleFoam tutorial, unchanged. Every cavity wall carries zeroGradient p, so p is determined only up to a constant; a reference cell pins that constant (the icoFoam/cavity PISO dict carries the same pRefCell 0 / pRefValue 0 for the same reason). No corpus annotation exists for pitzDaily. Laminar model follows from the scenario's flow_type. _(cites: $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSolution, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/fvSolution, of_user_guide_urf)_
- **Alternatives:** Run icoFoam (transient) to steady state as in the tutorial; rejected because the scenario specifies a steady SIMPLE solve. pimpleFoam with large time steps; same objection.
- **When it breaks:** A steady solver presumes a steady solution exists; if the cavity flow becomes time-periodic, SIMPLE residuals stall instead of converging and the stall is itself the diagnostic. The pitzDaily residualControl thresholds are loose for a benchmark comparison; whether they stop the run before the centerline profiles settle is observable in the residual history.

</details>

## [10:19:33] boundary_conditions / ok — Lid (1,0,0), no-slip walls, empty front/back

- **Decision:** (scenario-specified) 0/U and 0/p copied verbatim from icoFoam/cavity: movingWall fixedValue (1 0 0), fixedWalls noSlip, frontAndBack empty; p zeroGradient on all walls.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Matches the scenario's boundary_conditions block and Ghia's problem statement (top wall at U_lid in +x, other three walls no-slip, 2-D). Patch names already match the scenario, so the tutorial fields need no edits. _(cites: ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/0/U)_
- **Alternatives:** _no alternatives surfaced_ beyond regularised lid profiles, which would change the benchmark problem away from Ghia's.
- **When it breaks:** The lid/side-wall corners carry a velocity discontinuity (singular pressure); local values near the top corners are mesh-dependent, which affects the near-lid u samples at y ≥ 0.95 more than the interior.

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

## [10:19:41] mesh / ok — blockMesh: tutorial 20×20×1 uniform grid (400 cells)

- **Decision:** (agent's call) Start the grid-convergence study at the tutorial's own 20×20 uniform resolution (Δx = Δy = 0.05) and refine only if validation misses.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario leaves resolution open and asks for it to be established by refinement; the reference's tolerance rationale says the resolution meeting 5% is not known in advance and must come from a convergence study. The tutorial grid is the natural first level. Ghia's own solution used a 129×129 uniform grid, the only sourced anchor. _(cites: ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict)_
- **Alternatives:** Start directly near Ghia's 129×129; rejected because it skips the convergence evidence the scenario asks for.
- **When it breaks:** First-principles: the cell Péclet number U·Δx/nu = 1·0.05/0.0025 = 20 near the lid, so the thin lid and wall shear layers span only a few cells and the upwind-biased convection scheme adds numerical diffusion; under-resolution would show as a damped centerline profile.

</details>

### Mesh stats

| cells | points | faces | internal_faces |
|---|---|---|---|
| 400 | 882 | 1640 | 760 |

### Patches

| name | type | faces |
|---|---|---|
| movingWall | wall | 20 |
| fixedWalls | wall | 60 |
| frontAndBack | empty | 800 |

## [10:19:58] mesh_quality / ok — checkMesh: Mesh OK, orthogonal uniform hexes

- **Decision:** Accept the mesh with nNonOrthogonalCorrectors 0 and `corrected` snGrad as copied.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality=0 (< 60 deg), max_skewness=1.78e-14 (< 1), max_aspect_ratio=1 (< 10), severe_non_orthogonal_faces=0. _(cites: of_check_mesh_src, versteeg_2007)_
- **Alternatives:** Not needed: no metric approaches a band that calls for non-orthogonal correctors or re-meshing.
- **When it breaks:** Quality metrics say nothing about resolution; a perfectly orthogonal grid can still under-resolve the shear layers. Resolution is judged by validation.

</details>

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0 | good |
| max_skewness | 1.78e-14 | good |
| max_aspect_ratio | 1 | good |
| severe_non_orthogonal_faces | 0 | good |

## [10:20:02] convergence / warning — SIMPLE stopped at iteration 50 by residualControl, ~3 orders dropped

<details><summary>why · alternatives · when it breaks</summary>

- **Why:** _uncited choice — no annotation, reference, or paper cited._ _(cites: of_user_guide_urf)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1.0 | 7.08e-04 | 3.15 |
| Uy | 0.993 | 9.98e-04 | 3 |
| p | 1.0 | 1.23e-03 | 2.91 |

simpleFoam reported "SIMPLE solution converged in 50 iterations" because the pitzDaily residualControl (p 1e-2, U 1e-3) was met. Initial residuals fell only ~3 orders, short of the scenario's qualitative check of >= 4 orders, and assess_residuals classifies every field as `still_running` (dropping steadily, still above 1e-5). Validation proceeds on this solution; the residual shortfall is carried forward as an open issue.

## [10:20:36] validation / error — 20×20, iter 50: v centerline misses Ghia (L2 0.046 > 0.038)

- **Decision:** Validation FAIL on the tutorial grid at the residualControl stop point; u passes, v fails.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** compare_profiles (RMS of sim − Ghia at the 17 Ghia stations, tolerance 5% of the reference range) gives u L2 = 0.0316 (tol 0.0664) and v L2 = 0.0463 (tol 0.0376). The overlay shows both v extrema damped: peak v ≈ 0.25 vs Ghia 0.302 near x ≈ 0.23, trough ≈ −0.37 vs −0.450 near x ≈ 0.86. Removing Ghia's suspected-typo point at x = 0.9063 barely changes the v error (0.0452), so the miss is not driven by that point. _(cites: ghia_1982)_
- **Alternatives:** Two observed causes are confounded in this result: the solution is only ~3 orders iterated (convergence entry above), and the grid is 20×20. Changing both at once would hide which one mattered, so the iteration shortfall is removed first on the same grid, then the grid is refined if the miss persists.
- **When it breaks:** If the v miss survives a fully iterated solve, it is discretisation error and only refinement addresses it.

</details>

### Comparison vs Ghia 1982 (Re=400)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) at x=0.5 | 0.0316 | 0.0686 | 0.0664 | pass |
| v(x) at y=0.5 | 0.0463 | 0.0904 | 0.0376 | FAIL |

Plot: `postProcessing/analysis/centerlines_vs_ghia.png`

## [10:20:51] solver_config / fixed — (deviation from tutorial) residualControl p, U: 1e-2/1e-3 → 1e-5
_retry of: 'SIMPLE stopped at iteration 50 by residualControl, ~3 orders dropped'_

- **Decision:** (agent's call) Tighten SIMPLE residualControl to 1e-5 for p and U; grid unchanged at 20×20 so the effect of iteration error alone is measured.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The first run stopped with initial residuals ~1e-3 (3 orders dropped), below the scenario's >= 4-order check, and assess_residuals classified all fields `still_running`. 1e-5 is the consultant's `converged` band and gives ~5 orders from the unit initial residual. residualControl is the documented stopping criterion for SIMPLE in OpenFOAM. _(cites: of_user_guide_urf)_
- **Alternatives:** Disable residualControl and run the full 5000 iterations; equivalent outcome but wastes iterations once the field is converged.
- **When it breaks:** If residuals stall above 1e-5 (e.g. an unsteady flow or a limiter cycling), the run goes to endTime without meeting the criterion; the stall would then be the diagnostic.

</details>

## [10:21:03] validation / error — 20×20, fully iterated: v still misses (L2 0.044 > 0.038)

- **Decision:** Validation FAIL persists after full iteration on 20×20; attribute the miss to discretisation error and refine the grid.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** With residuals at 1e-5 (117 iterations, ~5 orders) v L2 dropped only from 0.0463 to 0.0440 and u from 0.0316 to 0.0300. Iteration error therefore accounts for a small part of the gap; the remaining damping of the v extrema is the grid. First-principles: cell Péclet U·Δx/nu = 20 at Δx = 0.05 means the convection term dominates on the cell scale, and the upwind-biased linearUpwind scheme's truncation error falls with Δx, so refinement is the direct remedy. _(cites: ghia_1982, versteeg_2007)_
- **Alternatives:** Switch div(phi,U) to a less dissipative scheme on the same grid; rejected for now because the scenario asks for a grid-convergence study and a scheme change would mix two error sources.
- **When it breaks:** If refinement does not shrink the v error monotonically, the cause is not grid resolution (e.g. a sampling or BC issue) and must be re-diagnosed.

</details>

### Comparison vs Ghia 1982 (Re=400)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) at x=0.5 | 0.03 | 0.0645 | 0.0664 | pass |
| v(x) at y=0.5 | 0.044 | 0.087 | 0.0376 | FAIL |

## [10:21:24] mesh / fixed — Grid refinement level 2: 40×40 uniform (1600 cells), checkMesh OK
_retry of: '20×20, fully iterated: v still misses (L2 0.044 > 0.038)'_

- **Decision:** (agent's call) Halve Δx to 0.025 (40×40×1); schemes, URFs, and residualControl unchanged.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The fully iterated 20×20 solution missed the v tolerance with damped extrema, the signature of discretisation error; halving Δx halves the cell Péclet number to 10 and reduces truncation error. checkMesh: Mesh OK, max non-orthogonality 0, max skewness 3.1e-14, aspect ratio 1. SIMPLE converged to residualControl 1e-5 in 152 iterations. _(cites: ghia_1982, versteeg_2007, of_check_mesh_src)_
- **Alternatives:** Wall-graded mesh to cluster cells into the lid and wall layers; held back so the study stays a clean uniform-refinement sequence comparable to Ghia's uniform grid.
- **When it breaks:** At higher Re the wall and lid shear layers thin, and uniform refinement becomes an expensive way to resolve them.

</details>

### Mesh stats

| cells | points | faces | internal_faces |
|---|---|---|---|
| 1600 | 3362 | 6480 | 3120 |

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0 | good |
| max_skewness | 3.14e-14 | good |
| max_aspect_ratio | 1 | good |
| severe_non_orthogonal_faces | 0 | good |

## [10:21:28] validation / ok — 40×40: both centerlines within tolerance (u 0.008, v 0.031)

<details><summary>why · alternatives · when it breaks</summary>

- **Why:** _uncited choice — no annotation, reference, or paper cited._ _(cites: ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Comparison vs Ghia 1982 (Re=400)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) at x=0.5 | 0.008 | 0.0173 | 0.0664 | pass |
| v(x) at y=0.5 | 0.0313 | 0.1221 | 0.0376 | pass |

u L2 fell 0.030 → 0.008 and v L2 0.044 → 0.031 on halving Δx. v's L_inf (0.122) sits at x = 0.9063, Ghia's suspected-typo station (printed −0.23827 between −0.44993 and −0.22847); excluding that one point (information only, not the verdict) gives v L2 = 0.010, so the remaining v error is almost entirely that point. A further refinement (80×80) follows to check that the profiles have stopped changing.

## [10:22:07] mesh / ok — Grid refinement level 3: 80×80 uniform (6400 cells), checkMesh OK

- **Decision:** (agent's call) Refine once more to Δx = 0.0125 (80×80×1) to test whether the passing 40×40 profiles have stopped changing; adopt 80×80 as the reported solution.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** One passing grid shows the tolerance is met, not that the solution is grid-converged; the scenario and the reference's tolerance rationale ask for refinement until the profiles stop changing. checkMesh: Mesh OK, max non-orthogonality 0, max skewness 5.3e-14, aspect ratio 1. _(cites: ghia_1982, of_check_mesh_src)_
- **Alternatives:** Stop at 40×40 (passes, but no evidence of convergence); refine to Ghia's 129×129 (the 80×80 change from 40×40 is already small, see validation entry).
- **When it breaks:** Uniform refinement cost grows with the square of N in 2-D; for higher Re where corner eddies and thinner wall layers matter, graded meshes become the more economical route.

</details>

### Mesh stats

| cells | points | faces | internal_faces |
|---|---|---|---|
| 6400 | 13122 | 25760 | 12640 |

### Patches

| name | type | faces |
|---|---|---|
| movingWall | wall | 80 |
| fixedWalls | wall | 240 |
| frontAndBack | empty | 12800 |

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0 | good |
| max_skewness | 5.33e-14 | good |
| max_aspect_ratio | 1 | good |
| severe_non_orthogonal_faces | 0 | good |

## [10:22:13] convergence / ok — 80×80: SIMPLE converged in 374 iterations, >= 5 orders on all fields

- **Decision:** Accept the 80×80 steady solution as iteratively converged.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: good. Ux converged (last 9.96e-06), Uy converged (9.54e-06), p converged (2.16e-06); every field dropped at least 5 orders, meeting the scenario's >= 4-order check. Monotone residual descent with no stall is consistent with a steady solution existing at this Re. _(cites: of_user_guide_urf)_
- **Alternatives:** Tighter residualControl (1e-6) would cost more iterations; the 20×20 test showed iteration error at 1e-3 versus 1e-5 moved the profile error by only ~0.002, so 1e-5 is well below the discretisation error.
- **When it breaks:** If the flow had no steady solution, SIMPLE residuals would plateau or oscillate rather than fall monotonically.

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1.0 | 9.96e-06 | 5 |
| Uy | 1.0 | 9.54e-06 | 5.02 |
| p | 1.0 | 2.16e-06 | 5.67 |

## [10:22:16] post_processing / ok — |U| field at iteration 374 (80×80)

Image: `postProcessing/images/U_tlatest.png`. Single primary vortex; the |U| minimum marking its core sits near (x, y) ≈ (0.55, 0.61) by eye, consistent with the scenario's expected location near (0.55, 0.60). High-speed fluid hugs the lid and turns down the right wall. The two lower-corner secondary vortices cannot be confirmed from a |U| contour (their velocities are near the colour-map floor); a streamline or vorticity plot would be needed, so that qualitative check is left unverified.

## [10:22:28] validation / ok — PASS on 80×80: u L2 0.0022, v L2 0.0349 vs Ghia (grid-converged)

- **Decision:** Validation PASS; report the 80×80 solution, with grid convergence shown across 20/40/80.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** compare_profiles against Ghia Re=400 Tables I and II: u L2 = 0.0022 (tol 0.0664), v L2 = 0.0349 (tol 0.0376). The grid study shows the u error falling roughly 4x per halving of Δx (0.030 → 0.008 → 0.0022), the rate expected of a second-order scheme. The v error is dominated by one station: at x = 0.9063 the simulation gives v ≈ −0.38 against Ghia's printed −0.23827, which the reference JSON flags as a suspected typo (it breaks the otherwise smooth trough between −0.44993 and −0.22847). With that point excluded (information only, not the verdict) v L2 falls 0.042 → 0.010 → 0.0015, also ~4x per refinement. The full-dataset v error rises slightly from 40×40 to 80×80 (0.031 → 0.035) because the converging solution moves away from that printed value. _(cites: ghia_1982, cases/lid-cavity/reference/ghia_1982.json (data_provenance: suspected typo at Re=400, x=0.9063))_
- **Alternatives:** Exclude the suspected-typo point from the verdict; rejected because the reference ships the printed value deliberately and no published Re=400 re-tabulation exists to replace it, so the verdict uses the dataset as shipped.
- **When it breaks:** The v margin (0.0349 vs 0.0376) is set almost entirely by the x = 0.9063 point. Its contribution alone is 0.144/sqrt(17) ≈ 0.035, so on finer grids where the sim value at that station settles a little further from −0.238, the full-dataset v check could flip to FAIL with no change in solution quality. A verdict near that boundary should be read alongside the excluded-point metric.

</details>

### Comparison vs Ghia 1982 (Re=400), 80×80

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) at x=0.5 | 0.0022 | 0.0039 | 0.0664 | pass |
| v(x) at y=0.5 | 0.0349 | 0.1436 | 0.0376 | pass |

### Grid convergence (residualControl 1e-5)

| grid | cells | iterations | u_L2 | v_L2 | v_L2_excl_x0.9063 | verdict |
|---|---|---|---|---|---|---|
| 20×20 | 400 | 117 | 0.03 | 0.044 | 0.0425 | FAIL (v) |
| 40×40 | 1600 | 152 | 0.008 | 0.0313 | 0.0104 | pass |
| 80×80 | 6400 | 374 | 0.0022 | 0.0349 | 0.0015 | pass |

Overlay: `postProcessing/analysis/centerlines_vs_ghia.png`; per-grid metrics and samples in `gridstudy/`.

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | (scenario-specified) Adopt incompressible/icoFoam/cavity/cavity as the structural template (single hex block, patches movingWall / fixedWalls / frontAndBack) with `scale 1` so L = 1 m; nu = 0.0025 m²/s gives Re = U_lid·L/nu = 1·1/0.0025 = 400. | ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict | — |
| solver_config | (scenario-specified) simpleFoam, laminar; fvSchemes and fvSolution copied verbatim from incompressible/simpleFoam/pitzDaily (steadyState, bounded Gauss linearUpwind for div(phi,U), SIMPLEC `consistent yes`, URF 0.9, residualControl p 1e-2 / U 1e-3). (agent's call) Added pRefCell 0 / pRefValue 0, endTime 5000 iterations, writeInterval 1000, and a `sets` functionObject sampling U on x = 0.5 and y = 0.5. | $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSolution, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/fvSolution, of_user_guide_urf | — |
| boundary_conditions | (scenario-specified) 0/U and 0/p copied verbatim from icoFoam/cavity: movingWall fixedValue (1 0 0), fixedWalls noSlip, frontAndBack empty; p zeroGradient on all walls. | ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/0/U | — |
| mesh | (agent's call) Start the grid-convergence study at the tutorial's own 20×20 uniform resolution (Δx = Δy = 0.05) and refine only if validation misses. | ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict | — |
| mesh_quality | Accept the mesh with nNonOrthogonalCorrectors 0 and `corrected` snGrad as copied. | of_check_mesh_src, versteeg_2007 | — |
| convergence |  | of_user_guide_urf | alts, breaks |
| validation | Validation FAIL on the tutorial grid at the residualControl stop point; u passes, v fails. | ghia_1982 | — |
| solver_config | (agent's call) Tighten SIMPLE residualControl to 1e-5 for p and U; grid unchanged at 20×20 so the effect of iteration error alone is measured. | of_user_guide_urf | — |
| validation | Validation FAIL persists after full iteration on 20×20; attribute the miss to discretisation error and refine the grid. | ghia_1982, versteeg_2007 | — |
| mesh | (agent's call) Halve Δx to 0.025 (40×40×1); schemes, URFs, and residualControl unchanged. | ghia_1982, versteeg_2007, of_check_mesh_src | — |
| validation |  | ghia_1982 | alts, breaks |
| mesh | (agent's call) Refine once more to Δx = 0.0125 (80×80×1) to test whether the passing 40×40 profiles have stopped changing; adopt 80×80 as the reported solution. | ghia_1982, of_check_mesh_src | — |
| convergence | Accept the 80×80 steady solution as iteratively converged. | of_user_guide_urf | — |
| validation | Validation PASS; report the 80×80 solution, with grid convergence shown across 20/40/80. | ghia_1982, cases/lid-cavity/reference/ghia_1982.json (data_provenance: suspected typo at Re=400, x=0.9063) | — |

<!-- END DECISIONS TABLE -->
