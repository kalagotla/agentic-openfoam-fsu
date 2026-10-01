#!/usr/bin/env bash
#
# Pick, pull, and wire up the local Ollama model for the workshop.
#
#   ./scripts/local-model.sh              # choose a model from this machine's hardware
#   ./scripts/local-model.sh gemma4:12b   # use a model of your choice
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
# A server on another machine (scripts/hpc-gpu.sh points us at the Ollama in
# a GPU job, through a tunnel on localhost:11435). Then we neither start a
# server nor look at this machine's GPU.
REMOTE=${AOF_REMOTE:+true}; REMOTE=${REMOTE:-false}
[[ $OLLAMA_URL =~ ^https?://(localhost|127\.0\.0\.1)(:|/|$) ]] || REMOTE=true

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

# Tiers, all US-developed open models (OpenAI, Google, NVIDIA). gpt-oss:20b
# was the strongest local model in docs/evaluation-results.md and is an MoE
# (~3.6B active), so it is usable even partly on CPU.
choose_model() {
    local vram=$1 ram=$2
    if (( vram >= 14 )) || (( vram == 0 && ram >= 24 )) || (( vram > 0 && vram + ram >= 32 )); then
        echo gpt-oss:20b
    elif (( ram >= 12 || vram >= 8 )); then
        echo gemma4:12b
    else
        echo nemotron-3-nano:4b
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
    $REMOTE && die "The Ollama server at $OLLAMA_URL is not reachable."
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

# A read-only model store shared by the class (cluster: instructor-staged with
# scripts/stage-hpc-shared.sh, path in workshop/hpc-site.env). Instead of
# downloading, copy the model's small manifest into our own store and
# symlink its weight blobs, so the weights cost no download and no quota,
# while `ollama create` still has a writable store of our own.
[[ -f $REPO_DIR/workshop/hpc-site.env ]] && source "$REPO_DIR/workshop/hpc-site.env"
link_shared_model() {
    local shared=${AOF_OLLAMA_MODELS_SHARED:-} rel mine digest
    [[ -n $shared && -d $shared/manifests ]] || return 1
    rel=$(manifest_path "$1")
    [[ -r $shared/$rel ]] || return 1
    mine=${OLLAMA_MODELS:-$HOME/.ollama/models}
    mkdir -p "$mine/blobs" "$(dirname "$mine/$rel")"
    for digest in $(grep -o 'sha256:[0-9a-f]\{64\}' "$shared/$rel" | sort -u); do
        digest=${digest/:/-}
        [[ -r $shared/blobs/$digest ]] || return 1
        [[ -e $mine/blobs/$digest ]] || ln -s "$shared/blobs/$digest" "$mine/blobs/$digest"
    done
    cp "$shared/$rel" "$mine/$rel"
}

# Path of a pulled model's manifest, and of its weights blob.
manifest_path() {
    local name=${1%%:*} tag=${1#*:}
    [[ $1 == *:* ]] || tag=latest
    [[ $name == */* ]] || name=library/$name
    echo "manifests/registry.ollama.ai/$name/$tag"
}
blob_path() {
    local store=${OLLAMA_MODELS:-$HOME/.ollama/models} digest
    digest=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1]))
print(next(l["digest"] for l in m["layers"] if l["mediaType"].endswith(".model")))' \
        "$store/$(manifest_path "$1")" 2>/dev/null) || return 0
    echo "$store/blobs/${digest/:/-}"
}
# The `ollama create` equivalent for FROM + PARAMETERs: same layers as the
# base model with its params layer replaced, plus a matching config.
write_alias() {
    python3 - "${OLLAMA_MODELS:-$HOME/.ollama/models}" "$(manifest_path "$1")" \
        "$(manifest_path "$ALIAS")" "$2" "${3:-}" <<'PY'
import hashlib, json, os, sys
store, base, alias, ctx, threads = sys.argv[1:]
def blob(data):
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    with open(os.path.join(store, "blobs", digest.replace(":", "-")), "wb") as f:
        f.write(data)
    return digest
def read_blob(digest):
    return open(os.path.join(store, "blobs", digest.replace(":", "-")), "rb").read()
m = json.load(open(os.path.join(store, base)))
params, layers = {}, []
for layer in m["layers"]:
    if layer["mediaType"] == "application/vnd.ollama.image.params":
        params = json.loads(read_blob(layer["digest"]))
    else:
        layers.append(layer)
params["num_ctx"] = int(ctx)
if threads:
    params["num_thread"] = int(threads)
data = json.dumps(params).encode()
layers.append({"mediaType": "application/vnd.ollama.image.params",
               "digest": blob(data), "size": len(data)})
config = json.loads(read_blob(m["config"]["digest"]))
config.setdefault("rootfs", {"type": "layers"})["diff_ids"] = [l["digest"] for l in layers]
data = json.dumps(config).encode()
m["config"] = dict(m["config"], digest=blob(data), size=len(data))
m["layers"] = layers
path = os.path.join(store, alias)
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(m, f)
PY
}

show() {
    if [[ -f $REPO_DIR/.local-model ]]; then
        echo "$ALIAS -> $(cat "$REPO_DIR/.local-model")"
        OLLAMA_URL=$(configured_url)
    else
        echo "$ALIAS is not configured yet — run ./scripts/local-model.sh"
    fi
    ollama_up || echo "(Ollama at $OLLAMA_URL is not running — any agent call will start failing until it is)"
    return 0
}
# The server Kilo was last pointed at (recorded in .local-model).
configured_url() {
    local url
    url=$(grep -o 'url=[^ ]*' "$REPO_DIR/.local-model" 2>/dev/null | cut -d= -f2-)
    echo "${url:-http://localhost:11434}"
}

# --- main -------------------------------------------------------------------
case "${1:-}" in
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    --show)    show; exit 0 ;;
    --url)     configured_url; exit 0 ;;
esac

if $REMOTE; then
    # The GPU is on the other machine; hpc-gpu.sh passes its size.
    VRAM=${AOF_REMOTE_VRAM:-16}; RAM=0
    say "Using the Ollama server at $OLLAMA_URL"
else
    VRAM=$(gpu_vram_gb); RAM=$(ram_gb)
fi
MODEL=${1:-$(choose_model "$VRAM" "$RAM")}
CTX=${CFD_LOCAL_CTX:-$(choose_ctx "$VRAM" "$RAM")}

say "Hardware: GPU ${VRAM} GB VRAM, ${RAM} GB RAM -> model ${MODEL}, context ${CTX}"
if (( VRAM == 0 )); then
    warn "No NVIDIA GPU visible — the local model runs on CPU. Fine for short tasks; a full"
    warn "agent run needs a GPU (the ~18k-token agent prompt alone takes many minutes on CPU)."
fi
[[ $MODEL == nemotron-3-nano:4b ]] && warn "Small machine: nemotron-3-nano:4b can drive short tasks, but the full local-only run is unlikely to finish cleanly. The frontier + local loop is the better demo here."

ensure_ollama

if ollama show "$MODEL" >/dev/null 2>&1; then
    say "$MODEL already pulled."
elif link_shared_model "$MODEL" && ollama show "$MODEL" >/dev/null 2>&1; then
    say "$MODEL linked from the shared store $AOF_OLLAMA_MODELS_SHARED (no download)."
elif [[ -n ${HTTPS_PROXY:-${https_proxy:-}} ]] && command -v sbatch >/dev/null; then
    # Cluster node behind the web proxy: `ollama pull` stalls there, so fetch
    # with curl into our own store.
    say "Downloading $MODEL (one-time, via the proxy)…"
    "$REPO_DIR/scripts/ollama-fetch.sh" "${OLLAMA_MODELS:-$HOME/.ollama/models}" "$MODEL" \
        || die "Download of $MODEL failed."
    ollama show "$MODEL" >/dev/null 2>&1 || die "Ollama cannot read $MODEL after download."
else
    say "Pulling $MODEL (one-time download)…"
    ollama pull "$MODEL"
fi

say "Creating alias $ALIAS -> $MODEL (num_ctx $CTX)…"
THREADS=$($REMOTE || job_cpus)
[[ -n $THREADS ]] && say "Limiting the model to the job's $THREADS CPU threads."
if [[ -L $(blob_path "$MODEL") ]]; then
    # Weights are symlinks into the read-only shared store, where `ollama
    # create` fails (it touches each blob's mtime), so write the alias directly.
    write_alias "$MODEL" "$CTX" "$THREADS" || die "Could not write the $ALIAS alias"
else
    tmp=$(mktemp)
    printf 'FROM %s\nPARAMETER num_ctx %s\n' "$MODEL" "$CTX" >"$tmp"
    [[ -n $THREADS ]] && printf 'PARAMETER num_thread %s\n' "$THREADS" >>"$tmp"
    ollama create "$ALIAS" -f "$tmp" >/dev/null 2>&1 || die "ollama create failed"
    rm -f "$tmp"
fi

mkdir -p "$REPO_DIR/.kilo"
cat >"$REPO_DIR/.kilo/kilo.jsonc" <<EOF
// Written by scripts/local-model.sh — per-machine, gitignored.
// Kilo merges this over kilo.jsonc. Re-run the script to change it.
{
  "provider": {
    "ollama": {
      "options": { "baseURL": "$OLLAMA_URL/v1" },
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
echo "$MODEL ctx=$CTX url=$OLLAMA_URL" >"$REPO_DIR/.local-model"

say "Loading the model into memory…"
# An empty prompt only loads the weights; no generation, so it is quick even
# on CPU.
if curl -fsS "$OLLAMA_URL/api/generate" -d "{\"model\":\"$ALIAS\",\"keep_alive\":\"30m\"}" >/dev/null; then
    say "Done: agents will use ollama/$ALIAS ($MODEL)."
else
    warn "Warm-up request failed; check 'ollama ps' and ~/.ollama/serve.log."
fi
