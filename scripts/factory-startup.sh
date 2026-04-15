#!/bin/bash
# factory-startup.sh — Sequenced startup for Factory services on Whitebox
#
# Solves the thundering herd problem: on reboot, all services launching
# simultaneously causes OOM (two 7.3GB E4B models + 2.9GB 26B = 17.5GB
# at once on a 32GB machine). This script staggers model loads and waits
# for health checks before starting dependent services.
#
# Called by: com.bootindustries.factory-startup.plist (RunAtLoad, not KeepAlive)
# Replaces: per-service RunAtLoad for MLX and Hermes services
#
# Phase 1: Lightweight services (already RunAtLoad in their own plists)
# Phase 2: MLX Boot E4B (:41961)
# Phase 3: MLX Kelk E4B (:41962) — after Boot loaded
# Phase 4: MLX 26B shared (:41966) — after E4Bs settled
# Phase 5: Hermes gateways — MLX guaranteed ready

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
  if launchctl list "$label" 2>/dev/null | grep -q '"PID"'; then
    log "$label: already running, skipping"
    return 0
  fi

  launchctl bootstrap gui/$(id -u) "$plist" 2>/dev/null
  log "$label: bootstrapped"
}

# =========================================================================
log "=== Factory startup sequence begin ==="
log "Memory: $(sysctl -n hw.memsize | awk '{printf "%.0fGB", $1/1073741824}')"
log "Free: $(top -l 1 -s 0 2>/dev/null | grep PhysMem | sed 's/.*) //')"

# Phase 1: Lightweight services
# These have RunAtLoad=true in their own plists, so they're already starting.
# Just verify they're up.
log "Phase 1: Lightweight services (already launching via RunAtLoad)"
for svc in portal-caddy gsd-sidecar factory-auth qdrant-mcp research-mcp matrix-mcp-boot; do
  if launchctl list "com.bootindustries.${svc}" 2>/dev/null | grep -q 'PID'; then
    log "  $svc: running"
  else
    log "  $svc: not yet running (launchd will handle)"
  fi
done

# Phase 2: MLX Boot E4B (:41961)
log "Phase 2: MLX Boot E4B (:41961)"
bootstrap "com.bootindustries.mlx-vlm-boot"
wait_for_health "http://127.0.0.1:41961/v1/models" "mlx-vlm-boot" 180

# Phase 3: MLX Kelk E4B (:41962)
log "Phase 3: MLX Kelk E4B (:41962)"
bootstrap "com.bootindustries.mlx-vlm-kelk"
wait_for_health "http://127.0.0.1:41962/v1/models" "mlx-vlm-kelk" 180

# Phase 4: MLX 26B shared (:41966)
log "Phase 4: MLX 26B shared (:41966)"
bootstrap "com.bootindustries.mlx-vlm-whitebox"
wait_for_health "http://127.0.0.1:41966/v1/models" "mlx-vlm-whitebox" 180

# Phase 5: Hermes gateways
log "Phase 5: Hermes gateways"
bootstrap "com.bootindustries.hermes-boot"
sleep 5
bootstrap "com.bootindustries.hermes-kelk"
sleep 5
bootstrap "com.bootindustries.hermes-ig88"

# Final health report
log "=== Startup complete ==="
log "Free: $(top -l 1 -s 0 2>/dev/null | grep PhysMem | sed 's/.*) //')"

# Check all services
for port_label in "41961:mlx-vlm-boot" "41962:mlx-vlm-kelk" "41966:mlx-vlm-whitebox"; do
  port="${port_label%%:*}"
  label="${port_label##*:}"
  if curl -sf --max-time 3 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
    log "  :${port} ${label}: UP"
  else
    log "  :${port} ${label}: DOWN"
  fi
done

for agent in boot kelk ig88; do
  if pgrep -f "hermes.*${agent}.*gateway" >/dev/null 2>&1; then
    log "  hermes-${agent}: UP"
  else
    log "  hermes-${agent}: DOWN"
  fi
done

log "=== Factory startup sequence end ==="
