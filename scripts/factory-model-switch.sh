#!/bin/bash
# factory-model-switch.sh — Switch between inference models on Whitebox
#
# Usage:
#   factory-model-switch.sh 35b    # Switch to Ornstein3.6-35B-A3B (default)
#   factory-model-switch.sh 27b    # Switch to Qwen3.6-27B (intensive)
#   factory-model-switch.sh status # Show current model
#
# FCT074: Dual-model deployment

set -euo pipefail

PORT=41961
HEALTH_URL="http://127.0.0.1:${PORT}/v1/models"
MLX_PYTHON="/Users/nesbitt/dev/vendor/mlx-vlm/.venv/bin/python3"
LOG_DIR="/Users/nesbitt/Library/Logs/factory"
PLIST_DIR="$HOME/Library/LaunchAgents"

log() {
  echo "[$(date '+%H:%M:%S')] $*"
}

# --- Model definitions ---
declare -A MODEL_PATHS=(
  [35b]="/Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit"
  [27b]="/Users/nesbitt/models/Qwen3.6-27B-MLX-6bit"
)

declare -A MODEL_LABELS=(
  [35b]="com.bootindustries.mlx-vlm-ornstein"
  [27b]="com.bootindustries.mlx-vlm-qwen27b"
)

declare -A MODEL_NAMES=(
  [35b]="Ornstein3.6-35B-A3B-MLX-6bit"
  [27b]="Qwen3.6-27B-MLX-6bit"
)

# --- Commands ---
case "${1:-status}" in
  status)
    # Check what's running on :41961
    if curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
      RUNNING=$(curl -sf --max-time 3 "$HEALTH_URL" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null || echo "unknown")
      log "Current model: $RUNNING"
      log "Port: :41961"
      log "Status: HEALTHY"
    else
      log "No model running on :41961"
    fi
    ;;

  35b|27b)
    TARGET="$1"
    TARGET_PATH="${MODEL_PATHS[$TARGET]}"
    TARGET_LABEL="${MODEL_LABELS[$TARGET]}"
    TARGET_NAME="${MODEL_NAMES[$TARGET]}"
    TARGET_PLIST="${PLIST_DIR}/${TARGET_LABEL}.plist"

    log "=== Switching to $TARGET_NAME ==="

    # Check model exists
    if [[ ! -d "$TARGET_PATH" ]]; then
      log "ERROR: Model not found at $TARGET_PATH"
      exit 1
    fi

    # Find and stop current model server on :41961
    CURRENT_LABEL=$(ls "$PLIST_DIR"/com.bootindustries.mlx-vlm-*.plist 2>/dev/null | while read plist; do
      label=$(basename "$plist" .plist)
      if launchctl list "$label" &>/dev/null; then
        # Check if this plist uses port 41961
        if grep -q "41961" "$plist" 2>/dev/null; then
          echo "$label"
          break
        fi
      fi
    done)

    if [[ -n "$CURRENT_LABEL" ]]; then
      log "Stopping $CURRENT_LABEL..."
      launchctl unload "${PLIST_DIR}/${CURRENT_LABEL}.plist" 2>/dev/null || true
      sleep 2
    fi

    # Verify port is free
    if lsof -i :$PORT -sTCP:LISTEN &>/dev/null; then
      log "ERROR: Port $PORT still in use"
      exit 1
    fi

    # Check target plist exists
    if [[ ! -f "$TARGET_PLIST" ]]; then
      log "ERROR: Plist not found: $TARGET_PLIST"
      log "       Create it first."
      exit 1
    fi

    # Start target
    log "Starting $TARGET_LABEL..."
    launchctl load "$TARGET_PLIST"

    # Health check
    log "Waiting for health..."
    MAX_WAIT=120
    ELAPSED=0
    while [ $ELAPSED -lt $MAX_WAIT ]; do
      if curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
        log "Healthy after ${ELAPSED}s"
        break
      fi
      sleep 5
      ELAPSED=$((ELAPSED + 5))
    done

    if [ $ELAPSED -ge $MAX_WAIT ]; then
      log "ERROR: Not healthy after ${MAX_WAIT}s"
      exit 1
    fi

    log "=== Now running: $TARGET_NAME on :$PORT ==="
    ;;

  *)
    echo "Usage: factory-model-switch.sh {35b|27b|status}"
    exit 1
    ;;
esac
