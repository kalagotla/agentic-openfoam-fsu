# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — PASS: Re=100 centreline u and v within tolerance of Ghia et al. (1982)

9 steps · 9 decisions · 1 retry · 4 gaps
<!-- END SUMMARY -->

## [09:13:16] geometry / ok — Template: icoFoam cavity; operating point Re = 100 vs Ghia et al. (1982)

- **Decision:** (agent's call) Template incompressible/icoFoam/cavity/cavity; Re = U_lid L / nu = 100 (L = 0.1 m, U_lid = 1 m/s, nu = 1e-3 m^2/s); benchmark ghia_1982 Re=100 centreline profiles u(y) at x = L/2 and v(x) at y = L/2.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario asks for a 2-D lid-driven cavity against the standard published benchmark; the reference library holds Ghia, Ghia & Shin (1982) Tables I/II for Re = 100, 400, 1000, which define the cavity as a unit square with lid velocity 1 and three no-slip walls, steady and incompressible. icoFoam/cavity has exactly this topology (movingWall / fixedWalls / empty front-back, 2-D single cell in z). The tutorial runs Re = 1 * 0.1 / 0.01 = 10, which has no Ghia column, so nu is the one physics value that must change. Re = 100 is the lowest tabulated column: a laminar, steady flow is what both a steady benchmark and a transient laminar solver presume, and it is the operating point closest to the tutorial's own regime. Geometry (scale 0.1) and lid velocity are kept from the tutorial; only nu changes (0.01 -> 0.001). No corpus annotation exists for this tutorial (corpus/incompressible/icoFoam/cavity/cavity.md missing). _(cites: ghia_1982, incompressible/icoFoam/cavity/cavity (no corpus annotation))_
- **Alternatives:** Re = 400 or 1000 (also tabulated): stronger, thinner shear layers near the lid and secondary corner vortices demand more resolution than the tutorial grid, and the Re = 400 v-column carries a suspected typo at x = 0.9063 noted in the reference file. A steady SIMPLE solver (simpleFoam laminar) would reach the steady state directly but would mean departing from the cavity tutorial's transient PISO template.
- **When it breaks:** If the researcher intends a higher-Re point, the thin lid shear layer would need a finer grid than this template ships. If icoFoam has not reached a time-independent state by endTime, a comparison against Ghia's steady solution is not meaningful.

</details>

## [09:13:39] mesh / ok — blockMesh: tutorial 20x20x1 uniform grid, 400 cells

- **Decision:** (agent's call) Tutorial blockMeshDict kept verbatim: one hex block, 20x20x1, uniform grading, dx = L/20 = 5 mm.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Geometry is block-aligned, so the tutorial blockMesh applies unchanged. Resolution stays at the tutorial value for the first run; the Ghia comparison decides whether it is adequate. The only sourced grid anchor is Ghia's own 129x129 solution (ghia_1982), and the reference's acceptance band is meant to be reached by refinement rather than an a-priori cell count. _(cites: ghia_1982, incompressible/icoFoam/cavity/cavity/system/blockMeshDict)_
- **Alternatives:** Refining up front (e.g. toward Ghia's 129x129) was deferred: the comparison against the reference is the evidence that should motivate any refinement.
- **When it breaks:** A 5 mm cell spans 5% of the cavity; the near-lid shear layer and the u-minimum near y/L ~ 0.45 may be under-resolved, which would show up as a centreline L2 miss.

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

## [09:13:43] mesh_quality / ok — checkMesh: Mesh OK, verdict good on all metrics

- **Decision:** Accept mesh; no non-orthogonal correction needed.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality=0 (< 60 deg), max_skewness=1.67e-14 (< 1), max_aspect_ratio=1 (< 10), severe_non_orthogonal_faces=0. A uniform Cartesian grid is orthogonal by construction. _(cites: of_check_mesh_src, versteeg_2007)_
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

## [09:13:48] boundary_conditions / ok — BCs: tutorial lid/no-slip/empty set, unchanged

- **Decision:** (agent's call) Tutorial 0/U and 0/p verbatim: lid fixedValue (1 0 0), other walls noSlip, p zeroGradient on walls, empty front/back.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** These reproduce Ghia's problem statement exactly: top wall moving at U_lid in +x, the other three walls no-slip, 2-D. With an all-wall boundary the pressure level is fixed by the tutorial's pRefCell/pRefValue in fvSolution. _(cites: ghia_1982, incompressible/icoFoam/cavity/cavity/0)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** The lid velocity is discontinuous at the two top corners (singular corner pressure); this is shared with Ghia's formulation, so it does not bias the comparison, but corner values themselves are grid-dependent.

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

## [09:13:53] solver_config / ok — icoFoam, tutorial schemes/PISO/time controls; nu = 1e-3; centreline sets added

- **Decision:** (agent's call) icoFoam with tutorial fvSchemes, fvSolution and time controls (deltaT 0.005 s, endTime 0.5 s); only nu changed (0.01 -> 0.001) and a `sets` functionObject added sampling U on x = L/2 and y = L/2 (101 points each, cellPoint) at every write.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** icoFoam is the tutorial's transient laminar incompressible solver, and Re = 100 is laminar. Courant number at the lid: U dt/dx = 1 * 0.005 / 0.005 = 1, the tutorial's own value. The validation server cannot run postProcess, so the solver writes the centreline samples itself. _(cites: incompressible/icoFoam/cavity/cavity/system)_
- **Alternatives:** Extending endTime ahead of evidence was deferred; whether 0.5 s (5 lid convective times L/U) reaches a steady state will be read from the residual history.
- **When it breaks:** At Re = 100 the viscous diffusion time L^2/nu = 10 s is 20x endTime, so if the spin-up is diffusion-limited the field at 0.5 s is still transient and the steady benchmark comparison is invalid.

</details>

## [09:14:07] convergence / warning — icoFoam to t = 0.5 s: velocity residuals still decaying, not steady

- **Decision:** Do not compare against the steady benchmark at t = 0.5 s; the flow has not reached a time-independent state.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: marginal. Ux still_running (2.21e-3 -> 6.08e-4 over the last 50 steps), Uy still_running (2.79e-3 -> 7.15e-4). In a transient solver the initial residual of each step measures the change from the previous step, so a residual still falling monotonically means the field is still evolving. The p 'oscillating' flag comes from the log interleaving the two PISO corrector solves per step (first ~8e-4, second ~3e-4), not from a physical oscillation. Ghia et al. tabulate a steady solution, so the comparison needs a steady field. _(cites: of_user_guide_urf, ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 0.000608 | 3.22 |
| Uy | 0 (first step) | 0.000715 | n/a |
| p | 1 | 0.000303 | 3.52 |

## [09:14:25] convergence / fixed — endTime 0.5 -> 5 s: steady state reached, U residuals ~1e-10
_retry of: 'icoFoam to t = 0.5 s: velocity residuals still decaying, not steady'_

- **Decision:** (deviation from tutorial) endTime 0.5 s -> 5 s (50 lid convective times, half the viscous time L^2/nu = 10 s); writeInterval 20 -> 200 steps (writes every 1 s). deltaT unchanged.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Motivated by the unconverged residuals at t = 0.5 s. The observed decay rate there (Ux down ~3.6x per 50 steps) gave a rough estimate of ~1 s more to reach 1e-5; 5 s adds a wide margin at negligible cost on 400 cells. Result: Ux and Uy initial residuals 7.3e-11 / 1.1e-10 at t = 5 s, and the linear solvers take 0 iterations because the per-step change is already below their tolerance. The p residual sits at 8.7e-7, just under the tutorial's p solver tolerance (1e-6), so it no longer moves. Max Courant 0.84. _(cites: of_user_guide_urf, incompressible/icoFoam/cavity/cavity/system/fvSolution)_
- **Alternatives:** A steady SIMPLE solve would reach the same fixed point without time-marching but means changing the solver family away from the template; a residualControl-style stop is not available in icoFoam.
- **When it breaks:** If the flow had a periodic attractor (higher Re), extending endTime would never yield a stationary field and the residual floor would not drop.

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 7.34e-11 | 10.1 |
| Uy | first-step 0 | 1.05e-10 | n/a |
| p | 1 | 8.73e-7 | 6.06 |

## [09:15:06] validation / ok — PASS: Re=100 centreline u and v within tolerance of Ghia et al. (1982)

- **Decision:** Accept the 20x20 tutorial grid at Re = 100: both centreline profiles are inside the 5%-of-range L2 tolerance. No refinement triggered.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Scored by compare_profiles on Ghia's 17 tabulated stations per line. u(y) on x/L = 0.5: L2 = 0.0049 vs threshold 0.0605 (reference range 1.21). v(x) on y/L = 0.5: L2 = 0.0067 vs threshold 0.0210 (range 0.42). The field is stationary: the largest centreline change between t = 4 s and 5 s is 1e-6 U_lid. The largest pointwise errors are at the profile extrema, where a 5 mm cell is coarsest relative to the curvature: u minimum near y/L ~ 0.45-0.5 (L_inf 0.013) and the v peak near x/L ~ 0.23 (0.166 vs 0.175, L_inf 0.0095). The v margin (L2 at 32% of threshold) is tighter than u (8%). _(cites: ghia_1982)_
- **Alternatives:** A three-grid refinement study (GCI) would quantify discretisation error directly; the scenario did not request one, and the comparison did not miss, so it was not run.
- **When it breaks:** The pass is specific to Re = 100. The reference file notes that the grid that meets the band is not known in advance; at Re = 400 or 1000 the thinner lid shear layer and sharper extrema would stress this 20x20 grid much more, and the result here should not be taken as evidence of grid independence.

</details>

### Comparison vs ghia_1982 (Re = 100)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u(y) at x/L = 0.5 | 0.0049 | 0.013 | 0.0605 | pass |
| v(x) at y/L = 0.5 | 0.0067 | 0.0095 | 0.021 | pass |

Overlay: `postProcessing/analysis/centreline_vs_ghia.png`; metrics with provenance: `postProcessing/analysis/metrics.json` (sample time 5 s, git aecc137).

## [09:15:10] post_processing / ok — |U| field at t = 5 s: single primary vortex, core in upper half

<details><summary>why · alternatives · when it breaks</summary>

- **Why:** _uncited choice — no annotation, reference, or paper cited._ _(cites: ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

Rendered `postProcessing/images/U_tlatest.png` (cell values, |U| 1.4e-4 to 0.84). The lid shear layer occupies the top cell rows; the low-speed vortex core sits above mid-height and right of centre, close to the primary-vortex location Ghia et al. tabulate for Re = 100 (x, y) ~ (0.62, 0.74) L. The 20x20 cells are visible; the lower corner eddies are too weak to show on a linear |U| scale.

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | (agent's call) Template incompressible/icoFoam/cavity/cavity; Re = U_lid L / nu = 100 (L = 0.1 m, U_lid = 1 m/s, nu = 1e-3 m^2/s); benchmark ghia_1982 Re=100 centreline profiles u(y) at x = L/2 and v(x) at y = L/2. | ghia_1982, incompressible/icoFoam/cavity/cavity (no corpus annotation) | — |
| mesh | (agent's call) Tutorial blockMeshDict kept verbatim: one hex block, 20x20x1, uniform grading, dx = L/20 = 5 mm. | ghia_1982, incompressible/icoFoam/cavity/cavity/system/blockMeshDict | — |
| mesh_quality | Accept mesh; no non-orthogonal correction needed. | of_check_mesh_src, versteeg_2007 | alts, breaks |
| boundary_conditions | (agent's call) Tutorial 0/U and 0/p verbatim: lid fixedValue (1 0 0), other walls noSlip, p zeroGradient on walls, empty front/back. | ghia_1982, incompressible/icoFoam/cavity/cavity/0 | alts |
| solver_config | (agent's call) icoFoam with tutorial fvSchemes, fvSolution and time controls (deltaT 0.005 s, endTime 0.5 s); only nu changed (0.01 -> 0.001) and a `sets` functionObject added sampling U on x = L/2 and y = L/2 (101 points each, cellPoint) at every write. | incompressible/icoFoam/cavity/cavity/system | — |
| convergence | Do not compare against the steady benchmark at t = 0.5 s; the flow has not reached a time-independent state. | of_user_guide_urf, ghia_1982 | alts, breaks |
| convergence | (deviation from tutorial) endTime 0.5 s -> 5 s (50 lid convective times, half the viscous time L^2/nu = 10 s); writeInterval 20 -> 200 steps (writes every 1 s). deltaT unchanged. | of_user_guide_urf, incompressible/icoFoam/cavity/cavity/system/fvSolution | — |
| validation | Accept the 20x20 tutorial grid at Re = 100: both centreline profiles are inside the 5%-of-range L2 tolerance. No refinement triggered. | ghia_1982 | — |
| post_processing |  | ghia_1982 | alts, breaks |

<!-- END DECISIONS TABLE -->
