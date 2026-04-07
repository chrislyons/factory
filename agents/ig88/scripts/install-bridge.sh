#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# IG-88 Matrix Bridge Installation Script
# Builds TypeScript and installs systemd service on RP5
# ═══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./install-bridge.sh              # Full install (build + service)
#   ./install-bridge.sh --build      # Build only
#   ./install-bridge.sh --service    # Service install only
#   ./install-bridge.sh --status     # Check service status
#   ./install-bridge.sh --logs       # View service logs
#   ./install-bridge.sh --stop       # Stop the service
#   ./install-bridge.sh --restart    # Restart the service
#
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="${PROJECT_DIR}/src"
SERVICE_NAME="matrix-bridge"
SERVICE_FILE="${SCRIPT_DIR}/matrix-bridge.service"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[INSTALL]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }

# Build TypeScript
build() {
    log "Building TypeScript..."
    cd "${SRC_DIR}"

    # Check for node_modules
    if [[ ! -d "node_modules" ]]; then
        log "Installing dependencies..."
        npm install
    fi

    # Build
    npm run build

    # Verify output
    if [[ -f "dist/matrix-bridge.js" ]]; then
        log "Build successful: dist/matrix-bridge.js"
    else
        error "Build failed: dist/matrix-bridge.js not found"
        exit 1
    fi
}

# Install systemd service
install_service() {
    log "Installing systemd service..."

    # Check if running as root or with sudo
    if [[ $EUID -ne 0 ]]; then
        warn "Not running as root - using sudo for service installation"
    fi

    # Copy service file
    sudo cp "${SERVICE_FILE}" /etc/systemd/system/
    log "Copied service file to /etc/systemd/system/"

    # Reload systemd
    sudo systemctl daemon-reload
    log "Reloaded systemd daemon"

    # Enable service
    sudo systemctl enable "${SERVICE_NAME}"
    log "Enabled ${SERVICE_NAME} service"

    # Start service
    sudo systemctl start "${SERVICE_NAME}"
    log "Started ${SERVICE_NAME} service"

    # Show status
    echo ""
    sudo systemctl status "${SERVICE_NAME}" --no-pager || true
}

# Check prerequisites
check_prereqs() {
    local errors=0

    # Check node
    if ! command -v node &>/dev/null; then
        error "Node.js not found"
        ((errors++))
    else
        info "Node.js: $(node --version)"
    fi

    # Check npm
    if ! command -v npm &>/dev/null; then
        error "npm not found"
        ((errors++))
    fi

    # Check claude CLI
    if ! command -v claude &>/dev/null; then
        error "Claude CLI not found"
        echo "  Install with: npm install -g @anthropic-ai/claude-code"
        ((errors++))
    else
        info "Claude CLI: found"
    fi

    # Check config
    local config_dir="${HOME}/.config/ig88"
    if [[ ! -f "${config_dir}/.env" ]]; then
        warn "Config file not found: ${config_dir}/.env"
    fi

    if [[ ! -f "${config_dir}/matrix_token" ]]; then
        error "Matrix token not found: ${config_dir}/matrix_token"
        ((errors++))
    fi

    if [[ ${errors} -gt 0 ]]; then
        error "Prerequisites check failed"
        exit 1
    fi

    log "Prerequisites check passed"
}

# View logs
view_logs() {
    log "Viewing ${SERVICE_NAME} logs (Ctrl+C to exit)..."
    sudo journalctl -u "${SERVICE_NAME}" -f
}

# Show status
show_status() {
    sudo systemctl status "${SERVICE_NAME}" --no-pager || true
}

# Stop service
stop_service() {
    log "Stopping ${SERVICE_NAME}..."
    sudo systemctl stop "${SERVICE_NAME}"
    log "Service stopped"
}

# Restart service
restart_service() {
    log "Restarting ${SERVICE_NAME}..."
    sudo systemctl restart "${SERVICE_NAME}"
    log "Service restarted"
    sleep 2
    show_status
}

# Full install
full_install() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  IG-88 Matrix Bridge Installation"
    echo "═══════════════════════════════════════"
    echo ""

    check_prereqs
    build
    install_service

    echo ""
    log "Installation complete!"
    echo ""
    info "Useful commands:"
    echo "  View logs:     journalctl -u ${SERVICE_NAME} -f"
    echo "  Stop service:  sudo systemctl stop ${SERVICE_NAME}"
    echo "  Start service: sudo systemctl start ${SERVICE_NAME}"
    echo "  Restart:       sudo systemctl restart ${SERVICE_NAME}"
    echo ""
}

# Test run (without systemd)
test_run() {
    log "Running bridge in test mode (Ctrl+C to stop)..."
    build

    # Load env
    if [[ -f "${HOME}/.config/ig88/.env" ]]; then
        source "${HOME}/.config/ig88/.env"
        export MATRIX_HOMESERVER MATRIX_ROOM_ID MATRIX_TOKEN_FILE
    fi

    cd "${SRC_DIR}"
    node dist/matrix-bridge.js
}

# Main
main() {
    local mode="${1:-full}"

    case "${mode}" in
        --build|-b)
            build
            ;;
        --service|-s)
            install_service
            ;;
        --status)
            show_status
            ;;
        --logs|-l)
            view_logs
            ;;
        --stop)
            stop_service
            ;;
        --restart|-r)
            restart_service
            ;;
        --test|-t)
            test_run
            ;;
        --help|-h)
            echo "Usage: $0 [option]"
            echo ""
            echo "Options:"
            echo "  --build, -b     Build TypeScript only"
            echo "  --service, -s   Install systemd service only"
            echo "  --status        Show service status"
            echo "  --logs, -l      View service logs (follow mode)"
            echo "  --stop          Stop the service"
            echo "  --restart, -r   Restart the service"
            echo "  --test, -t      Run bridge in test mode (foreground)"
            echo "  --help, -h      Show this help"
            echo ""
            echo "Default: full install (build + service)"
            ;;
        *)
            full_install
            ;;
    esac
}

main "$@"
