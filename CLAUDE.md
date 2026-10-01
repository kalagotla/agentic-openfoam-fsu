# Working in this repo

This repo ships four MCP servers under `servers/`, scenario files under
`cases/scenarios/`, and reference data for validation under
`cases/*/reference/` and `cases/examples/*/reference/`.

## Sources of truth

Every setup choice comes from one of two places, in this order:

1. **The OpenFOAM tutorial** you adopt as the template — its dictionaries,
   mesh, schemes and controls are the starting point for everything the
   scenario does not specify.
2. **A promoted corpus entry** for that tutorial
   (`consultant.get_tutorial_annotation`) — knowledge earned by an earlier
   validated run and reviewed by a human. Where it exists, it overrides
   the tutorial's defaults, and you cite it.

Beyond those, only **evidence from this run** (a failed check, a
validation miss) justifies a change. Not memory of how this benchmark is
"usually" set up, not a value seen in a paper or forum (those may support
a `why` citation, never a setup value up front), and not other runs in
this repo: do not read `workshop/` (walkthrough and recorded runs),
`docs/evaluation-*`, other `cases/work/*` directories, or
`cases/examples/*/baseline/` while setting up a case.

## How to set up a CFD case (the workflow that matters)

The user gives you a **scenario YAML** at `cases/scenarios/<name>.yaml` —
e.g. `cases/scenarios/flat-plate.yaml`. Your job is to author a fresh,
runnable OpenFOAM case at `cases/work/<name>/` from that description.

**Workflow:**

1. Read the scenario YAML.
2. Browse `$FOAM_TUTORIALS` with the `list_tutorials` and
   `read_tutorial_file` MCP tools. Find a tutorial whose physics matches
   the scenario (incompressible/compressible, steady/transient,
   turbulence model, geometry style). That is your structural template.
3. Create the work directory with **`prepare_case(cases/work/<name>)`**
   before authoring anything — the authoring tools require the case
   directory to exist, and `prepare_case` refuses to overwrite a prior
   attempt's directory unless you pass `overwrite=True` (it asks you to
   confirm with the researcher first). Do NOT `mkdir` the case by hand;
   use `prepare_case` so that guard runs.
4. Author each dictionary. Two paths:
   - **`copy_tutorial_dict`** when a tutorial file is the right
     structural base — reads the tutorial bytes and writes them into
     the case verbatim, with an optional `replacements={old: new, ...}`
     map for exact-string patches (e.g.
     `{"endTime         0.5;": "endTime         5.0;"}`). Every patch
     must match exactly once. Prefer this for any dict you can pull
     from a tutorial — it keeps the FoamFile header, banner, and
     trailing separator intact.
   - **`write_dict`** for files with no tutorial counterpart, or when
     you need to author content from scratch. Pass full text via
     `content`.

   Both accept `subdir="system"` for solver control (controlDict,
   fvSchemes, fvSolution, blockMeshDict), `subdir="constant"` for
   transportProperties / turbulenceProperties, and `subdir="0"` for
   initial/boundary fields (U, p, k, omega, nut). Write **all of
   system/ first** — `blockMesh` and `checkMesh` refuse to run without
   controlDict/fvSchemes/fvSolution. Adapt patch names, geometry, BCs,
   schemes, and controls to the scenario. Do not blindly copy.
5. Pick a meshing path based on the scenario geometry:
   - **Structured (block-aligned) geometry** (cavity, channel, BFS,
     flat plate): write `system/blockMeshDict` with `write_dict`, then
     `run_blockmesh`.
   - **Arbitrary CAD/STL geometry** (airfoil, wing, full aircraft):
     write a background `system/blockMeshDict` and a
     `system/snappyHexMeshDict`, drop the STL into
     `<case>/constant/triSurface/` via `prepare_surface_mesh`, then
     `run_blockmesh` (background) followed by `run_snappy_hex_mesh`
     (carves the geometry out). The phase report tells you whether
     castellation / snap / layer addition succeeded or only partially
     ran — partial layer addition is the most common failure and the
     agent should flag it and decide whether to relax parameters or
     accept fewer layers.
   Then **always** `check_mesh` before solving. A converged solver on
   a bad mesh is still wrong — flag high non-orthogonality / skewness
   and either re-mesh or compensate (e.g. raise
   `nNonOrthogonalCorrectors`).
6. `run_solver`. For meshes larger than ~1M cells (typical for 3-D
   RANS, including the ONERA M6 case), decompose first with
   `decompose_par(n_procs=N, method="scotch")`, run with
   `run_solver(..., n_procs=N)` (which dispatches `mpirun`), then
   `reconstruct_par` to stitch time directories back together before
   postprocessing.
7. Read residuals (`get_residuals`, summary mode), then validate against
   the reference data the scenario names in `validation.reference`. **Validation is
   agent-authored analysis, not a fixed tool.** A fixed metric vocabulary
   can't span the space (Cd/Cl, Cp, Cf, reattachment, Strouhal, Nusselt,
   shock angle, spectra), so:
   - Write a per-case Python script at `<case>/analysis/validate.py` that
     (a) extracts the case-specific quantity from solver output, (b) loads
     reference arrays with `validation.read_reference(<name>)`, (c) scores
     them by calling `validation.compare_profiles(...)` — do NOT
     re-implement the error norm, (d) draws matplotlib overlays into
     `postProcessing/analysis/`, and (e) prints `<<<ANALYSIS_RESULT>>>`
     then one line of JSON `{"metrics": {...}, "plots": [...]}` as its last
     output.
   - `validation_mcp.analysis` handles the generic parts:
     `latest_set(".", <set name>, <field>)` finds the newest sampled file,
     `read_set(path)` returns `(coord, values)`, and `emit(metrics, plots)`
     prints the result block. Use them rather than re-deriving file layouts.
   - Run it with `validation.run_analysis(case_path)`. **The trust hinge:**
     the pass/fail number is produced by the tested `compare_profiles`, not
     by the script's own math — the script only extracts and plots.
   - The validation server runs WITHOUT OpenFOAM sourced, so the script
     reads solver output **files directly** (e.g. a sampled
     `postProcessing/sets/.../line_U.xy` the solver wrote) — it cannot shell
     out to `postProcess`. Configure the sampling functionObject in
     `system/controlDict` during authoring so the solver produces what the
     script reads.
   - Load the reference via `read_reference(<name>)` (resolves regardless of
     working directory), never a hand-rolled relative path — that path
     breaks when the case is archived and relocated.
   `list_references` / `check_convergence` remain available for discovery and
   residual classification. If validation fails, diagnose and re-author the
   relevant dict or the analysis script — don't just rerun.
8. Render fields with `export_field_image` for a visual sanity check.

**Narrate every step with `record_step`.** The user watches
`<case>/REPORT.md` live (`tail -f`) as the run unfolds. After each of
geometry choice, mesh stats, `checkMesh` outcome, BC summary, solver
convergence, validation comparison, and rendered images, call
`record_step` with the relevant `phase`, a `status` of
`ok` / `warning` / `error` / `fixed` / `info` / `pending_review`, a
one-line title, and a short markdown body. When you retry after a
failure, record the fix with `status="fixed"` and
`retry_of="<prior failing title>"` — the audit trail of
"tried X, hit Y, applied Z" is the artifact this project produces.

**Close the run with `finalize_report`.** Once validation has returned
its verdict (pass or fail) and any post-processing image is rendered,
call `finalize_report(case_path)` exactly once. It adds two skim aids
without touching the live narration: a **verdict banner** near the top
(PASS / FAIL / REVIEW / INCOMPLETE, read off the last `validation`
entry, plus step / decision / retry / gap counts) and a **compact
Decisions index** at the end — one line per decision carrying only the
phase, the decision one-liner, its citations, and which consultant
fields are still gaps. The full why / alternatives / when-it-breaks
reasoning stays in each step's collapsible block, so the index is a map
into the narration, not a second copy of it. Until you call
`finalize_report`, REPORT.md is live narration only; the banner and
index are the review artifacts, not live-updating accumulators. If the
researcher asks you to apply a fix and re-record steps, call
`finalize_report` again afterwards to refresh both in place. Then run the
integrity audit — `consultant.flag_uncited_claims(case_path)` — and resolve any
flagged uncited claim (derive it from first principles, or cite it to
`corpus/references/`) before treating the run as closed.

Each decision entry renders the **Decision** line in the open and folds
**Why / Alternatives / When it breaks** into a `<details>` block, so the
live narration stays scannable while the depth is one click away. Write
prose with literal `<`, `>`, and `&` — do NOT HTML-escape them to
`&lt;` / `&gt;` / `&amp;`; the only intended markup in an entry is the
`<details>` wrapper, which `record_step` adds for you.

**Structured data goes in `tables`, not prose.** `record_step` accepts
a `tables` argument:
`{title: [{column: value, ...}, ...]}`. Use it for anything a reader
needs to scan rather than read. Canonical shapes per phase:

- *mesh* — one row in `Mesh stats` with `cells`, `points`, `faces`,
  `internal_faces`; a `Patches` table with one row per patch
  (`name`, `type`, `faces`).
- *mesh_quality* — `checkMesh metrics` rows of (`metric`, `value`,
  `verdict`) for `max_non_orthogonality`, `max_skewness`,
  `max_aspect_ratio`, `severe_non_orthogonal_faces`.
- *boundary_conditions* — `Boundary conditions` with one row per
  patch and one column per field (`patch`, `U`, `p`, `k`, `omega`,
  `nut`, …).
- *convergence* — `Residuals` with rows `(field, initial, final,
  orders_dropped)` per solved field.
- *validation* — `Comparison vs <reference>` with rows `(profile, L2,
  L_inf, tolerance, verdict)` per compared profile.

Prose still belongs in `decision` / `why` / `alternatives` /
`when_it_breaks` for the *reasoning*; `tables` is for the *numbers*.
A single `record_step` call can carry both.

**Audit-trail voice.** `record_step` entries are CFD case notes for a
researcher reading REPORT.md. Write physical reasoning, citations to
papers and tutorial annotations, and numerical results from the run.
Do NOT quote this file or any process-meta language ("the workflow",
"the audit-trail moment", "this project ships ..."); do NOT predict
failures you have not observed; do NOT name "the agent" as an entity
inside the entry. The reader treats entries as research case notes,
not as commentary on how the case was produced. Cite the CFD source
of any claim — annotation path, paper DOI, Versteeg chapter — never
this file.

**Decisions carry the consultant schema.** Whenever a `record_step` call
records a *choice* (mesh template, scheme, BC, turbulence model, solver,
URF, ...), fill the four consultant fields:

- `decision` — one-line summary of what was chosen.
- `why` — rationale; must cite a tutorial annotation or referenced paper
  via `citations=[...]`.
- `alternatives` — other options considered and why they were rejected.
- `when_it_breaks` — regimes / assumptions under which this choice would
  be wrong.

Empty fields are rendered as honest weakness (`_uncited choice_`,
`_no alternatives surfaced_`, `_failure modes not characterized_`) and
returned in `consultant_gaps`. **Never invent CFD wisdom to fill the
fields** — if no annotation or reference supports the choice, leave the
field empty so the gap is visible. The gap is the signal that the corpus
needs an annotation; suppressing it removes the only signal that the
corpus has a hole.

**No uncited assertions — cite or derive, never assert from memory.** The
empty-field rule above is about a *missing annotation*; this rule is about
*claimed facts*. Any factual claim in a consultant field — a number, a
threshold, a regime boundary (a transition / critical-Reynolds / bifurcation
value) — must be EITHER cited OR derived from first principles, and never
asserted from unsourced recall ("the literature says ~Re 8000"). Two grounded
forms are allowed:

- **Cited.** The `why` cites a source, and that citation must resolve to an
  entry in `corpus/references/` (or a corpus annotation). When you actually use
  a new external source, add it to `corpus/references/manifest.json` — pulled
  information goes into the library, it does not live only in a `why` line.
- **First principles.** A derivation the reader can check (e.g. "a steady
  solver presumes a steady solution exists; if the flow is inherently
  unsteady the steady solve stalls — the stall is itself the diagnostic"),
  with no appeal to an unsourced number.

If you have only unsourced recall of a fact, derive it from first principles or
drop the specific claim — do not state it, and do not invent a citation. After
`finalize_report`, run **`consultant.flag_uncited_claims(case_path)`** and
resolve every flag (it lints REPORT.md for authority-appeal /
regime-with-a-number / self-admitted-uncited claims, and for citations that
don't resolve to the library).

**Narrate the key setup choices even when the scenario already specified
them, and tag their origin.** A corpus entry drafted from this run has to
teach a future user who lacks the scenario's input, so the entry should
document the whole setup — not only the choices you had to figure out.
Record the load-bearing choices (solver, geometry/BCs, mesh strategy,
turbulence model, key schemes) regardless of who decided them, and note
the origin inline in `decision`: `(scenario-specified)` when the YAML
fixed it, `(agent's call)` when you chose it, `(deviation from scenario)`
when you changed a scenario value because a check failed. The agent's
calls and deviations are the corpus gold — a reviewer scans the origin
tags to see where to focus. This does not contradict "let validation
drive": you still adopt tutorial defaults and change only what the
scenario demands; you are just *documenting* the resulting choices.

**Human-in-the-loop levels.** The scenario YAML may declare an
`automation_level` (1–5). Default is 2 if unspecified.

| Level | Behaviour |
|---|---|
| 1 — Consult | Before *and* after each phase, call `record_step` with `status="pending_review"`, then STOP and ask the researcher to approve before continuing. |
| 2 — Review (default) | After each phase, surface a `record_step` entry and STOP for the researcher to confirm before the next phase. |
| 3 — Validate | Phases run through; pause for the researcher only at the validation step. |
| 4 — Notify | No pauses; agent runs through. On validation failure, STOP — do NOT auto-retry. Surface a `record_step` with full consultant fields explaining the failure and ask the researcher how to proceed. |
| 5 — Auto | Fully autonomous including retries. Reserved for parameter sweeps / overnight runs with a trusted template. |

**This is enforced, not just advised.** A Claude Code PreToolUse hook
(`.claude/hooks/automation_gate_hook.py`) and the bring-your-own-agent
harness (`scripts/run_agent.py`) share one policy
(`scripts/automation_gate.py`) that reads the scenario's
`automation_level` and forces an approval prompt before the gated step:
levels 1–2 gate every state-changing tool (`run_blockmesh`,
`run_snappy_hex_mesh`, `check_mesh`, `run_solver`, `decompose_par`,
`reconstruct_par`); level 1 also gates every `record_step`; levels 2–3
gate the `validation` `record_step` so the verdict is reviewed. Levels
4–5 never gate. Other MCP clients (Cursor, Cline) have no hook, so there
the levels are advisory — honor them yourself.

**Honor the level in your own behavior too** — the gate is a backstop,
not a substitute. Before phase 1, state the level and where you will
pause (e.g. "automation_level 2 → I stop for approval before each
phase"). Treat STOP as *end your turn*: do NOT call the next phase's
tool in the same response — surface the `record_step` and wait for the
researcher's reply. Re-read the level before each phase. If a gated step
is denied, stop and ask how to proceed; never retry it.

**Do NOT auto-retry on validation failure at levels 1–4.** A failed
validation indicates a real problem with the case (mesh, BC, scheme,
or model choice) that needs diagnosis, not re-execution. Silently
re-running hides the cause. Record the failure with full consultant
fields and stop.

**Adapt only what the scenario demands; let validation drive
everything else.** When you adopt a tutorial as a structural template,
change *only* the fields the scenario YAML explicitly requires
(steady-vs-transient solver swap, Reynolds-number scaling, geometry
sizing, BC patch names that fit the case, etc.). Leave every other
choice — mesh resolution, finite-volume schemes, under-relaxation
factors, turbulence model, time step, decomposition method, BC type
variants — at the tutorial's value for the first run.

Do **not** preemptively change those other choices because you
"know" from training, prior runs, or scenario-YAML hints that they
will be wrong. If you anticipate the mesh will miss the reference,
the scheme will be too diffusive, the URFs will diverge, the
turbulence model is mismatched, or the time step is too aggressive —
defer it. Run with the tutorial's value, let validation or a quality
check fail, and let the miss drive the fix.

The correct sequence:

1. Adopt the tutorial; change only scenario-required fields.
2. Mesh → `check_mesh` → solve → `get_residuals` → validate.
3. If everything passes, you're done.
4. If validation misses, or `check_mesh` / `assess_residuals` /
   `assess_y_plus` flag an issue, *now* propose the change, record
   it as a separate `record_step` entry citing the specific miss
   that motivated it, and re-run.

This applies even when scenario YAML hints (e.g.
`cells_recommended_*`), training intuition, or prior runs suggest a
non-tutorial choice would be "better." Anticipation skips the audit
trail; validation creates it. The audit trail — tried X, hit Y,
applied Z — is what this project produces.

**End-of-run handoff.** After validation has returned its verdict and
you've called `finalize_report`, consult the scenario YAML's
`end_of_run` block for two optional promotions. Both default to `false`
in the shipped scenarios; the researcher opts in by editing the YAML
before the run.

```yaml
end_of_run:
  archive_case: false        # → openfoam.archive_case(case_path, <scenario_name>)
                             #   copies the case to cases/examples/<name>/baseline/
  draft_corpus: false        # → consultant.draft_annotation_from_report(case_path, tutorial_path)
                             #   writes corpus/<...>.draft.md
```

If a flag is `true`, invoke the corresponding tool with the values
shown above (use the scenario name from `name:` for the archive, and
the tutorial path the structural template came from for the
annotation). If a flag is `false` or absent, skip it silently — do
NOT prompt the researcher; their answer is already in the YAML. Both
flags are independent; honor each on its own.

**When `draft_corpus` is `true`, complete the draft — don't hand back a
blank scaffold.** You ran the case, so fill the frontmatter you know by
passing it to `draft_annotation_from_report`: `solver`, `physics`,
`geometry` (facts from the run, generalised to the tutorial — describe
the regime class, not this run's exact parameter values), `references` (the paper/doc
citations you used), and your *proposed* `suitable_for` /
`not_suitable_for` (generalise them from your `when_it_breaks` reasoning;
the tool marks them "agent-proposed, confirm" so the reviewer knows to
check). The decision table fills itself from your `record_step` entries.
What you leave for the human is only judgment: confirming those two
proposals and the scenario→tutorial-template generalisation. Do not
fabricate metadata you don't have — omit a field and it stays a visible
`<fill in>` placeholder, which is honest.

Never invoke `archive_case` or `draft_annotation_from_report`
autonomously without an explicit `true` in the YAML. Both modify
tracked content that the researcher may want to review by hand first.

**When `archive_case` is `true`, make the archive replayable.** `archive_case`
copies case inputs (`system/`, `constant/` minus `polyMesh`, `0/`, `REPORT.md`,
the `analysis/` script, and the carved-out `postProcessing/analysis/` plots +
metrics) but deliberately skips the mesh, time directories, and bulk run
output. So replay is **re-mesh + re-solve from the archived inputs, then
`run_analysis`** — not `run_analysis` alone. Two things must travel with the
archive for this to work: (1) copy the scenario YAML into the case directory
before archiving (archive picks up a top-level YAML in the case dir, not the
canonical `cases/scenarios/<name>.yaml`), so the analysis spec and acceptance
intent survive; (2) have `analysis/validate.py` stamp its `metrics.json` with
provenance (numpy/matplotlib versions, git commit, sample time, reference
dataset name) so a later re-run can be compared against an attributed
baseline, not a bare number.

- **Do NOT read or copy from `cases/examples/<name>/baseline/`.** Baseline
  directories under `cases/examples/` are reference cases for validation
  comparison, not authoring templates. The tutorials library
  (`$FOAM_TUTORIALS`) is where you go for templates (see Sources of truth).
- **Output goes to `cases/work/<scenario-name>/`** — a fresh directory. If
  it already exists from a prior attempt, ask before overwriting.
- **Web access is allowed** for unfamiliar physics: NASA TMR, the OpenFOAM
  user guide, CFD-Online, vendor docs. Use it to explain and cite, not to
  pick setup values ahead of the tutorial and the corpus. Cite the URL.
- **Every tool returns `{success: bool, ...}`.** Read `reason` and
  `log_tail` on failure and recover. Don't ignore failures.
- **Don't dump raw fields, meshes, or full logs into your context.** Use
  the structured returns (`mesh_stats`, `final_residuals`, `residuals`,
  rendered PNGs). The architecture doc (`docs/architecture.md`) calls
  this "context budget is finite" — take it seriously.
- **Run `of2412` (or source `/usr/lib/openfoam/openfoam2412/etc/bashrc`)
  if a tool returns `*_not_found` or `foam_tutorials_unset`.** The MCP
  server's wrapper in `.mcp.json` already does this; the failure means
  someone broke the wiring.

## Where things live

| Path | What it is |
|------|------------|
| `cases/scenarios/*.yaml` | Inputs you read |
| `cases/work/<name>/` | Cases you author (gitignored) |
| `cases/work/<name>/analysis/validate.py` | The validation script you author; run via `validation.run_analysis` |
| `cases/work/<name>/postProcessing/analysis/` | Plots + `metrics.json` the script writes (archived for replay) |
| `cases/*/reference/`, `cases/examples/*/reference/` | Reference data for validation (load with `validation.read_reference`) |
| `cases/examples/*/baseline/` | Archived validated runs — do not read while setting up |
| `workshop/`, `docs/evaluation-*` | For humans: walkthrough, recorded runs, scores — do not read while setting up |
| `corpus/` | The consultant's knowledge layer — "why this choice" annotations earned from validated runs (or hand-authored), cited by `consultant.get_tutorial_annotation`. Ships empty. |
| `servers/openfoam/` | OpenFOAM MCP tools — actions (mesh, solve, dict I/O, narration) |
| `servers/validation/` | Validation MCP tools — reference comparison primitives + `run_analysis` (runs the agent-authored analysis script) |
| `servers/consultant/` | Consultant MCP tools — checkMesh verdicts, tutorial-annotation lookup |
| `servers/research_assistant/` | Research-assistant MCP tools — wmake loop, source-tree examples |
| `$FOAM_TUTORIALS` | OpenFOAM tutorial library (browse via tools) |
| `docs/architecture.md` | Why MCP, design principles |
| `docs/how-to-extend-openfoam.md` | Custom OpenFOAM C++ (BCs, function objects, ...) |

## When the user asks something other than "set up a case"

Use normal judgment. Most other asks (fixing a tool, writing a test,
extending the scenario format) follow the repo's general conventions: see
`docs/architecture.md` for design rules and the existing implementations
in `servers/openfoam/src/openfoam_mcp/tools.py` for the structured-return
pattern.
