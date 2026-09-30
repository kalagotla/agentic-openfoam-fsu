#!/usr/bin/env bash
#
# One-command setup for the agentic-openfoam workshop.
#
#   Windows: open the Ubuntu (WSL2) terminal, clone this repo into your Linux
#            home (NOT /mnt/c/...), cd into it, and run ./setup.sh
#   Ubuntu 22.04 / 24.04: same.
#   HPC (e.g. FSU RCC): same command, on a compute node; no sudo needed.
#            Detected automatically when Slurm is present and apt is not
#            (force with --hpc). See workshop/hpc.md.
#
# What it installs (each step is skipped if already present, so re-running
# is safe and fast):
#                    workstation (sudo)               HPC (no sudo)
#   OpenFOAM v2412   ESI apt package                  Apptainer image (.hpc/)
#   ParaView         apt + headless pvbatch wrapper   (skipped: renders off)
#   Python           uv + the MCP servers' env        same
#   Node.js 22       NodeSource apt                   user-space tarball
#   Agents           Claude Code + Kilo CLI           same
#   Local model      Ollama + a model for this        user-space Ollama, same
#                    machine as `cfd-local`           model logic
#   Health check     scripts/doctor.sh                same
#
# Options:
#   --model TAG     use this Ollama model instead of the automatic pick
#   --no-local      skip Ollama and the local model (frontier-only setup)
#   --no-claude     skip Claude Code
#   --no-kilo       skip Kilo
#   --hpc           force HPC mode (no sudo, Apptainer for OpenFOAM)
#   -h, --help      show this help
#
# HPC: OpenFOAM v2412 ships as one portable Apptainer image (.sif). setup.sh
# uses, in order: $AOF_OPENFOAM_SIF, the shared path / URL in
# workshop/hpc-site.env, a copy already in .hpc/, or builds one (compute
# node only). Model weights go to $OLLAMA_MODELS (default ~/.ollama/models).
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

OF_VERSION=2412
OF_BASHRC=/usr/lib/openfoam/openfoam${OF_VERSION}/etc/bashrc
OF_IMAGE=docker://opencfd/openfoam-default:${OF_VERSION}
NODE_MAJOR=22

MODEL=""
WANT_LOCAL=true
WANT_CLAUDE=true
WANT_KILO=true
HPC=auto
while (($#)); do
    case "$1" in
        --model)     MODEL=${2:?--model needs a tag, e.g. qwen3:8b}; shift ;;
        --no-local)  WANT_LOCAL=false ;;
        --no-claude) WANT_CLAUDE=false ;;
        --no-kilo)   WANT_KILO=false ;;
        --hpc)       HPC=true ;;
        -h|--help)   sed -n '2,36p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

LOG="$REPO_DIR/setup.log"
: >"$LOG"
step() { printf '\n\033[1;36m[%s]\033[0m %s\n' "$1" "$2"; }
say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$*" >&2; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n       Full log: %s\n' "$*" "$LOG" >&2; exit 1; }
# Run a noisy command with its output going to setup.log.
quiet() { "$@" >>"$LOG" 2>&1; }
have() { command -v "$1" >/dev/null 2>&1; }

mkdir -p "$HOME/.local/bin"
export PATH="$HOME/.local/bin:$PATH"

# --- 0. Preflight ------------------------------------------------------------
step 0/6 "Checking the machine"
[[ $(uname -s) == Linux ]] || die "This script runs on Linux, Windows WSL2, or an HPC login/compute node. On Windows, open the Ubuntu (WSL) terminal first — see docs/setup-wsl.md."
[[ $EUID -eq 0 ]] && die "Run as your normal user, not root."

if [[ $HPC == auto ]]; then
    if ! have apt-get && have sbatch; then HPC=true; else HPC=false; fi
fi

IS_WSL=false
grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=true
if $IS_WSL && [[ $REPO_DIR == /mnt/* ]]; then
    die "The repo is on the Windows drive ($REPO_DIR). OpenFOAM breaks on NTFS and it is 10x slower.
       Clone it into your Linux home instead:
         cd ~ && git clone <repo-url> && cd <repo> && ./setup.sh"
fi

. /etc/os-release
if $HPC; then
    say "OS: $PRETTY_NAME — HPC mode (no sudo; OpenFOAM via Apptainer)"
    have apptainer || have singularity || die "HPC mode needs Apptainer (or Singularity) for OpenFOAM. Ask your cluster admins, or load its module."
    # Clusters like FSU RCC give compute nodes internet only through a web
    # proxy that login shells set up. Warn if neither route works.
    if ! curl -fsS -m 10 -o /dev/null https://registry.npmjs.org 2>/dev/null; then
        die "No internet from this shell. On a compute node, use a login shell (bash -l) so the site web proxy is loaded, or run setup from a login node."
    fi
else
    have apt-get || die "apt-get not found. setup.sh supports Ubuntu 22.04/24.04 (native or WSL2), or an HPC cluster with Slurm (--hpc)."
    say "OS: $PRETTY_NAME$($IS_WSL && echo ' (WSL2)')"
    case "${VERSION_ID:-}" in
        22.04|24.04) ;;
        *) warn "Tested on Ubuntu 22.04/24.04; ${PRETTY_NAME} may work but is untested." ;;
    esac
    say "sudo is needed for system packages — you may be asked for your Linux password."
    sudo -v || die "sudo failed."
fi

# --- 1+2. System packages and OpenFOAM ---------------------------------------
install_workstation_base() {
    step 1/6 "System packages"
    local PKGS=(ca-certificates curl wget git build-essential python3 python3-venv zstd xvfb paraview)
    # python3-paraview is split out on 24.04; on 22.04 the bindings ship inside paraview.
    apt-cache show python3-paraview >/dev/null 2>&1 && PKGS+=(python3-paraview)
    local missing=() p
    for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
    if ((${#missing[@]})); then
        say "Installing: ${missing[*]}"
        quiet sudo apt-get update
        quiet sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}" \
            || die "apt-get install failed."
    fi
    ok "system packages"

    # Ubuntu's ParaView is an X11 build. Without a display (plain WSL2 on
    # Windows 10, SSH, CI) pvbatch cannot open a window, so route it through
    # a throwaway Xvfb server. ~/.local/bin precedes /usr/bin on PATH.
    if [[ -z ${DISPLAY:-} && ! -e $HOME/.local/bin/pvbatch ]]; then
        printf '#!/usr/bin/env bash\nexec xvfb-run -a /usr/bin/pvbatch "$@"\n' >"$HOME/.local/bin/pvbatch"
        chmod +x "$HOME/.local/bin/pvbatch"
        ok "headless pvbatch wrapper (~/.local/bin/pvbatch)"
    fi

    step 2/6 "OpenFOAM v${OF_VERSION}"
    if [[ -f $OF_BASHRC ]]; then
        ok "already installed ($OF_BASHRC)"
    else
        say "Adding the OpenCFD apt repository and installing openfoam${OF_VERSION}-default (~1 GB)…"
        curl -fsSL https://dl.openfoam.com/add-debian-repo.sh | quiet sudo bash \
            || die "Could not add the OpenFOAM apt repository."
        quiet sudo apt-get update
        quiet sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "openfoam${OF_VERSION}-default" \
            || die "OpenFOAM install failed."
        ok "installed"
    fi
}

install_hpc_base() {
    step 1/6 "Cluster tools"
    case "$(hostname)" in
        *login*) die "This is a login node ($(hostname)). Run setup on a compute node — see workshop/hpc.md §1 (srun ... --pty bash -l)." ;;
    esac
    local t
    for t in git curl tar zstd; do have "$t" || die "$t is not available on this cluster node."; done
    ok "git, curl, tar, zstd on $(hostname)"
    say "ParaView renders are skipped on HPC (export_field_image reports pvbatch_not_found); the demos do not need them."

    step 2/6 "OpenFOAM v${OF_VERSION} (portable Apptainer image)"
    # Site defaults (shared image path / download URL) for this cluster.
    # shellcheck disable=SC1091
    [[ -f $REPO_DIR/workshop/hpc-site.env ]] && source "$REPO_DIR/workshop/hpc-site.env"
    local sif=$REPO_DIR/.hpc/openfoam-v${OF_VERSION}.sif
    if [[ -n ${AOF_OPENFOAM_SIF:-} && -f $AOF_OPENFOAM_SIF ]]; then
        sif=$AOF_OPENFOAM_SIF
        ok "shared image $sif"
    elif [[ -f $sif ]]; then
        ok "image present ($sif)"
    else
        mkdir -p "$REPO_DIR/.hpc"
        if [[ -n ${AOF_OPENFOAM_SIF_URL:-} ]]; then
            say "Downloading the portable image (455 MB) from $AOF_OPENFOAM_SIF_URL…"
            if curl -fL --retry 3 -o "$sif.part" "$AOF_OPENFOAM_SIF_URL" >>"$LOG" 2>&1; then
                mv "$sif.part" "$sif"
                ok "downloaded $sif"
            else
                rm -f "$sif.part"
                warn "Download failed (a private repo's release needs a login); building instead."
            fi
        fi
        if [[ ! -f $sif ]]; then
            export APPTAINER_CACHEDIR="$REPO_DIR/.hpc/cache" APPTAINER_TMPDIR="$REPO_DIR/.hpc/tmp"
            mkdir -p "$APPTAINER_TMPDIR"
            say "Building $sif from $OF_IMAGE (~10 min)…"
            quiet apptainer build "$sif" "$OF_IMAGE" \
                || die "Apptainer build failed. Point AOF_OPENFOAM_SIF at an existing openfoam-v${OF_VERSION}.sif and re-run."
            rm -rf "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"
            ok "built $sif"
        fi
    fi
    export AOF_OPENFOAM_SIF=$sif
    # The MCP servers are launched by the agents, not this shell — make the
    # image path permanent for them.
    if ! grep -qF "AOF_OPENFOAM_SIF=" "$HOME/.bashrc" 2>/dev/null; then
        echo "export AOF_OPENFOAM_SIF=$sif   # agentic-openfoam: portable OpenFOAM v${OF_VERSION}" >>"$HOME/.bashrc"
        say "Added AOF_OPENFOAM_SIF to ~/.bashrc"
    fi
    scripts/with-openfoam.sh blockMesh -help >/dev/null 2>&1 || die "OpenFOAM in the image does not run (scripts/with-openfoam.sh blockMesh -help)."
    ok "OpenFOAM runs through scripts/with-openfoam.sh"
}

if $HPC; then install_hpc_base; else install_workstation_base; fi

# Shell conveniences, added once between markers so re-runs don't duplicate.
MARK_BEGIN="# >>> agentic-openfoam >>>"
if ! grep -qF "$MARK_BEGIN" "$HOME/.bashrc" 2>/dev/null; then
    {
        echo
        echo "$MARK_BEGIN"
        echo 'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac'
        $HPC || echo "alias of${OF_VERSION}='source ${OF_BASHRC}'"
        echo "# <<< agentic-openfoam <<<"
    } >>"$HOME/.bashrc"
    ok "added ~/.local/bin to PATH$($HPC || echo " and the 'of${OF_VERSION}' alias") in ~/.bashrc"
fi

# --- 3. Python (uv) ----------------------------------------------------------
step 3/6 "Python environment (uv)"
if ! have uv; then
    curl -LsSf https://astral.sh/uv/install.sh | quiet sh || die "uv install failed."
fi
ok "uv $(uv --version | awk '{print $2}')"
say "Installing the MCP servers' dependencies (uv sync)…"
quiet uv sync --all-packages || die "uv sync failed."
ok "MCP server environment (.venv)"

# --- 4. Node.js + agents -----------------------------------------------------
step 4/6 "Agents"
node_ok() { have node && (( $(node -p 'process.versions.node.split(".")[0]') >= 20 )); }
install_node_userspace() {
    # No sudo: unpack the official build into ~/.local/node and link it in.
    local ver
    ver=$(curl -fsSL "https://nodejs.org/dist/latest-v${NODE_MAJOR}.x/SHASUMS256.txt" \
        | awk '/linux-x64.tar.xz$/ {print $2; exit}') || true
    [[ -n $ver ]] || die "Could not find a Node.js ${NODE_MAJOR} download."
    rm -rf "$HOME/.local/node" && mkdir -p "$HOME/.local/node"
    curl -fsSL "https://nodejs.org/dist/latest-v${NODE_MAJOR}.x/$ver" \
        | tar -xJ -C "$HOME/.local/node" --strip-components=1 || die "Node.js download failed."
    ln -sf "$HOME/.local/node/bin/"{node,npm,npx} "$HOME/.local/bin/"
    # Global packages (the Kilo CLI) must land in ~/.local/bin, which is on
    # PATH, not in ~/.local/node/bin, which is not.
    "$HOME/.local/bin/npm" config set prefix "$HOME/.local"
    hash -r
}
if ($WANT_CLAUDE || $WANT_KILO) && ! node_ok; then
    say "Installing Node.js ${NODE_MAJOR}…"
    if $HPC; then
        install_node_userspace
    else
        curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | quiet sudo -E bash - \
            || die "Could not add the NodeSource repository."
        quiet sudo apt-get install -y nodejs || die "Node.js install failed."
    fi
    node_ok || die "Node.js ${NODE_MAJOR} install did not take effect."
fi
if have npm; then
    # Global npm installs go to ~/.local so they never need sudo.
    if [[ ! -w $(npm config get prefix) ]]; then
        npm config set prefix "$HOME/.local"
        say "npm global prefix set to ~/.local"
    fi
fi

if $WANT_CLAUDE; then
    if have claude; then
        ok "Claude Code $(claude --version 2>/dev/null | awk '{print $1}')"
    else
        say "Installing Claude Code…"
        curl -fsSL https://claude.ai/install.sh | quiet bash || die "Claude Code install failed."
        ok "Claude Code installed (run 'claude' once to sign in)"
    fi
fi
if $WANT_KILO; then
    if have kilo; then
        ok "Kilo CLI $(kilo --version 2>/dev/null | tail -1)"
    else
        say "Installing the Kilo CLI…"
        quiet npm install -g @kilocode/cli || die "Kilo CLI install failed."
        ok "Kilo CLI installed"
    fi
fi

# --- 5. Local model ----------------------------------------------------------
step 5/6 "Local model (Ollama)"
install_ollama_userspace() {
    # No sudo: the release archive holds bin/ollama plus its GPU runtimes.
    say "Downloading Ollama (~1.4 GB, user-space)…"
    rm -rf "$HOME/.local/ollama" && mkdir -p "$HOME/.local/ollama"
    curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst \
        | zstd -d | tar -x -C "$HOME/.local/ollama" || die "Ollama download failed."
    ln -sf "$HOME/.local/ollama/bin/ollama" "$HOME/.local/bin/ollama"
    hash -r
}
if $WANT_LOCAL; then
    if ! have ollama; then
        if $HPC; then
            install_ollama_userspace
        else
            say "Installing Ollama…"
            curl -fsSL https://ollama.com/install.sh | quiet sh || die "Ollama install failed."
        fi
    fi
    ok "Ollama $(ollama --version 2>/dev/null | tail -1 | awk '{print $NF}')"
    # local-model.sh starts the server if needed, picks + pulls the model,
    # and creates the `cfd-local` alias the Kilo agents use.
    "$REPO_DIR/scripts/local-model.sh" ${MODEL:+"$MODEL"} || die "Local model setup failed."
else
    say "Skipped (--no-local)."
fi

# --- 6. Health check ---------------------------------------------------------
step 6/6 "Health check"
"$REPO_DIR/scripts/doctor.sh" || warn "Some checks failed — see above. Re-run ./setup.sh after fixing, or ask a helper."

cat <<EOF

$(printf '\033[1;32mSetup complete.\033[0m') Open a NEW terminal (or run: source ~/.bashrc), then:

  cd $REPO_DIR

  Frontier (Claude Code):   claude
      > Set up and run cases/scenarios/lid-cavity.yaml

  Kilo (any model):         kilo
      Tab cycles agents: cfd  |  cfd-orchestrator (frontier + local)  |  cfd-local (local only)

  Watch the audit trail:    tail -f cases/work/lid-cavity/REPORT.md

  The workshop walkthrough: workshop/README.md$($HPC && printf '\n  On the cluster:           workshop/hpc.md')
EOF
