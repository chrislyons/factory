#!/bin/bash
# factory-startup.sh — Sequenced startup for Factory services on Whitebox
#
# FCT074: Single model deployment (Ornstein3.6-35B-A3B via mlx-vlm.server).
# The 35B-A3B is mmap'd — only ~5GB resident initially (attention/routing),
# expert weights stream from SSD on demand. No thundering herd.
#
# Phase 1: Lightweight services (already RunAtLoad in their own plists)
# Phase 2: MLX Ornstein3.6-35B-A3B (:41961)
# Phase 3: Hermes gateways — MLX guaranteed ready
#
# Called by: com.bootindustries.factory-startup.plist (RunAtLoad, not KeepAlive)

set -uo pipefail

LOG="/Users/nesbitt/Library/Logs/factory/factory-startup.log"
mkdir -p "$(dirname "$LOG")"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
  echo "[$(date '+%H:%M:%S')] $*"
}

wait_for_health() {
  local url="$1"
  local label="$2"
  local max_wait="${3:-120}"
  local elapsed=0

  while [ $elapsed -lt $max_wait ]; do
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      log "$label: healthy after ${elapsed}s"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done

  log "ERROR: $label not healthy after ${max_wait}s"
  return 1
}

bootstrap() {
  local label="$1"
  local plist="/Users/nesbitt/Library/LaunchAgents/${label}.plist"

  if [ ! -f "$plist" ]; then
    log "ERROR: plist not found: $plist"
    return 1
  fi

  # Check if already running
  if launchctl list "$label" 2>/dev/null | grep -q '\"PID\"'; then
    log "$label: already running, skipping"
    return 0
  fi

  launchctl bootstrap gui/$(id -u) "$plist" 2>/dev/null
  log "$label: bootstrapped"
}

get_free_mb() {
  top -l 1 -s 0 2>/dev/null | awk '/PhysMem/{
    for(i=1;i<=NF;i++){
      if($(i+1)=="unused." || $(i+1)=="unused,"){
        val=$i; gsub(/[^0-9]/,"",val)
        if($i ~ /G/) { printf "%d", val*1024 }
        else          { printf "%d", val }
      }
    }
  }'
}

require_free_memory() {
  local required_mb="$1"
  local phase="$2"
  local free_mb
  free_mb="$(get_free_mb)"

  if [ -z "$free_mb" ] || [ "$free_mb" -eq 0 ]; then
    log "WARN: could not read free memory — proceeding cautiously"
    return 0
  fi

  log "$phase: free=${free_mb}MB, required=${required_mb}MB"
  if [ "$free_mb" -lt "$required_mb" ]; then
    log "ERROR: $phase — insufficient memory (${free_mb}MB < ${required_mb}MB). ABORTING phase."
    return 1
  fi
  return 0
}

# =========================================================================
log "=== Factory startup sequence begin ==="
log "Memory: $(sysctl -n hw.memsize | awk '{printf "%.0fGB", $1/1073741824}')"
log "Free: $(top -l 1 -s 0 2>/dev/null | grep PhysMem | sed 's/.*) //')"

# Phase 1: Lightweight services
# These have RunAtLoad=true in their own plists, so they're already starting.
log "Phase 1: Lightweight services (already launching via RunAtLoad)"
for svc in portal-caddy gsd-sidecar factory-auth qdrant-mcp research-mcp matrix-mcp-boot hindsight-api; do
  if launchctl list "com.bootindustries.${svc}" 2>/dev/null | grep -q 'PID'; then
    log "  $svc: running"
  else
    log "  $svc: not yet running (launchd will handle)"
  fi
done

# Phase 2: MLX Ornstein3.6-35B-A3B (:41961)
# mmap-based: ~5GB resident initially (attention/routing), experts stream from SSD.
# mmap spike is transient and smaller than loading a full dense model.
# Require 10GB free (5GB model + 5GB headroom for macOS).
log "Phase 2: MLX Ornstein3.6-35B-A3B (:41961)"
if require_free_memory 10000 "Phase 2"; then
  bootstrap "com.bootindustries.mlx-vlm-ornstein"
  wait_for_health "http://127.0.0.1:41961/v1/models" "mlx-vlm-ornstein" 180
else
  log "Phase 2 SKIPPED — not enough memory for Ornstein model"
  log "  Manual recovery: free memory, then run factory-startup.sh again"
fi

# Phase 3: Hermes gateways
log "Phase 3: Hermes gateways"
bootstrap "com.bootindustries.hermes-boot"
sleep 5
bootstrap "com.bootindustries.hermes-kelk"
sleep 5
bootstrap "com.bootindustries.hermes-ig88"

# Final health report
log "=== Startup complete ==="
log "Free: $(top -l 1 -s 0 2>/dev/null | grep PhysMem | sed 's/.*) //')"

# Check all services
if curl -sf --max-time 3 "http://127.0.0.1:41961/v1/models" >/dev/null 2>&1; then
  log "  :41961 ornstein: UP"
else
  log "  :41961 ornstein: DOWN"
fi

for agent in boot kelk ig88; do
  if pgrep -f "hermes.*${agent}.*gateway" >/dev/null 2>&1; then
    log "  hermes-${agent}: UP"
  else
    log "  hermes-${agent}: DOWN"
  fi
done

log "=== Factory startup sequence end ==="
