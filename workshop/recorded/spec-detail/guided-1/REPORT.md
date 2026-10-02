# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — Validation run 3 (40×40): u and v centrelines within 5% of Ghia — PASS

12 steps · 11 decisions · 3 retries · 3 gaps
<!-- END SUMMARY -->

## [09:13:52] geometry / ok — Template: icoFoam/cavity geometry + simpleFoam/pitzDaily steady controls

- **Decision:** (agent's call) Geometry, patches, 0/U and 0/p from incompressible/icoFoam/cavity/cavity; steady SIMPLE controls (controlDict, fvSchemes, fvSolution, turbulenceProperties) from incompressible/simpleFoam/pitzDaily; solver simpleFoam. Unit square (scenario-specified), blockMesh scale 0.1 → 1.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The icoFoam cavity tutorial is exactly the lid-driven cavity topology with the scenario's patch names (movingWall, fixedWalls, frontAndBack), but icoFoam is a transient PISO solver. The scenario asks for a steady solution, and simpleFoam is the steady incompressible SIMPLE solver; pitzDaily is the canonical simpleFoam tutorial supplying steadyState ddt, SIMPLE block and relaxation factors. SIMPLE pressure–velocity coupling for steady incompressible flow: Versteeg & Malalasekera (2007) ch. 6. No corpus annotation exists for either tutorial (get_tutorial_annotation: corpus empty). _(cites: versteeg_2007, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily)_
- **Alternatives:** icoFoam run to steady state with the cavity tutorial unchanged: valid, but marches in physical time and the scenario specifies a steady solve. pimpleFoam: transient, same objection.
- **When it breaks:** If the flow had no steady solution (time-periodic cavity flow), SIMPLE would stall with residuals plateauing; a transient solver would then be required. A stalled residual history would be the diagnostic.

</details>

Closed domain with zeroGradient p on every wall → pressure level undetermined; `pRefCell 0; pRefValue 0;` added to the SIMPLE block (the icoFoam cavity's PISO block carries the same pair). The pitzDaily `#includeFunc streamlines` was replaced by a `sets` functionObject sampling U on x=0.5 and y=0.5 (201 points each) for validation. Viscosity derived: ν = U_lid·L/Re = 1·1/400 = 0.0025 m²/s.

## [09:13:57] solver_config / ok — Flow model: laminar (simulationType laminar), ν = 0.0025

- **Decision:** (agent's call) Laminar — no turbulence model; turbulenceProperties simulationType laminar. Re = 400 (scenario-specified).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The validation reference is Ghia, Ghia & Shin (1982), a steady solution of the laminar incompressible Navier–Stokes equations (streamfunction–vorticity, multigrid) with no turbulence closure. Comparing against it with a RANS model would add an eddy viscosity absent from the reference, so a laminar model is the like-for-like choice. If the true flow were not steady-laminar at this Re, the steady laminar solve would fail to converge, and that stall would itself show it (first principles). _(cites: ghia_1982)_
- **Alternatives:** k-ε (pitzDaily default) or k-ω SST: these add modelled turbulent viscosity; in a laminar flow they at best predict ν_t ≈ 0 and at worst damp the recirculation, biasing the comparison against a laminar reference.
- **When it breaks:** At Reynolds numbers where cavity flow becomes unsteady or turbulent, a steady laminar solve will not converge to a fixed point; the residual history would plateau or oscillate.

</details>

## [09:14:02] boundary_conditions / ok — BCs: lid U=(1,0,0), noSlip walls, zeroGradient p, empty front/back

- **Decision:** (scenario-specified) Patch types and values as in the icoFoam cavity tutorial, unchanged.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario's BCs (moving lid at +x 1 m/s, no-slip on the other walls, empty front/back for 2-D) map one-to-one onto the icoFoam cavity tutorial's 0/U and 0/p. zeroGradient p at walls is the standard wall condition for pressure-based segregated solvers (Versteeg & Malalasekera 2007, ch. 9). _(cites: versteeg_2007, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/0)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

## [09:14:14] mesh / ok — Mesh: tutorial 20×20×1 uniform blockMesh (400 cells)

- **Decision:** (agent's call) Keep the icoFoam cavity tutorial resolution (20×20, simpleGrading 1 1 1) for the first run; the scenario defers resolution and asks for refinement if validation misses.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Tutorial default is the starting point. The reference JSON for Ghia (1982) explicitly states that the resolution meeting 5% must be established by refinement, not assumed up front; Ghia's own solution used a 129×129 uniform grid, the only sourced grid anchor. _(cites: ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict)_
- **Alternatives:** Start at a finer uniform grid or with wall grading. Deferred: no run-evidence yet that 20×20 is inadequate.
- **When it breaks:** Thin lid and wall shear layers are under-resolved on a coarse uniform grid. If they are, the centreline extrema (u minimum near y≈0.28, v peaks near the side walls) miss the reference.

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

## [09:14:18] mesh_quality / ok — checkMesh: Mesh OK, verdict good

- **Decision:** Accept mesh.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality=0 (< 60 deg), max_skewness=1.78e-14 (< 1), max_aspect_ratio=1 (< 10), severe faces 0. Orthogonal Cartesian cells need no non-orthogonal correctors. _(cites: of_check_mesh_src)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0 | good |
| max_skewness | 1.78e-14 | good |
| max_aspect_ratio | 1 | good |
| severe_non_orthogonal_faces | 0 | good |

## [09:14:29] convergence / warning — simpleFoam (20×20): residualControl met at iteration 50, residuals still falling

- **Decision:** (agent's call) Keep pitzDaily residualControl (p 1e-2, U 1e-3), endTime 2000, writeInterval 100 for this run; validate the result as written.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: acceptable (vs a 1e-3 band). Ux converged (7.08e-04), Uy still_running (9.98e-04), p still_running (1.23e-03); about 3 orders dropped, monotonic. The run stopped because the tutorial's residualControl thresholds were met, not because the residuals had plateaued, so iterative error may still be present. Whether it matters at the 5% level is for validation to show. _(cites: of_user_guide_urf, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSolution)_
- **Alternatives:** Tighten residualControl (e.g. to 1e-5) up front. Deferred until validation shows the iterative error matters.
- **When it breaks:** If the centreline profiles are still evolving between iteration 50 and a tighter stop, the early exit contaminates the validation with iterative error that would be mistaken for discretisation error.

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 7.08e-04 | 3.15 |
| Uy | 0.993 | 9.98e-04 | 3 |
| p | 1 | 1.23e-03 | 2.91 |

## [09:14:56] validation / error — Validation run 1 (20×20, 50 its): v-centreline misses Ghia

- **Decision:** FAIL: u passes (L2 0.0316 < 0.0664), v fails (L2 0.0463 > 0.0376). Both v-extrema are under-predicted: the peak near x≈0.23 is 0.25 against 0.30, and the trough near x≈0.86 is −0.37 against −0.45.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Two candidate causes are confounded in this run. (1) Iterative error: SIMPLE stopped at iteration 50 on the pitzDaily residualControl with residuals still falling (convergence entry). (2) Discretisation error: 20 cells across the cavity give only a few cells across the side-wall jets that set the v extrema. Peak flattening is the expected signature of both. Iterative error must be removed before grid error can be measured (Celik et al. 2008: solutions for a grid study must be iteratively converged). Scored with compare_profiles at the default tolerance of 5% of the reference range. _(cites: ghia_1982, celik_2008)_
- **Alternatives:** Refine the mesh directly without tightening convergence. Rejected because the residual-limited stop would then contaminate every grid level with the same unquantified iterative error.
- **When it breaks:** If the miss were caused by a model or BC error rather than resolution, neither tighter convergence nor refinement would close it. The u-profile already passing, and the profile shape being right with only the extrema flattened, argue against that.

</details>

### Comparison vs ghia_1982 (Re=400)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) @ x=0.5 | 0.0316 | 0.0686 | 0.0664 | pass |
| v(x) @ y=0.5 | 0.0463 | 0.0904 | 0.0376 | FAIL |

Plots: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png`.

## [09:15:18] validation / error — Validation run 2 (20×20, residualControl 1e-5): v still misses
_retry of: 'Validation run 1 (20×20, 50 its): v-centreline misses Ghia'_

- **Decision:** (deviation from tutorial) residualControl p,U tightened 1e-2/1e-3 → 1e-5. Converged in 117 iterations (all initial residuals < 1e-5). v-centreline L2 0.0463 → 0.0440, still above 0.0376; u L2 0.0316 → 0.0300 (pass).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Motivated by the 'Validation run 1' miss together with the run-1 convergence warning. Removing iterative error changed v-L2 by only 0.002 against a gap of 0.006 to tolerance, so the remaining error is discretisation error on the 20×20 grid. Iteratively converged solutions are a prerequisite for attributing error to the grid (Celik et al. 2008). _(cites: celik_2008, of_user_guide_urf)_
- **Alternatives:** Raising U/p relaxation or switching to a higher-order convection scheme: no evidence points at either. The scheme is already second-order linearUpwind, and convergence is monotonic.
- **When it breaks:** A 1e-5 residual target is close to the U linear-solver tolerance (1e-5), so a few final iterations do zero sweeps. Tighter targets would need a lower solver tolerance.

</details>

### Comparison vs ghia_1982 (Re=400)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) @ x=0.5 | 0.03 | 0.0645 | 0.0664 | pass |
| v(x) @ y=0.5 | 0.044 | 0.087 | 0.0376 | FAIL |

## [09:15:36] mesh / fixed — Mesh refined 20×20 → 40×40 uniform (1600 cells), checkMesh OK
_retry of: 'Validation run 2 (20×20, residualControl 1e-5): v still misses'_

- **Decision:** (agent's call, per scenario guidance 'refine if the first validation misses') Uniform refinement by a factor of 2 in x and y, grading unchanged (1 1 1).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Run 2 isolated the v-centreline miss as discretisation error (see 'Validation run 2'). A constant refinement ratio r = 2 keeps the grid sequence systematic, so a third level can feed a GCI estimate if needed (Celik et al. 2008). Grading was left uniform because no evidence yet localises the error to the walls rather than the core. Ghia's 129×129 uniform grid is the only sourced resolution anchor. _(cites: celik_2008, ghia_1982)_
- **Alternatives:** Wall-graded 20×20 or 30×30 grid: fewer cells, but it introduces an untested grading choice and breaks the constant-ratio sequence.
- **When it breaks:** If the error were concentrated in the thin wall layers, uniform refinement would converge slowly and wall grading would be more efficient.

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

## [09:15:49] convergence / ok — simpleFoam (40×40): converged in 152 iterations, ≥5 orders drop

- **Decision:** Accept: all initial residuals < 1e-5 (residualControl met), monotonic decrease.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Iteratively converged to the 1e-5 residualControl adopted in run 2; Ux, Uy drop 5.0 orders, p 5.5 orders. SIMPLE convergence monitored by initial residuals per OpenFOAM User Guide 6.3. _(cites: of_user_guide_urf)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 9.39e-06 | 5.03 |
| Uy | 0.998 | 9.15e-06 | 5.04 |
| p | 1 | 3.33e-06 | 5.48 |

## [09:16:00] validation / fixed — Validation run 3 (40×40): u and v centrelines within 5% of Ghia — PASS
_retry of: 'Validation run 2 (20×20, residualControl 1e-5): v still misses'_

- **Decision:** PASS on the 40×40 uniform grid with residualControl 1e-5: u L2 0.0080 (tol 0.0664), v L2 0.0313 (tol 0.0376).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Halving the cell size cut v-L2 from 0.0440 to 0.0313 and u-L2 from 0.0300 to 0.0080, which confirms the 20×20 miss was discretisation error. Scored by compare_profiles at the default tolerance of 5% of the reference range, matching the scenario's 0.05 relative-L2 criterion. The largest v deviation (L_inf 0.122) is at x = 0.9063, where Ghia's printed value −0.23827 is the suspected typo documented in the reference dataset: it breaks the otherwise smooth trough between −0.44993 (x = 0.8594) and −0.22847 (x = 0.9453). The point is kept as printed and still counts toward the L2. Away from it, the trough is still slightly shallow (−0.43 against −0.45 near x ≈ 0.86). _(cites: ghia_1982)_
- **Alternatives:** Refine to 80×80 for margin and a 3-level GCI: not required by the scenario (no grid_convergence block), and the pass is already established. Dropping the suspected-typo point: rejected because no published Re=400 re-tabulation justifies a replacement.
- **When it breaks:** The v margin is modest (0.0313 vs 0.0376). The pass depends on the 1e-5 iterative convergence and on keeping second-order linearUpwind convection. A first-order scheme, a looser residual stop, or a 20×20 grid each put v back over tolerance on this evidence (runs 1–2).

</details>

### Comparison vs ghia_1982 (Re=400)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) @ x=0.5 | 0.008 | 0.0173 | 0.0664 | pass |
| v(x) @ y=0.5 | 0.0313 | 0.1221 | 0.0376 | pass |

### Refinement history (v-centreline L2)

| run | grid | residualControl | iterations | u_L2 | v_L2 | verdict |
|---|---|---|---|---|---|---|
| 1 | 20×20 | p 1e-2, U 1e-3 | 50 | 0.0316 | 0.0463 | FAIL |
| 2 | 20×20 | 1e-5 | 117 | 0.03 | 0.044 | FAIL |
| 3 | 40×40 | 1e-5 | 152 | 0.008 | 0.0313 | PASS |

Plots: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png`; metrics with provenance in `postProcessing/analysis/metrics.json`. Run-2 (20×20) outputs retained under `history/run2_20x20/`.

## [09:16:08] post_processing / ok — |U| field at iteration 152 (40×40)

![U magnitude](postProcessing/images/U_tlatest.png)

A single primary vortex fills the cavity. The low-speed core sits slightly right of and above the geometric centre, with a high-speed lid layer and a downward wall jet along the right (downstream) wall. The bottom corners are near-stagnant. |U| spans 9.7e-05 to 0.88 at cell centres; the lid value of 1 lives on the boundary face. The image shows no checkerboarding or unphysical extrema.

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | (agent's call) Geometry, patches, 0/U and 0/p from incompressible/icoFoam/cavity/cavity; steady SIMPLE controls (controlDict, fvSchemes, fvSolution, turbulenceProperties) from incompressible/simpleFoam/pitzDaily; solver simpleFoam. Unit square (scenario-specified), blockMesh scale 0.1 → 1. | versteeg_2007, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily | — |
| solver_config | (agent's call) Laminar — no turbulence model; turbulenceProperties simulationType laminar. Re = 400 (scenario-specified). | ghia_1982 | — |
| boundary_conditions | (scenario-specified) Patch types and values as in the icoFoam cavity tutorial, unchanged. | versteeg_2007, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/0 | alts, breaks |
| mesh | (agent's call) Keep the icoFoam cavity tutorial resolution (20×20, simpleGrading 1 1 1) for the first run; the scenario defers resolution and asks for refinement if validation misses. | ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict | — |
| mesh_quality | Accept mesh. | of_check_mesh_src | alts, breaks |
| convergence | (agent's call) Keep pitzDaily residualControl (p 1e-2, U 1e-3), endTime 2000, writeInterval 100 for this run; validate the result as written. | of_user_guide_urf, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSolution | — |
| validation | FAIL: u passes (L2 0.0316 < 0.0664), v fails (L2 0.0463 > 0.0376). Both v-extrema are under-predicted: the peak near x≈0.23 is 0.25 against 0.30, and the trough near x≈0.86 is −0.37 against −0.45. | ghia_1982, celik_2008 | — |
| validation | (deviation from tutorial) residualControl p,U tightened 1e-2/1e-3 → 1e-5. Converged in 117 iterations (all initial residuals < 1e-5). v-centreline L2 0.0463 → 0.0440, still above 0.0376; u L2 0.0316 → 0.0300 (pass). | celik_2008, of_user_guide_urf | — |
| mesh | (agent's call, per scenario guidance 'refine if the first validation misses') Uniform refinement by a factor of 2 in x and y, grading unchanged (1 1 1). | celik_2008, ghia_1982 | — |
| convergence | Accept: all initial residuals < 1e-5 (residualControl met), monotonic decrease. | of_user_guide_urf | alts, breaks |
| validation | PASS on the 40×40 uniform grid with residualControl 1e-5: u L2 0.0080 (tol 0.0664), v L2 0.0313 (tol 0.0376). | ghia_1982 | — |

<!-- END DECISIONS TABLE -->
