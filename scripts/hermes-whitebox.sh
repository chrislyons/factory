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
      # Remove plists FIRST so KeepAlive can't respawn, then bootout
      LAUNCH_DIR="$HOME/Library/LaunchAgents"
      if $BOOT_ACTIVE; then
        echo "  Stopping Boot MLX (:41961)..."
        launchctl bootout "gui/${UID_NUM}/com.bootindustries.mlx-vlm-boot" 2>/dev/null || true
        rm -f "${LAUNCH_DIR}/com.bootindustries.mlx-vlm-boot.plist"
      fi
      if $KELK_ACTIVE; then
        echo "  Stopping Kelk MLX (:41962)..."
        launchctl bootout "gui/${UID_NUM}/com.bootindustries.mlx-vlm-kelk" 2>/dev/null || true
        rm -f "${LAUNCH_DIR}/com.bootindustries.mlx-vlm-kelk.plist"
      fi
      if $IG88_MLX_ACTIVE; then
        echo "  Stopping IG-88 MLX (:41988)..."
        launchctl bootout "gui/${UID_NUM}/com.bootindustries.mlx-vlm-ig88" 2>/dev/null || true
        rm -f "${LAUNCH_DIR}/com.bootindustries.mlx-vlm-ig88.plist"
      fi

      # Kill any stragglers that survived bootout
      pkill -f "mlx_vlm.server" 2>/dev/null || true

      # Wait for ALL mlx_vlm processes to fully exit and release memory
      echo -n "  Waiting for memory to free"
      for i in $(seq 1 30); do
        if ! pgrep -f "mlx_vlm.server" >/dev/null 2>&1; then
          echo ""
          echo "  ✓ All MLX processes exited"
          break
        fi
        # Force kill if still alive after 20 seconds
        if [ "$i" -eq 10 ]; then
          pkill -9 -f "mlx_vlm.server" 2>/dev/null || true
        fi
        echo -n "."
        sleep 2
      done
      # Verify nothing is listening on the ports
      if lsof -i :41961 -i :41962 -i :41988 -t >/dev/null 2>&1; then
        echo "  ✗ WARNING: Ports still in use. Killing remaining processes..."
        lsof -i :41961 -i :41962 -i :41988 -t 2>/dev/null | xargs kill -9 2>/dev/null || true
        sleep 3
      fi
      # Extra pause for OS to reclaim pages
      sleep 5
      echo "  ✓ Memory freed"
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

# ── Cleanup on exit: stop 26B, restore E4B instances ──
cleanup() {
  echo ""
  echo "  Shutting down 26B-A4B on :41966..."
  launchctl bootout "gui/$(id -u)/com.bootindustries.mlx-vlm-whitebox" 2>/dev/null || true
  pkill -f "mlx_vlm.server.*41966" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/com.bootindustries.mlx-vlm-whitebox.plist"
  sleep 5

  echo "  Restoring Boot+Kelk E4B instances..."
  PLIST_SRC="$HOME/dev/factory/plists"
  LAUNCH_DIR="$HOME/Library/LaunchAgents"
  cp "${PLIST_SRC}/com.bootindustries.mlx-vlm-boot.plist" "${LAUNCH_DIR}/" 2>/dev/null
  cp "${PLIST_SRC}/com.bootindustries.mlx-vlm-kelk.plist" "${LAUNCH_DIR}/" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "${LAUNCH_DIR}/com.bootindustries.mlx-vlm-boot.plist" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "${LAUNCH_DIR}/com.bootindustries.mlx-vlm-kelk.plist" 2>/dev/null || true
  echo "  ✓ Boot (:41961) and Kelk (:41962) restored"
}
trap cleanup EXIT

# ── Launch Hermes ──
export HERMES_HOME="/Users/nesbitt/.hermes/profiles/whitebox"
export HERMES_STREAM_READ_TIMEOUT=600
export HERMES_STREAM_STALE_TIMEOUT=600
export HERMES_AGENT_TIMEOUT=7200

hermes -p whitebox chat "$@"
