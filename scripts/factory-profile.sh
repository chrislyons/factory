#!/bin/bash
# factory-profile.sh — rotate Hermes profile tags across Boot/Kelk/IG-88.
#
# FCT064 Phase 3. Supersedes `factory-mlx-switch.sh` for the higher-level
# profile rotation; factory-mlx-switch.sh remains for Kelk's per-model
# experimentation and shares plist primitives via scripts/_mlx-lib.sh.
#
# Tags:
#   ideal           all three agents on local E4B main + local E4B aux
#   ideal --or-aux  local E4B main + OpenRouter 31B aux (inert until OR back)
#   cont-a          Boot/Kelk = ideal; IG-88 top-level → OpenRouter 31B (Stage 2)
#   cont-b <agent>  mega-agent mode: selected agent → local 26B-A4B,
#                   other two Hermes+MLX services booted out
#   status          report current tag, drift, MLX layout, resolved context
#   restore         re-apply the previous tag from the state file
#
# State: ~/.hermes/factory-profile.state  (tag, mega_agent, applied_at, sha256s)
# Log:   ~/Library/Logs/factory/profile-switcher.log
#
# Constraints (FCT064):
#   - Do NOT kickstart IG-88's Hermes gateway or MLX server except for
#     `cont-b ig88`. IG-88 profile edits take effect on next natural restart.
#   - Canonical model ID is the ABSOLUTE PATH. Never use mlx-community/...
#   - Refuse to run as root.
#   - Refuse cont-b if the target agent has an active webhook (log mtime <5s).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_mlx-lib.sh
. "${SCRIPT_DIR}/_mlx-lib.sh"

# ---- config ----
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROFILE_TEMPLATES="${REPO_ROOT}/profiles"
REPO_PLIST_DIR="${REPO_ROOT}/plists"
HERMES_PROFILES="${HOME}/.hermes/profiles"
STATE_FILE="${HOME}/.hermes/factory-profile.state"
CTX_CACHE="${HOME}/.hermes/context_length_cache.yaml"
LOG_DIR="${HOME}/Library/Logs/factory"
LOG_FILE="${LOG_DIR}/profile-switcher.log"
UID_NUM="$(id -u)"

AGENTS="boot kelk ig88"

port_for_agent() {
  case "$1" in
    boot) echo 41961 ;;
    kelk) echo 41962 ;;
    ig88) echo 41988 ;;
    *) return 1 ;;
  esac
}

mlx_label_e4b_for_agent() {
  case "$1" in
    boot) echo "com.bootindustries.mlx-vlm-factory" ;;
    kelk) echo "com.bootindustries.mlx-vlm-kelk" ;;
    ig88) echo "com.bootindustries.mlx-vlm-ig88" ;;
    *) return 1 ;;
  esac
}

mlx_label_26b_for_agent() {
  case "$1" in
    boot) echo "com.bootindustries.mlx-vlm-factory-26b-a4b" ;;
    kelk) echo "com.bootindustries.mlx-vlm-kelk-26b-a4b" ;;
    ig88) echo "com.bootindustries.mlx-vlm-ig88-26b-a4b" ;;
    *) return 1 ;;
  esac
}

hermes_label_for_agent() {
  echo "com.bootindustries.hermes-$1"
}

log_event() {
  mkdir -p "$LOG_DIR"
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"
}

usage() {
  cat <<'EOF' >&2
factory-profile.sh — rotate Hermes profile tags across Boot/Kelk/IG-88

USAGE:
  factory-profile.sh status
  factory-profile.sh ideal [--or-aux]
  factory-profile.sh cont-a
  factory-profile.sh cont-b <agent>       # agent ∈ {boot, kelk, ig88}
  factory-profile.sh restore

See docs/fct/FCT064 for design details.
EOF
  exit 2
}

sha_file() {
  if [ -f "$1" ]; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "missing"
  fi
}

write_state() {
  local tag="$1" mega="${2:-(none)}" variant="${3:-}"
  local applied
  applied="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$STATE_FILE")"
  {
    printf 'tag: %s\n' "$tag"
    printf 'variant: %s\n' "$variant"
    printf 'mega_agent: %s\n' "$mega"
    printf 'applied_at: %s\n' "$applied"
    printf 'previous_tag: %s\n' "${PREVIOUS_TAG:-(none)}"
    printf 'template_sha256:\n'
    for a in $AGENTS; do
      local live="${HERMES_PROFILES}/${a}/config.yaml"
      printf '  %s: %s\n' "$a" "$(sha_file "$live")"
    done
  } > "$STATE_FILE"
}

read_state_field() {
  local field="$1"
  [ -f "$STATE_FILE" ] || { echo ""; return; }
  awk -v k="$field:" '$1==k {print $2; exit}' "$STATE_FILE"
}

check_cont_b_safety() {
  local agent="$1"
  local log="${LOG_DIR}/hermes-${agent}.log"
  if [ -f "$log" ]; then
    # Refuse if mtime within last 5s (active webhook or in-flight request).
    local age
    age=$(( $(date +%s) - $(stat -f %m "$log" 2>/dev/null || echo 0) ))
    if [ "$age" -lt 5 ]; then
      mlx_lib::die "hermes-${agent}.log modified ${age}s ago — refusing cont-b mid-request"
    fi
  fi
}

template_path() {
  local agent="$1" tag="$2" variant="${3:-}"
  if [ "$tag" = "ideal" ] && [ "$variant" = "or-aux" ]; then
    echo "${PROFILE_TEMPLATES}/${agent}/ideal-or.yaml"
  else
    echo "${PROFILE_TEMPLATES}/${agent}/${tag}.yaml"
  fi
}

apply_profile_file() {
  local agent="$1" tpl="$2"
  local dest="${HERMES_PROFILES}/${agent}/config.yaml"
  [ -f "$tpl" ] || mlx_lib::die "template missing: $tpl"
  mkdir -p "$(dirname "$dest")"
  install -m 644 "$tpl" "$dest"
  mlx_lib::info "  $agent ← $(basename "$(dirname "$tpl")")/$(basename "$tpl")"
}

cmd_status() {
  echo "=== factory-profile status ==="
  if [ -f "$STATE_FILE" ]; then
    cat "$STATE_FILE"
  else
    echo "(no state file — tag never applied via factory-profile.sh)"
  fi
  echo
  echo "=== Live profile drift (live SHA256 vs state) ==="
  for a in $AGENTS; do
    local live="${HERMES_PROFILES}/${a}/config.yaml"
    local live_sha
    live_sha="$(sha_file "$live")"
    local state_sha=""
    if [ -f "$STATE_FILE" ]; then
      state_sha=$(awk -v a="${a}:" '$1==a {print $2}' "$STATE_FILE" | tail -1)
    fi
    if [ -n "$state_sha" ] && [ "$live_sha" = "$state_sha" ]; then
      printf '  %-5s  CLEAN  %s\n' "$a" "$live_sha"
    else
      printf '  %-5s  DRIFT  live=%s state=%s\n' "$a" "$live_sha" "${state_sha:-none}"
    fi
  done
  echo
  echo "=== MLX layout ==="
  for a in $AGENTS; do
    local port label
    port="$(port_for_agent "$a")"
    label="$(mlx_lib::current_label_on_port "$port")"
    printf '  %-5s  :%s  %s\n' "$a" "$port" "$label"
  done
  echo
  if [ -f "$CTX_CACHE" ]; then
    echo "=== context_length_cache.yaml ==="
    cat "$CTX_CACHE"
  else
    echo "(no ~/.hermes/context_length_cache.yaml — profile context_length will be resolved on next gateway start)"
  fi
}

cmd_ideal() {
  local variant=""
  if [ "${1:-}" = "--or-aux" ]; then
    variant="or-aux"
    if [ -z "${OPENROUTER_API_KEY:-}" ]; then
      mlx_lib::warn "OPENROUTER_API_KEY not in env — ideal --or-aux will fail every aux call until OR is back"
    fi
  fi
  echo "Applying tag: ideal${variant:+ ($variant)}"
  PREVIOUS_TAG="$(read_state_field tag)"
  for a in $AGENTS; do
    apply_profile_file "$a" "$(template_path "$a" ideal "$variant")"
  done
  # Kickstart Boot and Kelk ONLY. IG-88 is left alone (user constraint).
  mlx_lib::kickstart_hermes boot
  mlx_lib::kickstart_hermes kelk
  mlx_lib::info "IG-88 left undisturbed (profile change takes effect on next natural restart)"
  write_state "ideal" "(none)" "$variant"
  log_event "applied tag=ideal variant=${variant:-none}"
  mlx_lib::info "Done."
}

cmd_cont_a() {
  echo "Applying tag: cont-a"
  mlx_lib::warn "IG-88 cont-a template is INERT until OpenRouter access is restored — expect inference errors"
  PREVIOUS_TAG="$(read_state_field tag)"
  apply_profile_file boot "$(template_path boot cont-a)"
  apply_profile_file kelk "$(template_path kelk cont-a)"
  apply_profile_file ig88 "$(template_path ig88 cont-a)"
  mlx_lib::kickstart_hermes boot
  mlx_lib::kickstart_hermes kelk
  mlx_lib::info "IG-88 left undisturbed (cont-a profile takes effect on next natural restart)"
  write_state "cont-a"
  log_event "applied tag=cont-a"
  mlx_lib::info "Done."
}

cmd_cont_b() {
  local mega="${1:-}"
  case "$mega" in
    boot|kelk|ig88) ;;
    *) mlx_lib::die "cont-b requires <agent> ∈ {boot, kelk, ig88}" ;;
  esac

  local moe_dir="/Users/nesbitt/models/gemma-4-26b-a4b-it-6bit"
  [ -d "$moe_dir" ] || mlx_lib::die "26B-A4B model directory not found: $moe_dir"

  check_cont_b_safety "$mega"

  echo "Applying tag: cont-b mega_agent=${mega}"
  PREVIOUS_TAG="$(read_state_field tag)"

  # 1. Bootout the two non-selected Hermes gateways + their E4B MLX servers.
  for a in $AGENTS; do
    [ "$a" = "$mega" ] && continue
    mlx_lib::info "Offlining non-selected agent: $a"
    mlx_lib::bootout "$(hermes_label_for_agent "$a")"
    mlx_lib::bootout "$(mlx_label_e4b_for_agent "$a")"
    # Also bootout any 26B variant left over from a prior cont-b session.
    mlx_lib::bootout "$(mlx_label_26b_for_agent "$a")"
  done

  # 2. Swap the selected agent's MLX server from E4B to 26B-A4B on its port.
  local port old_e4b new_26b new_plist
  port="$(port_for_agent "$mega")"
  old_e4b="$(mlx_label_e4b_for_agent "$mega")"
  new_26b="$(mlx_label_26b_for_agent "$mega")"
  new_plist="${REPO_PLIST_DIR}/${new_26b}.plist"
  [ -f "$new_plist" ] || mlx_lib::die "plist missing: $new_plist"

  local current_label
  current_label="$(mlx_lib::current_label_on_port "$port")"
  mlx_lib::swap "$current_label" "$new_26b" "$new_plist" "$port" \
    || mlx_lib::die "MLX swap failed for $mega on :$port"

  # 3. Copy cont-b profile into the selected agent's live config.
  apply_profile_file "$mega" "$(template_path "$mega" cont-b)"

  # 4. Kickstart the selected agent's Hermes gateway (cont-b IS allowed to
  #    touch IG-88 — it's the explicit mega-agent selection).
  mlx_lib::kickstart_hermes "$mega"

  # 5. Smoke test the MLX server (note: the 26B model path differs).
  mlx_lib::smoke_test_inference "$port" "$moe_dir" || \
    mlx_lib::warn "Smoke test on :$port did not return 200 — check mlx-vlm log"

  write_state "cont-b" "$mega"
  log_event "applied tag=cont-b mega_agent=${mega}"
  mlx_lib::info "ContB active — $mega on 26B-A4B; other agents offline"
}

cmd_restore() {
  local prev
  prev="$(read_state_field previous_tag)"
  if [ -z "$prev" ] || [ "$prev" = "(none)" ]; then
    mlx_lib::die "no previous_tag in state file — nothing to restore"
  fi
  mlx_lib::info "Restoring previous tag: $prev"
  case "$prev" in
    ideal) cmd_ideal ;;
    cont-a) cmd_cont_a ;;
    cont-b)
      local prev_mega
      prev_mega="$(read_state_field mega_agent)"
      cmd_cont_b "$prev_mega"
      ;;
    *) mlx_lib::die "unknown previous tag: $prev" ;;
  esac
}

# ---- main ----
mlx_lib::refuse_root

case "${1:-}" in
  status) cmd_status ;;
  ideal) shift; cmd_ideal "$@" ;;
  cont-a) cmd_cont_a ;;
  cont-b) shift; cmd_cont_b "$@" ;;
  restore) cmd_restore ;;
  ""|-h|--help) usage ;;
  *) usage ;;
esac
