#!/usr/bin/env bash
#
# Bring up the agentic-openfoam Docker image from a Linux / WSL2 shell:
# install Docker if needed, build the image, smoke-test it, then open a
# shell inside it.
#
#   Windows: install WSL2 first from an admin PowerShell (`wsl --install`),
#            then run this from the Ubuntu (WSL) terminal in the cloned repo.
#   macOS:   install Docker Desktop yourself, then run this.
#   Linux:   just run it.
#
# Pass through your Anthropic key for the agent by exporting it first:
#   export ANTHROPIC_API_KEY=sk-ant-... ; ./scripts/docker-up.sh
#
set -euo pipefail

IMAGE=agentic-openfoam
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# 1. Ensure Docker is installed and the daemon is running (Debian/Ubuntu/WSL).
if ! command -v docker >/dev/null 2>&1; then
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "Docker is not installed and this is not an apt system." >&2
        echo "Install Docker (or Docker Desktop on macOS), then re-run." >&2
        exit 1
    fi
    echo "==> Installing Docker (docker.io) — needs sudo…"
    sudo apt-get update
    sudo apt-get install -y docker.io
    sudo usermod -aG docker "$USER"   # takes effect when you reopen the terminal
fi
# Start the daemon only if it is not already reachable (avoids a needless
# sudo prompt when the docker group is already active for you).
docker info >/dev/null 2>&1 \
    || sudo service docker start 2>/dev/null \
    || sudo systemctl start docker 2>/dev/null \
    || true

# 2. Reach the daemon without forcing a re-login: use docker directly if the
#    group is already effective this session, otherwise via sudo (no repo
#    files are bind-mounted, so nothing ends up root-owned).
if docker info >/dev/null 2>&1; then
    DOCKER="docker"
else
    echo "==> docker group not active in this shell yet; using sudo for docker."
    echo "    Reopen the terminal (or 'wsl --shutdown' from Windows) later to drop sudo."
    DOCKER="sudo docker"
fi

# 3. Build → smoke-test → shell.
echo "==> Building $IMAGE (first build ~30 min, image ~10 GB)…"
$DOCKER build -t "$IMAGE" .

echo "==> Smoke-testing: uv run pytest …"
# Non-fatal: report the result but still open the shell. One sandbox test
# (process-group kill) is timing-flaky under load; a flaky miss should not
# block you from using the container.
if $DOCKER run --rm "$IMAGE" bash -lc 'cd /workspace && uv run pytest'; then
    echo "==> Smoke test passed."
else
    echo "==> WARNING: smoke test reported a failure. One sandbox test is" >&2
    echo "    timing-flaky under load — re-run inside the container with" >&2
    echo "    'uv run pytest' to confirm before worrying." >&2
fi

env_args=()
[ -n "${ANTHROPIC_API_KEY:-}" ] && env_args+=(-e ANTHROPIC_API_KEY)

echo "==> Opening a shell in the container (ctrl-d to exit)…"
exec $DOCKER run --rm -it "${env_args[@]}" "$IMAGE"
