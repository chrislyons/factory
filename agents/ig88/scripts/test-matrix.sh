#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# IG-88 Matrix Alert Test Script
# Tests Matrix connectivity and message sending
# ═══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./test-matrix.sh              # Send test message
#   ./test-matrix.sh --trade      # Send fake trade alert
#   ./test-matrix.sh --error      # Send fake error notification
#   ./test-matrix.sh --daily      # Send fake daily summary
#   ./test-matrix.sh --all        # Send all test message types
#
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_DIR="${HOME}/.config/ig88"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[TEST]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Load environment
load_env() {
    if [[ -f "${CONFIG_DIR}/.env" ]]; then
        source "${CONFIG_DIR}/.env"
        log "Loaded config from ${CONFIG_DIR}/.env"
    else
        warn "No .env file found at ${CONFIG_DIR}/.env"
    fi
}

# Check prerequisites
check_prereqs() {
    local errors=0

    # Check jq
    if ! command -v jq &>/dev/null; then
        error "jq not found. Install with: sudo apt install jq"
        ((errors++))
    fi

    # Check curl
    if ! command -v curl &>/dev/null; then
        error "curl not found. Install with: sudo apt install curl"
        ((errors++))
    fi

    # Check token file
    local token_file="${MATRIX_TOKEN_FILE:-${CONFIG_DIR}/matrix_token}"
    if [[ ! -f "${token_file}" ]]; then
        error "Matrix token file not found: ${token_file}"
        echo ""
        echo "To create it:"
        echo "  echo 'YOUR_TOKEN' > ${token_file}"
        echo "  chmod 600 ${token_file}"
        ((errors++))
    fi

    # Check room ID
    if [[ -z "${MATRIX_ROOM_ID:-}" ]]; then
        error "MATRIX_ROOM_ID not set"
        echo ""
        echo "Set it in ${CONFIG_DIR}/.env:"
        echo "  MATRIX_ROOM_ID=!roomid:matrix.org"
        ((errors++))
    fi

    if [[ ${errors} -gt 0 ]]; then
        exit 1
    fi
}

# Send a raw message
send_message() {
    local message="$1"
    local token_file="${MATRIX_TOKEN_FILE:-${CONFIG_DIR}/matrix_token}"
    local token
    token=$(cat "${token_file}")
    local homeserver="${MATRIX_HOMESERVER:-https://matrix.org}"
    local room_id="${MATRIX_ROOM_ID}"

    local txn_id="ig88_test_$(date +%s)_$$"
    local url="${homeserver}/_matrix/client/r0/rooms/$(printf '%s' "${room_id}" | jq -sRr @uri)/send/m.room.message/${txn_id}"

    local payload
    payload=$(jq -n --arg body "${message}" '{"msgtype":"m.text","body":$body}')

    local response
    response=$(curl -s -w "\n%{http_code}" -X PUT "${url}" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "${payload}")

    local http_code
    http_code=$(echo "${response}" | tail -1)
    local body
    body=$(echo "${response}" | head -n -1)

    if [[ "${http_code}" == "200" ]]; then
        log "Message sent successfully"
        return 0
    else
        error "Failed to send message (HTTP ${http_code})"
        echo "${body}" | jq . 2>/dev/null || echo "${body}"
        return 1
    fi
}

# Test: Basic connectivity
test_basic() {
    log "Sending basic test message..."

    local message="🤖 IG-88 Matrix Test
═══════════════════════
Time: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Host: $(hostname)
Status: Matrix integration working

This is a test message from IG-88.
═══════════════════════"

    send_message "${message}"
}

# Test: Trade alert format
test_trade() {
    log "Sending fake trade alert..."

    local message="🚨 IG-88 TRADE SIGNAL [TEST]
═══════════════════════
Cycle: C999
Token: TESTTOKEN (Test Token)

📍 Entry: \$0.001234
🛑 Stop Loss: \$0.001111
🎯 Take Profit: \$0.001600
💰 Position: \$150.00
📊 R:R: 3.0:1
🔥 Conviction: 75%

Reasoning: TEST - This is a test trade alert

⚠️ This is a TEST message - not a real signal
═══════════════════════"

    send_message "${message}"
}

# Test: Error notification
test_error() {
    log "Sending fake error notification..."

    local message="⚠️ IG-88 ERROR [TEST]
═══════════════════════
Component: test-matrix
Error: This is a test error message
Context: Testing error notification format
Time: $(date -u +"%Y-%m-%d %H:%M:%S UTC")

⚠️ This is a TEST message - not a real error
═══════════════════════"

    send_message "${message}"
}

# Test: Daily summary
test_daily() {
    log "Sending fake daily summary..."

    local message="📊 IG-88 DAILY SUMMARY [TEST]
═══════════════════════
Date: $(date -u +"%Y-%m-%d")
Cycles Run: 2
Trade Signals: 0
Dominant Regime: UNCERTAIN

Notes:
• This is a test daily summary
• No actual trades were analyzed
• System is functioning normally

⚠️ This is a TEST message
═══════════════════════"

    send_message "${message}"
}

# Verify configuration
verify_config() {
    echo ""
    log "Configuration:"
    echo "  Homeserver: ${MATRIX_HOMESERVER:-https://matrix.org}"
    echo "  Room ID: ${MATRIX_ROOM_ID:-NOT SET}"
    echo "  Token file: ${MATRIX_TOKEN_FILE:-${CONFIG_DIR}/matrix_token}"
    echo ""

    # Verify token with whoami
    local token_file="${MATRIX_TOKEN_FILE:-${CONFIG_DIR}/matrix_token}"
    local token
    token=$(cat "${token_file}")
    local homeserver="${MATRIX_HOMESERVER:-https://matrix.org}"

    log "Verifying token..."
    local whoami
    whoami=$(curl -s "${homeserver}/_matrix/client/r0/account/whoami" \
        -H "Authorization: Bearer ${token}")

    if echo "${whoami}" | jq -e '.user_id' &>/dev/null; then
        log "Token valid for: $(echo "${whoami}" | jq -r '.user_id')"
    else
        error "Token verification failed"
        echo "${whoami}" | jq . 2>/dev/null || echo "${whoami}"
        exit 1
    fi
    echo ""
}

# Main
main() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  IG-88 Matrix Alert Test"
    echo "═══════════════════════════════════════"
    echo ""

    load_env
    check_prereqs
    verify_config

    local mode="${1:-basic}"

    case "${mode}" in
        --trade|-t)
            test_trade
            ;;
        --error|-e)
            test_error
            ;;
        --daily|-d)
            test_daily
            ;;
        --all|-a)
            test_basic && sleep 1
            test_trade && sleep 1
            test_error && sleep 1
            test_daily
            ;;
        *)
            test_basic
            ;;
    esac

    echo ""
    log "Test complete. Check Element for messages."
}

main "$@"
