#!/bin/bash
# factory-mlx-switch.sh — switch the model loaded on Kelk's :41962 slot.
#
# Usage:
#   factory-mlx-switch.sh <tag>
#   factory-mlx-switch.sh status
#   factory-mlx-switch.sh list
#
# Tags:
#   gemma-e4b   → mlx_vlm.server + gemma-4-e4b-it-6bit  (FCT054 canonical)
#   hermes4-14b → mlx_lm.server  + Hermes-4-14B-6bit
#   harmonic-9b → mlx_lm.server  + Harmonic-Hermes-9B-MLX-8bit
#
# All three plists target port 41962. Only one may be bootstrapped at a time.
# This script enforces that interlock and updates Kelk's profile config.yaml
# `model:` field to match so the next h-kelk launch picks up the right slug.
#
# Why this exists: FCT054 §Architecture pins all three Hermes agents to a
# single Gemma 4 E4B 6-bit surface. The 2026-04-09 planned divergence (Boot
# and IG-88 temporarily on OpenRouter while Kelk tests local) opened :41962
# as Kelk's experimentation slot. This script makes model swaps low-friction
# without breaking the FCT054 invariant for the other two agents.
#
# Note: stock macOS /bin/bash is 3.2, no associative arrays. Using case stmts.

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_mlx-lib.sh
. "${SCRIPT_DIR}/_mlx-lib.sh"

PORT=41962
PLIST_DIR="$HOME/Library/LaunchAgents"
REPO_PLIST_DIR="$HOME/dev/factory/plists"
KELK_CONFIG="$HOME/.hermes/profiles/kelk/config.yaml"
UID_NUM="$(id -u)"

mlx_lib::refuse_root

# tag → (label, model_path, loader) lookup via case statements
label_for() {
  case "$1" in
    gemma-e4b)   echo "com.bootindustries.mlx-vlm-kelk" ;;
    hermes4-14b) echo "com.bootindustries.mlx-lm-hermes4-14b" ;;
    harmonic-9b) echo "com.bootindustries.mlx-lm-harmonic-9b" ;;
    *) return 1 ;;
  esac
}

model_for() {
  case "$1" in
    gemma-e4b)   echo "/Users/nesbitt/models/gemma-4-e4b-it-6bit" ;;
    hermes4-14b) echo "/Users/nesbitt/models/Hermes-4-14B-6bit" ;;
    harmonic-9b) echo "/Users/nesbitt/models/Harmonic-Hermes-9B-MLX-8bit" ;;
    *) return 1 ;;
  esac
}

loader_for() {
  case "$1" in
    gemma-e4b)   echo "mlx_vlm.server" ;;
    hermes4-14b) echo "mlx_lm.server" ;;
    harmonic-9b) echo "mlx_lm.server" ;;
    *) return 1 ;;
  esac
}

ALL_TAGS="gemma-e4b hermes4-14b harmonic-9b"

usage() {
  cat <<EOF >&2
factory-mlx-switch.sh — switch Kelk's :41962 local model

USAGE:
  factory-mlx-switch.sh <tag>     Switch to the given model
  factory-mlx-switch.sh status    Show currently active model on :41962
  factory-mlx-switch.sh list      List available tags

TAGS:
  gemma-e4b    Gemma 4 E4B 6-bit  (mlx_vlm, FCT054 canonical)
  hermes4-14b  Hermes-4-14B 6bit  (mlx_lm, Nous Hermes namesake)
  harmonic-9b  Harmonic-Hermes-9B 8bit  (mlx_lm, instruction-tuned)
EOF
  exit 2
}

list_tags() {
  echo "Available model tags for :${PORT}:"
  for tag in $ALL_TAGS; do
    label="$(label_for "$tag")"
    model="$(model_for "$tag")"
    loader="$(loader_for "$tag")"
    printf "  %-12s  %-32s  via %s\n" "$tag" "$(basename "$model")" "$loader"
  done
}

current_active() {
  # Returns the tag (or "none") of whichever of the three labels is currently
  # bootstrapped into launchd. Uses `launchctl list | grep` per FCT061 secrets
  # hygiene rules — no `launchctl list <label>` (which dumps argv).
  local listing
  listing="$(launchctl list 2>&1 | awk '{print $3}' || true)"
  for tag in $ALL_TAGS; do
    label="$(label_for "$tag")"
    if grep -qx "$label" <<< "$listing"; then
      echo "$tag"
      return 0
    fi
  done
  echo "none"
}

show_status() {
  local active
  active="$(current_active)"
  echo "Active on :${PORT}: $active"
  if [ "$active" != "none" ]; then
    echo "  label:  $(label_for "$active")"
    echo "  model:  $(model_for "$active")"
    echo "  loader: $(loader_for "$active")"
  fi
  echo
  echo "Probing http://127.0.0.1:${PORT}/v1/models ..."
  if curl -sS -m 3 "http://127.0.0.1:${PORT}/v1/models" 2>&1; then
    echo
  else
    echo "(no response)"
  fi
}

switch_to() {
  local tag="$1"
  local target_label target_model target_plist deployed_plist
  if ! target_label="$(label_for "$tag")"; then
    echo "ERROR: unknown tag '$tag'" >&2
    list_tags >&2
    exit 2
  fi
  target_model="$(model_for "$tag")"
  target_plist="${REPO_PLIST_DIR}/${target_label}.plist"
  deployed_plist="${PLIST_DIR}/${target_label}.plist"

  # 1. Sanity: target model exists on disk
  if [ ! -d "$target_model" ]; then
    echo "ERROR: model dir missing: $target_model" >&2
    exit 3
  fi

  # 2. Sanity: target plist exists in repo
  if [ ! -f "$target_plist" ]; then
    echo "ERROR: plist missing in repo: $target_plist" >&2
    exit 3
  fi

  # 3-6. Delegate bootout → install → bootstrap → /v1/models poll to _mlx-lib.sh.
  # Note: factory-mlx-switch.sh's "active" concept is per-tag (which of the
  # three tagged labels is up), not per-port, so we compute it locally and pass
  # it into mlx_lib::swap. The library handles the same-label kickstart case
  # by detecting old==new and skipping the bootout.
  local active active_label=""
  active="$(current_active)"
  if [ "$active" != "none" ]; then
    active_label="$(label_for "$active")"
  fi
  if [ "$active" = "$tag" ]; then
    echo "Already active: $tag — kickstarting to reload"
    launchctl kickstart -k "gui/${UID_NUM}/${target_label}" 2>&1 || true
    install -m 644 "$target_plist" "$deployed_plist"
    mlx_lib::wait_for_port "$PORT" 20 || {
      echo "Check log: ~/Library/Logs/factory/${target_label#com.bootindustries.}.log" >&2
      exit 4
    }
  else
    mlx_lib::swap "$active_label" "$target_label" "$target_plist" "$PORT" || {
      echo "Check log: ~/Library/Logs/factory/${target_label#com.bootindustries.}.log" >&2
      exit 4
    }
  fi

  # 7. Update Kelk's profile config.yaml model: scalar to match.
  # FCT064 CORRECTION: use the ABSOLUTE PATH, not the basename. The FCT054
  # addendum assumed mlx_vlm's /v1/models listing was authoritative, but
  # Phase 0 pre-flight (2026-04-09) proved that sending any model-id string
  # different from the `--model` argv triggers mlx_vlm's hot-reload codepath,
  # which unloads the local weights and attempts an unauthenticated
  # HuggingFace fetch (HF is not part of our plumbing). The canonical id is
  # the absolute path that matches the plist's --model argv exactly.
  # See FCT064 Root Cause 3 for the reproduced trace.
  local target_slug="$target_model"
  if [ -f "$KELK_CONFIG" ]; then
    echo "Updating Kelk config.yaml model: → $target_slug"
    python3 - "$KELK_CONFIG" "$target_slug" <<'PY'
import sys, re
path, model = sys.argv[1], sys.argv[2]
with open(path) as f:
    txt = f.read()
new_txt, n = re.subn(
    r'^(model:\s*)\S.*$',
    lambda m: m.group(1) + model,
    txt,
    count=1,
    flags=re.M,
)
if n != 1:
    print(f'WARN: top-level model: line not found in {path}', file=sys.stderr)
    sys.exit(0)
with open(path, 'w') as f:
    f.write(new_txt)
print(f'  updated {n} line in {path}')
PY
  else
    echo "WARN: $KELK_CONFIG not found — skipping config update" >&2
  fi

  # 8. Probe /v1/models one more time and show what's loaded
  echo
  echo "=== Active model on :${PORT} ==="
  curl -sS -m 3 "http://127.0.0.1:${PORT}/v1/models" 2>&1
  echo
  echo
  echo "Done. Next: relaunch h-kelk in a fresh TTY to pick up the new model."
}

# ---- main ----
case "${1:-}" in
  ""|"-h"|"--help")
    usage
    ;;
  status)
    show_status
    ;;
  list)
    list_tags
    ;;
  *)
    switch_to "$1"
    ;;
esac
