# Workshop walkthrough: persistent knowledge, down the ladder

This is the hands-on part of the session. You will run one CFD benchmark
twice and watch the second run inherit what the first run learned. Then you
will drive the second run down a ladder of setups: a frontier model alone, a
frontier model planning for a local model, a large open model, and a local
model alone, with an open-ended prompt and then a targeted one. The ladder
shows how much the model matters, and how much the prompt does.

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
from an interactive compute node — see [`hpc.md`](hpc.md). Setup there
takes about a minute (the large files are pre-staged), but the workshop
accounts are CPU-only, so on the cluster you run the frontier loop (A) and
watch the speaker's GPU demo for the local-model loops. On a laptop setup
downloads ~15 GB (fast on FSU Wi-Fi), and every loop runs, at the speed of
your own GPU.

`setup.sh` installs OpenFOAM v2412, the Python environment, four coding
agents (Claude Code, GitHub Copilot CLI, Codex CLI and the Kilo CLI), Ollama,
and a local model sized to your machine, then runs a health check. To
install only some agents, list them: `./setup.sh --agents copilot,kilo`
(choose from `claude`, `kilo`, `codex`, `copilot`; `--no-codex` etc. drop
one). Every agent comes pre-wired to the four MCP servers. It takes 10–20 minutes, most of it downloads. Re-running it
is safe; finished steps are skipped. If something fails, the last lines of
`setup.log` say why, and `./scripts/doctor.sh` re-runs just the checks.

Open a **new** terminal afterwards so the PATH changes apply.

### Pick an agent and sign in

You need **one** of these. All four drive the same MCP servers with the
same prompts; the difference is whose models you use and who pays.

| Agent | Command | Cost | How to sign in |
|---|---|---|---|
| **GitHub Copilot CLI** | `copilot` | **free for students**: Copilot Pro through [GitHub Education](https://education.github.com/pack) (verify your student status once; approval can take a few days, so do it before the workshop) | run `copilot`, type `/login`, and follow the device code with your GitHub account. Pick a model with `/model` |
| Claude Code | `claude` | Claude Pro/Max or API key | see below |
| Codex CLI | `codex` | ChatGPT plan or OpenAI API key | run `codex` and choose "Sign in with ChatGPT"; on the cluster, `codex login --device-auth` |
| Kilo CLI | `kilo` | free models built in; local models free | see below |

No account at all? Kilo's free models and the local model need none.

| Agent | Details |
|---|---|
| Claude Code | run `claude` once in the repo; sign in with a Claude Pro/Max account or an API key, and **accept the "trust this folder" prompt** (until you do, the repo's MCP servers and pre-approved tools stay off) |
| Kilo (frontier models) | nothing needed for the free models: pick a US-developed one in `/models`, e.g. `kilo/nvidia/nemotron-3-ultra-550b-a55b:free` (NVIDIA) or `kilo/poolside/laguna-s-2.1:free` (Poolside). Avoid `kilo/kilo-auto/free`, which may route to non-US models; `kilo auth login` for a Kilo account, or `export ANTHROPIC_API_KEY=...` to use your own key |
| Kilo (local model) | nothing — it talks to Ollama on your machine |

### Which local model did I get?

```bash
./scripts/local-model.sh --show
```

`setup.sh` chose it from your GPU memory (or RAM, without a GPU):

| Your machine | Model | Download |
|---|---|---|
| GPU with ≥ 20 GB | `muse-glimmer:30b` (Meta) | 18 GB |
| GPU with ≥ 14 GB, or ≥ 24 GB RAM without one | `gpt-oss:20b` (OpenAI) | 14 GB |
| smaller GPU, or 12–24 GB RAM | `gemma4:12b` (Google) | 8 GB |
| less than that | `nemotron-3-nano:4b` (NVIDIA) | 2.8 GB |

All are US-developed open models. In our tests `muse-glimmer:30b` was by far
the most reliable at tool calls (it needs a recent Ollama; `setup.sh`
upgrades an old one). `gpt-oss:20b` works but garbles a fraction of its
tool arguments; the smaller two cannot carry a run. Switch with
`./scripts/local-model.sh <model>`; the agents always address the model as
`cfd-local`.

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
That is the thread through the ladder below.

## 2. Run it: the ladder

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

**Step 1 is always run with a strong frontier agent** (Claude Code, or a
strong model in Copilot/Codex): it writes the corpus entry everything after
it reuses, and a weak entry carries straight into a failed Step 2. Then run
Step 2 down the ladder, from the most capable setup to the least, and watch
two things change: who does the work, and how much the prompt has to say.

| Rung | Who plans · who executes | How to run Step 2 | Measured (Oct 1) |
|---|---|---|---|
| 1 | Frontier alone | `claude` → `Set up and run cases/scenarios/lid-cavity-re1000.yaml` | PASS, cited the entry 8×, 0 retries, 2.5 min, $1.23 |
| 2 | Frontier plans · local executes | `claude` → paste [`prompts/claude-drives-local.md`](prompts/claude-drives-local.md) | PASS, 0 failed local calls, 5.7 min, $1.15 |
| 3 | Large open model alone (free Nemotron 3 Ultra) | `kilo` (agent `cfd`) → the Step 2 prompt | PASS, but 15–23 min: many solver re-runs, dictionaries written from memory |
| 4 | Large open model · local executes | `kilo` (agent `cfd-orchestrator`) → the Step 2 prompt | PASS, 7 delegated tasks, 17 min (with gpt-oss as the worker it never reached a verdict) |
| 5a | Local alone, open-ended | `kilo` (agent `cfd-local`) → the Step 2 prompt | finishes, but misses the entry's lessons: REVIEW, 7–9 min |
| 5b | Local alone, targeted prompt | `kilo` (agent `cfd-local`) → paste [`prompts/local-step2-targeted.md`](prompts/local-step2-targeted.md) | PASS 3/3, ~75 s, 0 nudges |

What it shows:

- **Capability falls down the ladder, and the prompt can buy it back.** The
  same local model goes from REVIEW (open-ended) to a clean PASS in about a
  minute when the prompt is an exact plan (5a → 5b).
- **Frontier models self-heal; local models follow.** A frontier model reads
  the corpus, checks tutorial files, notices its own mistakes and plans. A
  local model does none of that reliably, but executes a precise plan well.
  Rung 2 is the practical combination: the frontier model writes the plan
  (`docs/local-plan-format.md`), the local model does the work, and the
  frontier model judges the result, at about the same cost as doing it alone
  ($1.15 vs $1.23), with the hands-on work and tool output on your machine.
- **The model matters more than the harness.** Nemotron behaved the same in
  Kilo, in the repo's own harness and in Hermes: it often skipped the
  tutorial's mesh for a fine grid and took 12–20 minutes per run through the
  free gateway (~14 s per model call).
- **The corpus is only as good as the run that earned it.** When Step 1 was
  run by Nemotron, its thin entry ("20×20 is enough") sent Step 2 to a FAIL.
  That is why a person reviews before promoting.

Recorded runs of every rung are in [`recorded/`](recorded/) as a fallback.

### Running the rungs

- **Rung 1** works in any agent: Claude Code, Copilot (`/login`), Codex.
  At the validation pause, read the verdict in REPORT.md and reply.
- **Rung 2** needs the local model running (`./scripts/local-model.sh
  --show`) and Kilo installed: the frontier agent writes
  `cases/work/plan-lid-cavity-re1000.md` and runs
  `scripts/local-worker.sh` on it. On the cluster, run
  `scripts/hpc-gpu.sh use` first so the local model is on the GPU.
- **Rungs 3–5** run in Kilo: `kilo`, then **Tab** to the agent. `cfd` and
  `cfd-orchestrator` use the free Nemotron by default (`/models` to
  change); `cfd-local` uses your local model. Free gateways sometimes time
  out; type `continue`.
- **Rung 5b** can also use the lean `cfd-local-plan` agent, which only
  executes plans.

### The session (FSU DC-QC, Oct 2, 2:00–4:00 PM)

Three demos on one benchmark, sharing one corpus: a **frontier** model
(Claude Code), a **mid-sized open** model (Nemotron 3 Ultra, free, in Kilo)
and a **local** model (Muse Glimmer 30B). The presenter's minute-by-minute
run sheet, with every command, is [`DEMO.md`](DEMO.md).

| Time | What |
|---|---|
| 2:00 | Clone and `./setup.sh` (laptop or cluster); setup runs during the slides |
| 2:05 | Slides. A Nemotron run *without* knowledge starts in the background |
| 2:40 | Frontier: Claude, Step 1 (grid study, GCI, REPORT.md, corpus draft) → promote |
| 2:55 | Frontier: Claude, Step 2 at Re = 1000 with the entry |
| 3:05 | Mid-size: the no-knowledge result; Nemotron with the entry, and Nemotron directing the local model (token savings) start in the background |
| 3:10 | Local: Muse with the entry, open-ended, then the targeted prompt |
| 3:25 | Mid-size results: with vs without knowledge, frontier tokens alone vs directing the local model |
| 3:35 | The ladder, wrap-up, Q&A |

Run several agents side by side with `./scripts/workshop.sh fork
<scenario> <tag> --auto` (its own case folder, no pauses). Show token use
with `python3 scripts/session-tokens.py <session> [<session>]`.

## 3. When things go wrong

| Symptom | Fix |
|---|---|
| `setup.sh` stops with an error | read the last lines of `setup.log`; re-run `./setup.sh` |
| `blockMesh: command not found` in your own shell | `of2412` (the agents source OpenFOAM themselves) |
| Kilo: agent says a tool is missing | `kilo mcp list` — all four servers should be `connected`; run `kilo` from the repo root |
| Kilo local agent: "connection refused" | Ollama is not running: `./scripts/local-model.sh --show`, then `./scripts/local-model.sh` to restart it |
| Local model stops or writes a tool call as text | reply `continue`; if it keeps failing, try `./scripts/local-model.sh muse-glimmer:30b` (GPU ≥ 24 GB) or use Loop B |
| Step 2 did not cite the corpus | `./scripts/workshop.sh status` — the entry must be promoted (no `.draft.md`) |
| `prepare_case` refuses: directory exists | `./scripts/workshop.sh reset` |
| `mpirun` hangs on WSL (doctor warning, or your own parallel runs) | Open MPI's hwloc probes X display `:1` over `localhost:6001`, which never answers under WSL's mirrored networking. The agents' tools already set the fix; for your own shell: `export HWLOC_COMPONENTS=-gl` (setup adds it to `~/.bashrc`) |
