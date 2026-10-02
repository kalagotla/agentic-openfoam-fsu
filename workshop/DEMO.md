# Presenter run sheet — FSU DC-QC, Oct 2, 2:00–4:00 PM

Three demos on one benchmark: a **frontier** model (Claude Code), a
**mid-sized open** model (Nemotron 3 Ultra, free, through Kilo) and a
**local** model (Muse Glimmer 30B on your GPU), all sharing one corpus. The
long runs (Nemotron, 15–25 min) go in a second terminal while you talk.
Every run has a recorded fallback in [`recorded/ladder/`](recorded/ladder/).

## Before 2:00

```bash
cd ~/agentic-openfoam            # your clone
./scripts/workshop.sh reset-all  # empty corpus, no work cases
./scripts/doctor.sh              # all green
./scripts/local-model.sh --show  # cfd-local -> muse-glimmer:30b (laptop GPU, or after hpc-gpu.sh use)
claude --version && kilo --version
```

Open three terminals in the repo: **T1** demos, **T2** background runs,
**T3** `tail -f` on the report being discussed.

## Timeline

| Time | What | Commands |
|---|---|---|
| 2:00 | **Clone and set up** (attendees). Laptop: `git clone … && ./setup.sh`; cluster: [`hpc.md`](hpc.md) §1–2 | — |
| 2:05 | **Start the no-knowledge run** in T2 (corpus is still empty) | `./scripts/workshop.sh fork lid-cavity-re1000 nemotron --auto`<br>`kilo run --agent cfd --auto "Set up and run cases/scenarios/lid-cavity-re1000--nemotron.yaml"` |
| 2:05 | **Slides**, Parts 1–2, while setup and the T2 run go | — |
| 2:40 | **Demo 1 · frontier, Step 1.** Claude discovers at Re = 400: tutorial mesh, validation miss, grid study, GCI, REPORT.md, corpus draft. Approve at the validation pause | T1: `claude` → `Set up and run cases/scenarios/lid-cavity.yaml`<br>T3: `tail -f cases/work/lid-cavity/REPORT.md` |
| 2:50 | **Review and promote** the draft (point at "Validated setup (start here)") | `./scripts/workshop.sh promote` |
| 2:55 | **Demo 1 · frontier, Step 2.** Claude at Re = 1000 cites the entry and goes straight to the validated grid | T1: `/clear` → `Set up and run cases/scenarios/lid-cavity-re1000.yaml` |
| 3:05 | **Demo 2 · mid-size.** Show T2's result (no knowledge: slow, trial and error). Then start two runs **with** the knowledge: | |
| | T2: Nemotron alone, with the entry | `./scripts/workshop.sh fork lid-cavity-re1000 nemo-k --auto`<br>`kilo run --agent cfd --auto "Set up and run cases/scenarios/lid-cavity-re1000--nemo-k.yaml"` |
| | T4: Nemotron directs the local model (token saving) | `./scripts/workshop.sh fork lid-cavity-re1000 orch --auto`<br>`kilo run --agent cfd-orchestrator --auto "Set up and run cases/scenarios/lid-cavity-re1000--orch.yaml"` |
| 3:10 | **Demo 3 · local.** Muse with the knowledge, open-ended, then the targeted prompt (~1 min, PASS) | T1: `./scripts/workshop.sh fork lid-cavity-re1000 local --auto` → `kilo` (Tab to `cfd-local`) → `Set up and run cases/scenarios/lid-cavity-re1000--local.yaml`<br>then `kilo run --agent cfd-local --auto "$(sed -n '/^---$/,$p' workshop/prompts/local-step2-targeted.md \| sed 1d)"` |
| 3:25 | **Back to demo 2.** Compare the T2/T4 runs; show the token split | `python3 scripts/session-tokens.py <T2 session> <T4 session>` (session ids: `kilo session list`) |
| 3:35 | **Wrap-up**: the ladder slide (frontier → frontier + local → open model → open + local → local; the prompt buys back capability) and Q&A | — |

Optional, if time allows: **Claude planning for the local model** (rung 2):
`claude` → paste [`prompts/claude-drives-local.md`](prompts/claude-drives-local.md) (~6 min, PASS).

## What to expect (from the Oct 1–2 rehearsals)

| Run | Typical result |
|---|---|
| Claude, Step 1 | tutorial 20×20 misses Ghia's v profile (5.9 % > 5 %) → refine 40×40, 80×80 → PASS, GCI (apparent order ≈ 2, fine-grid GCI ≈ 2 %), entry drafted with a "Validated setup" recipe; 5.8 min, $2.46 |
| Claude, Step 2 | cites the entry, 80×80 from the start, PASS; ~3 min, ~$1.25 |
| Nemotron, Step 2, no knowledge | skips the tutorial mesh for 128×128, 8 solver runs, 16 min; a borderline PASS (u 4.4 %, v 4.3 % vs 5 %). With the entry: 80×80, u 0.6 %, v 0.1 % |
| Nemotron, Step 2, with knowledge | PASS, but 15–23 min |
| Nemotron directs Muse | PASS in ~17 min; ~90% fewer frontier tokens (9.5 M → 0.8 M) |
| Muse, open-ended, with knowledge | finishes on its own in ~5 min, fixes setup errors itself, but its validation script never produces valid numbers; it narrates a pass anyway and the banner shows REVIEW ("not backed by the validation metrics"): a teaching moment |
| Muse, targeted prompt | PASS in ~1 min, no failed tool calls |

## If something goes wrong

- A free-gateway timeout ("Upstream idle timeout"): `kilo run --session <id> --agent <agent> --auto "continue"`.
- A local model stops early: type `continue` (or re-run the targeted prompt; it starts its own case folder).
- Out of time: open the matching report in [`recorded/ladder/`](recorded/ladder/).
- Start a demo over without touching the corpus: `./scripts/workshop.sh reset`
  (clears `cases/work/lid-cavity*`, including forks).
- Show a run without the knowledge after promoting: `./scripts/workshop.sh demote`, run, then `promote` again.
