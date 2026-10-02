# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — 40x40: both centerline profiles within 5% of Ghia (PASS)

11 steps · 10 decisions · 2 retries · 4 gaps
<!-- END SUMMARY -->

## [09:18:27] geometry / ok — Templates: icoFoam/cavity geometry + simpleFoam/rotatingCylinders controls

- **Decision:** Geometry, patches and BCs from incompressible/icoFoam/cavity/cavity; steady laminar SIMPLE controls (fvSchemes, fvSolution, controlDict skeleton, laminar turbulenceProperties) from incompressible/simpleFoam/rotatingCylinders (agent's call). Unit square, L = 1 m (scenario-specified): blockMeshDict scale 0.1 -> 1.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** icoFoam/cavity is the same geometry with the scenario's exact patch names (movingWall, fixedWalls, frontAndBack), but icoFoam is a transient PISO solver. The scenario asks for a steady solve, so the solution algorithm comes from a steady incompressible tutorial; rotatingCylinders is the simpleFoam tutorial that is already laminar, so no turbulence-model dictionaries need stripping. No corpus annotation exists for either tutorial (get_tutorial_annotation returned no_annotation for both). _(cites: $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, $FOAM_TUTORIALS/incompressible/simpleFoam/rotatingCylinders)_
- **Alternatives:** Run icoFoam/cavity transiently to a steady state (matches the template exactly but contradicts steady: true and costs time-accurate steps); pitzDaily simpleFoam controls (turbulent kOmegaSST/kEpsilon setup, would need its turbulence entries removed).
- **When it breaks:** A steady SIMPLE solver presumes a steady solution exists; if the cavity flow at the chosen Re were inherently unsteady, the residuals would stall instead of falling, and that stall would itself be the diagnostic to switch to a transient solver.

</details>

## [09:18:35] solver_config / ok — Laminar simpleFoam, nu = 0.0025 m^2/s from Re = 400

- **Decision:** simulationType laminar (agent's call, answering the scenario's guidance); nu = U_lid L / Re = 1 x 1 / 400 = 0.0025 m^2/s (derived from scenario Re); solver simpleFoam (agent's call).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The validation target, Ghia, Ghia & Shin (1982), solves the steady 2-D incompressible Navier-Stokes equations with no turbulence model, at Re up to 10000; the Re = 400 reference data is therefore a laminar solution, and a laminar model is the like-for-like comparison. Adding a RANS model would introduce an eddy viscosity absent from the reference and change the effective Re. nu follows directly from the Re definition in the reference's convention block (Re = U_lid L / nu). _(cites: ghia_1982, $FOAM_TUTORIALS/incompressible/simpleFoam/rotatingCylinders)_
- **Alternatives:** kOmegaSST / kEpsilon RANS: rejected because the reference is a laminar Navier-Stokes solution, so any modelled eddy viscosity is a modelling error against it. icoFoam transient laminar: rejected for steady: true.
- **When it breaks:** If the flow at the chosen Re were unsteady, a steady laminar SIMPLE solve would not converge; the residual history is the check. At high Re the 2-D steady laminar assumption itself breaks and the reference would no longer represent the flow.

</details>

Schemes and controls kept at rotatingCylinders values: steadyState ddt, `bounded Gauss linearUpwind grad(U)` for div(phi,U), Gauss linear corrected laplacian; GAMG p / smoothSolver U; URF p 0.3, U 0.7; pRefCell 0 (all-wall closed domain needs a pressure reference); endTime 1000 iterations, writeInterval 10, purgeWrite 3. Added a `sets` functionObject sampling U on x = 0.5 (vertical) and y = 0.5 (horizontal), 201 points each, for the Ghia comparison.

## [09:18:39] boundary_conditions / ok — BCs: moving lid (1,0,0), no-slip walls, empty front/back

- **Decision:** BCs copied verbatim from icoFoam/cavity, which already match the scenario (scenario-specified): movingWall fixedValue (1 0 0), fixedWalls noSlip, frontAndBack empty; p zeroGradient on all walls.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The tutorial's patches and BC types coincide with the scenario boundary_conditions block and with the geometry convention of the reference (top wall moves at U_lid in +x, other walls no-slip). _(cites: $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Boundary conditions

| patch | U | p |
|---|---|---|
| movingWall | fixedValue (1 0 0) | zeroGradient |
| fixedWalls | noSlip | zeroGradient |
| frontAndBack | empty | empty |

## [09:18:55] mesh / ok — Mesh: tutorial 20x20x1 uniform, h = 0.05

- **Decision:** Keep the icoFoam/cavity block resolution, 20x20x1 uniform with no grading, for the first run (agent's call). The scenario leaves resolution to the run and asks to refine if validation misses.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The tutorial resolution is the starting point; the reference file states that the grid meeting the 5% band is not known in advance and must be established by refinement against the data, with Ghia's own 129x129 uniform grid as the only sourced anchor. The first validation result decides whether refinement is needed. _(cites: $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, ghia_1982)_
- **Alternatives:** Start directly near Ghia's 129x129: skips the evidence that motivates the resolution. Wall-graded mesh: changes two variables at once; deferred until a uniform-grid miss shows where the error sits.
- **When it breaks:** At h = 0.05 the thin shear layer under the lid and the near-wall gradients are spanned by only a few cells, so the centerline extrema may be under-resolved; the validation comparison is the check.

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

## [09:18:59] mesh_quality / ok — checkMesh: Mesh OK, verdict good

- **Decision:** Accept mesh.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality=0 is good (< 60 deg). max_skewness=1.78e-14 is good (< 1). max_aspect_ratio=1 is good (< 10). severe_non_orthogonal_faces=0 is good (0). _(cites: of_check_mesh_src, versteeg)_
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

## [09:19:10] convergence / ok — 20x20 solve: residuals down 10-12 orders in 1000 iterations

- **Decision:** Accept the converged steady solution at iteration 1000.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: good. Ux converged (last=1.93e-12). Uy converged (last=2.25e-12). p converged (last=5.25e-11). The monotone fall to machine-level residuals also confirms that a steady solution exists at Re = 400 on this grid, as the steady SIMPLE choice presumed. _(cites: of_user_guide_urf)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 1.93e-12 | 11.7 |
| Uy | 0.993 | 2.25e-12 | 11.6 |
| p | 1 | 5.25e-11 | 10.3 |

## [09:19:48] validation / error — 20x20: v centerline misses Ghia band (L2 0.043 > 0.038)

- **Decision:** Validation fails on v(x); diagnose as grid under-resolution and refine the mesh.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** u(y) passes but v(x) does not. In the overlay, both v extrema fall short of Ghia: the peak is 0.256 against 0.302 near x = 0.23, and the trough is -0.37 against -0.45 near x = 0.86. The interior shape and the zero crossing near x = 0.5 match. Losing extrema while keeping the overall shape is how insufficient resolution shows up with a bounded second-order upwind-biased convection scheme, because the resolved gradients are smeared. With h = 0.05, only about 4-5 cells span each near-wall jet. The residuals fell 10+ orders, so iterative error is ruled out, and checkMesh was clean, so mesh quality is ruled out. That leaves resolution. The reference file itself directs establishing the grid by refinement. _(cites: ghia_1982)_
- **Alternatives:** Change the convection scheme to unbounded linear: changes the discretisation instead of first testing resolution, and the reference prescribes refinement. Wall grading: a second variable; uniform refinement keeps the grid sequence systematic for a later GCI.
- **When it breaks:** If refinement stops reducing the v error, the residual miss is not discretisation error. Candidates would be the suspected Re = 400 typo point at x = 0.9063 (v = -0.23827, flagged 'probably wrong' in the reference provenance) or a modelling mismatch.

</details>

### Comparison vs ghia_1982 (20x20)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u_centerline | 0.0296 | 0.0635 | 0.0664 | pass |
| v_centerline | 0.0432 | 0.085 | 0.0376 | FAIL |

Plots: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png`. Tolerance = 5% of the reference value range (compare_profiles default), matching the scenario's 0.05 relative-L2 check.

## [09:20:28] mesh / fixed — Refine to 40x40 uniform (h = 0.025), checkMesh clean
_retry of: '20x20: v centerline misses Ghia band (L2 0.043 > 0.038)'_

- **Decision:** Double the resolution in both in-plane directions, 20x20 -> 40x40x1, still uniform with no grading (agent's call, driven by the 20x20 v-centerline miss). Everything else unchanged.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** On the 20x20 grid the v extrema were too small while the residuals had converged and the mesh was orthogonal, which isolates discretisation error. A refinement ratio of 2 halves h and keeps the grid family systematic, as a Celik-style refinement sequence requires. The reference file directs establishing resolution by refinement toward Ghia's 129x129 anchor. _(cites: ghia_1982, celik_2008, of_check_mesh_src)_
- **Alternatives:** Wall-graded 20x20: puts the cells where the jets are but changes the grid family; a scheme change to unbounded linear: tests the discretisation instead of resolution.
- **When it breaks:** A different Re thins the wall jets as Re rises, so the resolution that passes here does not transfer to higher Re without re-checking.

</details>

### Mesh stats

| cells | points | faces | internal_faces |
|---|---|---|---|
| 1600 | 3362 | 6480 | 3120 |

### Patches

| name | type | faces |
|---|---|---|
| movingWall | wall | 40 |
| fixedWalls | wall | 120 |
| frontAndBack | empty | 3200 |

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0 | good |
| max_skewness | 3.14e-14 | good |
| max_aspect_ratio | 1 | good |
| severe_non_orthogonal_faces | 0 | good |

## [09:20:31] convergence / ok — 40x40 solve: residuals down to ~1e-10 in 1000 iterations

- **Decision:** Accept the converged steady solution at iteration 1000.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: good. Ux converged (last=1.63e-10). Uy converged (last=1.84e-10). p converged (last=5.80e-10). _(cites: of_user_guide_urf)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Residuals

| field | initial | final | orders_dropped |
|---|---|---|---|
| Ux | 1 | 1.63e-10 | 9.8 |
| Uy | ~1 | 1.84e-10 | 9.7 |
| p | 1 | 5.80e-10 | 9.2 |

## [09:20:40] validation / ok — 40x40: both centerline profiles within 5% of Ghia (PASS)
_retry of: '20x20: v centerline misses Ghia band (L2 0.043 > 0.038)'_

- **Decision:** Accept: u(y) L2 0.0079 (threshold 0.066), v(x) L2 0.031 (threshold 0.038).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Both checks pass compare_profiles at 5% of the reference range. Refining from 20x20 to 40x40 cut the u error by 3.7x (0.0296 to 0.0079) and the v error from 0.0432 to 0.0313. The v peak, 0.29 against 0.302, and trough, -0.43 against -0.450, now nearly match. The v L_inf of 0.122 sits at x = 0.9063. There Ghia's printed v = -0.23827 is the point the reference provenance flags as a suspected typo, an outlier in an otherwise smooth profile, and is shipped as printed. The simulated v at that station, about -0.36, lies on the smooth curve through the neighbouring reference points. That single point accounts for most of the remaining v error. _(cites: ghia_1982, celik_2008)_
- **Alternatives:** Refine further toward Ghia's 129x129 to shrink the margin on v. Not required, because the acceptance criterion is met, and the dominant residual error comes from a reference point rather than the solution.
- **When it breaks:** The v margin is modest (0.031 against 0.038) and is inflated by the suspected-typo point. No grid-convergence (GCI) study was run, so the discretisation uncertainty of the 40x40 profiles is not quantified. Only two grids are available here, and Celik's procedure needs three.

</details>

### Comparison vs ghia_1982 (40x40)

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u_centerline | 0.0079 | 0.0171 | 0.0664 | pass |
| v_centerline | 0.0313 | 0.1221 | 0.0376 | pass |

### Grid sequence

| mesh | h | u_L2 | v_L2 | verdict |
|---|---|---|---|---|
| 20x20 | 0.05 | 0.0296 | 0.0432 | FAIL (v) |
| 40x40 | 0.025 | 0.0079 | 0.0313 | PASS |

Plots: `postProcessing/analysis/u_centerline.png`, `postProcessing/analysis/v_centerline.png`; metrics with provenance in `postProcessing/analysis/metrics.json` (git aecc137, numpy 2.4.4, matplotlib 3.10.9, sample time 1000).

## [09:20:51] post_processing / ok — |U| field at iteration 1000 (40x40)

![U](postProcessing/images/U_tlatest.png)

The rendered |U| shows a single primary vortex. Its core, the low-speed region, sits right of centre and above mid-height, near (0.55, 0.6), shifted downstream of the lid motion. A high-speed jet runs along the lid and turns down the right (downstream) wall. The bottom corners are slow. This is consistent with the centerline profiles: the v minimum near x = 0.86 marks the downward wall jet, and u crosses zero just above y = 0.5. Colour range 8.7e-05 to 0.88 (cell-centred, so the lid's unit velocity sits on the boundary faces, not in the cells).

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | Geometry, patches and BCs from incompressible/icoFoam/cavity/cavity; steady laminar SIMPLE controls (fvSchemes, fvSolution, controlDict skeleton, laminar turbulenceProperties) from incompressible/simpleFoam/rotatingCylinders (agent's call). Unit square, L = 1 m (scenario-specified): blockMeshDict scale 0.1 -> 1. | $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, $FOAM_TUTORIALS/incompressible/simpleFoam/rotatingCylinders | — |
| solver_config | simulationType laminar (agent's call, answering the scenario's guidance); nu = U_lid L / Re = 1 x 1 / 400 = 0.0025 m^2/s (derived from scenario Re); solver simpleFoam (agent's call). | ghia_1982, $FOAM_TUTORIALS/incompressible/simpleFoam/rotatingCylinders | — |
| boundary_conditions | BCs copied verbatim from icoFoam/cavity, which already match the scenario (scenario-specified): movingWall fixedValue (1 0 0), fixedWalls noSlip, frontAndBack empty; p zeroGradient on all walls. | $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, ghia_1982 | alts, breaks |
| mesh | Keep the icoFoam/cavity block resolution, 20x20x1 uniform with no grading, for the first run (agent's call). The scenario leaves resolution to the run and asks to refine if validation misses. | $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity, ghia_1982 | — |
| mesh_quality | Accept mesh. | of_check_mesh_src, versteeg | alts, breaks |
| convergence | Accept the converged steady solution at iteration 1000. | of_user_guide_urf | alts, breaks |
| validation | Validation fails on v(x); diagnose as grid under-resolution and refine the mesh. | ghia_1982 | — |
| mesh | Double the resolution in both in-plane directions, 20x20 -> 40x40x1, still uniform with no grading (agent's call, driven by the 20x20 v-centerline miss). Everything else unchanged. | ghia_1982, celik_2008, of_check_mesh_src | — |
| convergence | Accept the converged steady solution at iteration 1000. | of_user_guide_urf | alts, breaks |
| validation | Accept: u(y) L2 0.0079 (threshold 0.066), v(x) L2 0.031 (threshold 0.038). | ghia_1982, celik_2008 | — |

<!-- END DECISIONS TABLE -->
