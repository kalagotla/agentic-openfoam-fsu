# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: PASS** — Centerline u(y), v(x) vs Ghia et al. (1982), Re = 1000

4 steps · 2 decisions · 0 retries · 1 gap
<!-- END SUMMARY -->

## [21:42:32] solver_config / ok — Case set up: cavity geometry, simpleFoam with pitzDaily SIMPLE controls, 80x80 grid

- **Decision:** Unit square cavity (scale 0.1 -> 1) from incompressible/icoFoam/cavity/cavity (scenario-specified template); simpleFoam laminar (scenario-specified) with fvSchemes/fvSolution/controlDict from incompressible/simpleFoam/pitzDaily, pRefCell 0 / pRefValue 0 in SIMPLE, residualControl p 1e-5 / U 1e-5 (corpus entry); nu = 0.001 so Re = 1*1/0.001 = 1000 (scenario-specified), with transportModel Newtonian added because simpleFoam's singlePhaseTransportModel requires it and icoFoam's transportProperties omits it (a first attempt stopped with 'transportModel not found'); uniform 80x80x1 grid (agent's call, from the corpus entry).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** The corpus entry for this template swaps in pitzDaily's SIMPLE controls for simpleFoam, carries pRefCell/pRefValue into the SIMPLE block because a closed all-wall domain with zeroGradient p fixes pressure only up to a constant, and replaces pitzDaily's residualControl (p 1e-2, U 1e-3), which stopped the cavity solve after about 3 orders, with 1e-5 to meet a 4-order drop. It lists the tutorial's 20x20 grid as not suitable for quantitative validation; 40x40 and 80x80 passed at Re = 400. Re = 1000 has thinner wall layers than Re = 400, so the finest validated grid is used. L = U_lid = 1 makes the solution directly comparable with Ghia's non-dimensional profiles. _(cites: corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982, of_user_guide_urf)_
- **Alternatives:** The tutorial's 20x20 grid (rejected by the corpus entry for quantitative validation). The template's own transient icoFoam (the scenario fixes simpleFoam).
- **When it breaks:** A steady solver presumes a steady solution exists; if the cavity flow at this Re were unsteady, SIMPLE would stall or oscillate instead of converging. The 80x80 grid is validated only at Re = 400; at Re = 1000 the validation below decides whether it is fine enough.

</details>

### Boundary conditions

| U | p | patch |
|---|---|---|
| fixedValue (1 0 0) | zeroGradient | movingWall |
| noSlip | zeroGradient | fixedWalls |
| empty | empty | frontAndBack |

## [21:42:39] mesh_quality / ok — checkMesh on the 80x80x1 grid

### checkMesh metrics

| cell_count | max_aspect_ratio | max_non_orthogonality | max_skewness |
|---|---|---|---|
| 6400 | 1.0 | 0.0 | 5.32907e-14 |

## [21:42:46] convergence / ok — simpleFoam run

simpleFoam converged in 405 iterations. Final residuals: Ux = 9.97629e-6, Uy = 9.37575e-6, p = 2.12103e-6. The log tail shows the last few iterations of the SIMPLE loop with residualControl met and continuity error near machine zero.

## [21:42:57] validation / ok — Centerline u(y), v(x) vs Ghia et al. (1982), Re = 1000

- **Decision:** Score the centerline profiles against ghia_re_1000_u_centerline and ghia_re_1000_v_centerline with a 5% relative-L2 tolerance (scenario-specified).
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Ghia, Ghia & Shin (1982) tabulate u(y) at x = 0.5 and v(x) at y = 0.5 for Re = 1000; the corpus entry validated the same template and sampling against the Re = 400 columns. _(cites: ghia_1982, corpus/incompressible/icoFoam/cavity/cavity.md)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Comparison vs ghia_1982

| L2 | L_inf | profile | relative_L2 | tolerance | verdict |
|---|---|---|---|---|---|
| 0.006459644305627074 | 0.011616260000000017 | u_centerline | 0.004671119398959479 | 0.0691445 | pass |
| 0.0016279101346494405 | 0.0043551000000005 | v_centerline | 0.001837474050058627 | 0.044297500000000004 | pass |

Overlays: postProcessing/analysis/u_centerline.png, postProcessing/analysis/v_centerline.png

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| solver_config | Unit square cavity (scale 0.1 -> 1) from incompressible/icoFoam/cavity/cavity (scenario-specified template); simpleFoam laminar (scenario-specified) with fvSchemes/fvSolution/controlDict from incompressible/simpleFoam/pitzDaily, pRefCell 0 / pRefValue 0 in SIMPLE, residualControl p 1e-5 / U 1e-5 (corpus entry); nu = 0.001 so Re = 1*1/0.001 = 1000 (scenario-specified), with transportModel Newtonian added because simpleFoam's singlePhaseTransportModel requires it and icoFoam's transportProperties omits it (a first attempt stopped with 'transportModel not found'); uniform 80x80x1 grid (agent's call, from the corpus entry). | corpus/incompressible/icoFoam/cavity/cavity.md, ghia_1982, of_user_guide_urf | — |
| validation | Score the centerline profiles against ghia_re_1000_u_centerline and ghia_re_1000_v_centerline with a 5% relative-L2 tolerance (scenario-specified). | ghia_1982, corpus/incompressible/icoFoam/cavity/cavity.md | alts, breaks |

<!-- END DECISIONS TABLE -->
