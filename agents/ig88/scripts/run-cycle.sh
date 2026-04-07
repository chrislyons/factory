#!/bin/bash
# IG-88 Analysis Cycle Runner
# Orchestrates: Scanner → Claude Analysis → Matrix Alerts
#
# Exit codes:
#   0 = Cycle complete, no trade
#   1 = Cycle complete, trade signal sent
#   2 = Error (logged, Matrix notified if possible)

set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_DIR="${HOME}/.config/ig88"
LOG_DIR="${PROJECT_DIR}/logs"
VALIDATION_DIR="${PROJECT_DIR}/.claude/validation/cycles"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
DATE=$(date -u +"%Y-%m-%d")

# Load environment if exists
[[ -f "${CONFIG_DIR}/.env" ]] && source "${CONFIG_DIR}/.env"

# Defaults
MATRIX_ENABLED="${MATRIX_ENABLED:-true}"
MAX_RETRIES="${MAX_RETRIES:-2}"
RETRY_DELAY="${RETRY_DELAY:-30}"  # seconds

# ─────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────

log() {
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] $*" | tee -a "${LOG_DIR}/cycle.log"
}

error() {
    log "ERROR: $*" >&2
}

# Send Matrix notification (best effort)
matrix_notify() {
    local message="$1"
    local msgtype="${2:-m.text}"

    if [[ "${MATRIX_ENABLED}" != "true" ]]; then
        return 0
    fi

    local token_file="${MATRIX_TOKEN_FILE:-${CONFIG_DIR}/matrix_token}"
    if [[ ! -f "${token_file}" ]]; then
        log "Matrix token file not found, skipping notification"
        return 0
    fi

    local token
    token=$(cat "${token_file}")
    local homeserver="${MATRIX_HOMESERVER:-https://matrix.org}"
    local room_id="${MATRIX_ROOM_ID:-}"

    if [[ -z "${room_id}" ]]; then
        log "MATRIX_ROOM_ID not set, skipping notification"
        return 0
    fi

    local txn_id="ig88_$(date +%s)_$$"
    local url="${homeserver}/_matrix/client/r0/rooms/$(printf '%s' "${room_id}" | jq -sRr @uri)/send/m.room.message/${txn_id}"

    local payload
    payload=$(jq -n --arg body "${message}" '{"msgtype":"m.text","body":$body}')

    curl -s -X PUT "${url}" \
        -H "Authorization: Bearer ${token}" \
        -H "Content-Type: application/json" \
        -d "${payload}" > /dev/null 2>&1 || true
}

# Clean up on exit
cleanup() {
    local exit_code=$?
    if [[ ${exit_code} -eq 2 ]]; then
        matrix_notify "⚠️ IG-88 cycle failed with error. Check logs."
    fi
}
trap cleanup EXIT

# ─────────────────────────────────────────────────────────────
# Pre-flight Checks
# ─────────────────────────────────────────────────────────────

preflight() {
    mkdir -p "${LOG_DIR}" "${VALIDATION_DIR}"

    # Check Node.js
    if ! command -v node &> /dev/null; then
        error "Node.js not found"
        exit 2
    fi

    # Check scanner is built
    if [[ ! -f "${PROJECT_DIR}/src/dist/scanner.js" ]]; then
        log "Scanner not built, attempting build..."
        cd "${PROJECT_DIR}/src" && npm run build || {
            error "Failed to build scanner"
            exit 2
        }
    fi

    # Check Claude Code (for autonomous analysis)
    if ! command -v claude &> /dev/null; then
        log "Warning: Claude Code not found, LLM analysis will be skipped"
    fi
}

# ─────────────────────────────────────────────────────────────
# Scanner Phase
# ─────────────────────────────────────────────────────────────

run_scanner() {
    local attempt=1
    local scan_output=""
    local exit_code=0

    while [[ ${attempt} -le ${MAX_RETRIES} ]]; do
        log "Running scanner (attempt ${attempt}/${MAX_RETRIES})..."

        cd "${PROJECT_DIR}/src"
        scan_output=$(node dist/scanner.js 2>&1) && exit_code=0 || exit_code=$?

        # Check for rate limit (CoinGecko returns 429)
        if echo "${scan_output}" | grep -q "429\|rate limit"; then
            log "Rate limited, waiting ${RETRY_DELAY}s..."
            sleep "${RETRY_DELAY}"
            ((attempt++))
            continue
        fi

        break
    done

    if [[ ${attempt} -gt ${MAX_RETRIES} ]]; then
        error "Scanner failed after ${MAX_RETRIES} attempts"
        matrix_notify "⚠️ IG-88 scanner failed: rate limit exceeded"
        exit 2
    fi

    echo "${scan_output}"
    return ${exit_code}
}

# ─────────────────────────────────────────────────────────────
# Parse Scanner Output
# ─────────────────────────────────────────────────────────────

parse_scanner() {
    local output="$1"

    CYCLE_ID=$(echo "${output}" | grep "SCAN CYCLE" | awk '{print $4}' || echo "UNKNOWN")
    SIGNAL=$(echo "${output}" | grep "^Signal:" | awk '{print $2}' || echo "NO_TRADE")
    ESCALATE=$(echo "${output}" | grep "^Escalate" | awk '{print $4}' || echo "NO")
    REGIME=$(echo "${output}" | grep "^Status:" | awk '{print $2}' || echo "UNKNOWN")
    TOP_CANDIDATE=$(echo "${output}" | grep -A1 "── CANDIDATES ──" | tail -1 | awk '{print $1}' || echo "")

    export CYCLE_ID SIGNAL ESCALATE REGIME TOP_CANDIDATE
}

# ─────────────────────────────────────────────────────────────
# LLM Analysis Phase (optional)
# ─────────────────────────────────────────────────────────────

run_llm_analysis() {
    local candidate="$1"

    if ! command -v claude &> /dev/null; then
        log "Claude Code not available, skipping LLM analysis"
        return 1
    fi

    log "Escalating to Claude for narrative analysis of ${candidate}..."

    local prompt_file="${PROJECT_DIR}/.claude/agents/autonomous-cycle.md"
    if [[ ! -f "${prompt_file}" ]]; then
        error "Autonomous cycle prompt not found: ${prompt_file}"
        return 1
    fi

    local llm_output
    llm_output=$(claude -p "$(cat "${prompt_file}")" --output-format json 2>&1) || {
        error "Claude analysis failed"
        return 1
    }

    echo "${llm_output}"
}

# ─────────────────────────────────────────────────────────────
# Log Cycle Results
# ─────────────────────────────────────────────────────────────

log_cycle() {
    local scan_output="$1"
    local llm_output="${2:-}"

    local log_file="${VALIDATION_DIR}/${CYCLE_ID:-UNKNOWN}_${DATE}.md"

    cat > "${log_file}" << EOF
# Analysis Cycle ${CYCLE_ID}

**Timestamp**: ${TIMESTAMP}
**Regime**: ${REGIME}
**Signal**: ${SIGNAL}
**Top Candidate**: ${TOP_CANDIDATE:-None}

## Scanner Output

\`\`\`
${scan_output}
\`\`\`

EOF

    if [[ -n "${llm_output}" ]]; then
        cat >> "${log_file}" << EOF
## LLM Analysis

\`\`\`json
${llm_output}
\`\`\`

EOF
    fi

    cat >> "${log_file}" << EOF
---
*Generated by run-cycle.sh*
EOF

    log "Logged to: ${log_file}"
}

# ─────────────────────────────────────────────────────────────
# Send Trade Alert
# ─────────────────────────────────────────────────────────────

send_trade_alert() {
    local llm_output="$1"

    # Parse trade parameters from LLM JSON output
    local entry stop_loss take_profit position_size
    entry=$(echo "${llm_output}" | jq -r '.trade.entry // empty')
    stop_loss=$(echo "${llm_output}" | jq -r '.trade.stopLoss // empty')
    take_profit=$(echo "${llm_output}" | jq -r '.trade.takeProfit // empty')
    position_size=$(echo "${llm_output}" | jq -r '.trade.positionSize // empty')

    if [[ -z "${entry}" ]]; then
        log "No trade parameters in LLM output"
        return 1
    fi

    local alert_message
    alert_message=$(cat << EOF
🚨 IG-88 TRADE SIGNAL
═══════════════════════
Cycle: ${CYCLE_ID}
Token: ${TOP_CANDIDATE}

📍 Entry: \$${entry}
🛑 Stop Loss: \$${stop_loss}
🎯 Take Profit: \$${take_profit}
💰 Position: \$${position_size}

⚠️ Paper trade only - validation phase
═══════════════════════
EOF
)

    matrix_notify "${alert_message}"
    log "Trade alert sent for ${TOP_CANDIDATE}"
}

# ─────────────────────────────────────────────────────────────
# Main Execution
# ─────────────────────────────────────────────────────────────

main() {
    log "═══════════════════════════════════════"
    log "Starting IG-88 analysis cycle"
    log "═══════════════════════════════════════"

    preflight

    # Phase 1: Run scanner
    local scan_output
    scan_output=$(run_scanner)
    echo "${scan_output}"
    parse_scanner "${scan_output}"

    log "Cycle ${CYCLE_ID}: Regime=${REGIME}, Signal=${SIGNAL}, Escalate=${ESCALATE}"

    # Phase 2: LLM analysis (if escalation needed)
    local llm_output=""
    local final_signal="${SIGNAL}"

    if [[ "${ESCALATE}" == "YES" && -n "${TOP_CANDIDATE}" ]]; then
        llm_output=$(run_llm_analysis "${TOP_CANDIDATE}") || true

        if [[ -n "${llm_output}" ]]; then
            # Parse final signal from LLM
            final_signal=$(echo "${llm_output}" | jq -r '.decision.signal // "WATCH"')
        fi
    fi

    # Phase 3: Log results
    log_cycle "${scan_output}" "${llm_output}"

    # Phase 4: Send alerts if TRADE signal
    if [[ "${final_signal}" == "TRADE" && -n "${llm_output}" ]]; then
        send_trade_alert "${llm_output}"
        log "Cycle ${CYCLE_ID} complete: TRADE SIGNAL"
        exit 1
    fi

    # Send summary for monitoring (optional)
    if [[ "${ESCALATE}" == "YES" ]]; then
        matrix_notify "📊 IG-88 Cycle ${CYCLE_ID}: ${final_signal} (${TOP_CANDIDATE:-no candidate})"
    fi

    log "Cycle ${CYCLE_ID} complete: ${final_signal}"
    exit 0
}

# Run
main "$@"
