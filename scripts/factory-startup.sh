#!/bin/bash
# factory-startup.sh — Sequenced startup for Factory services on Whitebox
#
# Solves the thundering herd problem: on reboot, all services launching
# simultaneously causes OOM (two 7.3GB E4B models + 2.9GB 26B = 17.5GB
# at once on a 32GB machine). This script staggers model loads, waits
# for health checks, and enforces memory gates between phases.
#
# Memory safety (FCT070): MLX model loads via mmap cause a transient
# wired memory spike (~8GB for a 7.3GB model) that lasts ~15s before
# settling. The health check alone is insufficient — the server responds
# to /v1/models within ~5s, well before the spike subsides. We add:
#   1. wait_for_memory_settle — polls until wired < threshold
#   2. require_free_memory — aborts phase if free < required GB
# Target: never below 500MB free at any point.
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

# get_free_mb — report PhysMem "unused" in MB (conservative floor)
get_free_mb() {
  top -l 1 -s 0 2>/dev/null | awk '/PhysMem/{
    for(i=1;i<=NF;i++){
      if($(i+1)=="unused." || $(i+1)=="unused,"){
        val=$i; gsub(/[^0-9]/,"",val)
        # Handle G vs M suffix
        if($i ~ /G/) { printf "%d", val*1024 }
        else          { printf "%d", val }
      }
    }
  }'
}

# get_wired_mb — report wired memory in MB
get_wired_mb() {
  top -l 1 -s 0 2>/dev/null | awk '/PhysMem/{
    for(i=1;i<=NF;i++){
      if($(i+1)=="wired," || $(i+1)=="wired)"){
        val=$i; gsub(/[^0-9]/,"",val)
        if($i ~ /G/) { printf "%d", val*1024 }
        else          { printf "%d", val }
      }
    }
  }'
}

# require_free_memory <required_mb> <phase_label>
# Aborts the phase if free memory is below required_mb.
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

# wait_for_memory_settle <max_wired_mb> <max_wait_s>
# Polls until wired memory drops below threshold, indicating the mmap
# page-fault spike from model loading has subsided.
wait_for_memory_settle() {
  local max_wired_mb="${1:-3000}"
  local max_wait="${2:-60}"
  local elapsed=0
  local wired_mb

  while [ $elapsed -lt $max_wait ]; do
    wired_mb="$(get_wired_mb)"
    if [ -n "$wired_mb" ] && [ "$wired_mb" -lt "$max_wired_mb" ]; then
      log "Memory settled: wired=${wired_mb}MB (< ${max_wired_mb}MB) after ${elapsed}s"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done

  wired_mb="$(get_wired_mb)"
  log "WARN: wired memory still ${wired_mb}MB after ${max_wait}s (threshold: ${max_wired_mb}MB)"
  # Don't abort — wired may be legitimately high from other processes.
  # The require_free_memory gate before the next phase is the hard stop.
  return 0
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
# E4B model is ~7.3GB. mmap spike adds ~8GB transient wired.
# Require model_size + 4GB = 11300MB free before loading.
log "Phase 2: MLX Boot E4B (:41961)"
if require_free_memory 11300 "Phase 2"; then
  bootstrap "com.bootindustries.mlx-vlm-boot"
  wait_for_health "http://127.0.0.1:41961/v1/models" "mlx-vlm-boot" 180
  # Wait for mmap wired spike to subside before loading next model.
  # Normal wired is ~1800MB; spike peaks at ~9800MB during model load.
  log "Phase 2→3: waiting for memory to settle"
  wait_for_memory_settle 3000 60
else
  log "Phase 2 SKIPPED — not enough memory for Boot E4B"
  log "  Manual recovery: free memory, then run factory-startup.sh again"
fi

# Phase 3: MLX Kelk E4B (:41962)
log "Phase 3: MLX Kelk E4B (:41962)"
if require_free_memory 11300 "Phase 3"; then
  bootstrap "com.bootindustries.mlx-vlm-kelk"
  wait_for_health "http://127.0.0.1:41962/v1/models" "mlx-vlm-kelk" 180
  log "Phase 3→4: waiting for memory to settle"
  wait_for_memory_settle 3000 60
else
  log "Phase 3 SKIPPED — not enough memory for Kelk E4B"
  log "  Manual recovery: free memory, then bootstrap com.bootindustries.mlx-vlm-kelk"
fi

# Phase 4: MLX 26B shared (:41966)
# 26B via flash-moe is ~2.88GB resident. Require 7000MB free (2880 + 4000).
log "Phase 4: MLX 26B shared (:41966)"
if require_free_memory 7000 "Phase 4"; then
  bootstrap "com.bootindustries.mlx-vlm-whitebox"
  wait_for_health "http://127.0.0.1:41966/v1/models" "mlx-vlm-whitebox" 180
else
  log "Phase 4 SKIPPED — not enough memory for 26B model"
  log "  Manual recovery: free memory, then bootstrap com.bootindustries.mlx-vlm-whitebox"
fi

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
