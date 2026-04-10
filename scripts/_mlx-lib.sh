#!/bin/bash
# _mlx-lib.sh — shared plist-swap + MLX health primitives.
#
# SOURCE this file; do not execute it directly. All helpers live in the
# `mlx_lib::` namespace to avoid collision with caller scripts. Callers must
# set `set -eo pipefail` on their own. Bash 3.2 compatible (stock macOS).
#
# Authored for FCT064 Phase 3 to factor common logic out of
# factory-mlx-switch.sh and factory-profile.sh.

# Guard against direct execution.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  cat <<'EOF' >&2
_mlx-lib.sh: this file is a library and must be sourced, not executed.

Usage (from another shell script):
  . "$(dirname "$0")/_mlx-lib.sh"
  mlx_lib::refuse_root
  mlx_lib::swap "$old_label" "$new_label" "$new_plist" "$port"
EOF
  exit 2
fi

# ---- config ----
: "${MLX_LIB_PLIST_DIR:=$HOME/Library/LaunchAgents}"
: "${MLX_LIB_UID:=$(id -u)}"
: "${MLX_LIB_CANONICAL_MODEL_PATH:=/Users/nesbitt/models/gemma-4-e4b-it-6bit}"

# ---- helpers ----

# mlx_lib::die <msg...> — print to stderr and exit 1
mlx_lib::die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# mlx_lib::warn <msg...> — print to stderr, no exit
mlx_lib::warn() {
  printf 'WARN: %s\n' "$*" >&2
}

# mlx_lib::info <msg...>
mlx_lib::info() {
  printf '%s\n' "$*"
}

# mlx_lib::refuse_root — abort if running as root
mlx_lib::refuse_root() {
  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    mlx_lib::die "must not run as root (use your normal user account)"
  fi
}

# mlx_lib::current_label_on_port <port>
# Echoes the com.bootindustries.* label currently bootstrapped whose plist
# targets <port>. Prints "none" if nothing matches. Parses `launchctl list`
# stdout only (no `launchctl list <label>` — avoid argv leakage per FCT061).
mlx_lib::current_label_on_port() {
  local port="$1"
  local listing line label plist
  listing="$(launchctl list 2>/dev/null | awk '{print $3}' | grep -E '^com\.bootindustries\.mlx-' || true)"
  while IFS= read -r label; do
    [ -z "$label" ] && continue
    plist="${MLX_LIB_PLIST_DIR}/${label}.plist"
    if [ -f "$plist" ] && grep -q ">${port}<" "$plist" 2>/dev/null; then
      echo "$label"
      return 0
    fi
  done <<< "$listing"
  echo "none"
}

# mlx_lib::bootout <label> — tolerant of already-out
mlx_lib::bootout() {
  local label="$1"
  [ -z "$label" ] || [ "$label" = "none" ] && return 0
  launchctl bootout "gui/${MLX_LIB_UID}/${label}" 2>/dev/null || true
  sleep 1
}

# mlx_lib::bootstrap <label> <repo_plist_path>
# install -m 644 → LaunchAgents/, then bootstrap. Returns 0 on success.
mlx_lib::bootstrap() {
  local label="$1" repo_plist="$2"
  local deployed="${MLX_LIB_PLIST_DIR}/${label}.plist"
  [ -f "$repo_plist" ] || mlx_lib::die "repo plist missing: $repo_plist"
  install -m 644 "$repo_plist" "$deployed"
  if ! launchctl bootstrap "gui/${MLX_LIB_UID}" "$deployed" 2>/dev/null; then
    mlx_lib::warn "bootstrap returned nonzero for $label (may already be loaded)"
  fi
}

# mlx_lib::wait_for_port <port> <timeout_s>
# Polls /v1/models on the port, returns 0 when it responds with "data", else 1.
mlx_lib::wait_for_port() {
  local port="$1" timeout="${2:-30}"
  local i
  printf 'Waiting for /v1/models on :%s ' "$port"
  for (( i=1; i<=timeout; i++ )); do
    sleep 1
    printf '.'
    if curl -sS -m 1 "http://127.0.0.1:${port}/v1/models" 2>/dev/null | grep -q '"data"'; then
      printf ' up after %ss\n' "$i"
      return 0
    fi
  done
  printf '\n'
  mlx_lib::warn "/v1/models on :${port} did not respond within ${timeout}s"
  return 1
}

# mlx_lib::swap <old_label> <new_label> <new_plist> <port>
# Full rotation: bootout old, install+bootstrap new, poll /v1/models.
mlx_lib::swap() {
  local old_label="$1" new_label="$2" new_plist="$3" port="$4"
  [ -f "$new_plist" ] || mlx_lib::die "new plist missing: $new_plist"
  if [ -n "$old_label" ] && [ "$old_label" != "none" ] && [ "$old_label" != "$new_label" ]; then
    mlx_lib::info "Booting out: $old_label"
    mlx_lib::bootout "$old_label"
  fi
  mlx_lib::info "Bootstrapping: $new_label ← $new_plist"
  mlx_lib::bootstrap "$new_label" "$new_plist"
  mlx_lib::wait_for_port "$port" 30 || return 1
  return 0
}

# mlx_lib::health_check_port <port> <timeout_s>
# Returns 0 if /v1/models responds within timeout, else 1.
mlx_lib::health_check_port() {
  local port="$1" timeout="${2:-5}"
  curl -sS -m "$timeout" "http://127.0.0.1:${port}/v1/models" 2>/dev/null \
    | grep -q '"data"'
}

# mlx_lib::kickstart_hermes <agent>
# Kickstart a bootindustries hermes-<agent> service if loaded. No-op otherwise.
mlx_lib::kickstart_hermes() {
  local agent="$1"
  local label="com.bootindustries.hermes-${agent}"
  if launchctl list 2>/dev/null | awk '{print $3}' | grep -qx "$label"; then
    mlx_lib::info "Kickstarting $label"
    launchctl kickstart -k "gui/${MLX_LIB_UID}/${label}" 2>/dev/null || \
      mlx_lib::warn "kickstart returned nonzero for $label"
  else
    mlx_lib::warn "$label not loaded — skipping kickstart"
  fi
}

# mlx_lib::smoke_test_inference <port> [<model_path>]
# POST a trivial "say OK" request using the absolute-path model ID (default:
# canonical E4B). Returns 0 on 200 OK within 30s, else 1.
mlx_lib::smoke_test_inference() {
  local port="$1"
  local model="${2:-$MLX_LIB_CANONICAL_MODEL_PATH}"
  local body http_code
  body=$(cat <<JSON
{"model":"${model}","messages":[{"role":"user","content":"say OK"}],"max_tokens":4}
JSON
)
  http_code=$(curl -sS -m 30 -o /dev/null -w '%{http_code}' \
    -X POST "http://127.0.0.1:${port}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "$body" 2>/dev/null || echo "000")
  if [ "$http_code" = "200" ]; then
    mlx_lib::info "Smoke test OK on :${port}"
    return 0
  fi
  mlx_lib::warn "Smoke test failed on :${port} (HTTP ${http_code})"
  return 1
}
