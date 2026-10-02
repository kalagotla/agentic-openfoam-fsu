# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — 40×40 grid: PASS vs Ghia Re = 400 (u 0.6 %, v 4.2 % rel. L2); GCI p ≈ 2

7 steps · 7 decisions · 2 retries · 4 gaps
<!-- END SUMMARY -->

## [07:40:17] geometry / ok — Template: icoFoam/cavity geometry + simpleFoam/pitzDaily SIMPLE controls

- **Decision:** Unit square cavity (L = 1 m, z-depth 0.1 m, one cell in z) from incompressible/icoFoam/cavity/cavity with scale 0.1 → 1 (scenario-specified); steady simpleFoam, laminar, nu = 0.0025 m²/s → Re = U·L/nu = 1·1/0.0025 = 400 (scenario-specified); fvSchemes/fvSolution/turbulenceProperties from incompressible/simpleFoam/pitzDaily (agent's call)
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario names icoFoam/cavity as the geometry template, but icoFoam is a transient PISO solver whose fvSolution has no SIMPLE block or relaxation factors and whose fvSchemes uses Euler time stepping and lacks the div((nuEff*dev2(T(grad(U))))) term that simpleFoam's momentum equation requires. pitzDaily is the stock steady simpleFoam tutorial, so its fvSchemes (steadyState, bounded Gauss linearUpwind for U) and fvSolution (GAMG p, SIMPLEC consistent, URF 0.9, residualControl) are taken verbatim. turbulenceProperties switched RAS → laminar because the flow is laminar at Re = 400 (scenario-specified). No corpus annotation exists for either tutorial. Reference data: Ghia, Ghia & Shin (1982). _(cites: incompressible/icoFoam/cavity/cavity (no annotation), incompressible/simpleFoam/pitzDaily (no annotation), ghia_1982)_
- **Alternatives:** Keep icoFoam and march transient to steady state (rejected: scenario fixes simpleFoam). Use the cavity tutorial's Gauss linear div(phi,U) scheme (not taken: the steady-solver template's schemes were adopted as a set).
- **When it breaks:** _failure modes not characterized._

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

Closed domain with zeroGradient p on every wall leaves pressure defined only up to a constant, so `pRefCell 0; pRefValue 0;` (from the cavity tutorial's PISO dict) were added to the SIMPLE dict. A `sets` function object samples U along x = 0.5 and y = 0.5 (201 points each, cellPoint interpolation) at every write time for validation.

## [07:40:28] mesh / ok — blockMesh: tutorial 20×20×1 uniform grid (h = 0.05)

- **Decision:** Keep the cavity tutorial's 20×20×1 uniform block (agent's call: tutorial default for the first run); checkMesh passes with a perfectly orthogonal Cartesian grid
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Tutorial resolution is retained for the first solve; refinement is left to validation and to the scenario's three-grid GCI study (celik_2008). A uniform Cartesian grid has zero non-orthogonality and unit aspect ratio by construction, as checkMesh confirms. _(cites: incompressible/icoFoam/cavity/cavity (no annotation), celik_2008)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

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

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0 | good |
| max_skewness | 1.8e-14 | good |
| max_aspect_ratio | 1 | good |
| severe_non_orthogonal_faces | 0 | good |

## [07:41:07] convergence / error — SIMPLE stopped at 50 iterations; residuals dropped only ~3 orders

- **Decision:** Reject this solution: the pitzDaily residualControl (p 1e-2, U 1e-3) terminated the run before the scenario's ≥4-orders residual drop was reached
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** simpleFoam stops as soon as every field's initial residual falls below residualControl. Starting from initial residuals of ~1, the thresholds inherited from pitzDaily allow at most ~2–3 orders of reduction, so the qualitative check "residuals drop >= 4 orders of magnitude" cannot pass by construction. assess_residuals classifies all three fields as still_running (still dropping, healthy trajectory), i.e. the solution is not yet converged. _(cites: of_user_guide_urf, incompressible/simpleFoam/pitzDaily (no annotation))_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 0.000708 | 3.15 |
| Uy | 0.993 | 0.000998 | 3 |
| p | 1 | 0.00123 | 2.91 |

## [07:41:25] convergence / fixed — residualControl tightened to 1e-5: converged in 117 iterations, ≥5 orders dropped
_retry of: 'SIMPLE stopped at 50 iterations; residuals dropped only ~3 orders'_

- **Decision:** residualControl p 1e-2 → 1e-5 and U 1e-3 → 1e-5 (deviation from template, driven by the failed ≥4-orders check); all other SIMPLE controls unchanged
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** With initial residuals normalised to ~1 at iteration 1, a stopping threshold of 1e-5 is the smallest power of ten that guarantees ≥4 orders of reduction with one order of margin, and matches the convergence threshold used by assess_residuals. The rerun reached it in 117 iterations with Ux, Uy and p all dropping ≥5 orders, satisfying the scenario check. _(cites: of_user_guide_urf)_
- **Alternatives:** Remove residualControl and run the full 5000-iteration endTime (rejected: wasted iterations once residuals plateau at solver-tolerance level; the threshold already enforces the criterion).
- **When it breaks:** If residuals plateau above 1e-5 (e.g. on a finer grid, or a weakly unsteady flow), the run continues to endTime = 5000 without meeting residualControl; then the plateau level, not the threshold, defines convergence.

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 9.43e-06 | 5.03 |
| Uy | 0.993 | 9.46e-06 | 5.02 |
| p | 1 | 3.38e-06 | 5.47 |

## [07:41:49] validation / error — 20×20 grid: u passes (2.3 %), v fails (5.9 % > 5 %) vs Ghia Re = 400

- **Decision:** Reject the 20×20 solution; refine the grid uniformly by r = 2 (20×20 → 40×40), keeping schemes, BCs and SIMPLE controls fixed
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The v(x) overlay shows both extrema attenuated: the positive peak near x ≈ 0.23 reaches 0.25 vs Ghia's 0.30, and the negative peak near x ≈ 0.86 reaches −0.37 vs −0.45, while the zero crossing and centre value (x = 0.5) agree. Peak clipping with correct shape and phase is the signature of discretisation error (insufficient resolution of steep gradients, plus numerical diffusion of the upwind-biased convection scheme on a coarse grid) rather than a wrong BC or model, whose errors would shift the profile globally. At h = 0.05 each wall-adjacent peak spans only ~4 cells. Refining by r = 2 also supplies the systematically refined grids the scenario's GCI study requires. _(cites: ghia_1982, celik_2008, versteeg_2007)_
- **Alternatives:** Switch div(phi,U) to the cavity tutorial's Gauss linear to cut numerical diffusion (deferred: the overlay points to under-resolution first, and refinement is required for the GCI study regardless). Wall-graded mesh as in cavityGrade (not taken: breaks the uniform h = L/N definition used for GCI).
- **When it breaks:** If 40×40 still misses, the remaining error is either scheme diffusion (then revisit div(phi,U)) or a sampling artefact (cellPoint interpolation near walls).

</details>

### Comparison vs ghia_1982 (20×20)

| profile | L2 | L_inf | tolerance | relative_L2 | verdict |
|---|---|---|---|---|---|
| u_centerline | 0.03 | 0.0645 | 0.0664 | 0.0226 | pass |
| v_centerline | 0.044 | 0.087 | 0.0376 | 0.0586 | fail |

Overlays: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png` (20×20 run, preserved under `gci/N020/`).

## [07:43:22] validation / fixed — 40×40 grid: PASS vs Ghia Re = 400 (u 0.6 %, v 4.2 % rel. L2); GCI p ≈ 2
_retry of: '20×20 grid: u passes (2.3 %), v fails (5.9 % > 5 %) vs Ghia Re = 400'_

- **Decision:** Accept the 40×40 solution (deviation from template mesh, driven by the 20×20 v-profile miss); 20/40/80 uniform grids (r = 2) form the scenario's three-grid GCI study
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** With refinement alone (schemes, BCs and controls unchanged), both centreline profiles fall within 5 % of the reference range, which confirms that the 20×20 miss came from discretisation error. GCI per Celik et al. (2008) on h = 1/20, 1/40, 1/80 at the interior Ghia stations: mean apparent order 2.16 (u) and 1.91 (v). This is consistent with the formally second-order Gauss linear / linearUpwind discretisation. 13/15 (u) and 14/15 (v) stations converge monotonically. Fine-grid (80×80) GCI is 1.5 % mean / 4.2 % max for u and 1.9 % mean / 2.8 % max for v. The Richardson-extrapolated v extrema (0.304 at x = 0.2344, −0.455 at x = 0.8594) agree with Ghia's 0.302 and −0.450 to within 0.005. _(cites: ghia_1982, celik_2008)_
- **Alternatives:** Report validation on 80×80 instead (it would also pass, but the 40×40 grid is the coarsest grid that meets the tolerance, and the 80×80 serves as the GCI fine grid). Gauss linear convection (not needed once refinement closed the gap).
- **When it breaks:** Per-station GCI is unreliable where the solution passes through zero (u near y ≈ 0.6, v at x = 0.5), where relative errors blow up and the asymptotic ratio departs from 1 (e.g. 16 at v, x = 0.5). The v stations nearest the right wall (x ≥ 0.945) show local order below 1.2 and asymptotic ratios of 0.3–0.6, so those wall-adjacent stations are not yet in the asymptotic range at h = 1/80. The largest pointwise residual vs Ghia (L_inf = 0.12) sits at x = 0.9063, where all three grids and the extrapolated value (−0.390) differ from the tabulated −0.239. The discrepancy is consistent across grids, so it is not a resolution effect in this solution.

</details>

### Comparison vs ghia_1982 (40×40)

| profile | L2 | L_inf | tolerance | relative_L2 | verdict |
|---|---|---|---|---|---|
| u_centerline | 0.008 | 0.0173 | 0.0664 | 0.006 | pass |
| v_centerline | 0.0313 | 0.1221 | 0.0376 | 0.0416 | pass |

### Grid convergence (Celik 2008), grids 20/40/80, r = 2

| quantity | mean_apparent_order | GCI_fine_mean | GCI_fine_max | monotonic_stations |
|---|---|---|---|---|
| u_centerline | 2.16 | 1.5 % | 4.2 % | 13/15 |
| v_centerline | 1.91 | 1.9 % | 2.8 % | 14/15 |

### Grid runs

| grid | cells | iterations | u_rel_L2 | v_rel_L2 |
|---|---|---|---|---|
| 20×20 | 400 | 117 | 0.0226 | 0.0586 |
| 40×40 | 1600 | 152 | 0.006 | 0.0416 |
| 80×80 | 6400 | 374 | - | - |

All three grids converged under residualControl 1e-5 (≥5 orders drop) with identical schemes and controls. Overlays with all three grids are in `postProcessing/analysis/{u,v}_centerline.png`; metrics and provenance are in `postProcessing/analysis/metrics.json`. The 80×80 grid was scored only through the GCI; it was not compared directly against Ghia.

## [07:44:03] post_processing / ok — Qualitative checks: primary vortex at (0.56, 0.60); both lower-corner eddies present

- **Decision:** All three scenario qualitative checks pass: ≥4 orders residual drop, a primary vortex near (0.55, 0.60), and two secondary vortices in the lower corners
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The streamfunction ψ(x,y) = ∫₀^y u dy′ (ψ = 0 on the walls) was computed from the cell-centred U (`analysis/vortices.py`). The clockwise primary vortex is the ψ minimum. A counter-rotating corner eddy shows up as a region of ψ > 0. Both lower corners contain ψ > 0 regions on every grid, and these regions grow under refinement (bottom-right: 22 → 78 → 293 cells; bottom-left: 4 → 14 → 51 cells), so they are resolved flow features rather than noise. As a first-principles consistency check, the bottom-right eddy is stronger (ψ_max ≈ 7e-4 vs 2e-5). That is expected because the primary vortex drives the flow down the right (downstream) wall into that corner. The ghia_1982 reference file carries only centreline profiles, so vortex positions are checked against the scenario's qualitative expectation, not scored. _(cites: ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Vortex structure

| grid | primary_core_x | primary_core_y | psi_min | BR_eddy_psi_max | BL_eddy_psi_max |
|---|---|---|---|---|---|
| 20×20 | 0.575 | 0.6 | -0.1029 | 1.1e-03 | 3.7e-05 |
| 40×40 | 0.562 | 0.6 | -0.111 | 7.7e-04 | 2.2e-05 |
| 80×80 | 0.556 | 0.613 | -0.1132 | 6.8e-04 | 1.6e-05 |

Velocity-magnitude render (40×40, iteration 152): `postProcessing/images/U_tlatest.png`. It shows the lid shear layer, the downward wall jet along the right wall, and a low-|U| core near (0.54, 0.60). Core locations are resolved only to cell size (h = 1/N).

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | Unit square cavity (L = 1 m, z-depth 0.1 m, one cell in z) from incompressible/icoFoam/cavity/cavity with scale 0.1 → 1 (scenario-specified); steady simpleFoam, laminar, nu = 0.0025 m²/s → Re = U·L/nu = 1·1/0.0025 = 400 (scenario-specified); fvSchemes/fvSolution/turbulenceProperties from incompressible/simpleFoam/pitzDaily (agent's call) | incompressible/icoFoam/cavity/cavity (no annotation), incompressible/simpleFoam/pitzDaily (no annotation), ghia_1982 | breaks |
| mesh | Keep the cavity tutorial's 20×20×1 uniform block (agent's call: tutorial default for the first run); checkMesh passes with a perfectly orthogonal Cartesian grid | incompressible/icoFoam/cavity/cavity (no annotation), celik_2008 | alts, breaks |
| convergence | Reject this solution: the pitzDaily residualControl (p 1e-2, U 1e-3) terminated the run before the scenario's ≥4-orders residual drop was reached | of_user_guide_urf, incompressible/simpleFoam/pitzDaily (no annotation) | alts, breaks |
| convergence | residualControl p 1e-2 → 1e-5 and U 1e-3 → 1e-5 (deviation from template, driven by the failed ≥4-orders check); all other SIMPLE controls unchanged | of_user_guide_urf | — |
| validation | Reject the 20×20 solution; refine the grid uniformly by r = 2 (20×20 → 40×40), keeping schemes, BCs and SIMPLE controls fixed | ghia_1982, celik_2008, versteeg_2007 | — |
| validation | Accept the 40×40 solution (deviation from template mesh, driven by the 20×20 v-profile miss); 20/40/80 uniform grids (r = 2) form the scenario's three-grid GCI study | ghia_1982, celik_2008 | — |
| post_processing | All three scenario qualitative checks pass: ≥4 orders residual drop, a primary vortex near (0.55, 0.60), and two secondary vortices in the lower corners | ghia_1982 | alts, breaks |

<!-- END DECISIONS TABLE -->
