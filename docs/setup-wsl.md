# OpenFOAM + Python + MCP on WSL2

## Target environment

- Windows 10 or 11 host
- WSL2 with Ubuntu 22.04 or 24.04
- **OpenFOAM-v2412** (ESI / OpenCFD release) — what the workshop targets and tests against
  - Earlier ESI releases (v2406+) and the `.org` Foundation OpenFOAM 11/12 should also work; the tool names in `tools.py` are the same. If you use a different version, update the `source` line and tutorial paths below.
- Python 3.11+ via `uv`
- VS Code on the Windows side with the WSL and Python extensions (optional)

## One-time setup

> **Shortcut:** after step 1 (WSL2 + Ubuntu), clone the repo and run
> `./setup.sh` — it performs steps 2–6 below, plus the agents and a local
> model, and finishes with a health check. The manual steps stay here for
> reference and for troubleshooting.

### 1. Enable WSL2 and install Ubuntu

From an elevated PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
```

Reboot when prompted. On first launch, create a username and password for the Linux side — this is independent of your Windows login.

### 2. Install OpenFOAM-v2412

Inside the Ubuntu shell:

```bash
# Add the ESI / OpenCFD apt repository
sudo sh -c "wget -O - https://dl.openfoam.com/add-debian-repo.sh | bash"
sudo apt update

# Install OpenFOAM-v2412 plus its default tooling
sudo apt install -y openfoam2412-default
```

Install path: `/usr/lib/openfoam/openfoam2412/`. Define an opt-in alias so new shells stay clean:

```bash
echo 'alias of2412="source /usr/lib/openfoam/openfoam2412/etc/bashrc"' >> ~/.bashrc
source ~/.bashrc

of2412
which blockMesh   # /usr/lib/openfoam/openfoam2412/platforms/linux64GccDPInt32Opt/bin/blockMesh
echo $FOAM_TUTORIALS  # /usr/lib/openfoam/openfoam2412/tutorials
```

For auto-sourcing, append the `source …/bashrc` line to `~/.bashrc` directly.

On the `.org` Foundation release (OpenFOAM 11/12), substitute `/opt/openfoam11/etc/bashrc` (or your version) throughout.

### 3. Install `uv` for Python

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

Verify:

```bash
uv --version  # 0.4+ is fine
```

### 4. Clone the repo and install dependencies

```bash
# In your preferred working directory
git clone https://github.com/kalagotla/agentic-openfoam.git
cd agentic-openfoam

# Install both MCP servers and dev tools
uv sync --all-packages
```

### 5. Smoke-test the baseline case

```bash
of2412                                # source OpenFOAM if you haven't already
cd cases/examples/pitz-daily/baseline
./Allrun
```

Expected: `blockMesh` generates a mesh, turbulent (kEpsilon) `simpleFoam` converges at Re ≈ 50,800, and `validation.py` prints a short table with the reattachment length within tolerance of the turbulent plateau (≈ 6 step heights). (The laminar Re ≈ 800 case that validates against Armaly's x_r/h ≈ 13 is the separate `cases/scenarios/pitz-daily.yaml` exercise, not this baseline.)

### 6. Smoke-test the MCP servers

```bash
of2412
uv run pytest servers/
```

Expect everything to pass, with a handful of skips when OpenFOAM isn't on PATH. With `of2412` sourced, the OpenFOAM-dependent skips run too.

## Connecting VS Code on Windows to WSL

Install the "WSL" extension in VS Code on Windows (ms-vscode-remote.remote-wsl). Then from an Ubuntu shell:

```bash
cd agentic-openfoam
code .
```

That launches VS Code on the Windows side but rooted in the WSL filesystem. The Python interpreter autodetection will pick up the `uv`-managed `.venv`.

## Connecting an MCP client

For Claude Code on WSL — register all four servers from the repo root:

```bash
claude mcp add openfoam            "uv run python -m openfoam_mcp"            --cwd "$(pwd)"
claude mcp add validation          "uv run python -m validation_mcp"          --cwd "$(pwd)"
claude mcp add consultant          "uv run python -m consultant_mcp"          --cwd "$(pwd)"
claude mcp add research_assistant  "uv run python -m research_assistant_mcp"  --cwd "$(pwd)"
```

Other clients (Claude Desktop, Cursor, Continue.dev, Cline, or the bare harness) read [`.mcp.json`](../.mcp.json) directly. See [`runtime-options.md`](runtime-options.md).

## Common gotchas

- **File mode issues across WSL/Windows boundary.** Keep the repo under the Linux filesystem (`/home/you/...`), not in `/mnt/c/Users/...`. OpenFOAM hates the case-insensitive NTFS path.
- **`blockMesh: command not found`.** You opened a new shell and OpenFOAM isn't sourced. Run `of2412` (or `source /usr/lib/openfoam/openfoam2412/etc/bashrc` directly).
- **`uv sync` fails on numpy build.** Almost always a missing build dep. `sudo apt install build-essential python3-dev` and retry.
- **ParaView can't open cases.** You need X forwarding (WSLg on Windows 11 handles this automatically; on Windows 10, install VcXsrv). For the workshop we use `pvbatch` via Python, not the GUI, so this is only an issue if you want to inspect cases interactively during development.
