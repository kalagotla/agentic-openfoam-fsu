# Recorded runs (GPU fallback)

> **Read this first.** The runs in the first table were recorded before an
> audit that removed answer hints from the scenarios and Kilo prompts (the
> Step 2 scenario spelled out Step 1's lessons, and the `cfd-local` prompt
> carried case-specific fixes). The second table is the re-test after it.

If the live GPU is not available, show these instead. They are the
two-step demo recorded on Oct 1, 2026, unedited: the agents' own
`REPORT.md` audit trails and validation plots. The local model was
`gpt-oss:20b` on an RTX 5090 (32 GB), the same model and settings
`setup.sh` installs. Each scenario was copied with `automation_level: 5`
so it ran without review pauses.

| Run | Agent and models | Result | Time |
|---|---|---|---|
| [Step 1, Loop A](loopA-step1/REPORT.md) | Claude Code (Opus) | **PASS** vs Ghia at Re = 400 after a coarse-mesh miss and a grid study (20×20 → 40×40 → 80×80); u L2 0.0022, v L2 0.035; 14 decisions, 2 retries; wrote the corpus draft ([as written](step1-corpus-entry.md)) | 4.75 min, $2.17 |
| *promote* | `scripts/workshop.sh promote` | draft becomes `corpus/incompressible/icoFoam/cavity/cavity.md` | — |
| [Step 2, Loop B](loopB-step2/REPORT.md) | Kilo `cfd-orchestrator`: Nemotron 3 Ultra (free) + `cfd-worker` on gpt-oss:20b (GPU) | **PASS** vs Ghia at Re = 1000; u L2 0.0065, v L2 0.0016; cited the corpus entry 10×, went straight to the 80×80 grid Step 1 had found; **0 retries**, no nudges | 25 min, free |
| [Step 2, Loop C](loopC-step2/REPORT.md) | Kilo `cfd-local`: gpt-oss:20b alone (GPU) | found the corpus entry and followed its template, meshed cleanly, then broke its own `simpleFoam` dictionaries and drifted to `pimpleFoam`; **no verdict** after 8 `continue` nudges | 5.5 min, free |

## What to point out

- **The knowledge carried over.** Step 1 needed a grid study and two
  retries to reach a passing mesh. Step 2 read that result from the
  corpus and used the 80×80 grid from the start: 0 retries, and every
  decision cites the entry.
- **The split in Loop B was partial.** The orchestrator delegated three
  tasks to the local worker. The worker meshed and ran checkMesh
  correctly, but it returned "tutorials not available" for the copy task
  and an empty report for the dictionary task, so the orchestrator did
  those itself. A stronger frontier model (Claude, GPT) holds the split
  better. This one is free and needs no account.
- **Local-only did not finish**, as in every rehearsal. It used the
  corpus correctly, which is the point of Step 2, but it cannot yet carry
  a full case alone. Loop B, where a frontier model keeps it on small
  tasks, is how a local model is useful today.
- The free frontier gateway timed out ("Upstream idle timeout") in two
  earlier attempts at Loop B. Those runs are not shown; the one above is
  the first that did not hit a timeout.

## Re-test after the instruction audit (Oct 1, evening)

Same scenarios, scenario hints removed, Kilo prompts tightened (speed
budgets, step caps). Kilo used the free Nemotron 3 Ultra; the local model
was gpt-oss:20b on the RTX 5090.

| Run | Result | Time |
|---|---|---|
| [Step 1, Claude Code](audited-claude-step1/REPORT.md) | **PASS**: started on the tutorial's 20×20 mesh, recorded the v-centerline miss (5.9% > 5%), refined 40×40 → 80×80 (u 0.17%, v 4.64%); 12 narrated steps, 3 retries; a rich [corpus entry](audited-claude-step1/corpus-entry.md) | 4.9 min, $2.30 |
| Step 1, Kilo `cfd` | PASS on the 20×20 tutorial mesh (v 4.3%: borderline, its sampling differed from Claude's); 7 steps; a thin corpus entry | 12 min |
| Step 2, Kilo `cfd` (frontier only), Kilo's entry | 20×20 missed, refined to 60×60, **PASS**; looked the entry up but cited it 0× | 15.5 min |
| Step 2, Kilo `cfd-orchestrator`, Kilo's entry | cited the entry 12×, stayed on its 20×20 advice, **FAIL**, then hit the step cap | 17.5 min |
| Step 2, Kilo `cfd-orchestrator`, Claude's entry | went straight to Claude's 80×80 and converged, but did most steps itself and hit the 90-step cap: **no verdict** | 20 min |
| Step 2, Kilo `cfd-local` | repaired its own dict headers, found pRefCell itself; **no verdict** after 8 nudges | 6 min |

What this says for the session: run **Step 1 with Claude Code** (or a
strong model in Copilot/Codex) so the entry is worth reusing, and run
**Step 2 with a strong frontier agent** too for a reliable live demo. Show
the Kilo frontier + local and local-only loops as experiments, and point
out that a weak Step 1 entry (Kilo's "20×20 is enough") carried straight
into a failed Step 2: the reason a human reviews before promoting.
