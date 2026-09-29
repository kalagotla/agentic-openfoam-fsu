#!/usr/bin/env bash
#
# One-command setup for the agentic-openfoam workshop.
#
# Windows: open the Ubuntu (WSL2) terminal, clone this repo into your Linux
# home (NOT /mnt/c/...), cd into it, and run:
#
#     ./setup.sh
#
# Linux (Ubuntu 22.04 / 24.04): same command.
#
# What it installs (each step is skipped if already present, so re-running
# is safe and fast):
#   1. System packages: git, curl, build tools, ParaView + Xvfb (renders)
#   2. OpenFOAM v2412 (ESI apt repository) + an `of2412` shell alias
#   3. uv + the four MCP servers' Python environment (uv sync)
#   4. Node.js 22, then the agents: Claude Code (`claude`) and Kilo (`kilo`)
#   5. Ollama + a local model chosen for this machine's GPU/RAM, exposed to
#      the agents as `cfd-local` (see scripts/local-model.sh)
#   6. A health check (scripts/doctor.sh)
#
# Options:
#   --model TAG     use this Ollama model instead of the automatic pick
#   --no-local      skip Ollama and the local model (frontier-only setup)
#   --no-claude     skip Claude Code
#   --no-kilo       skip Kilo
#   -h, --help      show this help
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

OF_VERSION=2412
OF_BASHRC=/usr/lib/openfoam/openfoam${OF_VERSION}/etc/bashrc
NODE_MAJOR=22

MODEL=""
WANT_LOCAL=true
WANT_CLAUDE=true
WANT_KILO=true
while (($#)); do
    case "$1" in
        --model)     MODEL=${2:?--model needs a tag, e.g. qwen3:8b}; shift ;;
        --no-local)  WANT_LOCAL=false ;;
        --no-claude) WANT_CLAUDE=false ;;
        --no-kilo)   WANT_KILO=false ;;
        -h|--help)   sed -n '2,28p' "$0"; exit 0 ;;
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

export PATH="$HOME/.local/bin:$PATH"

# --- 0. Preflight ------------------------------------------------------------
step 0/6 "Checking the machine"
[[ $(uname -s) == Linux ]] || die "This script runs on Linux or Windows WSL2. On Windows, open the Ubuntu (WSL) terminal first — see docs/setup-wsl.md."
have apt-get || die "apt-get not found. setup.sh supports Ubuntu 22.04/24.04 (native or WSL2)."
[[ $EUID -eq 0 ]] && die "Run as your normal user, not root (sudo is requested when needed)."

IS_WSL=false
grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=true
if $IS_WSL && [[ $REPO_DIR == /mnt/* ]]; then
    die "The repo is on the Windows drive ($REPO_DIR). OpenFOAM breaks on NTFS and it is 10x slower.
       Clone it into your Linux home instead:
         cd ~ && git clone <repo-url> && cd <repo> && ./setup.sh"
fi

. /etc/os-release
say "OS: $PRETTY_NAME$($IS_WSL && echo ' (WSL2)')"
case "${VERSION_ID:-}" in
    22.04|24.04) ;;
    *) warn "Tested on Ubuntu 22.04/24.04; ${PRETTY_NAME} may work but is untested." ;;
esac

say "sudo is needed for system packages — you may be asked for your Linux password."
sudo -v || die "sudo failed."

# --- 1. System packages ------------------------------------------------------
step 1/6 "System packages"
PKGS=(ca-certificates curl wget git build-essential python3 python3-venv zstd xvfb paraview)
# python3-paraview is split out on 24.04; on 22.04 the bindings ship inside paraview.
apt-cache show python3-paraview >/dev/null 2>&1 && PKGS+=(python3-paraview)
missing=()
for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
if ((${#missing[@]})); then
    say "Installing: ${missing[*]}"
    quiet sudo apt-get update
    quiet sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}" \
        || die "apt-get install failed."
fi
ok "system packages"

# Ubuntu's ParaView is an X11 build. Without a display (plain WSL2 on
# Windows 10, SSH, CI) pvbatch cannot open a window, so route it through a
# throwaway Xvfb server. ~/.local/bin precedes /usr/bin on PATH.
if [[ -z ${DISPLAY:-} && ! -e $HOME/.local/bin/pvbatch ]]; then
    mkdir -p "$HOME/.local/bin"
    printf '#!/usr/bin/env bash\nexec xvfb-run -a /usr/bin/pvbatch "$@"\n' >"$HOME/.local/bin/pvbatch"
    chmod +x "$HOME/.local/bin/pvbatch"
    ok "headless pvbatch wrapper (~/.local/bin/pvbatch)"
fi

# --- 2. OpenFOAM -------------------------------------------------------------
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

# Shell conveniences, added once between markers so re-runs don't duplicate.
MARK_BEGIN="# >>> agentic-openfoam >>>"
if ! grep -qF "$MARK_BEGIN" "$HOME/.bashrc" 2>/dev/null; then
    cat >>"$HOME/.bashrc" <<EOF

$MARK_BEGIN
case ":\$PATH:" in *":\$HOME/.local/bin:"*) ;; *) export PATH="\$HOME/.local/bin:\$PATH" ;; esac
alias of${OF_VERSION}='source ${OF_BASHRC}'
# <<< agentic-openfoam <<<
EOF
    ok "added ~/.local/bin to PATH and the 'of${OF_VERSION}' alias to ~/.bashrc"
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
if ($WANT_CLAUDE || $WANT_KILO) && ! node_ok; then
    say "Installing Node.js ${NODE_MAJOR} (NodeSource)…"
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | quiet sudo -E bash - \
        || die "Could not add the NodeSource repository."
    quiet sudo apt-get install -y nodejs || die "Node.js install failed."
fi
if have npm; then
    # Global npm installs go to ~/.local so they never need sudo.
    prefix=$(npm config get prefix)
    if [[ ! -w $prefix ]]; then
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
if $WANT_LOCAL; then
    if ! have ollama; then
        say "Installing Ollama…"
        curl -fsSL https://ollama.com/install.sh | quiet sh || die "Ollama install failed."
    fi
    ok "Ollama $(ollama --version 2>/dev/null | awk '{print $NF}')"
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

  The workshop walkthrough: workshop/README.md
EOF
