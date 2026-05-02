#!/bin/bash
# factory-startup.sh — Sequenced startup for Factory services on Whitebox
#
# Phase 0: Infrastructure services (no model dependency)
# Phase 1: MLX inference tier (FCT091/FCT093)
#   :41961 E4B-SABER (Boot)   — primary agentic, 12 GB wrapper limits
#   :41962 E4B-SABER (Kelk)   — primary agentic, 12 GB wrapper limits
# Phase 2: Hermes gateways — MLX guaranteed ready
#
# Note: :41963 (Coord aux E2B-SABER) deprecated 2026-05-02 (FCT093) —
# returned ~6 GB to the budget for E4B headroom; aux slots fold back into
# primary E4B per profile config. Plist .deprecated.
# Note: :41966 (Nemostein vllm-mlx) deprecated 2026-05-02 (FCT092). Plist
# .deprecated. See FCT092 for hot-swap recipe if heavy-reasoning fallback ever
# becomes needed.

set -uo pipefail

LOG="/Users/nesbitt/Library/Logs/factory/factory-startup.log"
mkdir -p "$(dirname "$LOG")"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
}

wait_for_health() {
  local url="$1"
  local label="$2"
  local max_wait="${3:-120}"
  local elapsed=0

  while [ $elapsed -lt $max_wait ]; do
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      log "  $label: healthy after ${elapsed}s"
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done

  log "  $label: TIMEOUT after ${max_wait}s"
  return 1
}

bootstrap() {
  local label="$1"
  local plist="/Users/nesbitt/Library/LaunchAgents/${label}.plist"

  if [ ! -f "$plist" ]; then
    log "  SKIP $label — plist not found"
    return 1
  fi

  # Already registered and running?
  if launchctl list "$label" 2>/dev/null | grep -q '"PID"'; then
    log "  $label: already running"
    return 0
  fi

  launchctl bootstrap gui/$(id -u) "$plist" 2>/dev/null
  if [ $? -eq 0 ]; then
    log "  $label: bootstrapped"
    return 0
  else
    log "  $label: bootstrap FAILED"
    return 1
  fi
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
    log "  WARN: could not read free memory — proceeding cautiously"
    return 0
  fi

  log "  Free memory: ${free_mb}MB (need ${required_mb}MB)"
  if [ "$free_mb" -lt "$required_mb" ]; then
    log "  ERROR: insufficient memory (${free_mb}MB < ${required_mb}MB). SKIPPING $phase."
    return 1
  fi
  return 0
}

# =========================================================================
log "=== Factory startup sequence begin ==="
log "Memory: $(sysctl -n hw.memsize | awk '{printf "%.0fGB", $1/1073741824}')"
log "Free: $(top -l 1 -s 0 2>/dev/null | grep PhysMem | sed 's/.*） //')"

# ── Phase 0: Infrastructure (no model dependency) ──────────────────────
log "Phase 0: Infrastructure services"
# qdrant-server must start before qdrant-mcp
bootstrap "com.bootindustries.qdrant-server"
sleep 2
for svc in portal-caddy gsd-sidecar factory-auth latch-dev hermes-dashboard hermes-workspace; do
  bootstrap "com.bootindustries.${svc}"
done
# MCP servers (depend on qdrant-server being up)
sleep 2
for svc in qdrant-mcp research-mcp matrix-mcp-boot; do
  bootstrap "com.bootindustries.${svc}"
done
# hindsight-api — known broken (exit 127), bootstrap anyway for when it's fixed
bootstrap "com.bootindustries.hindsight-api"

# ── Phase 1: MLX dual-server (FCT091/FCT093) ───────────────────────────
# Boot/Kelk on E4B-SABER (:41961/:41962). FCT078 mlx_lm wrapper at 12 GB
# Metal + 12 GB wired limits each. Each: ~6 GB RSS / ~12 GB wired peak.
log "Phase 1: MLX inference tier (E4B-SABER ×2 @ 12 GB wrapper limits)"
if require_free_memory 24000 "Phase 1"; then
  bootstrap "com.bootindustries.mlx-lm-factory-boot"
  bootstrap "com.bootindustries.mlx-lm-factory-kelk"
  wait_for_health "http://127.0.0.1:41961/v1/models" "mlx-boot (:41961)" 120
  wait_for_health "http://127.0.0.1:41962/v1/models" "mlx-kelk (:41962)" 120
else
  log "  SKIPPED — not enough memory"
fi

# ── Phase 2: Hermes gateways ──────────────────────────────────────────
# MLX server guaranteed healthy from Phase 1.
log "Phase 2: Hermes gateways"
bootstrap "com.bootindustries.hermes-boot"
sleep 5
bootstrap "com.bootindustries.hermes-kelk"
sleep 5
bootstrap "com.bootindustries.hermes-ig88"

# ── Health report ─────────────────────────────────────────────────────
log ""
log "=== Startup complete ==="
log "Free: $(top -l 1 -s 0 2>/dev/null | grep PhysMem | sed 's/.*） //')"

log ""
log "--- Model servers ---"
for port_label in "41961/mlx-boot" "41962/mlx-kelk"; do
  port="${port_label%%/*}"
  label="${port_label##*/}"
  if curl -sf --max-time 3 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
    log "  ${label} (:${port}): UP"
  else
    log "  ${label} (:${port}): DOWN"
  fi
done

log ""
log "--- Hermes gateways ---"
for agent in boot kelk ig88; do
  if pgrep -f "hermes.*${agent}.*gateway" >/dev/null 2>&1; then
    log "  hermes-${agent}: UP"
  else
    log "  hermes-${agent}: DOWN"
  fi
done

log ""
log "--- Infrastructure ---"
for svc in portal-caddy qdrant-server qdrant-mcp research-mcp matrix-mcp-boot factory-auth gsd-sidecar latch-dev hermes-dashboard hermes-workspace; do
  if launchctl list "com.bootindustries.${svc}" 2>/dev/null | grep -q '"PID"'; then
    log "  ${svc}: UP"
  else
    log "  ${svc}: DOWN"
  fi
done

log "=== Factory startup sequence end ==="
