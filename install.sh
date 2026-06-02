#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Koza Agent — Linux/macOS installer
#  Usage:
#    curl -fsSL https://raw.githubusercontent.com/haydarkadioglu/koza-agent/main/install.sh | bash
#  Or locally:
#    chmod +x install.sh && ./install.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="https://github.com/haydarkadioglu/koza-agent.git"
INSTALL_DIR="${HOME}/.koza-agent"
BIN_LINK="/usr/local/bin/koza"
VENV_DIR="${INSTALL_DIR}/.venv"

# ── Colors ───────────────────────────────────────────────────────────────────
TEAL="\033[38;5;43m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
GREY="\033[0;90m"
BOLD="\033[1m"
RESET="\033[0m"

info()    { echo -e "${TEAL}  ▸  $*${RESET}"; }
success() { echo -e "${GREEN}  ✓  $*${RESET}"; }
warn()    { echo -e "${YELLOW}  ⚠  $*${RESET}"; }
error()   { echo -e "${RED}  ✗  $*${RESET}" >&2; exit 1; }
dim()     { echo -e "${GREY}      $*${RESET}"; }

# ── Banner ───────────────────────────────────────────────────────────────────
echo -e "${TEAL}${BOLD}"
cat << 'EOF'
   ██╗  ██╗ ██████╗ ███████╗ █████╗
   ██║ ██╔╝██╔═══██╗╚══███╔╝██╔══██╗
   █████╔╝ ██║   ██║  ███╔╝ ███████║
   ██╔═██╗ ██║   ██║ ███╔╝  ██╔══██║
   ██║  ██╗╚██████╔╝███████╗██║  ██║
   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝
EOF
echo -e "${RESET}"
echo -e "${BOLD}  Koza Agent Installer${RESET}"
echo -e "${GREY}  ─────────────────────────────────────────${RESET}"
echo ""

# ── Check Python ─────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=${ver%%.*}
        minor=${ver##*.}
        if [[ $major -ge 3 && $minor -ge 11 ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

[[ -z "$PYTHON" ]] && error "Python 3.11+ not found. Install it first:\n      sudo apt install python3.12  (Debian/Ubuntu)\n      brew install python@3.12     (macOS)"
success "Python found: $($PYTHON --version)"

# ── Check git ────────────────────────────────────────────────────────────────
command -v git &>/dev/null || error "git not found. Install: sudo apt install git"
success "git found: $(git --version)"

# ── Clone or update ──────────────────────────────────────────────────────────
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Updating existing install at ${INSTALL_DIR} …"
    git -C "${INSTALL_DIR}" pull --ff-only --quiet
    success "Repository updated."
else
    info "Cloning koza-agent into ${INSTALL_DIR} …"
    git clone --depth=1 "${REPO_URL}" "${INSTALL_DIR}"
    success "Repository cloned."
fi

# ── Create virtual environment ───────────────────────────────────────────────
if [[ ! -d "${VENV_DIR}" ]]; then
    info "Creating virtual environment …"
    "$PYTHON" -m venv "${VENV_DIR}"
    success "Virtualenv created at ${VENV_DIR}"
else
    dim "Virtualenv already exists, skipping."
fi

VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"

# ── Ensure pip is available in the venv ──────────────────────────────────────
if [[ ! -f "${VENV_PIP}" ]]; then
    warn "pip not found in venv — attempting to bootstrap with ensurepip …"
    "${VENV_PYTHON}" -m ensurepip --upgrade 2>/dev/null || true
fi

# If still missing, recreate the venv from scratch
if [[ ! -f "${VENV_PIP}" ]]; then
    warn "Bootstrapping failed — recreating virtualenv …"
    rm -rf "${VENV_DIR}"
    "$PYTHON" -m venv --copies "${VENV_DIR}"
    success "Virtualenv recreated."
fi

[[ ! -f "${VENV_PIP}" ]] && error "Cannot create a virtualenv with pip.\n      Try: sudo apt install python3-venv python3-pip"

# ── Low-memory install mode ──────────────────────────────────────────────────
# Tiny VPS instances can kill pip while resolving/installing the full optional
# stack. In that case, install Koza editable with no deps and add only the core
# runtime dependencies. Heavy tools remain available after manual pip install.
mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
swap_kb="$(awk '/SwapTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
LOW_MEMORY_INSTALL="${KOZA_LIGHT_INSTALL:-auto}"
if [[ "${LOW_MEMORY_INSTALL}" == "auto" ]]; then
    if [[ "${mem_kb:-0}" -lt 1100000 || ( "${mem_kb:-0}" -lt 1800000 && "${swap_kb:-0}" -lt 524288 ) ]]; then
        LOW_MEMORY_INSTALL="1"
    else
        LOW_MEMORY_INSTALL="0"
    fi
fi

# ── Install package ──────────────────────────────────────────────────────────
info "Installing Koza and dependencies (this may take a minute) …"
PIP_FLAGS=(--quiet --no-cache-dir --prefer-binary)

if ! "${VENV_PIP}" install "${PIP_FLAGS[@]}" --upgrade pip; then
    error "pip upgrade failed."
fi

if [[ "${LOW_MEMORY_INSTALL}" == "1" ]]; then
    warn "Low-memory system detected (${mem_kb} KiB RAM, ${swap_kb} KiB swap). Installing core dependencies only."
    CORE_DEPS=(
        "setuptools>=68"
        "wheel"
        "prompt_toolkit>=3.0.0"
        "openai>=1.30.0"
        "anthropic>=0.28.0"
        "requests>=2.31.0"
        "apscheduler>=3.10.4"
        "psutil>=5.9.8"
        "pyyaml>=6.0.1"
        "python-dotenv>=1.0.1"
        "packaging>=23.0"
        "pygments>=2.17.0"
        "orjson>=3.9.0"
    )
    if ! "${VENV_PIP}" install "${PIP_FLAGS[@]}" "${CORE_DEPS[@]}"; then
        warn "Core dependency install failed. If the previous line says 'Killed', add swap and rerun."
        dim "  fallocate -l 4G /swapfile && chmod 600 /swapfile"
        dim "  mkswap /swapfile && swapon /swapfile"
        exit 1
    fi
    if ! "${VENV_PIP}" install "${PIP_FLAGS[@]}" --no-deps -e "${INSTALL_DIR}"; then
        error "Koza editable install failed."
    fi
    warn "Optional heavy features were skipped: TUI/Textual, data science, browser automation, media downloads, some Google/Gemini helpers."
    dim "Install them later inside the venv if needed."
elif ! "${VENV_PIP}" install "${PIP_FLAGS[@]}" -e "${INSTALL_DIR}"; then
    warn "pip install failed. If the previous line says 'Killed', the server likely ran out of RAM/swap."
    dim "Check memory: free -h"
    dim "Temporary swap fix:"
    dim "  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile"
    dim "  sudo mkswap /swapfile && sudo swapon /swapfile"
    dim "Then rerun the installer."
    exit 1
fi
success "Koza installed."

# ── Install optional Telegram dep ───────────────────────────────────────────
if [[ "${LOW_MEMORY_INSTALL}" == "1" && "${KOZA_INSTALL_TELEGRAM:-0}" != "1" ]]; then
    warn "Skipping optional Telegram dependency in low-memory mode."
    dim "Install later with: ${VENV_PIP} install --no-cache-dir --prefer-binary 'python-telegram-bot>=20.0'"
else
    info "Installing optional dependencies (telegram bot) …"
    "${VENV_PIP}" install "${PIP_FLAGS[@]}" "python-telegram-bot>=20.0" || warn "python-telegram-bot install failed (optional, Telegram bot won't work)"
fi

# ── koza entry point (created by pip install -e .) ───────────────────────────
VENV_KOZA="${VENV_DIR}/bin/koza"

# Verify the entry point was created
if [[ ! -f "${VENV_KOZA}" ]]; then
    error "pip install did not create '${VENV_KOZA}'. Check pyproject.toml [project.scripts]."
fi
chmod +x "${VENV_KOZA}"

# Helper: symlink koza to a bin directory
install_bin() {
    local target="$1"
    mkdir -p "$(dirname "$target")"
    ln -sf "${VENV_KOZA}" "$target"
    success "Command linked: ${target}"
}

if [[ -w "/usr/local/bin" ]]; then
    install_bin "${BIN_LINK}"
elif sudo -n true 2>/dev/null; then
    sudo ln -sf "${VENV_KOZA}" "${BIN_LINK}"
    success "Command linked (sudo): ${BIN_LINK}"
else
    LOCAL_BIN="${HOME}/.local/bin/koza"
    install_bin "${LOCAL_BIN}"
    # Add ~/.local/bin to PATH if missing
    for rc in "${HOME}/.bashrc" "${HOME}/.zshrc" "${HOME}/.profile"; do
        if [[ -f "$rc" ]] && ! grep -q '\.local/bin' "$rc" 2>/dev/null; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
            dim "Added ~/.local/bin to PATH in ${rc}"
        fi
    done
    warn "~/.local/bin/koza created. Restart your shell or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${TEAL}${BOLD}  ─────────────────────────────────────────${RESET}"
echo -e "${GREEN}${BOLD}  Koza Agent installed!${RESET}"
echo -e "${TEAL}${BOLD}  ─────────────────────────────────────────${RESET}"
echo ""
echo -e "  Run ${BOLD}koza${RESET} to start."
echo -e "${GREY}  Setup wizard will run on first launch.${RESET}"
echo ""
