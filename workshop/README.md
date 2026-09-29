# Workshop walkthrough: persistent knowledge, three ways

This is the hands-on part of the session. You will run one CFD benchmark
twice and watch the second run inherit what the first run learned, and you
will drive it three ways: with a frontier model, with a frontier model
directing a local model, and with a local model alone.

## 0. Setup (do this before the session)

**Windows.** Open **PowerShell as Administrator** and install WSL2 with
Ubuntu, then reboot:

```powershell
wsl --install -d Ubuntu-24.04
```

Open the **Ubuntu** app (it asks you to create a Linux username and
password on first launch). Everything below runs in that Ubuntu terminal.

**Linux (Ubuntu 22.04 / 24.04).** Open a terminal.

Then, in your Linux home directory (not under `/mnt/c`):

```bash
cd ~
git clone https://github.com/kalagotla/agentic-openfoam-fsu.git agentic-openfoam
cd agentic-openfoam
./setup.sh
```

**On the FSU cluster** instead of a laptop: same clone and `./setup.sh`,
from an interactive compute node — see [`hpc.md`](hpc.md).

`setup.sh` installs OpenFOAM v2412, the Python environment, Claude Code,
the Kilo CLI, Ollama, and a local model sized to your machine, then runs a
health check. It takes 10–20 minutes, most of it downloads. Re-running it
is safe; finished steps are skipped. If something fails, the last lines of
`setup.log` say why, and `./scripts/doctor.sh` re-runs just the checks.

Open a **new** terminal afterwards so the PATH changes apply.

### Sign in to the agents

| Agent | How to sign in |
|---|---|
| Claude Code | run `claude` once; sign in with a Claude Pro/Max account or an API key |
| Kilo (frontier models) | nothing needed for the free models (`kilo/kilo-auto/free` and the `:free` list in `/models`); `kilo auth login` for a Kilo account, or `export ANTHROPIC_API_KEY=...` to use your own key |
| Kilo (local model) | nothing — it talks to Ollama on your machine |

### Which local model did I get?

```bash
./scripts/local-model.sh --show
```

`setup.sh` chose it from your GPU memory (or RAM, without a GPU):

| Your machine | Model | Download |
|---|---|---|
| GPU with ≥ 14 GB, or ≥ 24 GB RAM without one | `gpt-oss:20b` | 13 GB |
| smaller GPU, or 12–24 GB RAM | `qwen3:8b` | 5 GB |
| less than that | `qwen3:4b` | 2.5 GB |

To use a different model, pass any Ollama tag, e.g.
`./scripts/local-model.sh qwen3:30b`. The agents always address it as
`cfd-local`, so nothing else changes.

## 1. The idea: knowledge that persists between runs

The `consultant` MCP server keeps a **corpus**: annotations on OpenFOAM
tutorials recording *why* a setup works: which solver swap, which mesh,
what broke and how it was fixed. The corpus starts empty. An entry is
*earned* by a validated run and then reused by every later run.

**Step 1 — Discover.** `cases/scenarios/lid-cavity.yaml`: 2-D lid-driven
cavity at Re = 400, validated against Ghia, Ghia & Shin (1982). The
consultant has nothing to cite, so the agent adapts the `icoFoam/cavity`
tutorial the hard way. It narrates each gap as `_uncited choice_`, usually
hits a coarse-mesh validation miss, and pauses for you to approve a
refinement. At the end it drafts a corpus entry from its own `REPORT.md`.
You review the draft and promote it.

**Step 2 — Reuse.** `cases/scenarios/lid-cavity-re1000.yaml`: same cavity,
Re = 1000. The agent calls the *same* consultant lookup that came back
empty in Step 1. This time it returns the entry you just promoted. The
agent applies it, cites it, and skips the rediscovery.

| | Step 1 (empty corpus) | Step 2 (entry promoted) |
|---|---|---|
| `get_tutorial_annotation` | `no_annotation` | returns the entry |
| setup choices in REPORT.md | `_uncited choice_` | cite `corpus/.../cavity.md` |
| coarse-mesh miss | discovered, paused, fixed | skipped |

The corpus is plain files in the repo, so it doesn't matter which model
earned it. An entry earned by a frontier model is reused by a local one.
That is the thread through the three loops below.

## 2. Run it

Keep a second terminal open on the audit trail while an agent works:

```bash
tail -f cases/work/lid-cavity/REPORT.md          # Step 1
tail -f cases/work/lid-cavity-re1000/REPORT.md   # Step 2
```

Between steps:

```bash
./scripts/workshop.sh status      # what the corpus holds, what has run
./scripts/workshop.sh promote     # review the Step 1 draft and promote it
./scripts/workshop.sh reset       # clear work cases, keep the corpus
./scripts/workshop.sh reset-all   # also forget the entry (back to Step 1)
```

### Loop A — frontier only (Claude Code)

```bash
claude
```
```
> Set up and run cases/scenarios/lid-cavity.yaml
```

At the validation pause, read the verdict in REPORT.md and reply (e.g.
"approved — refine the mesh"). When the run finishes:

```bash
./scripts/workshop.sh promote
```

then, in Claude Code, `/clear` and:

```
> Set up and run cases/scenarios/lid-cavity-re1000.yaml
```

The same loop works in Kilo: run `kilo`, keep the default `cfd` agent,
pick a frontier model with `/models`, and type the same prompts.

### Loop B — frontier + local (Kilo orchestrator)

```bash
kilo
```

Press **Tab** until the agent reads `cfd-orchestrator`, then choose a
frontier model with `/models` (a free `kilo/...:free` model works). Prompt:

```
Set up and run cases/scenarios/lid-cavity-re1000.yaml
```

The frontier model reads the scenario, looks up the corpus, makes and
narrates every decision, and judges the results. It has no tools that
change the case. Each hands-on step (copying dicts, meshing, solving,
running the analysis) goes to the `cfd-worker` subagent, which runs on
your local model. Kilo shows each delegated task and its report inline.
The long tool outputs stay on your machine, and the frontier model only
sees the summaries.

The split holds best with a strong frontier model (Claude, GPT, Gemini
Pro). Weaker free models sometimes lose patience and do a step
themselves. You'll see a `openfoam_*` call in the orchestrator's own
column instead of a delegated task. That's worth pointing out, not a
failure.

### Loop C — local only (Kilo)

```bash
kilo
```

Press **Tab** until the agent reads `cfd-local` (pinned to your Ollama
model). Prompt:

```
Set up and run cases/scenarios/lid-cavity-re1000.yaml
```

Run this **after** Step 1 has been promoted, so the local model inherits
the entry. That is the point: a frontier model discovered the setup once,
and a model small enough to run offline reuses it. Local models are
slower and clumsier with tools. If one stops mid-way, reply `continue`.

### A suggested session

| Time | Who drives | What |
|---|---|---|
| 15 min | Loop A, Claude Code | Step 1 — discover at Re = 400, promote the entry |
| 10 min | Loop C, local only | Step 2 — local model reuses the entry at Re = 1000 |
| 15 min | Loop B, frontier + local | Step 2 again, split across two models; compare REPORT.md |
| — | `reset-all` | start over, or try Step 1 local-only to see what the corpus saved you |

## 3. When things go wrong

| Symptom | Fix |
|---|---|
| `setup.sh` stops with an error | read the last lines of `setup.log`; re-run `./setup.sh` |
| `blockMesh: command not found` in your own shell | `of2412` (the agents source OpenFOAM themselves) |
| Kilo: agent says a tool is missing | `kilo mcp list` — all four servers should be `connected`; run `kilo` from the repo root |
| Kilo local agent: "connection refused" | Ollama is not running: `./scripts/local-model.sh --show`, then `./scripts/local-model.sh` to restart it |
| Local model stops or writes a tool call as text | reply `continue`; if it keeps failing, try `./scripts/local-model.sh qwen3:30b` (GPU ≥ 24 GB) or use Loop B |
| Step 2 did not cite the corpus | `./scripts/workshop.sh status` — the entry must be promoted (no `.draft.md`) |
| `prepare_case` refuses: directory exists | `./scripts/workshop.sh reset` |
| Doctor warns `mpirun hangs` | serial cases (all of today's) are unaffected |
