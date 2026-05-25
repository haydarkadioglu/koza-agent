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
ZIP_URL="https://github.com/haydarkadioglu/koza-agent/archive/refs/heads/main.zip"
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

# ── Check git (optional) ─────────────────────────────────────────────────────
HAS_GIT=false
if command -v git &>/dev/null; then
    HAS_GIT=true
    success "git found: $(git --version)"
else
    warn "git not found — will use ZIP download instead."
fi

# ── Clone, update, or download ZIP ───────────────────────────────────────────
if [[ "$HAS_GIT" == true ]]; then
    if [[ -d "${INSTALL_DIR}/.git" ]]; then
        info "Updating existing install at ${INSTALL_DIR} …"
        git -C "${INSTALL_DIR}" pull --ff-only --quiet
        success "Repository updated."
    else
        [[ -d "${INSTALL_DIR}" ]] && rm -rf "${INSTALL_DIR}"
        info "Cloning koza-agent into ${INSTALL_DIR} …"
        git clone --depth=1 "${REPO_URL}" "${INSTALL_DIR}"
        success "Repository cloned."
    fi
else
    info "Downloading koza-agent as ZIP …"
    TMP_ZIP="/tmp/koza-agent.zip"
    TMP_EXTRACT="/tmp/koza-agent-extract"
    if command -v curl &>/dev/null; then
        curl -fsSL "${ZIP_URL}" -o "${TMP_ZIP}"
    elif command -v wget &>/dev/null; then
        wget -q "${ZIP_URL}" -O "${TMP_ZIP}"
    else
        error "Neither curl nor wget found. Install one of them first."
    fi
    rm -rf "${TMP_EXTRACT}"
    mkdir -p "${TMP_EXTRACT}"
    unzip -q "${TMP_ZIP}" -d "${TMP_EXTRACT}"
    [[ -d "${INSTALL_DIR}" ]] && rm -rf "${INSTALL_DIR}"
    mv "${TMP_EXTRACT}"/koza-agent-main "${INSTALL_DIR}"
    rm -f "${TMP_ZIP}"
    rm -rf "${TMP_EXTRACT}"
    success "Downloaded and extracted to ${INSTALL_DIR}"
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

# ── Install package ──────────────────────────────────────────────────────────
info "Installing Koza and dependencies (this may take a minute) …"
"${VENV_PIP}" install --quiet --upgrade pip
"${VENV_PIP}" install --quiet -e "${INSTALL_DIR}"
success "Koza installed."

# ── Install optional Telegram dep ───────────────────────────────────────────
info "Installing optional dependencies (telegram bot) …"
"${VENV_PIP}" install --quiet "python-telegram-bot>=20.0" || warn "python-telegram-bot install failed (optional, Telegram bot won't work)"

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
    PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
    for rc in "${HOME}/.bashrc" "${HOME}/.zshrc" "${HOME}/.profile"; do
        if [[ -f "$rc" ]] && ! grep -q '\.local/bin' "$rc" 2>/dev/null; then
            echo "$PATH_LINE" >> "$rc"
            dim "Added ~/.local/bin to PATH in ${rc}"
        fi
    done
    # Apply to current session immediately
    export PATH="$HOME/.local/bin:$PATH"
    warn "~/.local/bin/koza created. If 'koza' is not found, run:  source ~/.bashrc  (or restart your shell)"
fi

# ── Verify koza is accessible ────────────────────────────────────────────────
if command -v koza &>/dev/null; then
    success "koza command is available: $(command -v koza)"
else
    warn "koza is installed but not in current PATH."
    echo -e "${GREY}      Run one of:${RESET}"
    echo -e "${GREY}        source ~/.bashrc${RESET}"
    echo -e "${GREY}        export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
    echo -e "${GREY}      Then try: koza${RESET}"
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
