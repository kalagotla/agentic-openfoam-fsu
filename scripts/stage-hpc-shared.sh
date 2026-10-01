#!/usr/bin/env bash
#
# Stage the class-wide shared install on the cluster (instructor, once):
#
#   scripts/stage-hpc-shared.sh /gpfs/research/<group>/agentic-openfoam-shared [model ...]
#
# Fills <dir> with what every attendee's `setup.sh` would otherwise download:
#   openfoam-v2412.sif   the portable OpenFOAM image (via build-openfoam-sif.sh)
#   ollama/              the Ollama release (binary + GPU runtimes, ~1.4 GB)
#   ollama-models/       model weights (default: every tier local-model.sh picks)
# and makes it world-readable. Point workshop/hpc-site.env at it; attendees
# then symlink to these files instead of downloading them. Re-running only
# adds what is missing, so it also adds models later.
#
# Run it on a COMPUTE node (login nodes kill the image build), in a login
# shell so the site web proxy is loaded.
#
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR=${1:?usage: $0 <shared-dir> [model ...]}
shift
MODELS=("$@")
((${#MODELS[@]})) || MODELS=(gpt-oss:20b qwen3:8b qwen3:4b)

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
case "$(hostname)" in *login*) echo "Run this on a compute node, not $(hostname)." >&2; exit 1 ;; esac
mkdir -p "$DIR"
DIR=$(cd "$DIR" && pwd)

# OpenFOAM image
if [[ -f $DIR/openfoam-v2412.sif ]]; then
    say "OpenFOAM image already staged."
else
    "$REPO_DIR/scripts/build-openfoam-sif.sh" "$DIR"
fi

# Ollama release
if [[ -x $DIR/ollama/bin/ollama ]]; then
    say "Ollama already staged: $("$DIR/ollama/bin/ollama" --version 2>/dev/null | tail -1)"
else
    say "Downloading Ollama…"
    rm -rf "$DIR/ollama.tmp" && mkdir -p "$DIR/ollama.tmp"
    curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst \
        | zstd -d | tar -x -C "$DIR/ollama.tmp"
    mv "$DIR/ollama.tmp" "$DIR/ollama"
fi

# Model weights, pulled by a private server on a spare port into the shared store
port=$((20000 + RANDOM % 20000))
export OLLAMA_HOST=127.0.0.1:$port OLLAMA_MODELS=$DIR/ollama-models
mkdir -p "$OLLAMA_MODELS"
"$DIR/ollama/bin/ollama" serve >"$DIR/.stage-serve.log" 2>&1 &
server=$!
trap 'kill $server 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -fsS "http://$OLLAMA_HOST/api/version" >/dev/null 2>&1 && break; sleep 1; done
for m in "${MODELS[@]}"; do
    say "Pulling $m…"
    "$DIR/ollama/bin/ollama" pull "$m"
done
kill $server; wait $server 2>/dev/null || true
rm -f "$DIR/.stage-serve.log"

chmod -R a+rX "$DIR"
say "Staged in $DIR:"
du -sh "$DIR"/* | sed 's/^/    /'
cat <<EOF

Point workshop/hpc-site.env at it:
    AOF_OPENFOAM_SIF=$DIR/openfoam-v2412.sif
    AOF_OLLAMA_SHARED=$DIR/ollama
    AOF_OLLAMA_MODELS_SHARED=$DIR/ollama-models
EOF
