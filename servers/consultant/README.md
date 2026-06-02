# Consultant MCP server

Reasons over the OpenFOAM and Validation servers' output — `checkMesh` metrics, residual histories, y+ on wall patches — and returns CFD-domain verdicts with thresholds, recommendations, and citations. Also fetches corpus annotations on tutorials and drafts new ones from completed runs.

## Tools

- **`assess_mesh_quality(case_path)`** — parses `log.checkMesh` and returns per-metric verdicts (good / acceptable / marginal / poor) for non-orthogonality, skewness, aspect ratio, severe-face count, with thresholds and remedies.

- **`assess_residuals(case_path)`** — reads the solver log and classifies each field as converged / still_running / stalled / oscillating / diverging, with CFD-domain recommendations (under-relaxation, scheme order, mesh quality).

- **`assess_y_plus(case_path, time="latest")`** — checks wall-patch y+ against the turbulence model's wall-treatment assumption (high-Re wall function vs low-Re resolved vs kOmegaSST hybrid). Reads `postProcessing/yPlus/<time>/yPlus.dat`.

- **`get_tutorial_annotation(tutorial_path)`** — fetches the corpus annotation for an `$FOAM_TUTORIALS` entry from `corpus/<solver>/<case>.md`. Returns parsed YAML frontmatter as `metadata` and the markdown body as `body`. Missing annotations are flagged, never silently substituted.

- **`list_tutorial_annotations()`** — enumerates the annotations in the corpus.

- **`draft_annotation_from_report(case_path, tutorial_path)`** — parses the per-step decision entries in `<case>/REPORT.md` (the full decision / why / alternatives / when-it-breaks + citations, not the compact index) and writes a candidate `.draft.md` under `corpus/<tutorial_path>`. Works straight off the narration — no `finalize_report` required first. The `.draft.md` suffix keeps it out of `get_tutorial_annotation` until a human reviews, edits (adds citations, generalises scenario-specific language, adds experience-based commentary), and renames the file to `.md` to promote it.

## Running

```bash
uv sync --all-packages
uv run --package consultant-mcp python -m consultant_mcp
```

## Testing

```bash
uv run pytest servers/consultant/tests
```

Pure numerical and filesystem checks. Most run without OpenFOAM; the
citation-resolution tests (which open the cited `$FOAM_SRC` / `$WM_PROJECT_DIR`
source files to confirm the thresholds still match) run only when OpenFOAM
is sourced and skip otherwise.

## Design rules

1. Every tool returns `{"success": bool, ...}`; never raise.
2. **Thresholds live in code, but their provenance is explicit — never hallucinated.** The band cutoffs and citations are in `assessments.py` (`CITATION_SOURCES`). Each cutoff is classified — source-verified (a real OpenFOAM constant or established law), practice convention, or tool heuristic — in [`docs/consultant-threshold-provenance.md`](../../docs/consultant-threshold-provenance.md), and every cited source is verified and archived offline under [`corpus/references/`](../../corpus/references/manifest.json). Where no source backs a cutoff it is labeled as such, not dressed in a fake citation; tutorial rationale comes from the corpus (`corpus/`).
3. Output is small and structured. Verdicts feed the consultant fields on `openfoam.record_step` — keep them tight.
