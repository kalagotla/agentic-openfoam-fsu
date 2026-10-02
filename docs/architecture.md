# Architecture

## Why MCP

MCP (Model Context Protocol) standardises how agents call tools — to agent-tool communication what HTTP is to web APIs.

- **Tool-agnostic.** The same server works with Claude, GPT, Gemini, or a local Qwen / Llama. Swap the agent, keep the tools.
- **Testable.** Each tool is a typed Python function. `run_blockmesh` is unit-testable against the Pitz-Daily baseline without involving an LLM.
- **Transparent.** Every agent action is a logged tool call with inputs and outputs. The session transcript is the audit trail.

## What an MCP server exposes

- **Tools** — typed functions with side effects (run a solver, write a dict).
- **Resources** — read-only data (reference datasets, schemas).
- **Prompts** — reusable workflow templates.

This repo uses tools and resources. No prompts — they'd turn agent reasoning into script-following.

## The four servers

### OpenFOAM

CLI and dictionary I/O. Tools by phase:

**Discovery**
- `list_tutorials(subpath)` → catalogue of `$FOAM_TUTORIALS` entries
- `read_tutorial_file(relative_path)` → contents of one tutorial dict

**Authoring**
- `prepare_case(case_path, overwrite)` → creates the work directory before authoring; refuses to clobber a non-empty prior attempt unless `overwrite=True` (the single overwrite-guard for case authoring, since `write_dict` requires the dir to exist)
- `write_dict(case_path, dict_name, content, subdir)` → writes a dict into `system/`, `constant/`, or `0/`
- `copy_tutorial_dict(case_path, tutorial_path, dict_name, subdir, replacements)` → copies a `$FOAM_TUTORIALS` dict verbatim into the case (keeps the FoamFile header/banner), with optional exact-string `replacements`

**Structured meshing**
- `run_blockmesh(case_path)` → `{success, mesh_stats, log_tail}`
- `check_mesh(case_path)` → `{success, quality_pass, metrics, warnings}`

**STL / CAD meshing**
- `prepare_surface_mesh(case_path, stl_path, patch_name)` → drops STL into `constant/triSurface/`, runs `surfaceCheck`, returns closure verdict
- `run_snappy_hex_mesh(case_path)` → `{success, mesh_stats, phases, log_tail}` with per-phase castellation / snap / layer-addition outcomes

**Parallel execution**
- `decompose_par(case_path, n_procs, method)` → splits the mesh
- `run_solver(case_path, solver, end_time, n_procs)` → serial (`n_procs=1`) or `mpirun -np N` (`n_procs>1`)
- `reconstruct_par(case_path, time)` → reassembles time directories

**Inspection and narration**
- `get_residuals(case_path, summary)` → per-field summary (default) or full history
- `export_field_image(case_path, field, time)` → PNG path
- `record_step(case_path, phase, status, title, details, retry_of)` → appends a timestamped entry to `<case>/REPORT.md` during the run
- `finalize_report(case_path)` → adds a verdict banner near the top of `REPORT.md` and a compact one-line-per-decision index at the end (phase · decision · cites · gaps); the full reasoning stays in each step's collapsible `<details>` block. Called once after validation; re-running refreshes both in place
- `archive_case(case_path, archive_name)` → copies case inputs to `cases/examples/<name>/baseline/` (skips time dirs, mesh, logs)

### Validation

Reference-data library plus case-agnostic comparison primitives, and a runner for agent-authored analysis scripts. Nothing physics-specific lives in the primitives — reattachment lengths, Strouhal numbers, drag coefficients are extracted by the agent's per-case script, which then scores through the trusted comparison primitive.

- `list_references()` → datasets discoverable under any `reference/` directory below `cases/`
- `read_reference(name)` → parsed JSON for one named reference (filename stem)
- `compare_profiles(sim_axis, sim_field, ref_axis, ref_field, tolerance)` → L2 / L∞ error with a tolerance gate
- `compare_scalar(sim_value, ref_value, tolerance_relative, tolerance_absolute)` → relative-or-absolute error for a single coefficient (Cl/Cd, reattachment length) — the case `compare_profiles` rejects as `too_few_points`
- `grid_convergence_index(h, values, safety_factor)` → three-grid GCI (Celik et al. 2008): apparent order, Richardson extrapolation, fine/medium GCI, asymptotic-range ratio; scalars or profiles at common stations
- `check_convergence(residual_history, threshold, stall_window)` → converged / diverged / stalled / still_running
- `run_analysis(case_path, script, args, timeout_s)` → runs the agent-authored `analysis/validate.py` in a hardened subprocess (own process group, RLIMIT caps, minimal env, headless single-threaded numerics), captures its `<<<ANALYSIS_RESULT>>>` JSON metrics + verified plot paths. The script extracts + plots; it scores via `compare_profiles`, so the verdict stays on tested code.

**Design principle — the verdict belongs to tested code.** A fixed metric vocabulary can't span every CFD comparison, so extraction + visualization are agent-authored (open-ended). But the pass/fail number is always produced by `compare_profiles`, not by the script's own arithmetic: a bad extraction yields a failing (or obviously-off) error, not a silent pass. `run_analysis` itself is deliberately incurious — it runs a subprocess, parses a sentinel, verifies plots exist, and never inspects or judges the metrics. The script + plots + the comparison numbers are archived together (`postProcessing/analysis/` is carved out of the archive exclusions), so the trust boundary is visible in the artifact and the validation replays.

Shipped reference data:

- `ghia_1982` — Ghia, Ghia & Shin, *JCP* 48 (1982); cavity centerline u(y), v(x) at Re=100, 400, 1000
- `reattachment_length` — Armaly et al., *JFM* 127 (1983); BFS x_r/h vs Re
- `xfoil_polar` — XFOIL v6.99 polar at Re_c = 1e6
- `agard_ar_138_qualitative` — qualitative Cl / Cd / Cp targets for the M6-style wing

Adding a new dataset: drop a JSON under any case's `reference/`.

### Consultant

Reasons over the other servers' output. CFD-domain verdicts with thresholds, recommendations, citations; tutorial-annotation lookup.

- `assess_mesh_quality(case_path)` → per-metric verdicts (non-orthogonality, skewness, aspect ratio, severe-face count) with thresholds and remedies
- `assess_residuals(case_path)` → per-field convergence classification with recommendations (URF, scheme order, mesh quality)
- `assess_y_plus(case_path, time)` → wall-patch y+ vs the turbulence model's wall-treatment assumption
- `assess_grid_convergence(h, values, quantity, gci_target)` → good / acceptable / marginal / poor verdict on a GCI study (via `validation.grid_convergence_index`), with the refinement needed when it falls short
- `get_tutorial_annotation(tutorial_path)` → fetches the annotation under `corpus/`
- `list_tutorial_annotations()` → enumerate the corpus
- `draft_annotation_from_report(case_path, tutorial_path)` → drafts a candidate annotation file by parsing the run's per-step decision entries (full why / alternatives / when-it-breaks + citations, not the compact index); writes `.draft.md` for the human to review and rename to promote
- `flag_uncited_claims(case_path)` → end-of-run integrity lint over REPORT.md (or a corpus entry): surfaces decision entries that appeal to outside authority, state a regime boundary with a number, or self-admit uncited, plus citations that don't resolve to `corpus/references/`

Citation provenance: each verdict's source lives in `CITATION_SOURCES` (in `assessments.py`). Every cutoff is classified — source-verified (a real OpenFOAM constant or established law), practice convention, or tool heuristic — in [`consultant-threshold-provenance.md`](consultant-threshold-provenance.md), and the cited sources are catalogued and archived offline under [`corpus/references/`](../corpus/references/manifest.json). No hallucinated wisdom: an unsourced cutoff is labeled, not given a fake citation.

### Research-assistant

Custom-OpenFOAM-C++ build loop. Does *not* generate code.

- `wmake_and_report(directory)` → runs `wmake`, parses errors into structured returns (missing_header, missing_library, undefined_symbol, compile_error) with hints
- `find_examples_of_base_class(base_class, max_results)` → greps `$FOAM_SRC` and `$FOAM_APP` for derivations
- `discover_user_lib_path()` → `$FOAM_USER_LIBBIN`, `$WM_PROJECT_USER_DIR`, `$WM_PROJECT_VERSION` (detects ESI vs Foundation fork)

## Design principles

**Tools are typed, small, composable.** A tool whose docstring runs past ~5 lines is too big — split it. Agents pick the right tool from descriptions; long ones confuse selection.

**Structured errors, not exceptions.** Every tool returns `{success: bool, ...}` instead of raising. The agent reasons about `{success: false, reason: "blockMesh failed: patch 'inlet' undefined"}` and recovers; a stack trace gets swallowed.

**Validation drives correction; agents do not anticipate.** When the agent picks a tutorial as a template, it adopts the tutorial's choices verbatim except for what the scenario explicitly requires. Mesh resolution, schemes, URFs, turbulence model, time step — left alone until validation or a quality check fails. Each subsequent fix is recorded as a separate `record_step` citing the specific miss. Anticipation skips the audit trail; the audit trail is the product.

**Context budget is finite.** Raw fields and meshes never reach the agent — only scalar summaries, sampled profiles, and exported images.
