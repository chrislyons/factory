#!/bin/bash
# switch-27b.sh — Switch between 27B quantization variants on :41966
#
# Usage:
#   switch-27b.sh 6bit    # Current: Ornstein-Hermes-3.6-27b-MLX-6bit
#   switch-27b.sh 4bit    # ~14 GB, faster, needs model on disk
#   switch-27b.sh 2bit    # ~8.5 GB, fastest, needs model on disk
#   switch-27b.sh status  # Show current model

set -euo pipefail

PLIST_DIR="$HOME/Library/LaunchAgents"
PORT=41966
LOG="/Users/nesbitt/Library/Logs/factory/mlx-lm-27b.log"

# Model paths — update when user confirms download locations
declare -A MODELS=(
  [6bit]="/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"
  [4bit]="/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-4bit"
  [2bit]="/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-2bit"
)

declare -A PRESETS=(
  [6bit]="256"    # Small prefill steps — Metal OOM at 2048 with 21 GB model
  [4bit]="2048"   # Standard — 14 GB model leaves room for GPU buffers
  [2bit]="4096"   # Aggressive — 8.5 GB model, plenty of headroom
)

case "${1:-status}" in
  status)
    if curl -sf --max-time 3 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
      MODEL=$(curl -sf --max-time 3 "http://127.0.0.1:${PORT}/v1/models" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])")
      echo "Current: $MODEL"
      echo "Port: :${PORT}"
      echo "Status: HEALTHY"
    else
      echo "No model running on :${PORT}"
    fi
    ;;

  6bit|4bit|2bit)
    QUANT="$1"
    TARGET="${MODELS[$QUANT]}"
    PREFILL="${PRESETS[$QUANT]}"

    if [[ ! -d "$TARGET" ]]; then
      echo "ERROR: Model not found at $TARGET"
      echo "Download it first."
      exit 1
    fi

    echo "=== Switching to 27B ${QUANT} ==="

    # Stop current server
    echo "Stopping :${PORT}..."
    launchctl unload "${PLIST_DIR}/com.bootindustries.mlx-lm-factory-27b.plist" 2>/dev/null || true
    kill -9 $(lsof -ti :${PORT}) 2>/dev/null || true
    sleep 2

    # Update plist with model path and prefill step size
    PLIST="${PLIST_DIR}/com.bootindustries.mlx-lm-factory-27b.plist"
    cp "${PLIST_DIR}/com.bootindustries.mlx-lm-factory-27b-${QUANT}.plist" "$PLIST"

    # Replace placeholder if present
    sed -i '' "s|__PLACEHOLDER_${QUANT}_MODEL_PATH__|${TARGET}|g" "$PLIST"

    # Update prefill step size
    # (already set in the template plists)

    # Clear log
    > "$LOG"

    # Start
    echo "Starting ${QUANT} on :${PORT} (prefill-step-size ${PREFILL})..."
    launchctl bootstrap gui/$(id -u) "$PLIST" 2>&1

    # Wait for health
    ELAPSED=0
    MAX_WAIT=180
    while [ $ELAPSED -lt $MAX_WAIT ]; do
      if curl -sf --max-time 3 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
        echo "Healthy after ${ELAPSED}s"
        echo "=== Now running: 27B ${QUANT} on :${PORT} ==="
        exit 0
      fi
      sleep 5
      ELAPSED=$((ELAPSED + 5))
    done

    echo "ERROR: Not healthy after ${MAX_WAIT}s"
    tail -20 "$LOG"
    exit 1
    ;;

  *)
    echo "Usage: switch-27b.sh {6bit|4bit|2bit|status}"
    exit 1
    ;;
esac
