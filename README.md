# Agentic CFD with OpenFOAM

Workshop materials for **Accelerating CFD Simulations with Agentic AI and OpenFOAM** — AIAA Aviation 2026, San Diego, 8–12 June 2026.

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
├── README.md / CLAUDE.md / LICENSE / Dockerfile / .mcp.json / .devcontainer/
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
└── scripts/run_agent.py      # bring-your-own-agent harness (Anthropic / Ollama)
```

## Prerequisites

- Linux, macOS, or Windows + WSL2 (Ubuntu 22.04 / 24.04)
- OpenFOAM v2412 (ESI release) — setup steps in [`docs/setup-wsl.md`](docs/setup-wsl.md). v2406+ ESI and Foundation 11/12 also work.
- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- *Optional:* [Ollama](https://ollama.com/) + a 30B-class tool-use model, for running the agent fully locally

## Install

| Path | What you need | First-run time |
|---|---|---|
| **Native** | OpenFOAM v2412 + git + uv | ~5 min |
| **Docker** | [Docker](https://docs.docker.com/get-docker/) — WSL2 on Windows | ~30 min first build, instant after |
| **Dev Container** | VS Code + Dev Containers extension | ~25 min build, instant after |

### Native

```bash
git clone https://github.com/kalagotla/agentic-openfoam.git
cd agentic-openfoam
uv sync --all-packages
of2412                                                       # source OpenFOAM
cd cases/examples/pitz-daily/baseline && ./Allrun && cd -    # smoke-test
```

### Docker

The image is self-contained: OpenFOAM v2412, ParaView (headless rendering),
the four MCP servers, the `run_agent.py` harness, and the agent runtimes —
the Claude Code CLI (`claude`), the `anthropic` Python SDK, Ollama for local
models, and the LiteLLM proxy. No API keys or model weights are baked in.

**Windows:** install WSL2 first from an **admin PowerShell**, reboot, then
open the **Ubuntu** terminal and run everything below inside it. (macOS:
install Docker Desktop. Linux: nothing extra.)
```powershell
wsl --install
```

Clone the repo and run the bring-up script — it installs Docker if missing,
builds the image, smoke-tests it, and drops you into a shell in `/workspace`:
```bash
git clone https://github.com/kalagotla/agentic-openfoam.git
cd agentic-openfoam
export ANTHROPIC_API_KEY=sk-ant-...   # optional; passed into the container
./scripts/docker-up.sh                # first build ~30 min, image ~10 GB
```

Inside the container you start in `/workspace` with OpenFOAM sourced:
```bash
uv run pytest                                            # 329 tests
uv run scripts/run_agent.py --backend anthropic --help   # the agent harness
claude                                                   # Claude Code CLI
ollama serve &                                           # local-model server
ollama pull gpt-oss:20b                                  # pull a model (multi-GB, CPU-only here)
```

<details>
<summary><b>What <code>docker-up.sh</code> does — or run it by hand</b></summary>

```bash
# 1. Install Docker in the WSL distro (skip on macOS/Linux if already present)
sudo apt-get update && sudo apt-get install -y docker.io
sudo service docker start
sudo usermod -aG docker "$USER"          # then reopen the terminal (or: wsl --shutdown)

# 2. Build, smoke-test, and open a shell
docker build -t agentic-openfoam .
docker run --rm agentic-openfoam bash -lc 'cd /workspace && uv run pytest'
docker run --rm -it agentic-openfoam     # -it required; a bare `docker run` exits at once
```
</details>

### Dev Container

Install the *Dev Containers* extension in VS Code. Open the repo → Command Palette → *Dev Containers: Reopen in Container*. Details in [`.devcontainer/README.md`](.devcontainer/README.md).

### Teardown

`docker-down.sh` removes the image, its containers, and the build cache. Add
`--repo` to also delete the checkout, `--docker` to uninstall docker.io:
```bash
./scripts/docker-down.sh                 # optionally: --repo --docker
```

<details>
<summary><b>What it does — or run it by hand</b></summary>

```bash
docker rm -f $(docker ps -aq --filter ancestor=agentic-openfoam) 2>/dev/null || true
docker rmi agentic-openfoam
docker builder prune -f
cd .. && sudo rm -rf agentic-openfoam    # sudo: a -v mount run can leave root-owned files
```
</details>

## Run

```bash
# Anthropic API (bring your own key):
export ANTHROPIC_API_KEY=sk-ant-...
uv run scripts/run_agent.py --backend anthropic \
    --prompt "Set up and run cases/scenarios/lid-cavity.yaml"

# Local Ollama (recommended model: gpt-oss:20b — emits real OpenAI tool_calls):
ollama serve &
ollama pull gpt-oss:20b
uv run scripts/run_agent.py --backend ollama --model gpt-oss:20b \
    --prompt "Set up and run cases/scenarios/lid-cavity.yaml"
```

Watch the agent's audit trail in a second terminal:

```bash
tail -f cases/work/lid-cavity/REPORT.md
```

GUI MCP clients (Claude Code, Claude Desktop, Cursor, Continue.dev, Cline) read the same `.mcp.json`. Matrix in [`docs/runtime-options.md`](docs/runtime-options.md). To use **Claude Code with a local Ollama model** (no Anthropic API key), see [`docs/local-llm-with-claude-code.md`](docs/local-llm-with-claude-code.md) — a LiteLLM proxy translates Anthropic's wire format to Ollama in both directions.

### Claude Code settings

`.claude/settings.json` is tracked and carries the project's shared Claude Code configuration, so a fresh clone is ready to run: it enables the four `.mcp.json` servers (`enabledMcpjsonServers`), pre-approves the case-authoring tool calls and `python3` invocations the workflow needs (`permissions.allow`), and registers the automation-gate `PreToolUse` hook that enforces each scenario's `automation_level`. `.claude/settings.local.json` is gitignored and holds your own per-machine overrides — it layers on top of the shared file and is never committed.

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
