#!/usr/bin/env bash
#
# Health check for the workshop environment. Safe to run any time:
#
#     ./scripts/doctor.sh
#
# Exits non-zero if something the demos need is missing or broken.
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
export PATH="$HOME/.local/bin:$PATH"

fails=0
pass() { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
fail() { printf '  \033[1;31m✗\033[0m %s\n' "$*"; fails=$((fails + 1)); }
note() { printf '  \033[1;33m!\033[0m %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "agentic-openfoam doctor"

# OpenFOAM (apt install or HPC Apptainer image, via the same wrapper the MCP
# servers use): mesh + solve a few steps of the cavity tutorial.
tmp=$(mktemp -d -p "$REPO_DIR" .doctor.XXXX)
if scripts/with-openfoam.sh bash -c '
        cp -r "$FOAM_TUTORIALS/incompressible/icoFoam/cavity/cavity" "$1/c" &&
        sed -i "s/^endTime .*/endTime 0.01;/" "$1/c/system/controlDict" &&
        blockMesh -case "$1/c" && icoFoam -case "$1/c"' bash "$tmp" >/dev/null 2>&1; then
    pass "OpenFOAM v2412 meshes and solves (cavity tutorial)"
else
    fail "OpenFOAM v2412 not usable — run ./setup.sh (scripts/with-openfoam.sh blockMesh -help shows why)"
fi
rm -rf "$tmp"

# Python environment for the MCP servers.
if have uv && uv run --quiet python -c 'import openfoam_mcp, validation_mcp, consultant_mcp, research_assistant_mcp' 2>/dev/null; then
    pass "MCP servers import (uv environment)"
else
    fail "MCP server environment broken — run: uv sync --all-packages"
fi

# ParaView for export_field_image.
if have pvbatch && timeout 60 pvbatch --no-mpi --version >/dev/null 2>&1; then
    pass "ParaView pvbatch (field renders)"
else
    note "pvbatch unavailable — field images will be skipped (the demos still run)"
fi

# MPI only matters for parallel runs (decompose_par + n_procs > 1). The
# workshop cases are serial, so this is a warning, not a failure.
if bash -c "timeout -s KILL 30 scripts/with-openfoam.sh mpirun -np 1 true" >/dev/null 2>&1; then
    pass "MPI starts (parallel runs available)"
else
    note "mpirun hangs or fails here — serial runs are fine; parallel runs are not."
fi

# Agents.
have claude && pass "Claude Code: $(claude --version 2>/dev/null | head -1)" || note "Claude Code not installed"
if have kilo; then
    pass "Kilo CLI: $(kilo --version 2>/dev/null | tail -1)"
    connected=$(timeout 120 kilo mcp list 2>/dev/null | grep -c "connected")
    if [[ $connected -ge 4 ]]; then
        pass "Kilo sees all 4 MCP servers"
    else
        fail "Kilo connected to $connected/4 MCP servers — run 'kilo mcp list' for details"
    fi
else
    note "Kilo CLI not installed"
fi
if have codex; then
    n=$(codex mcp list 2>/dev/null | grep -cE '^(openfoam|validation|consultant|research_assistant) ')
    if [[ $n -ge 4 ]]; then
        pass "Codex CLI: sees all 4 MCP servers (.codex/config.toml)"
    else
        fail "Codex sees $n/4 MCP servers — is the repo trusted in ~/.codex/config.toml? (re-run ./setup.sh)"
    fi
else
    note "Codex CLI not installed"
fi
if have copilot; then
    n=$(timeout 60 copilot mcp list 2>/dev/null | grep -cE '^ +(openfoam|validation|consultant|research_assistant) ')
    if [[ $n -ge 4 ]]; then
        pass "GitHub Copilot CLI: sees all 4 MCP servers (.mcp.json)"
    else
        fail "Copilot sees $n/4 MCP servers — re-run ./setup.sh, or start copilot here and answer yes to \"trust this folder\""
    fi
else
    note "GitHub Copilot CLI not installed"
fi

# Local model.
if have ollama; then
    url=$(OLLAMA_HOST= "$REPO_DIR/scripts/local-model.sh" --url)
    if curl -fsS "$url/api/version" >/dev/null 2>&1; then
        if OLLAMA_HOST=$url ollama show cfd-local >/dev/null 2>&1; then
            pass "Ollama running; $("$REPO_DIR/scripts/local-model.sh" --show | head -1)"
        else
            fail "Ollama is running but the cfd-local model is missing — run ./scripts/local-model.sh"
        fi
    else
        fail "Ollama is installed but not running — run ./scripts/local-model.sh (it starts the server)"
    fi
else
    note "Ollama not installed (fine for a frontier-only setup)"
fi

echo
if ((fails)); then
    echo "$fails check(s) failed."
    exit 1
fi
echo "All required checks passed."
