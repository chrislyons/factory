#!/bin/bash
# goose-whitebox.sh — Launch Goose agent on 26B-A4B (:41966)
# Same memory management as hermes-whitebox.sh — shuts down E4B instances,
# starts 26B, cleans up on exit.
set -euo pipefail

UID_NUM=$(id -u)
LAUNCH_DIR="$HOME/Library/LaunchAgents"
PLIST_SRC="$HOME/dev/factory/plists"

# ── Verify Goose is installed ──
if ! command -v goose >/dev/null 2>&1; then
  echo "  ✗ Goose not found. Install with: brew install block-goose-cli"
  exit 1
fi

# ── Check for active MLX instances ──
ACTIVE_PIDS=""
SERVICES_TO_KILL=""

for svc in boot:41961 kelk:41962 ig88:41988; do
  name="${svc%%:*}"
  port="${svc##*:}"
  if curl -sf --max-time 2 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
    echo "  ⚠  ${name} MLX active on :${port} (~6.6GB)"
    SERVICES_TO_KILL="${SERVICES_TO_KILL} com.bootindustries.mlx-vlm-${name}"
  fi
done

if [ -n "$SERVICES_TO_KILL" ]; then
  echo ""
  echo "  The 26B-A4B model requires ~20GB VRAM."
  echo "  Active MLX instances must be shut down."
  echo ""
  read -r -p "  Shut down and start 26B? [y/N] " response
  case "$response" in
    [yY]|[yY][eE][sS])
      for svc in $SERVICES_TO_KILL; do
        echo "  Stopping ${svc}..."
        launchctl bootout "gui/${UID_NUM}/${svc}" 2>/dev/null || true
        rm -f "${LAUNCH_DIR}/${svc}.plist"
      done
      pkill -f "mlx_vlm.server" 2>/dev/null || true

      echo -n "  Waiting for memory to free"
      for i in $(seq 1 30); do
        if ! pgrep -f "mlx_vlm.server" >/dev/null 2>&1; then
          echo ""
          echo "  ✓ All MLX processes exited"
          break
        fi
        if [ "$i" -eq 10 ]; then
          pkill -9 -f "mlx_vlm.server" 2>/dev/null || true
        fi
        echo -n "."
        sleep 2
      done
      if lsof -i :41961 -i :41962 -i :41988 -t >/dev/null 2>&1; then
        echo "  ✗ Ports still in use — force killing..."
        lsof -i :41961 -i :41962 -i :41988 -t 2>/dev/null | xargs kill -9 2>/dev/null || true
        sleep 3
      fi
      sleep 5
      echo "  ✓ Memory freed"
      ;;
    *)
      echo "  Aborted."
      exit 0
      ;;
  esac
fi

# ── Start 26B MLX if not running ──
if curl -sf --max-time 2 http://127.0.0.1:41966/v1/models >/dev/null 2>&1; then
  echo "  ✓ 26B-A4B already running on :41966"
else
  echo "  Starting 26B-A4B on :41966 (this takes ~30s to load weights)..."
  cp "${PLIST_SRC}/com.bootindustries.mlx-vlm-whitebox.plist" "${LAUNCH_DIR}/" 2>/dev/null || true
  launchctl bootstrap "gui/${UID_NUM}" "${LAUNCH_DIR}/com.bootindustries.mlx-vlm-whitebox.plist" 2>/dev/null || \
    launchctl kickstart "gui/${UID_NUM}/com.bootindustries.mlx-vlm-whitebox" 2>/dev/null || true

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
  rm -f "${LAUNCH_DIR}/com.bootindustries.mlx-vlm-whitebox.plist"
  sleep 5

  echo "  Restoring Boot+Kelk E4B instances..."
  cp "${PLIST_SRC}/com.bootindustries.mlx-vlm-boot.plist" "${LAUNCH_DIR}/" 2>/dev/null
  cp "${PLIST_SRC}/com.bootindustries.mlx-vlm-kelk.plist" "${LAUNCH_DIR}/" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "${LAUNCH_DIR}/com.bootindustries.mlx-vlm-boot.plist" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "${LAUNCH_DIR}/com.bootindustries.mlx-vlm-kelk.plist" 2>/dev/null || true
  echo "  ✓ Boot (:41961) and Kelk (:41962) restored"
}
trap cleanup EXIT

# ── Launch Goose ──
export OPENAI_HOST="http://127.0.0.1:41966/v1"
export OPENAI_API_KEY="local"

goose session start --model "/Users/nesbitt/models/gemma-4-26b-a4b-it-6bit" "$@"
