# Writing a plan a local model can execute

A local model (e.g. `muse-glimmer:30b`, `gpt-oss:20b`) cannot reliably plan an
OpenFOAM case on its own, but it executes a precise plan well. A frontier
model (or a person) writes the plan; `scripts/local-worker.sh <plan.md>` runs
it on the local model through Kilo's `cfd-local-plan` agent and reports the
verdict.

The plan holds the decisions; the local model only carries them out. So all
the knowledge in it must come from the usual sources of truth: the template
tutorial and a promoted corpus entry (see `CLAUDE.md`).

## Format

- A short header: execute exactly, one tool call per numbered step, run
  straight through, stop and report `reason`/`log_tail` on a failure.
- Numbered steps, each one tool call: the tool name as the agent sees it
  (`openfoam_copy_tutorial_dict`, `openfoam_run_solver`, …) followed by its
  arguments as a single JSON object on one line.
- Files with more than one line (the sampling function object, the
  validation script) are created with `write`: give the path and the full
  content in a fenced block.

## Rules that make a plan work on a small model

1. **Copy, never author dictionaries.** Use `openfoam_copy_tutorial_dict`
   with `replacements`; a small model rewriting a dictionary from memory is
   the most common failure.
2. **Check every replacement key against the tutorial file** with
   `openfoam_read_tutorial_file` before putting it in the plan. Each key
   must occur exactly once. Whitespace runs may differ (the tool matches
   `endTime 2000;` to `endTime         2000;`), nothing else may.
3. **Keep replacement values on one line.** For a multi-line insertion,
   `write` the text to its own file and insert a one-line `#include
   "<file>"` (e.g. a sampling function object included into the
   `functions` block of `controlDict`).
4. **Write the validation script into the plan in full.** Use
   `validation_mcp.analysis` (`latest_set`, `read_set`, `emit`) and
   `validation_mcp.tools` (`read_reference`, `compare_profiles`).
5. **Say where to narrate**: a `openfoam_record_step` after setup, after
   the solve, and after validation (citing the corpus entry), then
   `openfoam_finalize_report`.
6. **Use the case's real paths** (`cases/work/<name>`, the scenario's
   reference dataset names); never placeholders.

A worked example for one case is in `workshop/prompts/local-step2-targeted.md`
(for people; agents setting up a case should not read `workshop/`).
