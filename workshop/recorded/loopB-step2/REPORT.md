# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — Validation PASS: u L2=0.0065, v L2=0.0016 (both within 5% tol)

5 steps · 5 decisions · 0 retries · 0 gaps
<!-- END SUMMARY -->

## [10:33:31] geometry / ok — Set up Re=1000 cavity case from corpus-annotated template

- **Decision:** Adopt incompressible/icoFoam/cavity/cavity as structural template (single hex block, patches movingWall/fixedWalls/frontAndBack) with scale 1 (L=1m); 80x80x1 uniform grid from Re=400 grid-convergence study; nu=0.001 gives Re=U·L/nu=1000.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Corpus entry from Re=400 run (corpus/incompressible/icoFoam/cavity/cavity.md) records that 80x80 passes Ghia 5% tolerance at Re=400. Re=1000 sharpens wall jets and corner vortices, so starting at the already-validated 80x80 grid is the logical reuse of prior convergence evidence. The template carries the exact Ghia geometry and BC layout at L=0.1; only scale and nu change to match Re=1000. _(cites: corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict)_
- **Alternatives:** Start at 20x20 (tutorial default) and repeat grid study; rejected because the Re=400 study already established the passing resolution, and Re=1000 needs at least that. Start at Ghia's 129x129; rejected as it skips the documented reuse step the scenario asks for.
- **When it breaks:** If Re=1000 requires finer than 80x80 (thinner shear layers), the 80x80 profiles will miss the 5% tolerance and the validation step will trigger refinement. 3-D cavities where end-wall effects matter are excluded by the empty front/back patches.

</details>

## [10:33:52] solver_config / ok — Configure steady simpleFoam with pitzDaily dictionaries + pRefCell/pRefValue

- **Decision:** simpleFoam (laminar); fvSchemes and fvSolution copied from incompressible/simpleFoam/pitzDaily with pRefCell 0 / pRefValue 0 for closed domain, residualControl tightened to 1e-5 for p and U, SIMPLEC consistent yes, URF 0.9.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Corpus entry records: icoFoam's fvSchemes (Euler ddt) and PISO fvSolution do not apply to SIMPLE; pitzDaily is the canonical simpleFoam tutorial. Every cavity wall has zeroGradient p, so p is determined only up to a constant — pRefCell/pRefValue pins it (same as icoFoam/cavity PISO dict). ResidualControl 1e-5 gives ~5 orders drop, meeting the scenario's >=4-order check; the pitzDaily default (p 1e-2, U 1e-3) stops after ~3 orders. _(cites: corpus/incompressible/icoFoam/cavity/cavity.md, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSolution, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/fvSolution, of_user_guide_urf)_
- **Alternatives:** Run icoFoam transient to steady state; rejected because scenario specifies steady SIMPLE solve. pimpleFoam with large time steps; same objection.
- **When it breaks:** If cavity flow becomes time-periodic at this Re, SIMPLE residuals stall instead of converging — the stall is itself the diagnostic. If residuals stall above 1e-5 (e.g. limiter cycling), run goes to endTime without meeting criterion.

</details>

## [10:35:51] mesh_quality / ok — checkMesh: 80x80x1 uniform grid passes all metrics (good)

- **Decision:** Accept the 80x80x1 uniform mesh; no non-orthogonal correctors needed.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Mesh quality verdict: good. max_non_orthogonality=0 (< 60 deg), max_skewness=5.33e-14 (< 1), max_aspect_ratio=1 (< 10), severe_non_orthogonal_faces=0. All metrics in the 'good' band; standard fvSchemes (corrected snGrad, nNonOrthogonalCorrectors 0) are appropriate. The structured Cartesian block is exactly the Ghia geometry. _(cites: of_check_mesh_src, versteeg_2007, corpus/incompressible/icoFoam/cavity/cavity.md)_
- **Alternatives:** Wall-graded mesh to cluster cells in lid/wall shear layers; held back to keep the study a clean uniform-refinement sequence matching Ghia's uniform grid approach.
- **When it breaks:** At higher Re the wall and lid shear layers thin, and uniform refinement becomes an expensive way to resolve them — graded meshes become necessary. The quality metrics say nothing about resolution; a perfectly orthogonal grid can still under-resolve the shear layers (resolution judged by validation).

</details>

## [10:38:12] convergence / ok — SIMPLE converged in 405 iterations; all fields dropped >=5 orders

- **Decision:** Accept the 80x80 steady solution as iteratively converged (residualControl 1e-5).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Convergence verdict: good. Ux converged (last=9.98e-06), Uy converged (9.38e-06), p converged (2.12e-06); every field dropped at least 5 orders, meeting the scenario's >=4-order check. Monotone residual descent with no stall is consistent with a steady solution existing at this Re. The residualControl 1e-5 criterion was met (vs pitzDaily's loose 1e-2/1e-3 which stops after ~3 orders). _(cites: of_user_guide_urf, corpus/incompressible/icoFoam/cavity/cavity.md)_
- **Alternatives:** Tighter residualControl (1e-6) would cost more iterations; the 20x20 test showed iteration error at 1e-3 vs 1e-5 moved profile error by only ~0.002, so 1e-5 is well below discretisation error.
- **When it breaks:** If the flow had no steady solution, SIMPLE residuals would plateau or oscillate rather than fall monotonically. At Re=1000 the cavity is still steady-laminar; if Re were higher and time-periodic, the stall would be the diagnostic.

</details>

## [10:47:50] validation / ok — Validation PASS: u L2=0.0065, v L2=0.0016 (both within 5% tol)

- **Decision:** Validation PASS on 80x80 grid; both u and v centerline profiles within 5% L2 tolerance vs Ghia Re=1000.
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** compare_profiles against Ghia Re=1000 Tables I and II: u L2 = 0.0065 (tol 0.0691), v L2 = 0.0016 (tol 0.0443). Both well within the 5% relative-L2 tolerance. The 80x80 grid (from Re=400 grid convergence study) is sufficient for Re=1000 without further refinement. The primary vortex position, stronger compact lower-corner vortices, and residual drop >=4 orders are consistent with Re=1000 physics. _(cites: ghia_1982, cases/lid-cavity/reference/ghia_1982.json, corpus/incompressible/icoFoam/cavity/cavity.md)_
- **Alternatives:** Exclude the suspected-typo point from the verdict (for Re=400 only); rejected because the Re=1000 data has no suspected typo and the reference ships the printed value.
- **When it breaks:** If Re were higher and the flow became time-periodic, the steady simpleFoam solve would stall instead of converging. The 80x80 grid might under-resolve thinner shear layers at higher Re.

</details>

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | Adopt incompressible/icoFoam/cavity/cavity as structural template (single hex block, patches movingWall/fixedWalls/frontAndBack) with scale 1 (L=1m); 80x80x1 uniform grid from Re=400 grid-convergence study; nu=0.001 gives Re=U·L/nu=1000. | corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/blockMeshDict | — |
| solver_config | simpleFoam (laminar); fvSchemes and fvSolution copied from incompressible/simpleFoam/pitzDaily with pRefCell 0 / pRefValue 0 for closed domain, residualControl tightened to 1e-5 for p and U, SIMPLEC consistent yes, URF 0.9. | corpus/incompressible/icoFoam/cavity/cavity.md, $FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily/system/fvSolution, $FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/system/fvSolution, of_user_guide_urf | — |
| mesh_quality | Accept the 80x80x1 uniform mesh; no non-orthogonal correctors needed. | of_check_mesh_src, versteeg_2007, corpus/incompressible/icoFoam/cavity/cavity.md | — |
| convergence | Accept the 80x80 steady solution as iteratively converged (residualControl 1e-5). | of_user_guide_urf, corpus/incompressible/icoFoam/cavity/cavity.md | — |
| validation | Validation PASS on 80x80 grid; both u and v centerline profiles within 5% L2 tolerance vs Ghia Re=1000. | ghia_1982, cases/lid-cavity/reference/ghia_1982.json, corpus/incompressible/icoFoam/cavity/cavity.md | — |

<!-- END DECISIONS TABLE -->
