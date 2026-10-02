# Scenarios — agent input files

A scenario YAML describes a CFD problem; the agent reads it and authors a runnable case under `cases/work/<name>/`.

## How to use

1. Drop a YAML in this folder, e.g. `cases/scenarios/my-case.yaml`.
2. Prompt the agent: *"Set up and run the case described in `cases/scenarios/my-case.yaml`."*
3. The agent browses `$FOAM_TUTORIALS`, authors dicts into `cases/work/my-case/`, meshes, solves, validates.
4. Validate against the reference data the scenario names in `validation.reference`. Case-specific metrics (reattachment, drag, Strouhal) are extracted by an agent-authored `analysis/validate.py`, run via `validation.run_analysis`, and scored through `compare_profiles`.

## Standard structure

Scenarios follow one section order, mirroring how a CFD case is actually set
up — state the problem, build the domain, mesh it, then assign physics
properties / conditions / numerics, then run and validate:

```
name                  # short identifier (= the cases/work/<name>/ dir)
description           # one-paragraph problem statement
automation_level      # run mode, 1–5 (see below); default 2

physics               # regime: incompressible/compressible, steady/transient,
                      #   laminar/turbulent (+ turbulence model), Re/Ma definition
geometry              # shape, dimensions, coordinates; template_tutorial / stl_path
mesh                  # strategy (blockMesh / snappyHexMesh), y+ target, grading
fluid                 # kinematic viscosity, density
flow_conditions       # freestream velocity, pressure, Mach, angle of attack
boundary_conditions   # each patch + its BC type, in human terms
solver                # application (e.g. simpleFoam) + scheme/relaxation notes
controls              # end time, write interval, convergence criteria
parallel              # n_procs, decomposition_method (large 3-D cases)

validation            # analysis spec (see "The validation section")
notes                 # optional free-text (expected results, runtime, variants)
end_of_run            # post-run promotions (archive_case / draft_corpus)
```

Not every case has every section: a closed cavity has no `flow_conditions`, a
2-D case has no `parallel`, and `solver` is omitted when the regime already
implies the solver. Sections that are present sit in this order.

Field notes:

- **`physics`** — the problem statement; it defines mesh resolution, solver, and schemes downstream.
- **`geometry`** — be specific about coordinates so the agent places patches without guessing.
- **`mesh`** — strategy + a y+ target / grading intent. Resolution can be a concrete count or left for the agent to establish by grid convergence.
- **`flow_conditions`** — reference velocity / pressure / Mach / alpha (external or inflow cases). Omit for closed domains.
- **`boundary_conditions`** — name each patch and its BC type in human terms (`velocity-inlet`, `no-slip-wall`, `symmetry`). The agent maps to OpenFOAM syntax.
- **`solver`** — name the OpenFOAM `application` when the scenario requires a specific one (e.g. the steady-vs-transient choice). Optional — omit to let the agent pick from the structural tutorial.
- **`validation`** — an analysis spec (see [The validation section](#the-validation-section)): which agent-authored script runs, against which reference, and the acceptance intent. Plus optional `qualitative_checks`.
- **`automation_level`** — integer 1–5 (see below). Default 2.

Worked example: [`flat-plate.yaml`](flat-plate.yaml); the fully-specified
reference is [`lid-cavity.yaml`](lid-cavity.yaml).

## Unsure about a choice? Describe it and let the agent decide

You do not need to know the mesh resolution, turbulence model, or solver up
front — the agent carries the CFD expertise. Three levels, from most to least
deferred:

1. **Omit the section/field.** The agent adopts the structural tutorial's value
   and lets validation drive any change. Leaving out `mesh:` means "mesh it
   sensibly"; leaving out `solver:` means "pick the solver the regime implies."
2. **Describe the constraint, defer the choice.** Add a free-text `guidance:`
   to any section and the agent resolves it, recording the decision (with its
   *why / alternatives / when-it-breaks*) in `REPORT.md`:

   ```yaml
   mesh:
     guidance: "resolve the wall boundary layer; you choose the cell count"
   solver:
     guidance: "not sure if kEpsilon or kOmegaSST — pick based on whether the
                flow separates, and say why"
   ```
3. **Specify concretely** when you do know — a normal value.

"Let the agent decide" means it makes a *reasoned default* (usually the
tutorial value) and records the rationale — not that it invents an exotic
choice. Validation still drives any refinement from there.

The same lid-cavity case is shipped at three points on this spectrum, so you
can see how the input detail shapes the audit trail:

- [`lid-cavity-expert.yaml`](lid-cavity-expert.yaml) — every choice specified
  (mesh, schemes, relaxation, residual control); `REPORT.md` mostly confirms.
- [`lid-cavity-guided.yaml`](lid-cavity-guided.yaml) — physics and geometry
  given, a few choices deferred with `guidance:`; the agent decides those and
  records the reasoning.
- [`lid-cavity-prompt.yaml`](lid-cavity-prompt.yaml) — just the ask; the agent
  owns and justifies every choice (Reynolds number, geometry, mesh, solver,
  reference), producing the richest audit trail.

## The validation section

`validation` declares an **analysis spec**: which agent-authored script runs,
against which reference, and what "pass" means. It declares intent, not
mechanism — a fixed tool/metric vocabulary can't span the validation space
(Cd/Cl, Cp, Cf, reattachment, Strouhal, Nusselt, shock angle, spectra), so the
agent authors the script and `compare_profiles` owns the verdict.

```yaml
validation:
  reference: cases/lid-cavity/reference/ghia_1982.json   # provenance pointer
  analysis:
    script: analysis/validate.py     # case-relative; the agent authors it
    args: []                         # optional argv forwarded to the script
    timeout_s: 120                   # optional
    checks:                          # human-readable intent, NOT executed
      - quantity: u_centerline
        reference_dataset: ghia_re_400_u_centerline
        tolerance_relative_L2: 0.05
  grid_convergence:                  # optional: ask for a GCI study
    method: GCI                      #   three refined grids; validation.grid_convergence_index
    quantities: [u_centerline]
  qualitative_checks:
    - "residuals drop >= 4 orders of magnitude"
```

The agent reads `analysis.checks`, authors `analysis/validate.py` to extract
each quantity from solver output, load the reference via `read_reference`, score
via `compare_profiles`, and plot overlays, then runs it with
`validation.run_analysis`. Scalar-coefficient checks (e.g. Cl/Cd) are computed
the same way, but note `compare_profiles` needs ≥2 points per side — a
single-value coefficient is compared by relative error in the script, not routed
through `compare_profiles`.

## Automation level

| Level | Behaviour |
|---|---|
| `1` Consult | Before *and* after each phase, propose with `record_step(status="pending_review")`, then stop. |
| `2` Review (default) | After each phase, surface the result and stop for researcher confirmation. |
| `3` Validate | Phases run through; pause only at the validation step. |
| `4` Notify | No pauses, but on validation failure STOP — never auto-retry. |
| `5` Auto | Fully autonomous including retries. For sweeps / overnight runs with a trusted template. |

Pick the lowest level you can tolerate. Level 1 for learning a new regime; level 2 for normal research; 4–5 only when the workflow is well-trodden.

**Enforcement.** This isn't just a hint to the agent. A Claude Code
PreToolUse hook (`.claude/hooks/automation_gate_hook.py`) and the
harness (`scripts/run_agent.py`) share one policy
(`scripts/automation_gate.py`) that reads `automation_level` and forces
an approval prompt before the gated step — gating the state-changing
tools at levels 1–2 and the validation step at levels 2–3. Levels 4–5
run unattended. Bare MCP clients without hook support (Cursor, Cline)
fall back to honoring the level via the agent's own behavior.

```yaml
name: my-scenario
automation_level: 2
physics:
  ...
```

## Hard rules for the agent

Pinned in [`CLAUDE.md`](../../CLAUDE.md):

- **Author the case from scratch** in `cases/work/<scenario-name>/`.
- **Do NOT copy from `cases/examples/<name>/baseline/`** — baselines are validation references, not templates.
- **Use `list_tutorials` / `read_tutorial_file`** to find OpenFOAM-shipped templates under `$FOAM_TUTORIALS`.
- **Adapt only what the scenario demands; let validation drive the rest.** Mesh resolution, schemes, URFs, turbulence model stay at the tutorial's value until a check fails.
- **Web access is allowed** for setup guidance (NASA TMR, OpenFOAM forum, vendor docs). Cite the URL in your tool-call narration.
- **Validate before declaring done.** Author `analysis/validate.py`, run it via `validation.run_analysis`, and let `compare_profiles` produce the verdict. Even with no reference data, run `check_convergence` and inspect residuals.
