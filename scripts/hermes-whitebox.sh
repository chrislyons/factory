#!/bin/bash
# hermes-whitebox.sh — Launch Whitebox profile (26B-A4B on :41966)
# Requires shutting down Boot (:41961) and Kelk (:41962) E4B instances
# to free ~13GB VRAM for the 20GB 26B model.
set -euo pipefail

UID_NUM=$(id -u)

# ── Check for active Boot/Kelk MLX servers ──
BOOT_ACTIVE=false
KELK_ACTIVE=false

if launchctl list 2>/dev/null | grep -q "com.bootindustries.mlx-vlm-boot"; then
  if curl -sf --max-time 2 http://127.0.0.1:41961/v1/models >/dev/null 2>&1; then
    BOOT_ACTIVE=true
  fi
fi

if launchctl list 2>/dev/null | grep -q "com.bootindustries.mlx-vlm-kelk"; then
  if curl -sf --max-time 2 http://127.0.0.1:41962/v1/models >/dev/null 2>&1; then
    KELK_ACTIVE=true
  fi
fi

# Also check IG-88 MLX on :41988 (idle but consuming ~6.6GB)
IG88_MLX_ACTIVE=false
if launchctl list 2>/dev/null | grep -q "com.bootindustries.mlx-vlm-ig88"; then
  if curl -sf --max-time 2 http://127.0.0.1:41988/v1/models >/dev/null 2>&1; then
    IG88_MLX_ACTIVE=true
  fi
fi

if $BOOT_ACTIVE || $KELK_ACTIVE || $IG88_MLX_ACTIVE; then
  echo ""
  echo "  ⚠  Active MLX instances detected:"
  $BOOT_ACTIVE && echo "     • Boot MLX on :41961 (~6.6GB)"
  $KELK_ACTIVE && echo "     • Kelk MLX on :41962 (~6.6GB)"
  $IG88_MLX_ACTIVE && echo "     • IG-88 MLX on :41988 (~6.6GB, idle)"
  echo ""
  echo "  The 26B-A4B model requires ~20GB VRAM. ALL MLX instances"
  echo "  must be shut down to free memory (32GB total, need headroom)."
  echo ""
  read -r -p "  Shut down Boot+Kelk MLX and start 26B? [y/N] " response
  case "$response" in
    [yY]|[yY][eE][sS])
      $BOOT_ACTIVE && echo "  Stopping Boot MLX (:41961)..." && \
        launchctl bootout "gui/${UID_NUM}/com.bootindustries.mlx-vlm-boot" 2>/dev/null || true
      $KELK_ACTIVE && echo "  Stopping Kelk MLX (:41962)..." && \
        launchctl bootout "gui/${UID_NUM}/com.bootindustries.mlx-vlm-kelk" 2>/dev/null || true
      $IG88_MLX_ACTIVE && echo "  Stopping IG-88 MLX (:41988)..." && \
        launchctl bootout "gui/${UID_NUM}/com.bootindustries.mlx-vlm-ig88" 2>/dev/null || true

      # Wait for ALL mlx_vlm processes to fully exit and release memory
      echo -n "  Waiting for memory to free"
      for i in $(seq 1 30); do
        if ! pgrep -f "mlx_vlm.server" >/dev/null 2>&1; then
          echo ""
          echo "  ✓ E4B processes exited"
          break
        fi
        echo -n "."
        sleep 2
      done
      # Extra pause for OS to reclaim pages
      sleep 5
      ;;
    *)
      echo "  Aborted. Boot+Kelk remain active."
      exit 0
      ;;
  esac
fi

# ── Check if Whitebox MLX is already running ──
if curl -sf --max-time 2 http://127.0.0.1:41966/v1/models >/dev/null 2>&1; then
  echo "  ✓ 26B-A4B already running on :41966"
else
  echo "  Starting 26B-A4B on :41966 (this takes ~30s to load weights)..."
  # Deploy plist if not present
  cp /Users/nesbitt/dev/factory/plists/com.bootindustries.mlx-vlm-whitebox.plist \
     /Users/nesbitt/Library/LaunchAgents/ 2>/dev/null || true
  launchctl bootstrap "gui/${UID_NUM}" \
     /Users/nesbitt/Library/LaunchAgents/com.bootindustries.mlx-vlm-whitebox.plist 2>/dev/null || \
     launchctl kickstart "gui/${UID_NUM}/com.bootindustries.mlx-vlm-whitebox" 2>/dev/null || true

  # Wait for model to load
  echo -n "  Waiting for :41966"
  for i in $(seq 1 60); do
    if curl -sf --max-time 2 http://127.0.0.1:41966/v1/models >/dev/null 2>&1; then
      echo ""
      echo "  ✓ 26B-A4B ready on :41966"
      break
    fi
    echo -n "."
    sleep 2
  done

  if ! curl -sf --max-time 2 http://127.0.0.1:41966/v1/models >/dev/null 2>&1; then
    echo ""
    echo "  ✗ Failed to start 26B-A4B. Check: tail ~/Library/Logs/factory/mlx-vlm-whitebox.log"
    exit 1
  fi
fi

# ── Launch Hermes ──
export HERMES_HOME="/Users/nesbitt/.hermes/profiles/whitebox"
export HERMES_STREAM_READ_TIMEOUT=600
export HERMES_STREAM_STALE_TIMEOUT=600
export HERMES_AGENT_TIMEOUT=7200

exec hermes -p whitebox chat "$@"
