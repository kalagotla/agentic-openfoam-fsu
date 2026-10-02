# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — PASS vs Ghia 1982 Re = 100: u L2 = 0.0049, v L2 = 0.0067 (steady)

11 steps · 10 decisions · 1 retry · 3 gaps
<!-- END SUMMARY -->

## [09:17:56] geometry / ok — Template icoFoam/cavity; benchmark Ghia 1982 at Re = 100

- **Decision:** (agent's call) Template incompressible/icoFoam/cavity/cavity, validated against Ghia, Ghia & Shin (1982) centreline profiles at Re = 100. The tutorial's 0.1 m square and U_lid = 1 m/s stay; nu goes from 0.01 to 0.001 m²/s.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario asks for a 2-D lid-driven cavity checked against "the standard published benchmark". Ghia et al. (1982) tabulate u(y) on the vertical centreline and v(x) on the horizontal centreline, and the repository holds that data as reference `ghia_1982` for Re = 100, 400 and 1000. The icoFoam cavity tutorial uses the same configuration: a square box, a top lid moving in +x, no slip on the other three walls, 2-D (one cell deep with empty front/back), laminar and incompressible. Its native operating point is Re = U L / nu = 1 × 0.1 / 0.01 = 10, which is below every tabulated Ghia case. Re = 100 is the lowest tabulated value, so it needs the smallest departure from the template: one property, nu, changes by a factor of 10. Holding L and U_lid fixed keeps the mesh, the lid BC and the Courant number at Co = U Δt / Δx = 1 × 0.005 / 0.005 = 1 identical to the tutorial. No corpus annotation exists for this tutorial (get_tutorial_annotation returned no_annotation). _(cites: ghia_1982, incompressible/icoFoam/cavity/cavity)_
- **Alternatives:** Re = 400 or 1000 from the same tables. Both have thinner wall layers and a stronger primary vortex than Re = 100, so they ask more of the tutorial's 20×20 mesh, and the Re = 400 v-profile has a suspected misprint at x = 0.9063 (noted in the reference file). Another option was rescaling the geometry to L = 1. That changes nothing physically because Re is the only parameter, but it would also mean changing blockMesh scale and deltaT, so it was not done.
- **When it breaks:** Ghia's data describe the steady solution. icoFoam is transient, so the comparison is only valid once the run has reached that steady state. At higher Re (≥ 3200 in Ghia's tables) the reference data are not encoded here, and a 2-D laminar steady comparison stops being a meaningful test.

</details>

## [09:18:20] mesh / ok — Tutorial blockMesh kept: uniform 20×20×1, Δx = 0.005 m

- **Decision:** (agent's call) Use the tutorial blockMeshDict as-is: one hex block, 20×20×1 cells, scale 0.1, no grading.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Setup choices start from the template. The scenario does not set a resolution, and the Ghia reference file says the resolution that meets its 5% band "is NOT known in advance" and should come out of refinement. The first run therefore uses the tutorial grid, and any refinement is driven by validation. Ghia's own solution used a 129×129 uniform grid, which is the only sourced anchor. _(cites: incompressible/icoFoam/cavity/cavity, ghia_1982)_
- **Alternatives:** Refine up front (e.g. 40×40 or 80×80), or grade toward the walls. Both were deferred until validation shows a miss.
- **When it breaks:** On a 20-cell grid the lid boundary layer at Re = 100 is resolved by only a few cells. If the centreline peaks are under-predicted, the grid is the first suspect.

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

## [09:18:24] mesh_quality / ok — checkMesh: Mesh OK, all metrics good

- **Decision:** (agent's call) Accept the mesh.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality = 0 (< 60°), max_skewness = 1.7e-14 (< 1), max_aspect_ratio = 1 (< 10), severe non-orthogonal faces = 0. The cells are orthogonal and uniform, so the tutorial's `orthogonal` laplacian/snGrad schemes and nNonOrthogonalCorrectors 0 are consistent with the mesh. _(cites: of_check_mesh_src, versteeg_2007)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0 | good |
| max_skewness | 1.67e-14 | good |
| max_aspect_ratio | 1 | good |
| severe_non_orthogonal_faces | 0 | good |

## [09:18:30] boundary_conditions / ok — Tutorial BCs: lid U = (1 0 0), no-slip walls, zeroGradient p

- **Decision:** (agent's call) Keep the tutorial's 0/U and 0/p unchanged. With U_lid = 1 m/s, sampled velocities are already normalised by U_lid.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Ghia's convention is a top wall moving at U_lid in +x with no slip on the other three walls. The tutorial's movingWall fixedValue (1 0 0) and fixedWalls noSlip match this exactly. Pressure is zeroGradient on every wall: the domain is closed, so p is fixed only up to a constant, and pRefCell/pRefValue in fvSolution supplies that level. _(cites: ghia_1982, incompressible/icoFoam/cavity/cavity)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** The two top corners carry a velocity discontinuity (u = 1 on the lid, u = 0 on the side walls). Because of that singularity, the near-corner solution converges more slowly with grid refinement than the interior.

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

## [09:18:36] solver_config / ok — icoFoam (PISO), tutorial schemes/controls; nu = 0.001; centreline sampling

- **Decision:** (agent's call) Run icoFoam with the tutorial fvSchemes (Euler, Gauss linear), fvSolution (PISO, 2 correctors), Δt = 0.005 s and endTime = 0.5 s. The only physical patch is nu 0.01 → 0.001 (Re = 100). A `sets` functionObject samples U at 101 points along x = 0.05 m (vertical) and y = 0.05 m (horizontal) at mid-depth z = 0.005 m.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Re = U L / nu = 1 × 0.1 / 0.001 = 100. Courant number Co = U Δt / Δx = 1 × 0.005 / 0.005 = 1, the same as the tutorial. Ghia's tables are on the centrelines x/L = 0.5 and y/L = 0.5, so the case writes those lines directly. _(cites: incompressible/icoFoam/cavity/cavity, ghia_1982)_
- **Alternatives:** A steady solver (simpleFoam, laminar). It reaches the steady state without time-marching, but it would mean moving away from the template's transient PISO setup. Not adopted for the first run.
- **When it breaks:** endTime = 0.5 s is 5 convective times (L/U = 0.1 s). The viscous diffusion time L²/nu grows from 1 s at Re = 10 to 10 s at Re = 100, so the tutorial's end time may not be long enough to reach the steady state that Ghia tabulates. The residual and validation results will show whether it is.

</details>

## [09:18:51] convergence / warning — t = 0.5 s: residuals still falling, steady state not yet reached

- **Decision:** (agent's call) Go on to validation at t = 0.5 s and let the comparison show whether the remaining transient matters.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: marginal. Ux and Uy are still_running: the initial residuals fell from about 2.5e-3 to about 6–7e-4 over the last 50 steps and are still decreasing monotonically. The `oscillating` flag on p is an artifact of how the log is read. With PISO nCorrectors = 2 the log prints two p solves per time step, at about 8e-4 for the first corrector and about 3e-4 for the second. Interleaving the two produces a sawtooth, even though each sequence falls monotonically on its own (first corrector 8.65e-4 → 8.00e-4, second 3.37e-4 → 3.03e-4 over the last four steps). The URF advice from the classifier is for SIMPLE and does not apply here, because icoFoam has no under-relaxation. Max Co = 0.84. _(cites: of_user_guide_urf)_
- **Alternatives:** Extend endTime before validating. Held back so that the validation result is what drives that change.
- **When it breaks:** If the centreline profiles are still developing, comparing them with a steady benchmark mixes temporal error with discretisation error.

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 6.08e-04 | 3.22 |
| Uy | - | 7.15e-04 | - |
| p | 1 | 3.03e-04 | 3.52 |

## [09:19:26] validation / warning — t = 0.5 s: inside 5% band, but profiles not yet steady

- **Decision:** (agent's call) Do not accept this pass. The flow is still evolving, so the comparison with Ghia's steady solution is not yet like-for-like.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** compare_profiles: u(y) L2 = 0.0120 against a 0.0605 threshold, v(x) L2 = 0.0159 against 0.0210. Both are within tolerance. Over the last 0.1 s (t = 0.4 → 0.5) the sampled profiles still changed by up to 0.0130 U_lid in u and 0.0122 U_lid in v. That is the same size as the L2 error, so the score at t = 0.5 s partly reflects how far the transient has got. In the overlay the simulation under-shoots every extremum (u_min ≈ −0.18 against −0.21; v_max ≈ 0.15 against 0.175; v_min ≈ −0.22 against −0.245). The convergence step also showed the U residuals still decreasing monotonically. _(cites: ghia_1982)_
- **Alternatives:** Accept the t = 0.5 s pass as it stands. Rejected because Ghia's data are a steady solution, so the error budget should not include an unfinished transient.
- **When it breaks:** If the extremum under-shoot persists once the run is steady, the remaining error comes from the 20×20 discretisation and calls for grid refinement.

</details>

### Comparison vs ghia_1982 (Re = 100, t = 0.5 s)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) at x/L = 0.5 | 0.012 | 0.0232 | 0.0605 | within (not steady) |
| v(x) at y/L = 0.5 | 0.0159 | 0.0262 | 0.021 | within (not steady) |

Overlay: `postProcessing/analysis/centerline_profiles.png`

## [09:19:45] solver_config / fixed — endTime 0.5 → 3 s so the transient decays to steady state
_retry of: 't = 0.5 s: inside 5% band, but profiles not yet steady'_

- **Decision:** (deviation from tutorial, driven by the t = 0.5 s steadiness miss) Raise endTime from 0.5 s to 3 s (30 convective times L/U). Δt, schemes and PISO controls are unchanged, and the run restarts from t = 0.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** At t = 0.5 s the centreline profiles still changed by about 0.013 U_lid per 0.1 s, and the U residuals were decreasing monotonically (still_running), not stalled. The transient was decaying, not stuck. Cutting nu by 10× raises the viscous diffusion time L²/nu from 1 s to 10 s, so the start-up transient lasts longer than at the tutorial's Re = 10. A transient solver reaches the steady state only by integrating through that decay, so a longer endTime with the time step unchanged is the minimal fix. _(cites: incompressible/icoFoam/cavity/cavity)_
- **Alternatives:** Switch to a steady solver. Rejected because it changes the template's algorithm when only the integration length was short. Raising Δt to get there faster was also rejected, because Co would exceed the tutorial's value of 1.
- **When it breaks:** If the flow had a time-periodic state rather than a steady one, a longer endTime would never bring the profiles to rest. The diagnostic for that is a profile change between writes that does not decay.

</details>

## [09:19:50] convergence / ok — t = 3 s: steady state; U residuals ~1e-8, profiles frozen to 1e-6

- **Decision:** (agent's call) Treat t = 3 s as the steady state.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Over 600 time steps, Ux initial residuals fell 8.1 orders, to 7.8e-9. Uy reached 9.6e-9 and p is at 8.3e-7, the same order as the PCG tolerance of 1e-6. In the last steps the linear solvers take 0–1 iterations, because the fields already satisfy the tolerances on entry. Between t = 2.9 and 3.0 s the sampled centreline profiles change by at most 1e-6 U_lid, which is the 6-significant-figure write precision. _(cites: of_user_guide_urf)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 7.76e-09 | 8.11 |
| Uy | - | 9.61e-09 | - |
| p | 1 | 8.26e-07 | 6.08 |

## [09:20:00] validation / ok — PASS vs Ghia 1982 Re = 100: u L2 = 0.0049, v L2 = 0.0067 (steady)

- **Decision:** (agent's call) Accept. Both centreline profiles are inside the 5%-of-range band against Ghia et al. (1982) at Re = 100 on the tutorial's 20×20 grid.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** compare_profiles on the 17 Ghia stations per line gives u(y): L2 = 0.0049 against a threshold of 0.0605 (0.4% of the reference range 1.21), and v(x): L2 = 0.0067 against 0.0210 (1.6% of range 0.42). Reaching steady state roughly halved both errors compared with t = 0.5 s (u 0.0120 → 0.0049, v 0.0159 → 0.0067). The largest pointwise deviation, L_inf = 0.013 in u and 0.0095 in v, sits at the profile extrema. There the 20-cell grid smooths the peaks: v_min ≈ −0.236 against −0.245 at x/L ≈ 0.81, and v_max ≈ 0.167 against 0.175. The v profile has the smaller margin (32% of its threshold), so resolving its peaks is where the grid limits the result. _(cites: ghia_1982)_
- **Alternatives:** A grid-refinement / GCI study (Celik et al. 2008) would separate the remaining discretisation error from the reference. The scenario does not ask for one, and the tolerance is met on the first grid, so no refinement was run.
- **When it breaks:** This pass shows agreement on one grid. It is not grid independence. At Re = 400 or 1000 the wall layers and extrema sharpen, so the same 20×20 grid would leave more error at the peaks, and refinement would need to be demonstrated rather than assumed.

</details>

### Comparison vs ghia_1982 (Re = 100, t = 3 s)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) at x/L = 0.5 | 0.0049 | 0.013 | 0.0605 | PASS |
| v(x) at y/L = 0.5 | 0.0067 | 0.0095 | 0.021 | PASS |

Overlay: `postProcessing/analysis/centerline_profiles.png`; metrics with provenance in `postProcessing/analysis/metrics.json`.

## [09:20:09] post_processing / ok — |U| at t = 3 s: lid-driven shear layer and primary vortex

![U magnitude](postProcessing/images/U_tlatest.png)

The cell-centred |U| ranges from 6.8e-5 to 0.79 m/s. Fluid is fastest in the first cell row under the lid. Its cell-centre value is below U_lid = 1 because the lid value applies on the boundary face, not at the cell centre. A low-speed core sits below the lid near x/L ≈ 0.6, and that is where the primary vortex centre lies. A faster return flow runs down the right wall. The bottom corners are near stagnant. The pattern is qualitatively consistent with the centreline profiles validated above.

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | (agent's call) Template incompressible/icoFoam/cavity/cavity, validated against Ghia, Ghia & Shin (1982) centreline profiles at Re = 100. The tutorial's 0.1 m square and U_lid = 1 m/s stay; nu goes from 0.01 to 0.001 m²/s. | ghia_1982, incompressible/icoFoam/cavity/cavity | — |
| mesh | (agent's call) Use the tutorial blockMeshDict as-is: one hex block, 20×20×1 cells, scale 0.1, no grading. | incompressible/icoFoam/cavity/cavity, ghia_1982 | — |
| mesh_quality | (agent's call) Accept the mesh. | of_check_mesh_src, versteeg_2007 | alts, breaks |
| boundary_conditions | (agent's call) Keep the tutorial's 0/U and 0/p unchanged. With U_lid = 1 m/s, sampled velocities are already normalised by U_lid. | ghia_1982, incompressible/icoFoam/cavity/cavity | alts |
| solver_config | (agent's call) Run icoFoam with the tutorial fvSchemes (Euler, Gauss linear), fvSolution (PISO, 2 correctors), Δt = 0.005 s and endTime = 0.5 s. The only physical patch is nu 0.01 → 0.001 (Re = 100). A `sets` functionObject samples U at 101 points along x = 0.05 m (vertical) and y = 0.05 m (horizontal) at mid-depth z = 0.005 m. | incompressible/icoFoam/cavity/cavity, ghia_1982 | — |
| convergence | (agent's call) Go on to validation at t = 0.5 s and let the comparison show whether the remaining transient matters. | of_user_guide_urf | — |
| validation | (agent's call) Do not accept this pass. The flow is still evolving, so the comparison with Ghia's steady solution is not yet like-for-like. | ghia_1982 | — |
| solver_config | (deviation from tutorial, driven by the t = 0.5 s steadiness miss) Raise endTime from 0.5 s to 3 s (30 convective times L/U). Δt, schemes and PISO controls are unchanged, and the run restarts from t = 0. | incompressible/icoFoam/cavity/cavity | — |
| convergence | (agent's call) Treat t = 3 s as the steady state. | of_user_guide_urf | alts, breaks |
| validation | (agent's call) Accept. Both centreline profiles are inside the 5%-of-range band against Ghia et al. (1982) at Re = 100 on the tutorial's 20×20 grid. | ghia_1982 | — |

<!-- END DECISIONS TABLE -->
