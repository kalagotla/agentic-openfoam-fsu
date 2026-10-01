# `corpus/` — the consultant's knowledge layer

The corpus is what the consultant server reads *before* a run to reason
about a tutorial template, and what a finished run writes *back* to so
the next run starts from hard-won experience instead of from scratch.

Each entry is an annotation on a `$FOAM_TUTORIALS` tutorial: the missing
reasoning layer the tutorials don't ship — *why* this scheme, *what*
alternatives exist, *when* the choice would be wrong, and what mesh /
settings actually validated against reference data.

The directory mirrors the OpenFOAM tutorial tree. An entry at
`corpus/incompressible/icoFoam/cavity/cavity.md` documents the tutorial
at `$FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity/`.

## An empty corpus is a valid state

The corpus ships empty. That is by design, not an omission: an entry is
*earned* by a completed, validated run, so a missing entry honestly
signals "no run has yet established the reasoning for this tutorial."

When the agent picks a tutorial as a structural template, it calls
`consultant.get_tutorial_annotation` with the tutorial path:

- **Hit** — the returned body feeds the consultant fields on
  `openfoam.record_step`, so the REPORT.md entry carries cited rationale
  grounded in a prior validated run.
- **Miss** — `record_step` renders the gap as `_uncited choice_`. That
  gap is the signal an entry needs to be authored, not a failure to
  paper over with invented rationale.

## How an entry gets earned (the build-from-runs loop)

This is the loop the corpus is built around:

1. **Run the case.** The agent adopts a tutorial template and runs it
   with the tutorial's own mesh and settings. Each decision is narrated
   to `<case>/REPORT.md`.
2. **Let validation drive every change.** When a check or the validation
   misses, the miss — not anticipation — motivates the next change (for
   a mesh, a grid-convergence-style sequence), each recorded with the
   residual or error that justified it, until the run lands inside
   tolerance.
3. **Draft an entry from the run.** Call
   `consultant.draft_annotation_from_report(case_path, tutorial_path, ...)`.
   It parses the per-step decision entries in REPORT.md — the full
   decision / why / alternatives / when-it-breaks with citations — into
   the decision table, capturing the mesh that converged, the schemes
   that held, and the validation verdict. The agent (which ran the case)
   fills the frontmatter it knows via the optional args — `solver`,
   `physics`, `geometry`, `references`, and *proposed* `suitable_for` /
   `not_suitable_for` — so the draft arrives near-complete rather than as
   a blank scaffold. Anything not supplied stays a `<fill in>` placeholder.
4. **Review, confirm, promote.** Your job is judgment, not blank-filling:
   confirm the agent's `suitable_for` / `not_suitable_for` proposals,
   generalise any remaining scenario-specific language to
   tutorial-template language (the regime class rather than the run's
   exact parameter values), and add experience-based commentary in
   *Notes*. Promote by renaming `<name>.draft.md` → `<name>.md`. The
   `.draft.md` suffix kept it out of `get_tutorial_annotation` while you
   edited; the rename makes it live, and the next run that picks this
   tutorial inherits the certainty this run earned.

`.draft.md` files are gitignored — they are a staging area for human
review, not corpus content.

## Format

YAML frontmatter for machine-readable metadata, then a markdown table
of key choices, then a short freeform "Notes" section for nuance that
doesn't fit a cell. The table columns are the consultant schema:

| Choice | Decision | Why | Alternatives | When it breaks |

One row per key choice the tutorial encodes (solver, mesh strategy, BC
types, turbulence model, schemes, …). Cite references inline where
possible — paper citations, OpenFOAM User Guide section numbers.

## Template

Copy this into a new file at `corpus/<solver>/<case>.md` (mirroring the
tutorial's path under `$FOAM_TUTORIALS`):

```markdown
---
tutorial_path: <path under $FOAM_TUTORIALS, e.g. incompressible/simpleFoam/pitzDaily>
solver: <solver name>
physics: <one-line: regime, steady/transient, turbulence, Re or relevant dimensionless number>
geometry: <one-line geometry summary>
suitable_for_template:
  - <when this tutorial is a good structural starting point>
not_suitable_for:
  - <when this tutorial is the wrong choice>
references:
  - "<paper or doc citation>"
---

# `<tutorial_path>`

<One-paragraph framing: what this tutorial is and what role it plays as a template.>

| Choice | Decision | Why | Alternatives | When it breaks |
|---|---|---|---|---|
| <e.g. Solver> | <what the tutorial uses> | <one-line rationale + citation> | <comma-separated alternatives with one-line each> | <one-line regime / assumption where this fails> |
| <e.g. Mesh> | ... | ... | ... | ... |
| <e.g. BCs> | ... | ... | ... | ... |

## Notes

<Optional freeform paragraph for nuance the table can't hold —
edge cases, scenario-specific guidance, links to related entries.>
```

Authoring an entry from scratch (no agent run) works too — just start
with the template above. The draft tool is a convenience, not a
requirement. Cite every rationale; uncited *cells* render as
`_uncited choice_`, and that is fine — a missing annotation is honest.

A claimed *fact*, though, is different from a missing annotation: a number,
a threshold, or a regime boundary must be **cited or derived from first
principles, never asserted from memory**. A citation must resolve to a source
in [`references/`](references/) — when you use a new source, add it there.
`consultant.flag_uncited_claims` audits a finished entry (or a run's REPORT.md)
for unsourced assertions and for citations that don't resolve to the library.
