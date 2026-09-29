#!/usr/bin/env bash
#
# Build the portable OpenFOAM v2412 image (instructor, once per cluster):
#
#   scripts/build-openfoam-sif.sh /gpfs/research/<group>/<shared-dir>
#
# Run it on a COMPUTE node (login nodes kill mksquashfs for memory), in a
# login shell so the site web proxy is loaded. Produces
# <dir>/openfoam-v2412.sif (~1 GB), world-readable, then point
# workshop/hpc-site.env (AOF_OPENFOAM_SIF) at it.
#
set -euo pipefail
DIR=${1:?usage: $0 <shared-dir>}
IMAGE=docker://opencfd/openfoam-default:2412

case "$(hostname)" in *login*) echo "Run this on a compute node, not $(hostname)." >&2; exit 1 ;; esac
command -v apptainer >/dev/null || { echo "apptainer not found" >&2; exit 1; }

mkdir -p "$DIR"
work=$(mktemp -d -p "$DIR" .build.XXXX)
trap 'rm -rf "$work"' EXIT
export APPTAINER_CACHEDIR=$work/cache APPTAINER_TMPDIR=$work/tmp
mkdir -p "$APPTAINER_TMPDIR"

apptainer build "$work/openfoam-v2412.sif" "$IMAGE"
mv "$work/openfoam-v2412.sif" "$DIR/openfoam-v2412.sif"
chmod a+r "$DIR/openfoam-v2412.sif"
chmod a+rx "$DIR"

echo "Built $DIR/openfoam-v2412.sif"
apptainer exec "$DIR/openfoam-v2412.sif" bash -c \
    'source /usr/lib/openfoam/openfoam2412/etc/bashrc && echo "OpenFOAM $WM_PROJECT_VERSION OK"'
