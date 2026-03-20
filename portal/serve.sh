#!/bin/bash
# Factory Portal — Caddy static server for dist/ with optional sidecar proxies
#
# Usage:
#   ./serve.sh                  Start Caddy in foreground
#   ./serve.sh --open           Start Caddy + open browser
#   ./serve.sh --systemd        Install/update systemd services on Blackbox
#   ./serve.sh --status         Show local listener status
#   ./serve.sh --gen-hash       Generate a bcrypt password hash
#
# Required env vars:
#   PORTAL_PASSWORD_HASH        bcrypt hash from: caddy hash-password --algorithm bcrypt
#
# Optional env vars:
#   PORTAL_USER                 basicauth username (default: admin)
#   PORTAL_PORT                 bind port (default: 41933)
#   PORTAL_HOST                 bind host (default: 127.0.0.1)
#   GSD_BACKEND_HOST            task/status sidecar host (default: 127.0.0.1)
#   GSD_BACKEND_PORT            task/status sidecar port (default: 41935)
#   COORDINATOR_BACKEND_HOST    coordinator API host (default: 127.0.0.1)
#   COORDINATOR_BACKEND_PORT    coordinator API port (optional; unset keeps those routes static/404)
#   PORTAL_START_GSD            auto-start local server.py for task/status routes (default: 1)
#
set -euo pipefail

SCRIPT_DIR_EARLY="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "${SCRIPT_DIR_EARLY}/.env" ]]; then
  set +u
  set -o allexport
  source "${SCRIPT_DIR_EARLY}/.env"
  set +o allexport
  set -u
fi

PORT="${PORTAL_PORT:-41910}"
HOST="${PORTAL_HOST:-127.0.0.1}"
USER="${PORTAL_USER:-admin}"
PASS_HASH="${PORTAL_PASSWORD_HASH:-}"
GSD_HOST="${GSD_BACKEND_HOST:-127.0.0.1}"
GSD_PORT="${GSD_BACKEND_PORT:-41911}"
COORD_HOST="${COORDINATOR_BACKEND_HOST:-127.0.0.1}"
COORD_PORT="${COORDINATOR_BACKEND_PORT:-}"
START_GSD="${PORTAL_START_GSD:-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="${SCRIPT_DIR}/dist"
DATA_SERVER="${SCRIPT_DIR}/server.py"
CADDYFILE="${SCRIPT_DIR}/Caddyfile"
PID_FILE="${SCRIPT_DIR}/.factory-portal.pid"
GSD_PID_FILE="${SCRIPT_DIR}/.gsd-backend.pid"
GSD_LOG_FILE="${SCRIPT_DIR}/.gsd-backend.log"
SYSTEMD_CADDY="factory-portal.service"
SYSTEMD_GSD="gsd-backend.service"
SYSTEMD_PATH_CADDY="/etc/systemd/system/${SYSTEMD_CADDY}"
SYSTEMD_PATH_GSD="/etc/systemd/system/${SYSTEMD_GSD}"
REMOTE_ROOT="/home/nesbitt/projects/factory-portal"
REMOTE_DIST="${REMOTE_ROOT}/dist"

URL="http://${HOST}:${PORT}/"

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
      return 1
    fi
    echo "x Port ${PORT} already in use by PID ${owner} (${cmd})"
    echo "  Override with: PORTAL_PORT=<port> $0"
    exit 1
  fi
  return 0
}

require_password_hash() {
  if [[ -z "$PASS_HASH" ]]; then
    echo "x PORTAL_PASSWORD_HASH is not set."
    echo "  Generate one with: ./serve.sh --gen-hash"
    exit 1
  fi
}

require_dist() {
  if [[ ! -f "${DIST_DIR}/portal.html" ]]; then
    echo "x dist/ is missing. Run: pnpm build"
    exit 1
  fi
}

start_local_gsd_if_needed() {
  if [[ "$START_GSD" != "1" ]]; then
    return
  fi
  if [[ ! -f "$DATA_SERVER" ]]; then
    return
  fi
  if lsof -i ":${GSD_PORT}" -sTCP:LISTEN > /dev/null 2>&1; then
    echo "ok Using existing task/status sidecar -> http://${GSD_HOST}:${GSD_PORT}/"
    return
  fi
  if ! command -v python3 > /dev/null 2>&1; then
    echo "x python3 not found; cannot auto-start server.py"
    exit 1
  fi

  GSD_HOST="${GSD_HOST}" GSD_PORT="${GSD_PORT}" GSD_DATA_ROOT="${SCRIPT_DIR}" \
    python3 "$DATA_SERVER" > "$GSD_LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$GSD_PID_FILE"
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "x Failed to start task/status sidecar"
    [[ -f "$GSD_LOG_FILE" ]] && tail -20 "$GSD_LOG_FILE"
    exit 1
  fi
  echo "ok Started task/status sidecar -> http://${GSD_HOST}:${GSD_PORT}/"
}

stop_local_gsd_if_needed() {
  if [[ -f "$GSD_PID_FILE" ]]; then
    local pid
    pid=$(cat "$GSD_PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$GSD_PID_FILE"
  fi
}

gen_caddyfile() {
  local dist_root="${1:-${DIST_DIR}}"
  local project_root="${2:-${SCRIPT_DIR}}"
  local coordinator_block=""

  require_password_hash

  if [[ -n "$COORD_PORT" ]]; then
    coordinator_block=$(cat <<EOF
    handle /approvals/* {
        reverse_proxy ${COORD_HOST}:${COORD_PORT}
    }

    handle /budget/* {
        reverse_proxy ${COORD_HOST}:${COORD_PORT}
    }

    handle /analytics/* {
        reverse_proxy ${COORD_HOST}:${COORD_PORT}
    }

    handle /agents/* {
        reverse_proxy ${COORD_HOST}:${COORD_PORT}
    }

    handle /runs/* {
        reverse_proxy ${COORD_HOST}:${COORD_PORT}
    }

EOF
)
  fi

  cat > "$CADDYFILE" <<EOF
{
    admin off
}

http://${HOST}:${PORT} {
    encode gzip

    basic_auth * {
        ${USER} ${PASS_HASH}
    }

${coordinator_block}    handle /tasks.json {
        reverse_proxy ${GSD_HOST}:${GSD_PORT}
    }

    handle /jobs.json {
        reverse_proxy ${GSD_HOST}:${GSD_PORT}
    }

    handle /status/* {
        reverse_proxy ${GSD_HOST}:${GSD_PORT}
    }

    handle /repos/* {
        root * ${project_root}
        file_server
    }

    handle {
        root * ${dist_root}

        @fonts {
            path /fonts/*.ttf /fonts/*.woff2
        }
        header @fonts Cache-Control "public, max-age=31536000, immutable"

        @html {
            path *.html
        }
        header @html Cache-Control "no-cache"

        @json {
            path /index.json
        }
        header @json Cache-Control "no-store"

        file_server {
            index portal.html
        }
    }
}
EOF

  echo "ok Generated Caddyfile -> ${CADDYFILE}"
}

gen_hash() {
  check_caddy
  echo "Enter password (input hidden):"
  caddy hash-password --algorithm bcrypt
}

cleanup_local() {
  rm -f "$PID_FILE" "$CADDYFILE"
  stop_local_gsd_if_needed
}

start_foreground() {
  check_caddy
  require_dist
  check_port || { echo "ok Already running -> ${URL}"; exit 0; }
  start_local_gsd_if_needed
  gen_caddyfile "$DIST_DIR" "$SCRIPT_DIR"
  echo "$$" > "$PID_FILE"
  trap cleanup_local EXIT
  echo "ok Starting factory portal -> ${URL}"
  exec caddy run --config "$CADDYFILE"
}

start_open() {
  check_caddy
  require_dist
  check_port || { echo "ok Already running"; open "$URL"; exit 0; }
  start_local_gsd_if_needed
  gen_caddyfile "$DIST_DIR" "$SCRIPT_DIR"
  echo "$$" > "$PID_FILE"
  trap cleanup_local EXIT
  open "$URL" &
  echo "ok Starting factory portal -> ${URL}"
  exec caddy run --config "$CADDYFILE"
}

install_systemd() {
  check_caddy
  require_password_hash
  gen_caddyfile "$REMOTE_DIST" "$REMOTE_ROOT"

  sudo tee "$SYSTEMD_PATH_CADDY" > /dev/null <<UNIT
[Unit]
Description=Factory Portal — Caddy static server + API proxies
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

  sudo tee "$SYSTEMD_PATH_GSD" > /dev/null <<UNIT
[Unit]
Description=Factory Portal task/status sidecar
After=network.target

[Service]
Type=simple
User=nesbitt
WorkingDirectory=${REMOTE_ROOT}
Environment=GSD_HOST=127.0.0.1
Environment=GSD_PORT=${GSD_PORT}
Environment=GSD_DATA_ROOT=${REMOTE_ROOT}
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
  echo "  Portal       -> ${URL}"
  echo "  Dist         -> ${REMOTE_DIST}"
  echo "  Task/status  -> ${GSD_HOST}:${GSD_PORT}"
  if [[ -n "$COORD_PORT" ]]; then
    echo "  Coordinator  -> ${COORD_HOST}:${COORD_PORT}"
  else
    echo "  Coordinator  -> disabled (unset COORDINATOR_BACKEND_PORT)"
  fi
}

show_status() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ok Caddy running (foreground, PID $(cat "$PID_FILE"))"
  elif lsof -i ":${PORT}" -sTCP:LISTEN > /dev/null 2>&1; then
    echo "ok Something is listening on port ${PORT}"
  else
    echo "x Caddy not running"
  fi

  if lsof -i ":${GSD_PORT}" -sTCP:LISTEN > /dev/null 2>&1; then
    echo "ok Task/status sidecar listening on ${GSD_PORT}"
  else
    echo "x Task/status sidecar not running on ${GSD_PORT}"
  fi

  echo "  ${URL}"
}

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
    head -18 "$0" | tail -16
    ;;
  *)
    start_foreground
    ;;
esac
