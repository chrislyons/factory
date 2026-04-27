#!/bin/bash
# deploy-ornstein.sh — Deploy Ornstein3.6-35B-A3B as primary inference model
#
# Stops old Gemma 4 E4B + flash-moe services, moves model from staging,
# starts new service on :41961, smoke tests, updates Hermes configs.
#
# Usage: bash ~/dev/factory/scripts/deploy-ornstein.sh [--dry-run]
#
# FCT074: Dual-model deployment (35B-A3B default, 27B intensive)

set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

LOG="/Users/nesbitt/Library/Logs/factory/deploy-ornstein.log"
mkdir -p "$(dirname "$LOG")"

log() {
  echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"
}

run() {
  if $DRY_RUN; then
    log "DRY RUN: $*"
  else
    "$@"
  fi
}

# --- Config ---
MODEL_SRC="/Volumes/CL T04/models/DJLougen/Ornstein3.6-35B-A3B-MLX-6bit"
MODEL_DST="/Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit"
PORT=41961
HEALTH_URL="http://127.0.0.1:${PORT}/v1/models"
PLIST_LABEL="com.bootindustries.mlx-vlm-ornstein"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
MLX_PYTHON="/Users/nesbitt/dev/vendor/mlx-vlm/.venv/bin/python3"

OLD_LABELS=(
  "com.bootindustries.mlx-vlm-boot"
  "com.bootindustries.mlx-vlm-kelk"
  "com.bootindustries.mlx-vlm-whitebox"
)

HERMES_PROFILES=(
  "$HOME/.hermes/profiles/boot/config.yaml"
  "$HOME/.hermes/profiles/kelk/config.yaml"
)

# --- Preflight ---
log "=== Deploy Ornstein3.6-35B-A3B ==="
log "Mode: $($DRY_RUN && echo 'DRY RUN' || echo 'LIVE')"

# Check model source exists
if [[ ! -d "$MODEL_SRC" ]]; then
  log "ERROR: Model not found at $MODEL_SRC"
  log "       Waiting for LM Studio download to complete."
  exit 1
fi

# Check model files are complete (no .part files)
PART_COUNT=$(ls "$MODEL_SRC"/*.part 2>/dev/null | wc -l | tr -d ' ')
if [[ "$PART_COUNT" -gt 0 ]]; then
  log "ERROR: Download still in progress ($PART_COUNT .part files)"
  exit 1
fi

SAFETENSOR_COUNT=$(ls "$MODEL_SRC"/*.safetensors 2>/dev/null | wc -l | tr -d ' ')
log "Model: $SAFETENSOR_COUNT safetensors files found"

# Check disk space
NEEDED_GB=30
AVAIL_GB=$(df -g / | tail -1 | awk '{print $4}')
if [[ "$AVAIL_GB" -lt "$NEEDED_GB" ]]; then
  log "WARNING: Only ${AVAIL_GB}GB free, need ~${NEEDED_GB}GB"
  log "         Consider removing old models first."
fi

# --- Phase 1: Stop old services ---
log ""
log "--- Phase 1: Stop old services ---"
for label in "${OLD_LABELS[@]}"; do
  if launchctl list "$label" &>/dev/null; then
    log "Stopping $label..."
    run launchctl unload "$HOME/Library/LaunchAgents/${label}.plist" 2>/dev/null || true
    log "  stopped"
  else
    log "$label: not loaded"
  fi
done

# Wait for ports to free
log "Waiting for ports to free..."
sleep 3
if ! $DRY_RUN; then
  for port in 41961 41962 41966; do
    if lsof -i :$port -sTCP:LISTEN &>/dev/null; then
      log "  WARNING: Port $port still in use"
    else
      log "  Port $port: free"
    fi
  done
fi

# --- Phase 2: Move model ---
log ""
log "--- Phase 2: Move model ---"
if [[ -d "$MODEL_DST" ]]; then
  log "Model already at $MODEL_DST, skipping move"
else
  log "Moving model to $MODEL_DST..."
  run mkdir -p "$(dirname "$MODEL_DST")"
  run mv "$MODEL_SRC" "$MODEL_DST"
  log "  moved"
fi

# --- Phase 3: Start new service ---
log ""
log "--- Phase 3: Start $PLIST_LABEL ---"
log "Loading plist: $PLIST_PATH"
run launchctl load "$PLIST_PATH"

# --- Phase 4: Health check ---
log ""
log "--- Phase 4: Health check ---"
log "Waiting for $HEALTH_URL..."
MAX_WAIT=120
ELAPSED=0
if ! $DRY_RUN; then
  while [ $ELAPSED -lt $MAX_WAIT ]; do
    if curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
      log "  healthy after ${ELAPSED}s"
      break
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
  done
  if [ $ELAPSED -ge $MAX_WAIT ]; then
    log "ERROR: Server not healthy after ${MAX_WAIT}s"
    log "       Check: tail -50 ~/Library/Logs/factory/mlx-vlm-ornstein.log"
    exit 1
  fi
fi

# --- Phase 5: Smoke test ---
log ""
log "--- Phase 5: Smoke test ---"
SMOKE_RESPONSE=$(curl -sf --max-time 30 "http://127.0.0.1:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Ornstein3.6-35B-A3B-MLX-6bit",
    "messages": [{"role": "user", "content": "Say hello in exactly 5 words."}],
    "max_tokens": 20,
    "temperature": 0.0
  }' 2>/dev/null) || true

if [[ -n "$SMOKE_RESPONSE" ]]; then
  SMOKE_TEXT=$(echo "$SMOKE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'])" 2>/dev/null || echo "parse error")
  log "  Response: $SMOKE_TEXT"
else
  log "  WARNING: No response from smoke test"
fi

# --- Phase 6: Summary ---
log ""
log "--- Phase 6: Summary ---"
log "Model:   Ornstein3.6-35B-A3B-MLX-6bit"
log "Port:    :41961"
log "Server:  mlx_vlm.server (mmap, MoE expert streaming)"
log "Status:  $(curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1 && echo 'HEALTHY' || echo 'UNHEALTHY')"
log ""
log "Next steps:"
log "  1. Update Hermes configs (Boot + Kelk → :41961)"
log "  2. Restart Hermes gateways"
log "  3. Benchmark tok/s at various contexts"
log ""
log "=== Deploy complete ==="
