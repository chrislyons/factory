#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Blackbox Service Installation Script
# Installs systemd services for full auto-start on power loss
# ═══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./install-services.sh          # Install all services
#   ./install-services.sh --check  # Check current status
#   ./install-services.sh --remove # Remove all services
#
# Services installed:
#   - blackbox.target    (orchestration target)
#   - tailscaled.service (already installed by Tailscale)
#   - qdrant.service     (vector database)
#   - ollama.service     (embeddings)
#   - pantalaimon.service (Matrix E2EE proxy)
#   - matrix-coordinator.service (multi-agent coordinator)
#
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICES_DIR="${SCRIPT_DIR}/services"
SYSTEMD_DIR="/etc/systemd/system"

log() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }

# ─────────────────────────────────────────────────────────────
# Check Prerequisites
# ─────────────────────────────────────────────────────────────

check_prerequisites() {
    info "Checking prerequisites..."

    local missing=()

    # Check for required binaries
    command -v node &>/dev/null || missing+=("node")
    command -v tailscale &>/dev/null || missing+=("tailscale")

    # Check for optional binaries (warn but don't fail)
    command -v qdrant &>/dev/null || warn "qdrant not found - service may need adjustment"
    command -v ollama &>/dev/null || warn "ollama not found - service may need adjustment"
    command -v pantalaimon &>/dev/null || warn "pantalaimon not found - service may need adjustment"

    if [[ ${#missing[@]} -gt 0 ]]; then
        error "Missing required binaries: ${missing[*]}"
        exit 1
    fi

    # Check if running as root or with sudo
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root (use sudo)"
        exit 1
    fi

    log "Prerequisites OK"
}

# ─────────────────────────────────────────────────────────────
# Check Status
# ─────────────────────────────────────────────────────────────

check_status() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  Blackbox Service Status"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    local services=(
        "docker"
        "tailscaled"
        "qdrant"
        "ollama"
        "graphiti"
        "pantalaimon"
        "matrix-coordinator"
        "heartbeat"
    )

    printf "%-25s %-12s %-12s %s\n" "SERVICE" "ENABLED" "ACTIVE" "STATUS"
    echo "─────────────────────────────────────────────────────────────────"

    for service in "${services[@]}"; do
        local enabled active status

        if systemctl is-enabled "${service}.service" &>/dev/null; then
            enabled="${GREEN}enabled${NC}"
        else
            enabled="${YELLOW}disabled${NC}"
        fi

        if systemctl is-active "${service}.service" &>/dev/null; then
            active="${GREEN}running${NC}"
            status="$(systemctl show -p SubState --value "${service}.service" 2>/dev/null || echo "unknown")"
        else
            active="${RED}stopped${NC}"
            status="$(systemctl show -p SubState --value "${service}.service" 2>/dev/null || echo "not installed")"
        fi

        printf "%-25s %-22b %-22b %s\n" "$service" "$enabled" "$active" "$status"
    done

    echo ""
    echo "Target status:"
    if systemctl is-active blackbox.target &>/dev/null; then
        echo -e "  blackbox.target: ${GREEN}active${NC}"
    else
        echo -e "  blackbox.target: ${RED}inactive${NC}"
    fi

    echo ""
    echo "Tailscale network:"
    if tailscale status &>/dev/null; then
        tailscale status | head -5
    else
        echo -e "  ${RED}Not connected${NC}"
    fi

    echo ""
}

# ─────────────────────────────────────────────────────────────
# Install Services
# ─────────────────────────────────────────────────────────────

install_services() {
    info "Installing Blackbox services..."

    # Create log directory
    mkdir -p /home/nesbitt/projects/ig88/logs
    chown nesbitt:nesbitt /home/nesbitt/projects/ig88/logs

    # Copy service files
    local services=(
        "blackbox.target"
        "qdrant.service"
        "ollama.service"
        "graphiti.service"
        "pantalaimon.service"
        "matrix-coordinator.service"
        "heartbeat.service"
    )

    for service in "${services[@]}"; do
        if [[ -f "${SERVICES_DIR}/${service}" ]]; then
            cp "${SERVICES_DIR}/${service}" "${SYSTEMD_DIR}/${service}"
            log "Installed ${service}"
        else
            warn "Service file not found: ${service}"
        fi
    done

    # Reload systemd
    systemctl daemon-reload
    log "Systemd daemon reloaded"

    # Enable services
    info "Enabling services..."

    # Docker and Tailscale should already be enabled, but ensure they are
    systemctl enable docker.service 2>/dev/null || warn "docker already enabled or not installed"
    systemctl enable tailscaled.service 2>/dev/null || warn "tailscaled already enabled or not installed"

    # Enable our services
    systemctl enable qdrant.service 2>/dev/null || warn "qdrant.service enable failed"
    systemctl enable ollama.service 2>/dev/null || warn "ollama.service enable failed"
    systemctl enable graphiti.service 2>/dev/null || warn "graphiti.service enable failed"
    systemctl enable pantalaimon.service 2>/dev/null || warn "pantalaimon.service enable failed"
    systemctl enable matrix-coordinator.service 2>/dev/null || warn "matrix-coordinator.service enable failed"
    systemctl enable heartbeat.service 2>/dev/null || warn "heartbeat.service enable failed"

    # Enable the target
    systemctl enable blackbox.target
    log "blackbox.target enabled"

    echo ""
    log "Installation complete!"
    echo ""
    echo "To start all services now:"
    echo "  sudo systemctl start blackbox.target"
    echo ""
    echo "To check status:"
    echo "  ./install-services.sh --check"
    echo ""
    echo "Services will auto-start on boot."
}

# ─────────────────────────────────────────────────────────────
# Remove Services
# ─────────────────────────────────────────────────────────────

remove_services() {
    warn "Removing Blackbox services..."

    # Stop and disable services (reverse order)
    local services=(
        "heartbeat"
        "matrix-coordinator"
        "pantalaimon"
        "graphiti"
        "ollama"
        "qdrant"
    )

    for service in "${services[@]}"; do
        systemctl stop "${service}.service" 2>/dev/null || true
        systemctl disable "${service}.service" 2>/dev/null || true
        rm -f "${SYSTEMD_DIR}/${service}.service"
        log "Removed ${service}.service"
    done

    # Remove target
    systemctl disable blackbox.target 2>/dev/null || true
    rm -f "${SYSTEMD_DIR}/blackbox.target"
    log "Removed blackbox.target"

    systemctl daemon-reload
    log "Services removed"
}

# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

main() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  Blackbox Service Installer"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    case "${1:-}" in
        --check|-c)
            check_status
            ;;
        --remove|-r)
            check_prerequisites
            remove_services
            ;;
        --help|-h)
            echo "Usage: $0 [--check|--remove|--help]"
            echo ""
            echo "Options:"
            echo "  --check   Check current service status"
            echo "  --remove  Remove all Blackbox services"
            echo "  --help    Show this help"
            echo ""
            echo "Without options: Install all services"
            ;;
        *)
            check_prerequisites
            install_services
            check_status
            ;;
    esac
}

main "$@"
