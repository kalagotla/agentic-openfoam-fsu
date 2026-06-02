# Self-contained build image for agentic-openfoam. Bundles OpenFOAM
# v2412 (ESI), Python via uv, the four MCP servers, and the
# bring-your-own-agent harness at scripts/run_agent.py.
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

# Install Python + curl (for uv) + git (for clone-on-build use cases)
# + ca-certificates. The base image is Ubuntu 22.04 jammy.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Install uv (Astral) — handles its own Python versions if the system
# Python is too old, and gives us fast workspace dependency resolution.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && cp /root/.local/bin/uv /usr/local/bin/uv \
    && cp /root/.local/bin/uvx /usr/local/bin/uvx

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
# expects $FOAM_TUTORIALS, $WM_PROJECT_DIR, etc. The base image ships
# its bashrc at this path.
RUN echo 'source /usr/lib/openfoam/openfoam2412/etc/bashrc' >> /root/.bashrc

# Light banner on shell login so the user knows they're in the
# container env (and how to escape it).
RUN echo 'echo "agentic-openfoam container. OpenFOAM v2412 sourced. uv ready."' >> /root/.bashrc \
    && echo 'echo "  - quickstart:      uv run pytest"' >> /root/.bashrc \
    && echo 'echo "  - run the agent:   uv run scripts/run_agent.py --help"' >> /root/.bashrc \
    && echo 'echo "  - exit:            ctrl-d"' >> /root/.bashrc

# Default to an interactive bash shell with OF sourced. Override via
# the command to run the agent directly.
CMD ["/bin/bash", "-l"]
