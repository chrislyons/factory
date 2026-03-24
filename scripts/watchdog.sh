#!/usr/bin/env bash
# Cron entry (Blackbox):
# */2 * * * * /home/nesbitt/scripts/watchdog.sh
set -euo pipefail

WHITEBOX="100.88.222.111"
STATE_DIR="$HOME/.local/share/watchdog"
ALERT_LOG="$STATE_DIR/alerts.log"
TOKEN=$(cat ~/.config/ig88/matrix_token_watchdog 2>/dev/null || true)
ROOM_ID='!MDVmYJtAiHZoBfaQdK:matrix.org'
ROOM_ID_ENC='%21MDVmYJtAiHZoBfaQdK%3Amatrix.org'

mkdir -p "$STATE_DIR"
date +%s > "$STATE_DIR/last-run"

# --- helpers ---

send_matrix() {
  local msg="$1"
  [[ -z "$TOKEN" ]] && return 0
  local txn_id
  txn_id="wd_$(date +%s%N)"
  local body
  body=$(jq -n --arg m "$msg" '{"msgtype":"m.text","body":$m}')
  curl -sf -X PUT \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$body" \
    "https://matrix.org/_matrix/client/v3/rooms/$ROOM_ID_ENC/send/m.room.message/$txn_id" \
    >/dev/null 2>&1 || true
}

check_service() {
  local name="$1" ok="$2" code="${3:-}"
  local fail_file="$STATE_DIR/${name}.fail"

  if [[ "$ok" == "1" ]]; then
    if [[ -f "$fail_file" ]]; then
      rm -f "$fail_file"
      echo "$(date) RECOVERED $name" >> "$ALERT_LOG"
      send_matrix "WATCHDOG: $name recovered"
    fi
  else
    if [[ ! -f "$fail_file" ]]; then
      touch "$fail_file"
      echo "$(date) ALERT $name $code" >> "$ALERT_LOG"
      send_matrix "WATCHDOG: $name DOWN (HTTP $code)"
    fi
  fi
}

# --- checks ---

# MLX-LM servers (:41960-41963)
for port in 41960 41961 41962 41963; do
  code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 5 \
    "http://$WHITEBOX:$port/v1/models" 2>/dev/null || echo "000")
  [[ "$code" == "200" ]] && ok=1 || ok=0
  check_service "mlx-$port" "$ok" "$code"
done

# Qdrant (:6333)
code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 5 \
  "http://$WHITEBOX:6333/collections" 2>/dev/null || echo "000")
[[ "$code" == "200" ]] && ok=1 || ok=0
check_service "qdrant" "$ok" "$code"

# Graphiti SSE (:8444) — connection opened (exit 28) = healthy
ec=0
curl -sf -o /dev/null --max-time 3 "http://$WHITEBOX:8444/sse" 2>/dev/null || ec=$?
# exit 0 (response completed) or 28 (timeout = stream open) both mean healthy
[[ "$ec" == "0" || "$ec" == "28" ]] && ok=1 || ok=0
check_service "graphiti" "$ok" "exit-$ec"

# Pantalaimon TCP (:8009) — Pan binds to loopback on Whitebox, check via SSH
if ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new whitebox '(echo >/dev/tcp/127.0.0.1/8009) 2>/dev/null' 2>/dev/null; then
  ok=1
else
  ok=0
fi
check_service "pantalaimon" "$ok" "tcp-refused"

# Portal (:41910) — expects 302 redirect to login
code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 5 \
  "http://$WHITEBOX:41910/" 2>/dev/null || echo "000")
[[ "$code" == "302" ]] && ok=1 || ok=0
check_service "portal" "$ok" "$code"

# Coordinator log freshness (via SSH)
fresh=$(ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new whitebox \
  'find ~/Library/Logs/factory/coordinator.log -mmin -5 2>/dev/null' 2>/dev/null || true)
[[ -n "$fresh" ]] && ok=1 || ok=0
check_service "coordinator-log" "$ok" "stale"
