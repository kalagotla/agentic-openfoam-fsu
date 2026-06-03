#!/usr/bin/env bash
#
# Tear down the agentic-openfoam Docker artifacts: stop and remove any
# containers from the image, remove the image, and reclaim the build cache.
#
#   --repo     also delete this checkout (sudo, to clear any root-owned
#              files a `-v` mount run left behind)
#   --docker   also uninstall docker.io from the (Debian/Ubuntu) system
#
set -euo pipefail

IMAGE=agentic-openfoam
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DROP_REPO=false;   printf '%s\n' "$@" | grep -qx -- --repo   && DROP_REPO=true
DROP_DOCKER=false; printf '%s\n' "$@" | grep -qx -- --docker && DROP_DOCKER=true

DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"

echo "==> Removing containers spawned from $IMAGE…"
ids="$($DOCKER ps -aq --filter ancestor="$IMAGE" 2>/dev/null || true)"
[ -n "$ids" ] && $DOCKER rm -f $ids >/dev/null || true

echo "==> Removing image $IMAGE…"
$DOCKER rmi "$IMAGE" 2>/dev/null || true

echo "==> Pruning build cache…"
$DOCKER builder prune -f >/dev/null || true

if $DROP_DOCKER; then
    echo "==> Uninstalling docker.io…"
    sudo apt-get purge -y docker.io && sudo apt-get autoremove -y
fi

if $DROP_REPO; then
    echo "==> Removing repo at $REPO_DIR…"
    cd /
    sudo rm -rf "$REPO_DIR"
fi

echo "Done."
