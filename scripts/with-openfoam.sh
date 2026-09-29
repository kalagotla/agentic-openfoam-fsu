#!/usr/bin/env bash
#
# Run a command with OpenFOAM v2412 on PATH, wherever it comes from:
#
#   1. the ESI apt install (/usr/lib/openfoam/openfoam2412) — WSL2 / Ubuntu
#   2. the Apptainer image — HPC, where there is no sudo. The image is
#      $AOF_OPENFOAM_SIF if set, else .hpc/openfoam-v2412.sif in the repo
#      (setup.sh --hpc pulls it there).
#
#   scripts/with-openfoam.sh blockMesh -case cases/work/x
#   scripts/with-openfoam.sh uv run --package openfoam-mcp python -m openfoam_mcp
#
# .mcp.json and kilo.jsonc launch the OpenFOAM-dependent MCP servers through
# this script, so the same config works on a laptop and on the cluster.
#
set -eo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OF_BASHRC=/usr/lib/openfoam/openfoam2412/etc/bashrc

if [[ -f $OF_BASHRC ]]; then
    # shellcheck disable=SC1090
    source "$OF_BASHRC" >/dev/null 2>&1 || true
    exec "$@"
fi

SIF=${AOF_OPENFOAM_SIF:-$REPO_DIR/.hpc/openfoam-v2412.sif}
if [[ -f $SIF ]] && command -v apptainer >/dev/null 2>&1; then
    binds=()
    # Home is bound by default; cluster file systems usually are not.
    for d in /gpfs /scratch /work; do [[ -d $d ]] && binds+=(--bind "$d"); done
    # Apptainer swaps in the image's PATH; keep the host's user-space tools
    # (uv, the command's own directory) reachable inside it.
    extra="$HOME/.local/bin"
    cmd_path=$(command -v "$1" 2>/dev/null || true)
    [[ $cmd_path == /* ]] && extra="$(dirname "$cmd_path"):$extra"
    export APPTAINERENV_PREPEND_PATH="$extra"
    exec apptainer exec "${binds[@]}" "$SIF" \
        bash -c 'source '"$OF_BASHRC"' >/dev/null 2>&1; exec "$@"' bash "$@"
fi

echo "OpenFOAM v2412 not found: no $OF_BASHRC and no Apptainer image at $SIF." >&2
echo "Run ./setup.sh (or ./setup.sh --hpc on the cluster)." >&2
exit 127
