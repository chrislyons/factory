#!/bin/bash
# Factory Portal — Caddy static file server with basicauth + GSD backend proxy
# Port 41933 | systemd units: factory-portal.service + gsd-backend.service
#
# Usage:
#   ./serve.sh                  Start Caddy in foreground
#   ./serve.sh --systemd        Generate Caddyfile + install systemd units (Blackbox)
#   ./serve.sh --open           Start Caddy + open browser (local dev)
#   ./serve.sh --status         Check if Caddy is running on port
#   ./serve.sh --gen-hash       Generate bcrypt password hash (interactive)
#
# Required env vars (for auth):
#   PORTAL_USER                  basicauth username (default: admin)
#   PORTAL_PASSWORD_HASH         bcrypt hash from: caddy hash-password --algorithm bcrypt
#
# Optional env vars:
#   PORTAL_PORT                  port (default: 41933)
#   PORTAL_HOST                  bind host (default: 127.0.0.1)
#   GSD_BACKEND_PORT             GSD Python backend port (default: 41935)
#
set -euo pipefail

# Load local credentials if present (gitignored)
SCRIPT_DIR_EARLY="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "${SCRIPT_DIR_EARLY}/.env" ]]; then
  set +u  # bcrypt hashes contain $2a which triggers nounset
  set -o allexport
  source "${SCRIPT_DIR_EARLY}/.env"
  set +o allexport
  set -u
fi

PORT="${PORTAL_PORT:-41933}"
HOST="${PORTAL_HOST:-127.0.0.1}"
USER="${PORTAL_USER:-admin}"
PASS_HASH="${PORTAL_PASSWORD_HASH:-}"
GSD_PORT="${GSD_BACKEND_PORT:-41935}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CADDYFILE="${SCRIPT_DIR}/Caddyfile"
PID_FILE="${SCRIPT_DIR}/.factory-portal.pid"
SYSTEMD_CADDY="factory-portal.service"
SYSTEMD_GSD="gsd-backend.service"
SYSTEMD_PATH_CADDY="/etc/systemd/system/${SYSTEMD_CADDY}"
SYSTEMD_PATH_GSD="/etc/systemd/system/${SYSTEMD_GSD}"
REMOTE_ROOT="/home/nesbitt/projects/factory-portal"

URL="http://${HOST}:${PORT}/"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

check_caddy() {
  if ! command -v caddy > /dev/null 2>&1; then
    echo "x caddy not found. Install with: brew install caddy  OR  apt install caddy"
    exit 1
  fi
}

check_port() {
  if lsof -i ":${PORT}" -sTCP:LISTEN > /dev/null 2>&1; then
    local owner
    owner=$(lsof -i ":${PORT}" -sTCP:LISTEN -t 2>/dev/null | head -1)
    local cmd
    cmd=$(ps -p "$owner" -o comm= 2>/dev/null || echo "unknown")
    if [[ "$cmd" == *"caddy"* ]] && [[ -f "$PID_FILE" ]] && [[ "$(cat "$PID_FILE")" == "$owner" ]]; then
      return 1  # it's our caddy, already running
    fi
    echo "x Port ${PORT} already in use by PID ${owner} (${cmd})"
    echo "  Override with: PORTAL_PORT=<port> $0"
    exit 1
  fi
  return 0
}

gen_caddyfile() {
  local root="${1:-${SCRIPT_DIR}}"

  if [[ -z "$PASS_HASH" ]]; then
    echo "x PORTAL_PASSWORD_HASH is not set."
    echo "  Generate one with: ./serve.sh --gen-hash"
    exit 1
  fi

  # Write Caddyfile — use quoted heredoc to preserve $ in bcrypt hash,
  # then substitute the 5 variables with sed.
  cat > "$CADDYFILE" <<'CADDY'
{
    admin off
}

http://__HOST__:__PORT__ {
    root * __ROOT__
    encode gzip

    basic_auth * {
        __USER__ __PASS__
    }

    @gsd_write {
        method PUT
        path /tasks.json /status/*
    }
    reverse_proxy @gsd_write 127.0.0.1:__GSD_PORT__

    @fonts {
        path /fonts/*.ttf /fonts/*.woff2
    }
    header @fonts Cache-Control "public, max-age=31536000, immutable"

    @html {
        path *.html
    }
    header @html Cache-Control "no-cache"

    @json {
        path /index.json /tasks.json /status/*
    }
    header @json Cache-Control "no-store"

    file_server {
        index portal.html
    }
}
CADDY

  # Inject variables (use | delimiter to avoid conflicts with / in paths and hashes)
  sed -i.bak \
    -e "s|__HOST__|${HOST}|g" \
    -e "s|__PORT__|${PORT}|g" \
    -e "s|__ROOT__|${root}|g" \
    -e "s|__USER__|${USER}|g" \
    -e "s|__GSD_PORT__|${GSD_PORT}|g" \
    "$CADDYFILE"
  # PASS_HASH contains $ and / — use awk for safe substitution
  awk -v pass="$PASS_HASH" '{gsub(/__PASS__/, pass); print}' "$CADDYFILE" > "${CADDYFILE}.tmp"
  mv "${CADDYFILE}.tmp" "$CADDYFILE"
  rm -f "${CADDYFILE}.bak"

  echo "ok Generated Caddyfile -> ${CADDYFILE}"
}

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

gen_hash() {
  check_caddy
  echo "Enter password (input hidden):"
  caddy hash-password --algorithm bcrypt
}

start_foreground() {
  check_caddy
  check_port || { echo "ok Already running -> ${URL}"; exit 0; }
  gen_caddyfile "$SCRIPT_DIR"
  echo "$$" > "$PID_FILE"
  trap 'rm -f "$PID_FILE" "$CADDYFILE"' EXIT
  echo "ok Starting factory portal -> ${URL}"
  exec caddy run --config "$CADDYFILE"
}

start_open() {
  check_caddy
  check_port || { echo "ok Already running"; open "$URL"; exit 0; }
  gen_caddyfile "$SCRIPT_DIR"
  echo "$$" > "$PID_FILE"
  trap 'rm -f "$PID_FILE" "$CADDYFILE"' EXIT
  open "$URL" &
  echo "ok Starting factory portal -> ${URL}"
  exec caddy run --config "$CADDYFILE"
}

install_systemd() {
  check_caddy
  gen_caddyfile "$REMOTE_ROOT"

  # --- Caddy (factory-portal.service) ---
  sudo tee "$SYSTEMD_PATH_CADDY" > /dev/null <<UNIT
[Unit]
Description=Factory Portal — Caddy static server + GSD proxy
After=network.target gsd-backend.service
Wants=gsd-backend.service

[Service]
Type=simple
User=nesbitt
WorkingDirectory=${REMOTE_ROOT}
ExecStart=/usr/bin/caddy run --config ${REMOTE_ROOT}/Caddyfile
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

  # --- GSD Python backend (gsd-backend.service) ---
  sudo tee "$SYSTEMD_PATH_GSD" > /dev/null <<UNIT
[Unit]
Description=GSD Backend — Python PUT server for agent task/status writes
After=network.target

[Service]
Type=simple
User=nesbitt
WorkingDirectory=${REMOTE_ROOT}
Environment=GSD_HOST=127.0.0.1
Environment=GSD_PORT=${GSD_PORT}
ExecStart=/usr/bin/python3 ${REMOTE_ROOT}/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

  sudo systemctl daemon-reload
  sudo systemctl enable "${SYSTEMD_CADDY}" "${SYSTEMD_GSD}"
  sudo systemctl restart "${SYSTEMD_GSD}"
  sudo systemctl restart "${SYSTEMD_CADDY}"

  echo "ok Installed: ${SYSTEMD_CADDY} + ${SYSTEMD_GSD}"
  echo "  Portal  -> ${URL}"
  echo "  Port    -> ${PORT}"
  echo "  GSD     -> 127.0.0.1:${GSD_PORT}"
  echo "  Root    -> ${REMOTE_ROOT}"
  echo ""
  echo "  Manage:"
  echo "    sudo systemctl status ${SYSTEMD_CADDY}"
  echo "    sudo systemctl status ${SYSTEMD_GSD}"
  echo "    sudo journalctl -u ${SYSTEMD_CADDY} -f"
}

show_status() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ok Running (foreground, PID $(cat "$PID_FILE"))"
  elif lsof -i ":${PORT}" -sTCP:LISTEN > /dev/null 2>&1; then
    echo "ok Something is listening on port ${PORT}"
  else
    echo "x Not running"
  fi
  echo "  ${URL}"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "${1:-}" in
  --systemd)
    install_systemd
    ;;
  --open)
    start_open
    ;;
  --status)
    show_status
    ;;
  --gen-hash)
    gen_hash
    ;;
  -h|--help)
    head -14 "$0" | tail -12
    ;;
  *)
    start_foreground
    ;;
esac
