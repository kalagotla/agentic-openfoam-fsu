# Agentic CFD with OpenFOAM

Workshop materials for **Accelerating CFD Simulations with Agentic AI and OpenFOAM** — FSU DC-QC workshop edition (first given at AIAA Aviation 2026, San Diego).

Four MCP servers (`openfoam`, `validation`, `consultant`, `research_assistant`) that let any tool-using LLM drive OpenFOAM end-to-end: set up a case, mesh, solve, validate against published reference data, and narrate every decision to `<case>/REPORT.md`.

## Architecture

```
             ┌──────────────────────┐
             │   AI agent (LLM)     │
             │ Claude, GPT, Qwen…   │
             └───────────┬──────────┘
                         │  MCP protocol
    ┌───────────┬────────┴────┬───────────────┐
    ▼           ▼             ▼               ▼
┌────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐
│openfoam│ │validation│ │ consultant │ │  research_   │
│        │ │          │ │            │ │   assistant  │
│ACTIONS │ │ COMPARE  │ │ REASONING  │ │ CUSTOM CODE  │
│        │ │          │ │            │ │              │
│mesh +  │ │profiles  │ │ checkMesh  │ │ wmake build  │
│solve + │ │ vs ref   │ │ verdicts + │ │  loop +      │
│dict I/O│ │  data    │ │ tutorial   │ │ $FOAM_SRC    │
│+ live  │ │+ converg.│ │ annotation │ │  examples +  │
│REPORT  │ │  classifr│ │  lookup    │ │ user-dir     │
│        │ │          │ │            │ │  layout      │
│17 tools│ │ 6 tools  │ │  7 tools   │ │   3 tools    │
└───┬────┘ └────┬─────┘ └─────┬──────┘ └──────┬───────┘
    ▼           ▼             ▼               ▼
 OpenFOAM   cases/*/      tutorial_     $WM_PROJECT_
 CLI +      reference/    corpus/       USER_DIR +
 snappyHex  (Ghia,        + cited       $FOAM_SRC /
 + Par      Armaly,       thresholds    $FOAM_APP
            XFOIL)
```

## Repo layout

```
.
├── README.md / CLAUDE.md / AGENTS.md / LICENSE / .mcp.json / kilo.jsonc
├── setup.sh                  # one-command install (WSL2 / Ubuntu)
├── workshop/                 # the hands-on walkthrough
├── servers/                  # four MCP servers
│   ├── openfoam/             # actions: mesh, solve, dict I/O, record_step
│   ├── validation/           # comparison primitives + reference-data library
│   ├── consultant/           # CFD-domain reasoning: mesh-quality verdicts +
│   │                         #   tutorial-annotation lookup
│   └── research_assistant/   # wmake build loop + $FOAM_SRC examples
├── cases/
│   ├── lid-cavity/           # workshop focus — cavity vs Ghia 1982
│   ├── scenarios/            # YAML problem statements the agent reads
│   ├── examples/             # additional cases (table below)
│   └── work/                 # agent-authored cases (gitignored)
├── corpus/                   # consultant's knowledge layer: "why this choice"
│   │                         #   annotations earned from validated runs; mirrors
│   │                         #   $FOAM_TUTORIALS structure (ships empty)
│   └── references/           # offline literature library: manifest + fetch script
│       └── manifest.json     #   for every cited source (cache/ gitignored)
├── docs/                     # architecture, setup-wsl, runtime-options, …
└── scripts/                  # run_agent.py harness, local-model.sh, doctor.sh,
                              #   workshop.sh, eval/ (benchmark harness)
```

## Install — one script, two places to run it

| Where | How | Guide |
|---|---|---|
| **Your laptop** — Windows (WSL2) or Ubuntu 22.04 / 24.04 | `./setup.sh` (uses sudo for system packages) | below |
| **FSU cluster (RCC)** — interactive compute node | the same `./setup.sh`; it detects the cluster and installs without sudo | [`workshop/hpc.md`](workshop/hpc.md) |

No Docker, no manual OpenFOAM build.

### Laptop (WSL2 / Ubuntu)

**Windows first:** in an **admin PowerShell**, `wsl --install -d Ubuntu-24.04`,
reboot, and open the **Ubuntu** app. Run everything below in that terminal,
from your Linux home, not `/mnt/c`.

```bash
cd ~
git clone https://github.com/kalagotla/agentic-openfoam-fsu.git agentic-openfoam
cd agentic-openfoam
./setup.sh            # ~10–20 min, mostly downloads; safe to re-run
```

`setup.sh` installs, skipping anything already present:

| | What |
|---|---|
| OpenFOAM v2412 | ESI apt package, plus an `of2412` alias |
| Python | `uv` and the four MCP servers' environment |
| ParaView + Xvfb | headless field renders for `export_field_image` |
| Agents | Claude Code (`claude`) and the Kilo CLI (`kilo`) |
| Local model | Ollama plus a model chosen for your GPU/RAM, exposed to the agents as `cfd-local` |

It ends with `./scripts/doctor.sh`, which meshes and solves a tutorial,
checks that Kilo sees all four MCP servers, and checks the local model.
Options: `--model <ollama-tag>`, `--no-local`, `--no-claude`, `--no-kilo`.
Change the local model later with `./scripts/local-model.sh <tag>`.

### FSU cluster (RCC)

Start an interactive job **in a login shell** (compute nodes reach the
internet only through RCC's web proxy, which login shells load), then clone
and run the same script:

```bash
srun -A genacc_q -p genacc_q -c 8 --mem=32G -t 3:00:00 --pty bash -l     # CPU node
# local models need a GPU node instead, e.g.:
# srun -A backfill2 -p backfill2 --gres=gpu:1 -c 8 --mem=48G -t 3:00:00 --pty bash -l
git clone https://github.com/kalagotla/agentic-openfoam-fsu.git agentic-openfoam
cd agentic-openfoam && ./setup.sh
```

On the cluster there is no sudo and no apt. OpenFOAM v2412 comes from one
shared, portable Apptainer image (the cluster's own modules stop at
OpenFOAM 7 since the AlmaLinux 9 upgrade), and Node, the agents and Ollama
unpack under `~/.local`. Use the account/partition your instructor gives
you. Details, GPU notes and the instructor's one-time image build are in
[`workshop/hpc.md`](workshop/hpc.md).

## Run

Open a new terminal in the repo, then pick an agent:

```bash
claude     # frontier: Claude Code
kilo       # Kilo: Tab cycles cfd | cfd-orchestrator (frontier + local) | cfd-local (local only)
```

and give it a scenario:

```
Set up and run cases/scenarios/lid-cavity.yaml
```

Watch the agent's audit trail in a second terminal:

```bash
tail -f cases/work/lid-cavity/REPORT.md
```

**The workshop walkthrough is [`workshop/README.md`](workshop/README.md)**:
the two-step persistent-knowledge demo (discover at Re = 400, reuse at
Re = 1000), run as frontier only, frontier + local, and local only.

### Kilo agents

`kilo.jsonc` registers the four MCP servers and three agents:

| Agent | Model | Role |
|---|---|---|
| `cfd` (default) | whatever `/models` selects | the full workflow in one model |
| `cfd-orchestrator` | a frontier model you select | reads, decides, narrates, and judges; has no case-changing tools, so it delegates each hands-on step to `cfd-worker` |
| `cfd-worker` (subagent) | `ollama/cfd-local` | executes the delegated steps (dicts, mesh, solve, analysis) |
| `cfd-local` | `ollama/cfd-local` | the full workflow on the local model, with a trimmed tool set and prompt sized for a 64k context |

Prompts live in `.kilo/prompts/`. The per-machine model context size is
written to `.kilo/kilo.jsonc` (gitignored) by `scripts/local-model.sh`.

### Other runtimes

The same `.mcp.json` drives GitHub Copilot, Codex, Cursor, Claude Desktop
and others (`AGENTS.md` points them at the workflow in `CLAUDE.md`). The
bring-your-own-agent harness talks to the Anthropic API or any
OpenAI-compatible server (Ollama, vLLM, LM Studio, llama.cpp):

```bash
uv run scripts/run_agent.py --backend anthropic \
    --prompt "Set up and run cases/scenarios/lid-cavity.yaml"
uv run scripts/run_agent.py --backend ollama --model cfd-local \
    --prompt "Set up and run cases/scenarios/lid-cavity.yaml"
```

Matrix in [`docs/runtime-options.md`](docs/runtime-options.md).

### Claude Code settings

`.claude/settings.json` is tracked and carries the project's shared Claude Code configuration, so a fresh clone is ready to run: it enables the four `.mcp.json` servers (`enabledMcpjsonServers`), pre-approves every tool on those four servers plus the `python3` invocations the workflow needs (`permissions.allow`), and registers the automation-gate `PreToolUse` hook that enforces each scenario's `automation_level`. The hook's pauses apply even to pre-approved tools, so the scenario, not the allow-list, decides where a run stops for review. Claude Code applies all of this only after you accept its "trust this folder" prompt the first time you run `claude` in the repo. `.claude/settings.local.json` is gitignored and holds your own per-machine overrides — it layers on top of the shared file and is never committed.

## Shipped scenarios

| Scenario | Geometry | Reference | Laptop runtime |
|---|---|---|---|
| `lid-cavity.yaml` | blockMesh square cavity | Ghia 1982 centerline profiles | < 1 min |
| `flat-plate.yaml` | blockMesh flat plate | qualitative (log-law, residual drop) | ~ 2 min |
| `pitz-daily.yaml` | blockMesh backward-facing step | Armaly 1983 reattachment length (x_r/h, laminar Re≈800) | ~ 1–2 min |
| `naca-0012.yaml` | STL + snappyHexMesh, 2-D | XFOIL Cl/Cd polar at Re=1e6 | ~ 10–15 min |
| `onera-m6.yaml` | STL + snappyHexMesh, 3-D swept wing | qualitative ranges (Cl, Cd, suction-peak) | ~ 30–45 min on 4 cores |

Schema and how to write your own: [`cases/scenarios/README.md`](cases/scenarios/README.md).

## Docs

- [`docs/architecture.md`](docs/architecture.md) — design rules, full tool surface
- [`docs/setup-wsl.md`](docs/setup-wsl.md) — OpenFOAM v2412 on WSL2
- [`docs/runtime-options.md`](docs/runtime-options.md) — Claude Code, Cursor, Cline, Continue.dev, Ollama
- [`docs/how-to-extend-openfoam.md`](docs/how-to-extend-openfoam.md) — custom BCs, function objects, turbulence models
- [`workshop/README.md`](workshop/README.md) — the hands-on walkthrough
- [`workshop/hpc.md`](workshop/hpc.md) — running on the FSU cluster (RCC)
- [`docs/evaluation-plan.md`](docs/evaluation-plan.md) / [`docs/evaluation-results.md`](docs/evaluation-results.md) — how agents are scored, and the results
- [`docs/workshop-handout.md`](docs/workshop-handout.md) — 1-page session handout

## License

MIT — see [`LICENSE`](LICENSE).

## Citation

```bibtex
@misc{kalagotla2026agenticopenfoam,
  author       = {Kalagotla, Dilip},
  title        = {Accelerating {CFD} Simulations with Agentic {AI} and {OpenFOAM}},
  howpublished = {Workshop, AIAA Aviation Forum},
  year         = {2026},
  month        = jun,
  address      = {San Diego, CA, USA},
  note         = {8--12 June 2026}
}
```
