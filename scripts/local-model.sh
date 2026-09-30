#!/usr/bin/env bash
#
# Pick, pull, and wire up the local Ollama model for the workshop.
#
#   ./scripts/local-model.sh              # choose a model from this machine's hardware
#   ./scripts/local-model.sh qwen3:30b    # use a model of your choice
#   ./scripts/local-model.sh --show       # print what is configured now
#
# Whatever model you pick is exposed to the agents under ONE fixed name,
# `cfd-local` (an Ollama alias carrying a larger context window than
# Ollama's 4k default — agents need room for the tool schemas). kilo.jsonc
# always points at `ollama/cfd-local`, so switching models never touches
# tracked config. The context size is written to .kilo/kilo.jsonc
# (gitignored), which Kilo merges over kilo.jsonc.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALIAS=cfd-local
OLLAMA_URL=${OLLAMA_HOST:-http://localhost:11434}
[[ $OLLAMA_URL == http* ]] || OLLAMA_URL="http://$OLLAMA_URL"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --- hardware ---------------------------------------------------------------
gpu_vram_gb() {
    # Largest single GPU, in GB. WSL2 ships nvidia-smi under /usr/lib/wsl/lib.
    local smi
    smi=$(command -v nvidia-smi || true)
    [[ -z $smi && -x /usr/lib/wsl/lib/nvidia-smi ]] && smi=/usr/lib/wsl/lib/nvidia-smi
    [[ -z $smi ]] && { echo 0; return; }
    "$smi" --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null \
        | sort -n | tail -1 | awk '{printf "%d", $1/1024}' || echo 0
}
ram_gb() { awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo; }

# CPU threads this job may use. On a shared cluster node Ollama would
# otherwise start one thread per core on the whole node, far past the
# Slurm allocation. Empty = let Ollama decide (laptops, workstations).
job_cpus() {
    if [[ -n ${SLURM_CPUS_PER_TASK:-} ]]; then echo "$SLURM_CPUS_PER_TASK"; return; fi
    if [[ -n ${SLURM_CPUS_ON_NODE:-} ]]; then echo "$SLURM_CPUS_ON_NODE"; return; fi
    # Reached the node over plain ssh (VS Code Remote): ask Slurm for our job here.
    if command -v squeue >/dev/null 2>&1; then
        squeue -h -u "$USER" -w "$(hostname -s)" -t R -o %C 2>/dev/null | sort -n | tail -1
    fi
}

# Tiers. gpt-oss:20b was the strongest local model in docs/evaluation-results.md
# and is an MoE (~3.6B active), so it is usable even partly on CPU.
choose_model() {
    local vram=$1 ram=$2
    if (( vram >= 14 )) || (( vram == 0 && ram >= 24 )) || (( vram > 0 && vram + ram >= 32 )); then
        echo gpt-oss:20b
    elif (( ram >= 12 || vram >= 8 )); then
        echo qwen3:8b
    else
        echo qwen3:4b
    fi
}
choose_ctx() {
    # 64k when the machine has headroom, else 32k. The local agents start at
    # ~20k tokens of prompt + tool schemas, so 32k is the floor.
    local vram=$1 ram=$2
    if (( vram >= 16 )) || (( vram == 0 && ram >= 32 )); then echo 65536; else echo 32768; fi
}

# --- ollama -----------------------------------------------------------------
ollama_up() { curl -fsS "$OLLAMA_URL/api/version" >/dev/null 2>&1; }

ensure_ollama() {
    command -v ollama >/dev/null || die "ollama is not installed — run ./setup.sh first."
    ollama_up && return
    say "Starting the Ollama server…"
    if command -v systemctl >/dev/null && systemctl is-enabled ollama >/dev/null 2>&1; then
        sudo systemctl start ollama || true
    fi
    if ! ollama_up; then
        mkdir -p "$HOME/.ollama"
        nohup ollama serve >"$HOME/.ollama/serve.log" 2>&1 &
    fi
    for _ in $(seq 1 30); do ollama_up && return; sleep 1; done
    die "Ollama did not start. See ~/.ollama/serve.log"
}

show() {
    if [[ -f $REPO_DIR/.local-model ]]; then
        echo "$ALIAS -> $(cat "$REPO_DIR/.local-model")"
    else
        echo "$ALIAS is not configured yet — run ./scripts/local-model.sh"
    fi
    ollama_up || echo "(Ollama is not running — any agent call will start failing until it is)"
    return 0
}

# --- main -------------------------------------------------------------------
case "${1:-}" in
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    --show)    show; exit 0 ;;
esac

VRAM=$(gpu_vram_gb); RAM=$(ram_gb)
MODEL=${1:-$(choose_model "$VRAM" "$RAM")}
CTX=${CFD_LOCAL_CTX:-$(choose_ctx "$VRAM" "$RAM")}

say "Hardware: GPU ${VRAM} GB VRAM, ${RAM} GB RAM -> model ${MODEL}, context ${CTX}"
if (( VRAM == 0 )); then
    warn "No NVIDIA GPU visible — the local model runs on CPU. Fine for short tasks; a full"
    warn "agent run needs a GPU (the ~18k-token agent prompt alone takes many minutes on CPU)."
fi
[[ $MODEL == qwen3:4b ]] && warn "Small machine: qwen3:4b can drive short tasks, but the full local-only run is unlikely to finish cleanly. The frontier + local loop is the better demo here."

ensure_ollama

if ollama show "$MODEL" >/dev/null 2>&1; then
    say "$MODEL already pulled."
else
    say "Pulling $MODEL (one-time download)…"
    ollama pull "$MODEL"
fi

say "Creating alias $ALIAS -> $MODEL (num_ctx $CTX)…"
tmp=$(mktemp)
printf 'FROM %s\nPARAMETER num_ctx %s\n' "$MODEL" "$CTX" >"$tmp"
THREADS=$(job_cpus)
if [[ -n $THREADS ]]; then
    printf 'PARAMETER num_thread %s\n' "$THREADS" >>"$tmp"
    say "Limiting the model to the job's $THREADS CPU threads."
fi
ollama create "$ALIAS" -f "$tmp" >/dev/null 2>&1 || die "ollama create failed"
rm -f "$tmp"

mkdir -p "$REPO_DIR/.kilo"
cat >"$REPO_DIR/.kilo/kilo.jsonc" <<EOF
// Written by scripts/local-model.sh — per-machine, gitignored.
// Kilo merges this over kilo.jsonc. Re-run the script to change it.
{
  "provider": {
    "ollama": {
      "models": {
        "$ALIAS": {
          "name": "cfd-local ($MODEL)",
          "limit": { "context": $CTX, "output": 8192 }
        }
      }
    }
  }
}
EOF
echo "$MODEL ctx=$CTX" >"$REPO_DIR/.local-model"

say "Loading the model into memory…"
# An empty prompt only loads the weights; no generation, so it is quick even
# on CPU.
if curl -fsS "$OLLAMA_URL/api/generate" -d "{\"model\":\"$ALIAS\",\"keep_alive\":\"30m\"}" >/dev/null; then
    say "Done: agents will use ollama/$ALIAS ($MODEL)."
else
    warn "Warm-up request failed; check 'ollama ps' and ~/.ollama/serve.log."
fi
