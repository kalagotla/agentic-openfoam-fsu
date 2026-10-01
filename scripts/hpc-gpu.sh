#!/usr/bin/env bash
#
# Run the local model on a cluster GPU while you keep working on your CPU node.
#
#   scripts/hpc-gpu.sh submit [sbatch options]   queue a GPU job that serves Ollama
#   scripts/hpc-gpu.sh status                    is it running yet?
#   scripts/hpc-gpu.sh use [model]               point Kilo's cfd-local at the GPU job
#   scripts/hpc-gpu.sh cpu                       back to this node's Ollama (CPU)
#   scripts/hpc-gpu.sh cancel                    end the GPU job
#
# GPU queues can take hours to start, so submit early (the morning of the
# workshop) and carry on: Loop A needs no local model, and cfd-local keeps
# working on CPU (slowly) until the GPU job is up. `use` then switches Kilo
# over in place: same repo, same session, nothing to re-install. The GPU job
# serves the same model store as your CPU node (your home directory), so
# there is nothing to download there either.
#
# Defaults come from workshop/hpc-site.env (AOF_GPU_SBATCH); anything after
# `submit` is passed to sbatch, e.g. `submit -t 8:00:00`.
#
# The GPU server listens only on its own node's loopback; `use` reaches it
# through an SSH tunnel (localhost:11435 here -> the GPU node). A tunnel,
# not a direct connection, because RCC's web proxy intercepts plain HTTP
# between nodes. If the tunnel drops (e.g. your CPU job ended), run `use`
# again.
#
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE=$HOME/.agentic-openfoam
ENDPOINT=$STATE/gpu-endpoint          # "<host> <port> <vram-GB> <jobid>"
JOBFILE=$STATE/gpu-jobid
TUNNEL_PORT=11435
[[ -f $REPO_DIR/workshop/hpc-site.env ]] && source "$REPO_DIR/workshop/hpc-site.env"
: "${AOF_GPU_SBATCH:=-p gpu_q -A gpu_q --gres=gpu:1 -c 4 --mem=32G -t 4:00:00}"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

job_state() {
    [[ -f $JOBFILE ]] || return 0
    squeue -h -j "$(cat "$JOBFILE")" -o %T 2>/dev/null || true
}
TUNNEL_URL=http://localhost:$TUNNEL_PORT
gpu_up() {   # the GPU server, checked from its own node
    [[ -f $ENDPOINT ]] || return 1
    local host port
    read -r host port _ _ <"$ENDPOINT"
    ssh -n -o BatchMode=yes "$host" curl -fsS "http://127.0.0.1:$port/api/version" >/dev/null 2>&1
}
tunnel_up() { curl -fsS --noproxy '*' "$TUNNEL_URL/api/version" >/dev/null 2>&1; }
open_tunnel() {
    local host port
    read -r host port _ _ <"$ENDPOINT"
    tunnel_up && pkill -u "$USER" -f "ssh .*-L $TUNNEL_PORT:" 2>/dev/null || true
    ssh -f -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
        -L "$TUNNEL_PORT:127.0.0.1:$port" "$host" || return 1
    for _ in $(seq 1 10); do tunnel_up && return 0; sleep 1; done
    return 1
}

submit() {
    command -v sbatch >/dev/null || die "No Slurm here — this is for the cluster."
    local state; state=$(job_state)
    [[ -n $state ]] && die "A GPU job is already $state (job $(cat "$JOBFILE")). 'cancel' it first."
    local ollama; ollama=$(command -v ollama || echo "$HOME/.local/bin/ollama")
    [[ -x $ollama ]] || die "ollama not found — run ./setup.sh first."
    mkdir -p "$STATE"; rm -f "$ENDPOINT"
    # shellcheck disable=SC2086  # AOF_GPU_SBATCH is a list of options
    sbatch --parsable -J aof-gpu-ollama -o "$STATE/gpu-job.log" $AOF_GPU_SBATCH "$@" <<EOF >"$JOBFILE"
#!/bin/bash
# Ollama on this job's GPU, reachable from your other nodes.
port=\$((20000 + RANDOM % 20000))
vram=\$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | sort -n | tail -1 | awk '{printf "%d", \$1/1024}')
export OLLAMA_HOST=127.0.0.1:\$port OLLAMA_KEEP_ALIVE=-1
"$ollama" serve &
server=\$!
for _ in \$(seq 1 60); do curl -fsS "http://127.0.0.1:\$port/api/version" >/dev/null 2>&1 && break; sleep 1; done
echo "\$(hostname -s) \$port \${vram:-0} \$SLURM_JOB_ID" >"$ENDPOINT.tmp" && mv "$ENDPOINT.tmp" "$ENDPOINT"
echo "Ollama serving on \$(hostname -s):\$port (GPU \${vram} GB)"
wait \$server
EOF
    say "Submitted GPU job $(cat "$JOBFILE"). Check with: scripts/hpc-gpu.sh status"
    say "Until it starts, keep working: Loop A needs no local model."
}

status() {
    local state; state=$(job_state)
    if [[ -z $state ]]; then
        echo "No GPU job. Submit one with: scripts/hpc-gpu.sh submit"
        return 0
    fi
    echo "GPU job $(cat "$JOBFILE"): $state"
    if [[ $state == PENDING ]]; then
        squeue -h -j "$(cat "$JOBFILE")" -o '  reason: %r   expected start: %S' 2>/dev/null || true
    elif gpu_up; then
        echo "  Ollama is up on $(awk '{print $1 ", GPU " $3}' "$ENDPOINT") GB."
        if tunnel_up; then echo "  Tunnel open at $TUNNEL_URL."; else echo "  Switch to it: scripts/hpc-gpu.sh use"; fi
    else
        echo "  starting Ollama…"
    fi
    echo "  cfd-local now: $("$REPO_DIR/scripts/local-model.sh" --show | head -1)"
}

use() {
    [[ -f $ENDPOINT ]] || die "The GPU job has not started yet (scripts/hpc-gpu.sh status)."
    gpu_up || die "No Ollama answering in the GPU job — is it still running? (scripts/hpc-gpu.sh status)"
    open_tunnel || die "Could not open the SSH tunnel to $(awk '{print $1}' "$ENDPOINT")."
    say "Tunnel: $TUNNEL_URL -> $(awk '{print $1 ":" $2}' "$ENDPOINT")"
    OLLAMA_HOST=$TUNNEL_URL AOF_REMOTE=1 AOF_REMOTE_VRAM=$(awk '{print $3}' "$ENDPOINT") \
        "$REPO_DIR/scripts/local-model.sh" "$@"
    say "Kilo's cfd-local now runs on the GPU. Restart kilo if it is open."
}

cpu() {
    OLLAMA_HOST= "$REPO_DIR/scripts/local-model.sh" "$@"
    say "Kilo's cfd-local is back on this node. Restart kilo if it is open."
}

cancel() {
    local state; state=$(job_state)
    [[ -n $state ]] && scancel "$(cat "$JOBFILE")" && say "Cancelled GPU job $(cat "$JOBFILE")."
    rm -f "$JOBFILE" "$ENDPOINT"
    pkill -u "$USER" -f "ssh .*-L $TUNNEL_PORT:" 2>/dev/null || true
    if grep -q 'url=http://localhost' "$REPO_DIR/.local-model" 2>/dev/null; then return 0; fi
    say "cfd-local still points at the GPU job; run scripts/hpc-gpu.sh cpu to switch back."
}

cmd=${1:-status}; shift || true
case $cmd in
    submit|status|use|cpu|cancel) "$cmd" "$@" ;;
    -h|--help|help) sed -n '2,24p' "$0" ;;
    *) die "Unknown command: $cmd (see --help)" ;;
esac
