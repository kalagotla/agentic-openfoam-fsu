#!/usr/bin/env bash
#
# Download an Ollama model straight from the registry into a model store:
#
#   scripts/ollama-fetch.sh <store-dir> <model>     # e.g. ~/.ollama/models gpt-oss:20b
#
# The result is what `ollama pull` would leave in $OLLAMA_MODELS. Use it
# where `ollama pull` stalls: behind an HTTP proxy (FSU RCC compute nodes)
# Ollama's parallel ranged downloads hang, while one curl stream runs at
# full speed. Resumes partial downloads and checks every blob's sha256.
#
set -euo pipefail
STORE=${1:?usage: $0 <store-dir> <model>}
MODEL=${2:?usage: $0 <store-dir> <model>}
REGISTRY=https://registry.ollama.ai

name=${MODEL%%:*}; tag=${MODEL#*:}; [[ $MODEL == *:* ]] || tag=latest
[[ $name == */* ]] || name=library/$name
manifest=$STORE/manifests/registry.ollama.ai/$name/$tag
mkdir -p "$STORE/blobs" "$(dirname "$manifest")"

curl -fsSL -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
    "$REGISTRY/v2/$name/manifests/$tag" -o "$manifest.tmp" \
    || { echo "No such model in the Ollama registry: $MODEL" >&2; exit 1; }
for digest in $(grep -o 'sha256:[0-9a-f]\{64\}' "$manifest.tmp" | sort -u); do
    blob=$STORE/blobs/${digest/:/-}
    [[ -f $blob ]] && continue
    curl -fL --retry 5 --retry-all-errors -C - --progress-bar \
        "$REGISTRY/v2/$name/blobs/$digest" -o "$blob.partial"
    if [[ $(sha256sum "$blob.partial" | cut -d' ' -f1) != "${digest#sha256:}" ]]; then
        rm -f "$blob.partial"
        echo "Checksum mismatch for $digest; re-run to download it again." >&2
        exit 1
    fi
    mv "$blob.partial" "$blob"
done
mv "$manifest.tmp" "$manifest"
