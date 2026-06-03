# Self-contained build image for agentic-openfoam. Bundles OpenFOAM
# v2412 (ESI), ParaView (headless rendering), Python via uv, the four
# MCP servers, the bring-your-own-agent harness at scripts/run_agent.py,
# and the agent runtimes: the Claude Code CLI (Node.js) plus the anthropic
# SDK, the Ollama runtime for local models, and the LiteLLM proxy. No
# model weights or API keys are baked in — bring your own at runtime.
#
# The native github + uv path is the primary route — see README.md
# "Quickstart." This Dockerfile exists for users who do not have
# OpenFOAM installed locally or who want a hermetic environment.
#
# Build:
#   docker build -t agentic-openfoam .
#
# Run (interactive shell with OpenFOAM sourced):
#   docker run --rm -it agentic-openfoam
#
# Run (drive the agent with an Anthropic API key):
#   docker run --rm -it \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     agentic-openfoam \
#     uv run scripts/run_agent.py --backend anthropic \
#         --prompt "Set up and run cases/scenarios/lid-cavity.yaml"
#
# The image does NOT include any model weights or API keys. Bring
# your own.

FROM opencfd/openfoam-default:2412

# Switch to root for installs.
USER root

# Install Python + curl (for uv) + git (for clone-on-build use cases) +
# ca-certificates, plus ParaView (pvbatch + the python3 bindings) so
# export_field_image can render fields, and Xvfb + Mesa so it can do so
# headlessly. The base image is Ubuntu 24.04 noble.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        libgl1-mesa-dri \
        libosmesa6 \
        paraview \
        python3 \
        python3-paraview \
        python3-venv \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu's packaged ParaView is a GLX (X-only) build, so a direct
# `pvbatch --force-offscreen-rendering` aborts in a headless container
# (vtkXOpenGLRenderWindow::CreateAWindow, no X server). Shadow the real
# pvbatch with a wrapper earlier on PATH (/usr/local/bin precedes
# /usr/bin) that routes it through a throwaway Xvfb display, so
# export_field_image renders without a GPU or a real display.
RUN printf '%s\n' \
        '#!/usr/bin/env bash' \
        'exec xvfb-run -a /usr/bin/pvbatch "$@"' \
        > /usr/local/bin/pvbatch \
    && chmod +x /usr/local/bin/pvbatch

# Install uv (Astral) — handles its own Python versions if the system
# Python is too old, and gives us fast workspace dependency resolution.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && cp /root/.local/bin/uv /usr/local/bin/uv \
    && cp /root/.local/bin/uvx /usr/local/bin/uvx

# --- Agent runtimes (shipped so the workshop image is self-contained) ---
# These are clients/runtimes that drive the MCP servers; none carry API
# keys or model weights. Installed before the source COPY so they cache
# across code changes.
#
# Claude Code CLI (`claude`) needs Node.js; the anthropic Python SDK rides
# in with the workspace deps below.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        nodejs \
        npm \
        zstd \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code

# Ollama runtime for local models. The installer just drops the binary in
# a non-systemd container; start it at runtime with `ollama serve` and pull
# models with `ollama pull <name>` — none are baked in (they are multi-GB
# and run CPU-only without GPU passthrough).
RUN curl -fsSL https://ollama.com/install.sh | sh

# LiteLLM proxy (`litellm`) — the Claude-Code-over-Ollama route. Installed
# isolated via uv tool; its shim lands in /root/.local/bin (on PATH).
RUN uv tool install 'litellm[proxy]'

WORKDIR /workspace

# Copy dependency manifests first so we can cache the dep-install layer
# independently of the rest of the source tree.
COPY pyproject.toml uv.lock ./
COPY servers/openfoam/pyproject.toml servers/openfoam/pyproject.toml
COPY servers/validation/pyproject.toml servers/validation/pyproject.toml
COPY servers/consultant/pyproject.toml servers/consultant/pyproject.toml
COPY servers/research_assistant/pyproject.toml servers/research_assistant/pyproject.toml

# Pre-warm the uv resolver without installing the workspace members
# (the source isn't here yet). Frozen lockfile resolution only.
RUN uv sync --frozen --no-install-workspace || true

# Now copy the rest of the source tree.
COPY . .

# Final dependency sync with the workspace members in place.
RUN uv sync --frozen --all-packages

# Source OpenFOAM in every interactive shell — the MCP openfoam server
# expects $FOAM_TUTORIALS, $WM_PROJECT_DIR, etc. The base image ships its
# bashrc at this path. The OpenFOAM entrypoint drops the login shell in
# $HOME (/root), so also cd into the project — the banner's commands run
# from /workspace.
RUN echo 'source /usr/lib/openfoam/openfoam2412/etc/bashrc' >> /root/.bashrc \
    && echo 'cd /workspace' >> /root/.bashrc

# Light banner on shell login so the user knows they're in the
# container env, what's available, and how to escape it.
RUN echo 'echo "agentic-openfoam container. OpenFOAM v2412 sourced. uv + claude + ollama + litellm ready."' >> /root/.bashrc \
    && echo 'echo "  - run tests:       uv run pytest"' >> /root/.bashrc \
    && echo 'echo "  - agent (Claude):  uv run scripts/run_agent.py --backend anthropic --help"' >> /root/.bashrc \
    && echo 'echo "  - Claude Code CLI: claude"' >> /root/.bashrc \
    && echo 'echo "  - local models:    ollama serve &  then  ollama pull gpt-oss:20b"' >> /root/.bashrc \
    && echo 'echo "  - exit:            ctrl-d"' >> /root/.bashrc

# Default to an interactive bash shell with OF sourced. Override via
# the command to run the agent directly.
CMD ["/bin/bash", "-l"]
