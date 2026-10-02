# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — Both Ghia Re=1000 centerline checks pass on 80x80 (u 0.47%, v 0.18%)

7 steps · 7 decisions · 0 retries · 4 gaps
<!-- END SUMMARY -->

## [22:12:51] geometry / ok — Unit-square cavity from icoFoam/cavity, steady SIMPLE controls from pitzDaily

- **Decision:** Geometry, patches and BCs from incompressible/icoFoam/cavity/cavity (scenario-specified template), scale 0.1 -> 1 so L = 1 m; simpleFoam (scenario-specified) with fvSchemes/fvSolution/controlDict/turbulenceProperties from incompressible/simpleFoam/pitzDaily, laminar, nu = 0.001 (scenario-specified, Re = 1*1/0.001 = 1000); pRefCell 0 / pRefValue 0 in SIMPLE and residualControl p, U = 1e-5 (corpus override).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The promoted corpus entry for this tutorial prescribes exactly this composition: the cavity tutorial supplies geometry and patch names, pitzDaily supplies the steady SIMPLE dictionary, relaxation factors and steadyState ddt; the closed all-wall domain needs a pressure reference because only grad p enters momentum, so p is fixed only up to a constant. The corpus records that pitzDaily's residualControl (p 1e-2, U 1e-3) stopped the cavity solve after about 3 orders, short of the 4-order requirement, so 1e-5 is carried over. Ghia's data are non-dimensional with L = U_lid = 1, so L = 1 m and U_lid = 1 m/s let u, v compare directly. Centerline u(y) at x = 0.5 and v(x) at y = 0.5 are sampled by a sets functionObject (201 points, cellPoint interpolation) at each write. _(cites: corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982, of_user_guide_urf)_
- **Alternatives:** Keeping icoFoam would march a transient to steady state, but the scenario fixes simpleFoam.
- **When it breaks:** A steady solver presumes a steady solution exists. If the cavity flow at this Re were inherently unsteady, SIMPLE would stall or oscillate instead of converging, and that stall would itself be the diagnostic.

</details>

## [22:13:01] mesh / ok — Uniform 80x80x1 blockMesh, dx = dy = 0.0125 L

- **Decision:** Uniform 80x80x1 hex grid (corpus override of the tutorial's 20x20); depth 0.1 m, one cell in z with empty front/back.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The promoted corpus entry lists the tutorial's 20x20 grid as not suitable for quantitative validation: at Re = 400 it missed the v-centerline 5% band, and the 80x80 grid was the accepted validated result. That is the sourced starting point here. Re = 1000 has thinner wall shear layers than Re = 400, so whether 80x80 is sufficient at this Re is not established in advance; the 5% centerline check decides. Ghia's reference solution used a 129x129 uniform grid. _(cites: corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982)_
- **Alternatives:** 40x40 also passed at Re = 400 in the corpus run, but with v at 4.16%, close to the band; at higher Re the margin would only shrink, so the corpus's validated 80x80 is taken.
- **When it breaks:** If the v or u extrema near the walls are clipped relative to Ghia, the grid is under-resolving the Re = 1000 shear layers and needs refinement.

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

## [22:13:09] mesh_quality / ok — checkMesh: Mesh OK, orthogonal uniform grid

- **Decision:** Accept the mesh.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality=0 (< 60 deg), max_skewness=5.33e-14 (< 1), max_aspect_ratio=1 (< 10), severe_non_orthogonal_faces=0. No non-orthogonal correctors needed. _(cites: of_check_mesh_src, versteeg_2007)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0 | good |
| max_skewness | 5.33e-14 | good |
| max_aspect_ratio | 1 | good |
| severe_non_orthogonal_faces | 0 | good |

## [22:13:14] boundary_conditions / ok — Lid fixedValue (1 0 0), noSlip walls, empty front/back, zeroGradient p

- **Decision:** 0/U and 0/p taken verbatim from icoFoam/cavity, which already matches the scenario: movingWall fixedValue (1 0 0), fixedWalls noSlip, frontAndBack empty (scenario-specified); pressure level pinned by pRefCell 0 / pRefValue 0 (corpus override).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The scenario's lid velocity, no-slip walls and empty front/back are exactly the tutorial's BCs. With zeroGradient p on every boundary, pressure is determined only up to a constant, so a reference cell sets its level, as the corpus entry records. _(cites: corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** The lid's fixedValue meets the noSlip side walls at the top corners, giving a velocity discontinuity (a pressure singularity). Its influence on the centerline profiles is not characterized here.

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

## [22:13:20] convergence / ok — SIMPLE converged in 405 iterations, residuals dropped 5.0-5.7 orders

- **Decision:** Accept convergence. All fields fall below the 1e-5 residualControl and the 4-order drop check is met.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: good. Ux converged (last=9.98e-06), Uy converged (last=9.38e-06), p converged (last=2.12e-06). The decay reached the stopping criterion at the tutorial's relaxation factors (U 0.9, consistent SIMPLEC) with no stall or oscillation in the trailing 50-iteration window, consistent with a steady solution existing at Re = 1000. _(cites: of_user_guide_urf)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1.0 | 9.98e-06 | 5 |
| Uy | 1.0 | 9.38e-06 | 5.03 |
| p | 1.0 | 2.12e-06 | 5.67 |

## [22:14:05] validation / ok — Both Ghia Re=1000 centerline checks pass on 80x80 (u 0.47%, v 0.18%)

- **Decision:** Accept the 80x80 converged solution as validated against Ghia et al. (1982) Re = 1000 Tables I and II.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** compare_profiles on the 17 Ghia stations per line gives relative L2 (L2 / reference range) of 0.0047 for u(y) at x = 0.5 and 0.0018 for v(x) at y = 0.5, both well below the scenario's 0.05 band. The overlays show the wall-adjacent extrema captured: the u minimum near y ≈ 0.17 (Ghia -0.383) and the v trough near x ≈ 0.906 (Ghia -0.515) and peak near x ≈ 0.156 (Ghia 0.371) all lie on the simulated curves; the largest pointwise deviation is 0.0116 in u. The reference file notes no suspected typo in the Re = 1000 columns, so the full printed dataset is used without caveat. _(cites: ghia_1982, corpus/incompressible/icoFoam/cavity/cavity.md)_
- **Alternatives:** A grid study (40x40 / 160x160) would establish how far this result is from grid independence. It was not run because a single grid already sits an order of magnitude inside the band, and the scenario asks for a pass/fail check, not a grid-convergence demonstration.
- **When it breaks:** A single grid passing does not show mesh independence. Agreement within 0.5% at 80x80 may partly reflect cancellation between discretization error and the reference's own error, so this margin should not be extrapolated to coarser grids or higher Re without re-checking.

</details>

### Comparison vs ghia_1982 (Re = 1000)

| profile | L2 | L_inf | relative_L2 | tolerance | verdict |
|---|---|---|---|---|---|
| u(y) at x = 0.5 | 0.00646 | 0.0116 | 0.0047 | 0.05 (rel.) = 0.0691 abs | PASS |
| v(x) at y = 0.5 | 0.00163 | 0.00436 | 0.0018 | 0.05 (rel.) = 0.0443 abs | PASS |

Plots: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png`. Provenance-stamped metrics: `postProcessing/analysis/metrics.json`.

## [22:14:16] post_processing / ok — Qualitative checks met: primary vortex at (0.531, 0.569), both lower corner eddies present

- **Decision:** Qualitative checks met on the 80x80 field at iteration 405.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The stream function ψ(x, y) = ∫₀^y u dy' was integrated from the cell-centre U field. Its minimum (primary vortex core) is at x ≈ 0.531, y ≈ 0.569, ψ = -0.117, against the expected (~0.53, ~0.56). Positive-ψ (counter-rotating) regions sit in both lower corners: bottom-left peak ψ = 2.3e-4 at (0.081, 0.081), bottom-right peak ψ = 1.8e-3 at (0.869, 0.119), with the right eddy larger and stronger. Residuals dropped 5.0-5.7 orders, meeting the ≥ 4-order check. The |U| render shows the lid shear layer and the high-speed downflow jet along the right wall feeding the primary vortex. _(cites: ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Vortex locations

| vortex | x | y | psi |
|---|---|---|---|
| primary | 0.531 | 0.569 | -0.117 |
| bottom-left eddy | 0.081 | 0.081 | 2.3e-4 |
| bottom-right eddy | 0.869 | 0.119 | 1.8e-3 |

Images: `postProcessing/images/U_tlatest.png`, `postProcessing/analysis/streamfunction.png`. The thin positive-ψ contours hugging the top-left corner and the upper right wall in the stream-function plot are artefacts of the midpoint ψ integration (ψ on the lid is not exactly zero with cell-centre quadrature), not resolved eddies.

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | Geometry, patches and BCs from incompressible/icoFoam/cavity/cavity (scenario-specified template), scale 0.1 -> 1 so L = 1 m; simpleFoam (scenario-specified) with fvSchemes/fvSolution/controlDict/turbulenceProperties from incompressible/simpleFoam/pitzDaily, laminar, nu = 0.001 (scenario-specified, Re = 1*1/0.001 = 1000); pRefCell 0 / pRefValue 0 in SIMPLE and residualControl p, U = 1e-5 (corpus override). | corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982, of_user_guide_urf | — |
| mesh | Uniform 80x80x1 hex grid (corpus override of the tutorial's 20x20); depth 0.1 m, one cell in z with empty front/back. | corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982 | — |
| mesh_quality | Accept the mesh. | of_check_mesh_src, versteeg_2007 | alts, breaks |
| boundary_conditions | 0/U and 0/p taken verbatim from icoFoam/cavity, which already matches the scenario: movingWall fixedValue (1 0 0), fixedWalls noSlip, frontAndBack empty (scenario-specified); pressure level pinned by pRefCell 0 / pRefValue 0 (corpus override). | corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982 | alts |
| convergence | Accept convergence. All fields fall below the 1e-5 residualControl and the 4-order drop check is met. | of_user_guide_urf | alts, breaks |
| validation | Accept the 80x80 converged solution as validated against Ghia et al. (1982) Re = 1000 Tables I and II. | ghia_1982, corpus/incompressible/icoFoam/cavity/cavity.md | — |
| post_processing | Qualitative checks met on the 80x80 field at iteration 405. | ghia_1982 | alts, breaks |

<!-- END DECISIONS TABLE -->
