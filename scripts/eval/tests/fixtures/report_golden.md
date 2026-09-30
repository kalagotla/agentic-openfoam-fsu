# Case setup report

`tail -f` to watch the run unfold. A verdict banner and a compact
decisions index appear once the agent calls `finalize_report`.

---

<!-- BEGIN SUMMARY - auto-generated, do not edit -->
**VERDICT: REVIEW** — v(x) outside the tolerance band

6 steps · 4 decisions · 1 retry · 2 gaps
<!-- END SUMMARY -->

## [19:26:31] setup / info — Case directory prepared

Created cases/work/lid-cavity via prepare_case.

## [19:26:31] geometry / ok — Templated on the icoFoam cavity tutorial

- **Decision:** Adopt incompressible/icoFoam/cavity as the structural template (agent's call)
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Same square geometry and patch layout; only the Reynolds number and solver differ _(cites: corpus/incompressible/icoFoam/cavity/cavity.md)_
- **Alternatives:** incompressible/simpleFoam/pitzDaily — matching solver but wrong geometry, so the blockMeshDict would be rewritten anyway
- **When it breaks:** A cavity with a non-unit aspect ratio needs the block topology re-derived, not rescaled

</details>

## [19:26:31] mesh / ok — 80x80 uniform grid

- **Decision:** Uniform 80x80 cells over the unit square (agent's call)
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Ghia tabulates on 129x129; 80x80 uniform resolves the primary vortex and both lower-corner vortices _(cites: ghia_1982)_
- **Alternatives:** _no alternatives surfaced._
- **When it breaks:** _failure modes not characterized._

</details>

### Mesh stats

| cells | points | faces | internal_faces |
|---|---|---|---|
| 6400 | 13122 | 25760 | 12640 |

## [19:26:31] mesh_quality / error — Max non-orthogonality 78 deg

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 78.4 | poor |
| max_skewness | 1.2 | good |

checkMesh reported 312 severely non-orthogonal faces; the solve would need extra non-orthogonal correctors.

## [19:26:31] mesh_quality / fixed — Removed the grading that skewed the corner cells
_retry of: 'Max non-orthogonality 78 deg'_

- **Decision:** Drop the 4:1 wall grading in favour of a uniform spacing
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** checkMesh put max non-orthogonality at 78.4 deg, inside the severe band; uniform spacing on a square block is orthogonal by construction _(cites: of_check_mesh_src__primitiveMeshCheck.C)_
- **Alternatives:** Keep the grading and raise nNonOrthogonalCorrectors — trades a cheap mesh fix for per-iteration cost on every timestep
- **When it breaks:** A wall-resolved turbulent case needs the near-wall grading, so this trade reverses once y+ has to reach the viscous sublayer

</details>

### checkMesh metrics

| metric | value | verdict |
|---|---|---|
| max_non_orthogonality | 0.0 | good |
| max_skewness | 0.4 | good |

## [19:26:31] validation / warning — v(x) outside the tolerance band

- **Decision:** Report the miss rather than refine: u(y) passes, v(x) does not
<details><summary>why · alternatives · when it breaks</summary>

- **Why:** Relative L2 on v(x) is 0.071 against a 0.05 tolerance; the deficit sits at the horizontal-centerline extrema where the grid is coarsest _(cites: ghia_1982)_
- **Alternatives:** Refine to 129x129 and re-run — deferred until the researcher confirms the tolerance is the intended bar
- **When it breaks:** _failure modes not characterized._

</details>

### Comparison vs ghia_1982

| profile | L2 | L_inf | tolerance | verdict |
|---|---|---|---|---|
| u_centerline | 0.0023 | 0.0061 | 0.05 | pass |
| v_centerline | 0.0710 | 0.1180 | 0.05 | fail |

<!-- BEGIN DECISIONS TABLE - auto-generated, do not edit -->
## Decisions

One line per decision above; open an entry's *why · alternatives · when it breaks* block for the full reasoning. Generated on `finalize_report`.

| Phase | Decision | Cites | Gaps |
|---|---|---|---|
| geometry | Adopt incompressible/icoFoam/cavity as the structural template (agent's call) | corpus/incompressible/icoFoam/cavity/cavity.md | — |
| mesh | Uniform 80x80 cells over the unit square (agent's call) | ghia_1982 | alts, breaks |
| mesh_quality | Drop the 4:1 wall grading in favour of a uniform spacing | of_check_mesh_src__primitiveMeshCheck.C | — |
| validation | Report the miss rather than refine: u(y) passes, v(x) does not | ghia_1982 | breaks |

<!-- END DECISIONS TABLE -->
