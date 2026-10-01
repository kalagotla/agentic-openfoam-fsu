# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — PASS on 80x80 vs Ghia Re=400: u 0.17%, v 4.64% rel-L2 (tol 5%)

12 steps · 12 decisions · 3 retries · 8 gaps
<!-- END SUMMARY -->

## [16:36:23] geometry / ok — Template: icoFoam/cavity geometry + simpleFoam/pitzDaily SIMPLE controls

- **Decision:** Unit square cavity (L = 1 m, scale 0.1 -> 1) from incompressible/icoFoam/cavity/cavity (scenario-specified template), solved with simpleFoam (scenario-specified); fvSchemes/fvSolution/controlDict/transportProperties/turbulenceProperties taken from incompressible/simpleFoam/pitzDaily (agent's call), with laminar simulationType and nu = 0.0025 (scenario-specified, Re = 1*1/0.0025 = 400).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The cavity tutorial supplies the geometry, patch names (movingWall, fixedWalls, frontAndBack) and BCs that the scenario names, but its PISO/Euler controls belong to the transient icoFoam. simpleFoam needs a SIMPLE dictionary, relaxation factors and a steadyState ddt scheme, and pitzDaily is the stock simpleFoam tutorial that carries them. A closed cavity with zeroGradient p on every wall leaves the pressure level undetermined (only grad p enters the momentum equation), so pRefCell 0 / pRefValue 0 is carried over from the cavity tutorial's PISO block into the SIMPLE block. Reference data are non-dimensional with L = U_lid = 1, so L = 1 m and U_lid = 1 m/s let u, v compare directly. No corpus annotation exists for either tutorial. _(cites: ghia_1982, of_user_guide_urf)_
- **Alternatives:** Keeping icoFoam (the template's own solver) would march a transient to steady state, but the scenario fixes simpleFoam.
- **When it breaks:** A steady solver assumes a steady solution exists. If the cavity flow at the chosen Re were inherently unsteady, SIMPLE would stall or oscillate instead of converging, and that stall would itself be the diagnostic.

</details>

### Setup origin

| item | source |
|---|---|
| geometry / patches | icoFoam/cavity (scale 0.1 -> 1) |
| mesh 20x20x1 | icoFoam/cavity, unchanged |
| 0/U, 0/p | icoFoam/cavity, unchanged |
| fvSchemes | simpleFoam/pitzDaily, unchanged (linearUpwind for U) |
| fvSolution | simpleFoam/pitzDaily + pRefCell/pRefValue |
| controlDict | simpleFoam/pitzDaily; endTime 5000, writeInterval 1000, centerline sets |
| transport | pitzDaily, nu 0.0025 |
| turbulence | laminar |

## [16:36:34] mesh / ok — blockMesh: uniform 20x20x1 square (tutorial resolution)

- **Decision:** Uniform 20x20x1 hex grid, dx = dy = 0.05 L, kept at the cavity tutorial's resolution for the first run (agent's call: tutorial default retained).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The tutorial's resolution is the starting point. Ghia et al. computed their reference on a 129x129 uniform grid, so this mesh is far coarser. Validation against the 5% relative-L2 band decides whether refinement is needed. _(cites: ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** With only 20 cells per side the thin wall shear layers under the lid and the corner eddies are covered by a few cells. Under-resolution would show up as smeared centerline peaks against the reference.

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

## [16:36:37] mesh_quality / ok — checkMesh: Mesh OK, all metrics good

- **Decision:** Accept the mesh.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality=0 (< 60 deg), max_skewness=1.78e-14 (< 1), max_aspect_ratio=1 (< 10), severe_non_orthogonal_faces=0. No non-orthogonal correctors needed. _(cites: of_check_mesh_src, versteeg_2007)_
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

## [16:36:42] boundary_conditions / ok — BCs: moving lid U=(1 0 0), no-slip walls, zeroGradient p, empty z

- **Decision:** 0/U and 0/p taken verbatim from icoFoam/cavity, which already matches the scenario: movingWall fixedValue (1 0 0), fixedWalls noSlip, frontAndBack empty (scenario-specified). The fully enclosed domain is pinned with pRefCell 0 / pRefValue 0.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario's lid velocity, no-slip walls and empty front/back are exactly the tutorial's BCs. With zeroGradient p on every boundary, the pressure is fixed only up to a constant, so a reference cell sets its level. _(cites: ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** The lid's fixedValue meets the noSlip side walls at the top corners, giving a velocity discontinuity (a pressure singularity). Its influence on the centerline profiles is not characterized here.

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

## [16:36:57] convergence / warning — simpleFoam stopped at iteration 50 by residualControl: ~3 orders dropped

- **Decision:** Run 1 is flagged as under-converged: the inherited pitzDaily residualControl (p 1e-2, U 1e-3) ended the SIMPLE loop at iteration 50 of the scenario's 5000.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario requires residuals to drop at least 4 orders of magnitude. Measured drops were Ux 3.15, Uy 3.00, p 2.91. assess_residuals classes every field as still_running (healthy monotone decay that was cut off by the stopping criterion, not stalled), so the stop came from the criterion, not from a converged solution. _(cites: of_user_guide_urf)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1.0 | 7.08e-04 | 3.15 |
| Uy | 0.993 | 9.98e-04 | 3 |
| p | 1.0 | 1.23e-03 | 2.91 |

## [16:37:28] solver_config / fixed — residualControl tightened to p, U 1e-5 (deviation from pitzDaily)
_retry of: 'simpleFoam stopped at iteration 50 by residualControl: ~3 orders dropped'_

- **Decision:** SIMPLE residualControl changed from p 1e-2 / U 1e-3 to p 1e-5 / U 1e-5 (deviation from tutorial, driven by the failed 4-order check). Everything else is unchanged; the run restarts from t = 0.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Initial residuals start at O(1), so a 4-order drop means initial residuals at or below 1e-4. Setting the stop criterion at 1e-5 meets that with one order of margin, and matches assess_residuals' default "converged" level. The scenario's end_time 5000 stays as the upper bound. _(cites: of_user_guide_urf)_
- **Alternatives:** Remove residualControl entirely and run the full 5000 iterations. That reaches the same converged state at higher cost, and the run would not report when the solution stopped changing.
- **When it breaks:** If the residuals plateau above 1e-5 (for example from a discretization limit cycle), the run goes to 5000 without triggering the criterion. That outcome would be classed as stalled, not converged.

</details>

## [16:37:44] convergence / fixed — 20x20: SIMPLE converged in 117 iterations, 5.0-5.5 orders dropped
_retry of: 'simpleFoam stopped at iteration 50 by residualControl: ~3 orders dropped'_

- **Decision:** Accept convergence. All fields fall below 1e-5 and the 4-order criterion is met.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: good. Ux converged (last=9.43e-06), Uy converged (last=9.46e-06), p converged (last=3.38e-06). The decay is monotone, with no stall or oscillation at the tutorial's relaxation factors (U 0.9, consistent SIMPLEC). _(cites: of_user_guide_urf)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1.0 | 9.43e-06 | 5.03 |
| Uy | 0.993 | 9.46e-06 | 5.02 |
| p | 1.0 | 3.38e-06 | 5.47 |

## [16:37:53] validation / error — 20x20 vs Ghia Re=400: u passes (2.3%), v fails (5.9% > 5%)

- **Decision:** Validation fails on v(x) at y = 0.5. The cause is diagnosed as grid under-resolution, and the next step is mesh refinement.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The v overlay clips both extrema: simulated peak 0.25 vs reference 0.30 near x ≈ 0.23, and trough -0.37 vs -0.45 near x ≈ 0.86. Both sit in the regions of steepest v gradient beside the side walls, where 20 cells per side gives about 4 cells across each peak. The profile shape and the zero crossing near x = 0.5 match, which points to resolution rather than BC or model error. Ghia's own solution was computed on a 129x129 uniform grid, and the reference file's tolerance rationale prescribes refining until the profiles converge. Note that Ghia's printed point at x = 0.9063 (v = -0.23827) is flagged in the reference provenance as a suspected typo. It is kept as printed and contributes to the v error on any grid. _(cites: ghia_1982)_
- **Alternatives:** A higher-order or less-bounded convection scheme could sharpen the peaks on the same grid. It is not chosen because the overlay shows the miss is spread across the whole wall-adjacent region, which is a resolution signature, and refinement is what the reference's own acceptance criterion calls for.
- **When it breaks:** If refinement stops changing the profiles while the v error stays above 5%, the miss is not resolution. The suspected-typo point or a scheme or BC issue would then need diagnosis.

</details>

### Comparison vs ghia_1982

| profile | L2 | L_inf | rel_L2 | tolerance | verdict |
|---|---|---|---|---|---|
| u(y) at x=0.5 | 0.03 | 0.0645 | 0.0226 | 0.05 | pass |
| v(x) at y=0.5 | 0.044 | 0.087 | 0.0586 | 0.05 | fail |

Plots: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png` (sample time 117).

## [16:38:27] validation / fixed — 40x40 vs Ghia Re=400: u 0.6%, v 4.2% (both pass)
_retry of: '20x20 vs Ghia Re=400: u passes (2.3%), v fails (5.9% > 5%)'_

- **Decision:** Mesh refined uniformly from 20x20 to 40x40 (deviation from tutorial resolution, driven by the v-centerline miss). checkMesh: Mesh OK, non-orthogonality 0, aspect ratio 1. SIMPLE converged in 152 iterations below 1e-5.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Halving dx cut the v relative-L2 from 5.86% to 4.16% and the u relative-L2 from 2.26% to 0.60%, consistent with a discretization error that shrinks under refinement. The v peak (0.29 vs 0.30) and trough (-0.43 vs -0.45) now track the reference. The largest remaining v deviation (L_inf 0.122) is at x = 0.9063, where the simulation gives v = -0.360 against Ghia's printed -0.238. That is the point the reference provenance flags as a suspected typo, an outlier between -0.450 and -0.228. The simulated neighbours at x = 0.8594 (-0.428) and x = 0.9453 (-0.216) agree with the reference. _(cites: ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** A single refinement step does not show grid independence. The 80x80 level below tests whether the profiles have stopped changing.

</details>

### Comparison vs ghia_1982

| profile | L2 | L_inf | rel_L2 | tolerance | verdict |
|---|---|---|---|---|---|
| u(y) at x=0.5 | 0.008 | 0.0173 | 0.006 | 0.05 | pass |
| v(x) at y=0.5 | 0.0313 | 0.122 | 0.0416 | 0.05 | pass |

### Mesh stats

| cells | points | faces | internal_faces |
|---|---|---|---|
| 1600 | 3362 | 6480 | 3120 |

## [16:38:56] convergence / ok — 80x80: SIMPLE converged in 374 iterations, 5.0-5.7 orders dropped

- **Decision:** Accept convergence on the 80x80 grid (6400 cells; checkMesh: Mesh OK, non-orthogonality 0, skewness 5e-14, aspect ratio 1).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** All fields reach the 1e-5 residualControl with monotone decay. The iteration count grows with grid size (117 / 152 / 374 for 20 / 40 / 80 cells per side), as expected for SIMPLE on a finer grid at fixed relaxation factors. _(cites: of_user_guide_urf, versteeg_2007)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1.0 | 9.96e-06 | 5 |
| Uy | 1.0 | 9.54e-06 | 5.02 |
| p | 1.0 | 2.16e-06 | 5.67 |

### Mesh stats

| cells | points | faces | internal_faces |
|---|---|---|---|
| 6400 | 13122 | 25760 | 12640 |

## [16:39:08] validation / ok — PASS on 80x80 vs Ghia Re=400: u 0.17%, v 4.64% rel-L2 (tol 5%)

- **Decision:** Accept the 80x80 solution as the validated result. Both centerline checks pass against the full printed Ghia Re=400 data (deviation from tutorial resolution: 20x20 -> 80x80, driven by the 20x20 v miss and the grid study).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Grid study at 20 / 40 / 80 cells per side: u relative-L2 falls 2.26% -> 0.60% -> 0.17%, a monotone approach to the reference. v relative-L2 goes 5.86% -> 4.16% -> 4.64%. The non-monotone v trend comes entirely from Ghia's printed point at x = 0.9063 (v = -0.23827), which the reference provenance flags as a suspected typo. With that point excluded (diagnostic only; the verdict uses the full printed dataset), v relative-L2 on 80x80 is 0.20% with L_inf 0.0025. The refined simulation gives v = -0.382 at x = 0.9063, lying on the smooth trough between its neighbours, and it moves further from the printed value as the grid is refined (-0.360 on 40x40). The full-dataset v margin under 5% is therefore set by that one point, not by discretization error. _(cites: ghia_1982)_
- **Alternatives:** Excluding or replacing the suspected-typo point in the pass criterion is rejected. The reference file ships Ghia's value as printed, and no published Re=400 tabulation can adjudicate it, so the exclusion appears only as a labelled diagnostic.
- **When it breaks:** Because the v verdict sits only about 0.4 points under the 5% band and is dominated by one reference point, any change that moves the simulated trough toward the physically smooth value (further refinement, a higher-order scheme) will push the full-dataset v error up, possibly past 5%, even as the solution improves. A v failure on this dataset should be checked against the excluded-point diagnostic before it is treated as a model or mesh problem.

</details>

### Comparison vs ghia_1982 (80x80)

| profile | L2 | L_inf | rel_L2 | tolerance | verdict |
|---|---|---|---|---|---|
| u(y) at x=0.5 | 0.00223 | 0.00386 | 0.0017 | 0.05 | pass |
| v(x) at y=0.5 | 0.0349 | 0.1436 | 0.0464 | 0.05 | pass |
| v(x) excl. x=0.9063 (diagnostic) | 0.00154 | 0.00253 | 0.002 | 0.05 | diagnostic |

### Grid study

| grid | cells | iterations | u_rel_L2 | v_rel_L2 | verdict |
|---|---|---|---|---|---|
| 20x20 | 400 | 117 | 0.0226 | 0.0586 | fail (v) |
| 40x40 | 1600 | 152 | 0.006 | 0.0416 | pass |
| 80x80 | 6400 | 374 | 0.0017 | 0.0464 | pass |

Plots: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png`. Metrics with provenance: `postProcessing/analysis/metrics.json` (sample time 374); per-grid copies `metrics_20x20.json`, `metrics_40x40.json`.

## [16:39:42] post_processing / ok — Primary vortex at (0.556, 0.606); both bottom-corner eddies resolved

- **Decision:** Qualitative checks met on the 80x80 field at iteration 374.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Primary-vortex core, taken as the interior |U| minimum, is at x ≈ 0.556, y ≈ 0.606, against the expected (~0.55, ~0.60). The clockwise primary vortex drives u < 0 along the bottom wall, so u > 0 in the first cell row marks counter-rotating corner eddies. These appear at bottom-left (x ≤ 0.119, max u 3.3e-4) and bottom-right (x ≥ 0.744, max u 2.5e-3), with the right eddy larger and stronger. Residuals dropped 5.0-5.7 orders, meeting the ≥4-order check. _(cites: ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Qualitative checks

| check | result | verdict |
|---|---|---|
| residuals drop >= 4 orders | 5.0 (Ux), 5.0 (Uy), 5.7 (p) | met |
| primary vortex near (0.55, 0.60) | (0.556, 0.606) | met |
| two lower-corner secondary vortices | left x<=0.119, right x>=0.744 | met |

Image: `postProcessing/images/U_tlatest.png` (|U|, t = 374). Script: `analysis/vortex_check.py`. The vortex-core location is resolved to the 0.0125 cell size.

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | Unit square cavity (L = 1 m, scale 0.1 -> 1) from incompressible/icoFoam/cavity/cavity (scenario-specified template), solved with simpleFoam (scenario-specified); fvSchemes/fvSolution/controlDict/transportProperties/turbulenceProperties taken from incompressible/simpleFoam/pitzDaily (agent's call), with laminar simulationType and nu = 0.0025 (scenario-specified, Re = 1*1/0.0025 = 400). | ghia_1982, of_user_guide_urf | — |
| mesh | Uniform 20x20x1 hex grid, dx = dy = 0.05 L, kept at the cavity tutorial's resolution for the first run (agent's call: tutorial default retained). | ghia_1982 | alts |
| mesh_quality | Accept the mesh. | of_check_mesh_src, versteeg_2007 | alts, breaks |
| boundary_conditions | 0/U and 0/p taken verbatim from icoFoam/cavity, which already matches the scenario: movingWall fixedValue (1 0 0), fixedWalls noSlip, frontAndBack empty (scenario-specified). The fully enclosed domain is pinned with pRefCell 0 / pRefValue 0. | ghia_1982 | alts |
| convergence | Run 1 is flagged as under-converged: the inherited pitzDaily residualControl (p 1e-2, U 1e-3) ended the SIMPLE loop at iteration 50 of the scenario's 5000. | of_user_guide_urf | alts, breaks |
| solver_config | SIMPLE residualControl changed from p 1e-2 / U 1e-3 to p 1e-5 / U 1e-5 (deviation from tutorial, driven by the failed 4-order check). Everything else is unchanged; the run restarts from t = 0. | of_user_guide_urf | — |
| convergence | Accept convergence. All fields fall below 1e-5 and the 4-order criterion is met. | of_user_guide_urf | alts, breaks |
| validation | Validation fails on v(x) at y = 0.5. The cause is diagnosed as grid under-resolution, and the next step is mesh refinement. | ghia_1982 | — |
| validation | Mesh refined uniformly from 20x20 to 40x40 (deviation from tutorial resolution, driven by the v-centerline miss). checkMesh: Mesh OK, non-orthogonality 0, aspect ratio 1. SIMPLE converged in 152 iterations below 1e-5. | ghia_1982 | alts |
| convergence | Accept convergence on the 80x80 grid (6400 cells; checkMesh: Mesh OK, non-orthogonality 0, skewness 5e-14, aspect ratio 1). | of_user_guide_urf, versteeg_2007 | alts, breaks |
| validation | Accept the 80x80 solution as the validated result. Both centerline checks pass against the full printed Ghia Re=400 data (deviation from tutorial resolution: 20x20 -> 80x80, driven by the 20x20 v miss and the grid study). | ghia_1982 | — |
| post_processing | Qualitative checks met on the 80x80 field at iteration 374. | ghia_1982 | alts, breaks |

<!-- END DECISIONS TABLE -->
