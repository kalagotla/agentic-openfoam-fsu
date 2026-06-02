# Consultant threshold provenance

The consultant turns mesh/residual/y+ metrics into verdicts using a set of
band cutoffs. The citation tags on each band (`cites=[...]`, rendered in
REPORT.md and resolved via `CITATION_SOURCES`) point at the source for the
*recommendation*. This document audits the **cutoffs themselves** — the
numbers that decide which band a metric falls into — and classifies each:

- **source-verified** — equal to a specific OpenFOAM constant or an
  established physical law; the source is archived offline in
  [`corpus/references/`](../corpus/references/manifest.json) and (for the OpenFOAM
  constants) re-checked by a test against the live install.
- **practice convention** — standard CFD engineering practice with no
  single canonical source; cited to a textbook where one covers it, but
  the *exact* number is judgment, not a quotable constant.
- **tool heuristic** — the consultant's own algorithm. No external source.
  Listed here so the gap is visible rather than hidden behind a
  citation-shaped label.

The honest summary: the **boundary-defining** numbers (checkMesh defaults,
the meshQualityDict limits, the law-of-the-wall y+ bounds) are
source-verified; the **interior interpolated** cutoffs are practice
convention; and the **residual-pattern classifier** is a bespoke heuristic.

Verified OpenFOAM constants come from
`$FOAM_SRC/OpenFOAM/meshes/primitiveMesh/primitiveMeshCheck/primitiveMeshCheck.C`
(`of_check_mesh_src`) and `$WM_PROJECT_DIR/etc/caseDicts/meshQualityDict`
(`of_mesh_quality_dict`).

## Mesh non-orthogonality (degrees)

| Boundary | Value | Class | Justification |
|---|---|---|---|
| good / acceptable | 60 | practice convention | Conservative margin below the 65/70 limits; no scheme corrector needed in practice. |
| acceptable (upper) | ~65–70 | **source-verified** | `meshQualityDict maxNonOrtho = 65` (mesh-motion/snappy accept limit); `primitiveMeshCheck nonOrthThreshold_ = 70` (checkMesh "severe"). |
| marginal / poor | 80 | practice convention | Interpolated between the 70° severe limit and geometric degeneracy; near `maxConcave = 80`. |
| poor / degenerate | 90 | practice convention | Geometric reasoning (cell face becomes non-convex). Not a distinct checkMesh constant. |

## Face skewness

| Boundary | Value | Class | Justification |
|---|---|---|---|
| good / acceptable | 1 | practice convention | Conservative "comfortably clean" margin (stated as such in the code docstring). |
| acceptable / marginal | 4 | **source-verified** | `primitiveMeshCheck skewThreshold_ = 4` == `meshQualityDict maxInternalSkewness = 4`. |
| marginal / poor | 10 | practice convention | Interpolated; well below `maxBoundarySkewness = 20`. |

## Cell aspect ratio

| Boundary | Value | Class | Justification |
|---|---|---|---|
| good / acceptable | 10 | practice convention | "Nearly isotropic" — textbook bulk-mesh guidance (Versteeg). |
| acceptable / marginal | 100 | practice convention | Moderately wall-resolved range — practice. |
| marginal / poor | 1000 | **source-verified** | `primitiveMeshCheck aspectThreshold_ = 1000` (checkMesh default). |

## Severely non-orthogonal face count

| Boundary | Value | Class | Justification |
|---|---|---|---|
| "severe" face definition | > 70° | **source-verified** | `primitiveMeshCheck` severe threshold (cos of `nonOrthThreshold_`). |
| acceptable / marginal | 0.1% of cells | tool heuristic | Engineering judgment ("a handful is fine"); no canonical source. |
| marginal / poor | 1% of cells | tool heuristic | Engineering judgment ("systematic problem"); no canonical source. |

## y+ wall-treatment bands

The y+ band *bounds* are established law-of-the-wall / wall-treatment
physics; the intermediate sub-bands are practice.

| Band | Value | Class | Justification |
|---|---|---|---|
| high-Re wall function, log layer | 30 ≤ y+ ≤ 300 | **source-verified** | Law of the wall — Versteeg Ch.3, Wilcox §1.3 (`versteeg`, `wilcox`). |
| high-Re, viscous sublayer / buffer | 11, 30 | **source-verified** | Law-of-the-wall crossover (u+ = y+ to ~11; log law from ~30). |
| low-Re / LES, wall-resolved | y+ ≤ 1 | **source-verified** | NASA TMR flat-plate grids: wall-integration RANS needs avg min y+ < 1 (`nasa_tmr`). |
| low-Re sub-bands | 1 < y+ ≤ 5, > 5 | practice convention | Refinement guidance; not a TMR statement. |
| kOmegaSST hybrid | <1, <5, <30 | **source-verified** (concept) / practice (sub-bands) | Automatic/blended wall treatment — Menter et al. 2003 (`menter_sst`); the <5/<30 sub-bands are practice. |

## Residual-pattern classifier (`assess_residual_pattern`)

**The classification cutoffs below are a tool heuristic** — the
consultant's own pattern-detection algorithm. They are *not* drawn from
literature. (The *remediation advice* each verdict carries — URF tuning,
scheme order, corrector counts — IS cited, to `of_user_guide_urf` and
`versteeg`. Only the detection thresholds are bespoke.)

| Parameter | Value | Class | Note |
|---|---|---|---|
| converged threshold | 1e-5 | practice convention | Typical SIMPLE `residualControl`; tutorials span 1e-3…1e-6. |
| window | last 50 iters | tool heuristic | Detection window size. |
| converged | last ≤ thr and tail max ≤ 2·thr | tool heuristic | — |
| oscillating | CoV > 0.3 and non-monotonic | tool heuristic | — |
| diverging | last ≥ 2 × first | tool heuristic | — |
| stalled | CoV < 0.05 and last > thr | tool heuristic | — |
| still_running | last < first / 3 | tool heuristic | — |

## Policy

- **No invented citations.** Where no quotable source backs a cutoff, it is
  labeled practice-convention or tool-heuristic — never given a
  citation-shaped guess. A visible gap is the signal that the corpus has a
  hole; hiding it behind a fake citation removes that signal.
- **Source-verified cutoffs resolve to a real, offline source.** The
  OpenFOAM constants (`primitiveMeshCheck.C` checkMesh defaults,
  `meshQualityDict` limits) and the law-of-the-wall y+ bounds each map to a
  file or reference catalogued in [`corpus/references/manifest.json`](../corpus/references/manifest.json),
  and the source-code constants are re-checked by a test against the live
  install.
- **The residual-pattern classifier is a heuristic, not validated against
  reference data.** If a residual verdict matters for a deliverable, confirm
  it against a known convergence history rather than trusting the band label.
