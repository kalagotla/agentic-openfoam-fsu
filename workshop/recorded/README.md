# Recorded runs

Real, unedited runs of the workshop demos: each agent's own `REPORT.md` and
validation plots. Compare them with your runs, or read them when a model is
slow or unavailable.

## The ladder (Oct 1)

Step 1 by Claude Code earned the corpus entry
([report](audited-claude-step1/REPORT.md), [entry](audited-claude-step1/corpus-entry.md));
Step 2 (Re = 1000) was then run down the ladder with that entry promoted.
Unedited agent reports and plots; local model `muse-glimmer:30b` (Meta) on
an RTX 5090, the frontier models Claude Code (Opus) and the free Nemotron 3
Ultra through Kilo. Each scenario was copied with `automation_level: 5`.

| Rung | Setup | Result | Report |
|---|---|---|---|
| 0 | Step 1, Claude Code with the GCI requirement ([entry with "Validated setup"](ladder/step1-claude-gci/corpus-entry.md)) | **PASS** on 40×40 after a convergence and a validation miss; GCI on 20/40/80 (p ≈ 2, GCI ≈ 2 %); 5.8 min, $2.46 | [step1-claude-gci](ladder/step1-claude-gci/REPORT.md) |
| — | Nemotron alone, **no** corpus entry | borderline **PASS** (u 4.4 %, v 4.3 %) after jumping to 128×128; 8 solver runs, 16 min | [nemotron-no-knowledge](ladder/nemotron-no-knowledge/REPORT.md) |
| 1 | Claude Code alone | **PASS** (u 0.47%, v 0.18%), applied all three lessons of the entry, cited it 8×, 0 retries; 2.5 min, $1.23 | [rung1-claude-alone](ladder/rung1-claude-alone/REPORT.md) |
| 2 | Claude writes a plan ([as written](ladder/rung2-claude-plans-local/plan-written-by-claude.md)) · local Muse executes it | **PASS**, 0 failed local tool calls; 5.7 min, $1.15 | [rung2-claude-plans-local](ladder/rung2-claude-plans-local/REPORT.md) |
| 3 | Nemotron 3 Ultra alone (Kilo `cfd`) | **PASS** (u 0.59%, v 0.09%) on 80×80, but 23 min: 13 solver runs, 24 dictionaries written from memory, narration only at the end; 1 nudge | [rung3-nemotron-alone](ladder/rung3-nemotron-alone/REPORT.md) |
| 4 | Nemotron orchestrates · local Muse worker (Kilo `cfd-orchestrator`) | **PASS** (u 0.70%, v 0.17%), 7 delegated tasks; 17 min | [rung4-nemotron-orchestrates-local](ladder/rung4-nemotron-orchestrates-local/REPORT.md) |
| 5a | Muse alone, open-ended prompt (Kilo `cfd-local`) | **REVIEW**: finished on its own (1 nudge) but stayed on the tutorial's 20×20 and its validation found no sampled data; 8.8 min | [rung5a-local-open](ladder/rung5a-local-open/REPORT.md) |
| 5b | Muse alone, [targeted prompt](../prompts/local-step2-targeted.md) | **PASS** (u 0.64%, v 0.16%); 66 s | [rung5b-local-targeted](ladder/rung5b-local-targeted/REPORT.md) |

Across repeated tries: the targeted prompt passed 3/3 on Muse and about 2/3
on gpt-oss:20b (which garbles some tool arguments); Gemma 4 12B could not
follow it. Nemotron behaved the same in Kilo, the repo's own harness and
Hermes (fine grid up front, 12–22 min, often no verdict), so the model, not
the harness, limits rungs 3–4.

## Usage levels, measured (Oct 2)

Expert / guided / prompt inputs for the same cavity, two Claude Code runs
each: the agent's share of setup choices goes 0–1 → 4–5 → 6, while
consultant tool calls stay flat. See [spec-detail/](spec-detail/README.md).

