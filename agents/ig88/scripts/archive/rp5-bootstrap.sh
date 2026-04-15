#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# IG-88 Raspberry Pi 5 Bootstrap Script
# One-command setup for autonomous trading analysis
# ═══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/your-org/ig88/main/scripts/rp5-bootstrap.sh | bash
#   # OR
#   ./rp5-bootstrap.sh
#
# Prerequisites:
#   - Raspberry Pi 5 (8GB recommended)
#   - Raspberry Pi OS 64-bit (Bookworm)
#   - Internet connection
#   - sudo access
#
# What this script does:
#   1. Updates system packages
#   2. Installs Node.js 20 LTS
#   3. Installs Claude Code CLI
#   4. Clones/updates ig88 repository
#   5. Installs npm dependencies
#   6. Creates config directories
#   7. Guides Matrix token setup
#   8. Configures cron jobs
#   9. Installs Tailscale (optional)
#   10. Runs verification tests
#
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

REPO_URL="${REPO_URL:-https://github.com/your-org/ig88.git}"
INSTALL_DIR="${HOME}/projects/ig88"
CONFIG_DIR="${HOME}/.config/ig88"
NODE_VERSION="20"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────

log() {
    echo -e "${GREEN}[IG-88]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $*${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

confirm() {
    local prompt="$1"
    local default="${2:-y}"
    local response

    if [[ "${default}" == "y" ]]; then
        read -rp "${prompt} [Y/n]: " response
        response="${response:-y}"
    else
        read -rp "${prompt} [y/N]: " response
        response="${response:-n}"
    fi

    [[ "${response}" =~ ^[Yy] ]]
}

command_exists() {
    command -v "$1" &> /dev/null
}

# ─────────────────────────────────────────────────────────────
# Pre-flight Checks
# ─────────────────────────────────────────────────────────────

# Detect OS type
detect_os() {
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        case "${ID}" in
            ubuntu)
                OS_TYPE="ubuntu"
                OS_VERSION="${VERSION_ID}"
                ;;
            debian|raspbian)
                OS_TYPE="debian"
                OS_VERSION="${VERSION_ID}"
                ;;
            *)
                OS_TYPE="unknown"
                OS_VERSION=""
                ;;
        esac
    else
        OS_TYPE="unknown"
        OS_VERSION=""
    fi
    export OS_TYPE OS_VERSION
}

preflight() {
    header "Pre-flight Checks"

    # Check architecture
    local arch
    arch=$(uname -m)
    if [[ "${arch}" != "aarch64" && "${arch}" != "arm64" && "${arch}" != "x86_64" ]]; then
        error "Unsupported architecture: ${arch}"
        exit 1
    fi
    log "Architecture: ${arch}"

    # Detect and log OS
    detect_os
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        log "OS: ${PRETTY_NAME}"
    fi

    if [[ "${OS_TYPE}" == "ubuntu" ]]; then
        log "Detected Ubuntu ${OS_VERSION}"
        if [[ "${OS_VERSION}" != "24.04" && "${OS_VERSION}" != "24.10" ]]; then
            warn "Ubuntu ${OS_VERSION} detected. Recommended: 24.04 LTS"
        fi
    elif [[ "${OS_TYPE}" == "debian" ]]; then
        log "Detected Debian/Raspberry Pi OS"
    else
        warn "Unknown OS type. Proceeding with generic Debian/Ubuntu steps."
    fi

    # Check sudo access
    if ! sudo -n true 2>/dev/null; then
        log "This script requires sudo access for package installation."
        sudo -v
    fi

    # Check internet connectivity
    if ! ping -c 1 -W 5 8.8.8.8 &> /dev/null; then
        error "No internet connection detected"
        exit 1
    fi
    log "Internet connectivity: OK"
}

# ─────────────────────────────────────────────────────────────
# Step 1: System Updates
# ─────────────────────────────────────────────────────────────

update_system() {
    header "Step 1: System Updates"

    log "Updating package lists..."
    sudo apt-get update

    if [[ "${OS_TYPE}" == "ubuntu" ]]; then
        log "Running full upgrade (Ubuntu)..."
        sudo apt-get full-upgrade -y

        # Disable Ubuntu Pro spam
        if command_exists pro; then
            sudo pro config set apt_news=false 2>/dev/null || true
        fi
    else
        log "Running upgrade (Debian/Raspberry Pi OS)..."
        sudo apt-get upgrade -y
    fi

    log "Installing essential packages..."
    sudo apt-get install -y \
        git \
        curl \
        wget \
        jq \
        htop \
        tmux \
        build-essential \
        ca-certificates \
        gnupg

    # Verify jq installed (critical for Matrix JSON)
    if ! command_exists jq; then
        error "jq installation failed - required for Matrix alerts"
        exit 1
    fi

    log "System packages updated"
}

# ─────────────────────────────────────────────────────────────
# Step 2: Node.js Installation
# ─────────────────────────────────────────────────────────────

install_nodejs() {
    header "Step 2: Node.js ${NODE_VERSION} LTS"

    if command_exists node; then
        local current_version
        current_version=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
        if [[ "${current_version}" -ge "${NODE_VERSION}" ]]; then
            log "Node.js v$(node --version) already installed"
            return 0
        fi
    fi

    log "Installing Node.js ${NODE_VERSION} LTS via NodeSource..."
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_VERSION}.x" | sudo -E bash -
    sudo apt-get install -y nodejs

    log "Node.js $(node --version) installed"
    log "npm $(npm --version) installed"
}

# ─────────────────────────────────────────────────────────────
# Step 3: Claude Code Installation
# ─────────────────────────────────────────────────────────────

install_claude_code() {
    header "Step 3: Claude Code CLI"

    if command_exists claude; then
        log "Claude Code already installed: $(claude --version 2>/dev/null || echo 'version unknown')"
    else
        log "Installing Claude Code..."
        curl -fsSL https://claude.ai/install.sh | bash

        # Add to PATH if not already
        if ! echo "$PATH" | grep -q "${HOME}/.claude/bin"; then
            echo 'export PATH="${HOME}/.claude/bin:${PATH}"' >> "${HOME}/.bashrc"
            export PATH="${HOME}/.claude/bin:${PATH}"
        fi

        log "Claude Code installed"
    fi

    # Check authentication
    if ! claude whoami &>/dev/null 2>&1; then
        warn "Claude Code not authenticated"
        echo ""
        echo "Run 'claude login' to authenticate with your Anthropic account"
        echo "or set ANTHROPIC_API_KEY environment variable."
        echo ""
    else
        log "Claude Code authenticated"
    fi
}

# ─────────────────────────────────────────────────────────────
# Step 4: Repository Setup
# ─────────────────────────────────────────────────────────────

setup_repository() {
    header "Step 4: Repository Setup"

    mkdir -p "$(dirname "${INSTALL_DIR}")"

    if [[ -d "${INSTALL_DIR}" ]]; then
        log "Repository exists, updating..."
        cd "${INSTALL_DIR}"
        git pull || warn "Could not pull updates (may be local changes)"
    else
        if [[ -d "/media/${USER}"* ]] && confirm "Clone from USB drive instead of git?"; then
            local usb_path
            read -rp "Enter USB path to ig88 folder: " usb_path
            cp -r "${usb_path}" "${INSTALL_DIR}"
        else
            log "Cloning repository..."
            git clone "${REPO_URL}" "${INSTALL_DIR}"
        fi
    fi

    cd "${INSTALL_DIR}"
    log "Repository ready at ${INSTALL_DIR}"
}

# ─────────────────────────────────────────────────────────────
# Step 5: Dependencies
# ─────────────────────────────────────────────────────────────

install_dependencies() {
    header "Step 5: NPM Dependencies"

    cd "${INSTALL_DIR}/src"

    log "Installing npm packages..."
    npm install

    log "Building TypeScript..."
    npm run build

    log "Dependencies installed and built"
}

# ─────────────────────────────────────────────────────────────
# Step 6: Directory Structure
# ─────────────────────────────────────────────────────────────

setup_directories() {
    header "Step 6: Directory Structure"

    mkdir -p "${CONFIG_DIR}"
    mkdir -p "${INSTALL_DIR}/logs"
    mkdir -p "${INSTALL_DIR}/.claude/validation/cycles"

    chmod 700 "${CONFIG_DIR}"

    log "Created: ${CONFIG_DIR}"
    log "Created: ${INSTALL_DIR}/logs"
    log "Created: ${INSTALL_DIR}/.claude/validation/cycles"

    # Copy example env if not exists
    if [[ ! -f "${CONFIG_DIR}/.env" ]]; then
        if [[ -f "${INSTALL_DIR}/.env.example" ]]; then
            cp "${INSTALL_DIR}/.env.example" "${CONFIG_DIR}/.env"
            log "Created ${CONFIG_DIR}/.env from template"
        fi
    fi

    # Make scripts executable
    chmod +x "${INSTALL_DIR}/scripts/"*.sh

    log "Directory structure ready"
}

# ─────────────────────────────────────────────────────────────
# Step 7: Matrix Token Setup
# ─────────────────────────────────────────────────────────────

setup_matrix() {
    header "Step 7: Matrix Alert Configuration"

    local token_file="${CONFIG_DIR}/matrix_token"

    if [[ -f "${token_file}" ]]; then
        log "Matrix token already configured"
        return 0
    fi

    echo ""
    echo "Matrix is used for receiving trade alerts on your phone."
    echo ""
    echo "To set up Matrix:"
    echo "  1. Install Element app on your phone"
    echo "  2. Create a Matrix account (or use existing)"
    echo "  3. Create a private room for alerts"
    echo "  4. Get your access token from Element settings"
    echo ""

    if ! confirm "Configure Matrix now?"; then
        warn "Skipping Matrix setup. Run this script again or configure manually."
        return 0
    fi

    read -rp "Enter Matrix access token: " matrix_token
    echo "${matrix_token}" > "${token_file}"
    chmod 600 "${token_file}"

    read -rp "Enter Matrix room ID (e.g., !abc123:matrix.org): " room_id
    read -rp "Enter Matrix homeserver URL [https://matrix.org]: " homeserver
    homeserver="${homeserver:-https://matrix.org}"

    # Update .env
    cat >> "${CONFIG_DIR}/.env" << EOF

# Matrix Configuration (added by bootstrap)
MATRIX_HOMESERVER=${homeserver}
MATRIX_ROOM_ID=${room_id}
MATRIX_TOKEN_FILE=${token_file}
MATRIX_ENABLED=true
EOF

    log "Matrix configured"

    # Test the connection
    if confirm "Send test message to verify?"; then
        cd "${INSTALL_DIR}"
        source "${CONFIG_DIR}/.env"
        if node src/dist/matrix.js test 2>/dev/null; then
            log "Test message sent successfully!"
        else
            warn "Test message failed. Check token and room ID."
        fi
    fi
}

# ─────────────────────────────────────────────────────────────
# Step 8: Cron Setup
# ─────────────────────────────────────────────────────────────

setup_cron() {
    header "Step 8: Cron Job Configuration"

    local cron_line_13="0 13 * * * ${INSTALL_DIR}/scripts/run-cycle.sh >> ${INSTALL_DIR}/logs/cron.log 2>&1"
    local cron_line_01="0 1 * * * ${INSTALL_DIR}/scripts/run-cycle.sh >> ${INSTALL_DIR}/logs/cron.log 2>&1"

    echo ""
    echo "IG-88 runs analysis cycles at:"
    echo "  - 13:00 UTC (US market open)"
    echo "  - 01:00 UTC (Asia market open)"
    echo ""

    if ! confirm "Add cron jobs for scheduled cycles?"; then
        warn "Skipping cron setup. Add manually with 'crontab -e'."
        return 0
    fi

    # Check if already configured
    if crontab -l 2>/dev/null | grep -q "ig88.*run-cycle"; then
        log "Cron jobs already configured"
        return 0
    fi

    # Add to crontab
    (crontab -l 2>/dev/null; echo "${cron_line_13}"; echo "${cron_line_01}") | crontab -

    log "Cron jobs added"
    echo ""
    echo "Current crontab:"
    crontab -l | grep ig88
}

# ─────────────────────────────────────────────────────────────
# Step 9: Tailscale (Optional)
# ─────────────────────────────────────────────────────────────

setup_tailscale() {
    header "Step 9: Tailscale (Remote Access)"

    if command_exists tailscale; then
        log "Tailscale already installed"
        if tailscale status &>/dev/null; then
            log "Tailscale connected"
            tailscale ip -4
        else
            warn "Tailscale installed but not connected. Run 'sudo tailscale up'"
        fi
        return 0
    fi

    echo ""
    echo "Tailscale provides secure remote access to your Pi from anywhere."
    echo "This is highly recommended for monitoring and maintenance."
    echo ""

    if ! confirm "Install Tailscale?"; then
        warn "Skipping Tailscale installation"
        return 0
    fi

    log "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh

    log "Starting Tailscale..."
    sudo tailscale up

    log "Tailscale installed and connected"
    echo ""
    echo "Your Tailscale IP:"
    tailscale ip -4
}

# ─────────────────────────────────────────────────────────────
# Step 10: Verification
# ─────────────────────────────────────────────────────────────

verify_installation() {
    header "Step 10: Verification"

    local errors=0

    # Check Node.js
    if command_exists node; then
        log "✓ Node.js $(node --version)"
    else
        error "✗ Node.js not found"
        ((errors++))
    fi

    # Check npm
    if command_exists npm; then
        log "✓ npm $(npm --version)"
    else
        error "✗ npm not found"
        ((errors++))
    fi

    # Check Claude Code
    if command_exists claude; then
        log "✓ Claude Code installed"
    else
        warn "✗ Claude Code not found (optional but recommended)"
    fi

    # Check scanner build
    if [[ -f "${INSTALL_DIR}/src/dist/scanner.js" ]]; then
        log "✓ Scanner built"
    else
        error "✗ Scanner not built"
        ((errors++))
    fi

    # Check config directory
    if [[ -d "${CONFIG_DIR}" ]]; then
        log "✓ Config directory exists"
    else
        error "✗ Config directory missing"
        ((errors++))
    fi

    # Check cron
    if crontab -l 2>/dev/null | grep -q "ig88"; then
        log "✓ Cron jobs configured"
    else
        warn "✗ Cron jobs not configured"
    fi

    # Test scanner (with rate limit awareness)
    echo ""
    log "Testing scanner (may fail if rate limited)..."
    cd "${INSTALL_DIR}/src"
    if timeout 30 node dist/scanner.js 2>&1 | head -20; then
        log "✓ Scanner test passed"
    else
        warn "Scanner test failed (may be rate limited)"
    fi

    echo ""
    if [[ ${errors} -eq 0 ]]; then
        log "═══════════════════════════════════════"
        log "  Installation complete!"
        log "═══════════════════════════════════════"
        echo ""
        echo "Next steps:"
        echo "  1. Run 'claude login' if not authenticated"
        echo "  2. Edit ${CONFIG_DIR}/.env if needed"
        echo "  3. Test with: ${INSTALL_DIR}/scripts/run-cycle.sh"
        echo "  4. Monitor logs: tail -f ${INSTALL_DIR}/logs/cron.log"
        echo ""
    else
        error "═══════════════════════════════════════"
        error "  Installation completed with ${errors} error(s)"
        error "═══════════════════════════════════════"
        exit 1
    fi
}

# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

main() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "     IG-88 Raspberry Pi 5 Bootstrap"
    echo "     Autonomous Trading Analysis System"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    preflight
    update_system
    install_nodejs
    install_claude_code
    setup_repository
    install_dependencies
    setup_directories
    setup_matrix
    setup_cron
    setup_tailscale
    verify_installation
}

main "$@"
