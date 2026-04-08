#!/bin/bash
# hermes-boot.sh — launch Boot Hermes gateway with Matrix adapter
#
# FCT059: migrated from coordinator-dispatched HTTP mode (hermes-serve.py on
# :41970) to standalone `hermes gateway run`, matching the IG-88 pattern.
# Boot now owns its Matrix connection via matrix-nio -> Pantalaimon rather
# than receiving dispatched prompts over HTTP from coordinator-rs.
#
# The coordinator remains the inter-agent conductor at the Matrix protocol
# level (room routing, allowlists, approvals), but no longer speaks HTTP
# to Boot. Removes the hermes-serve.py shutdown race and eliminates the
# HTTP dispatch failure mode.
#
# Invoked by com.bootindustries.hermes-boot.plist via infisical-env.sh,
# which already supplies MATRIX_TOKEN_PAN_BOOT in the environment.

set -euo pipefail

# Required: Infisical-provided Pantalaimon access token for @boot.industries.
if [[ -z "${MATRIX_TOKEN_PAN_BOOT:-}" ]]; then
  echo "ERROR: MATRIX_TOKEN_PAN_BOOT not set — Infisical injection failed" >&2
  exit 2
fi

# Map the Infisical variable name into what matrix-nio expects.
MATRIX_ACCESS_TOKEN=${MATRIX_TOKEN_PAN_BOOT}
export MATRIX_ACCESS_TOKEN

# Matrix homeserver (Pantalaimon local proxy — handles E2EE for us).
export MATRIX_HOMESERVER="http://localhost:41200"
export MATRIX_USER_ID="@boot.industries:matrix.org"
export MATRIX_ENCRYPTION="false"

# User allowlist. Boot responds to Chris plus other agents for cross-agent
# coordination (teammate tagging, handoffs) and the coordinator user for
# system messages, approvals, and infra alerts. Matches coordinator's room
# allowlist semantics.
export GATEWAY_ALLOWED_USERS="@chrislyons:matrix.org,@coord:matrix.org,@ig88bot:matrix.org,@sir.kelk:matrix.org"

# Hermes profile directory (isolates state, sessions, matrix store, logs).
export HERMES_HOME="/Users/nesbitt/.hermes/profiles/boot"

# ---------------------------------------------------------------------------
# Preflight guards (FCT055 Phase 4 — structural defenses).
#
#   exit 2  — MATRIX_TOKEN_PAN_BOOT missing (above)
#   exit 3  — profile missing or not pinned to `provider: custom`
#   exit 4  — matrix-nio not importable in hermes-agent venv
#   exit 5  — local model file missing
#   exit 6  — mlx-vlm-factory not reachable on :41961
# ---------------------------------------------------------------------------

BOOT_PROFILE_CFG="${HERMES_HOME}/config.yaml"
BOOT_PROFILE_TMPL="/Users/nesbitt/dev/factory/scripts/profiles/boot-config.yaml.tmpl"
HERMES_AGENT_PY="/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3"
BOOT_MODEL_CONFIG="/Users/nesbitt/models/gemma-4-e4b-it-6bit/config.json"
MLX_VLM_HEALTH_URL="http://127.0.0.1:41961/health"

# FCT060: render live profile config from the versioned template by
# substituting only the WEBHOOK_SECRET_BOOT placeholder. envsubst with an
# explicit variable allowlist does NOT touch any other ${...} occurrences in
# the template (prompt bodies, comments, etc. remain literal). The rendered
# file is chmod 600 immediately so the HMAC secret is not world-readable.
# Without this step, Hermes would see ${WEBHOOK_SECRET_BOOT} as a literal
# string and reject startup with "Route 'memo' has no HMAC secret".
if [[ ! -f "${BOOT_PROFILE_TMPL}" ]]; then
  echo "ERROR: Boot profile template not found at ${BOOT_PROFILE_TMPL}" >&2
  exit 3
fi
if [[ -z "${WEBHOOK_SECRET_BOOT:-}" ]]; then
  echo "ERROR: WEBHOOK_SECRET_BOOT not set — Infisical injection failed" >&2
  exit 2
fi
mkdir -p "${HERMES_HOME}"
envsubst '${WEBHOOK_SECRET_BOOT}' < "${BOOT_PROFILE_TMPL}" > "${BOOT_PROFILE_CFG}"
chmod 600 "${BOOT_PROFILE_CFG}"

# 1. Profile must exist AND pin provider: custom. See FCT055 RC-1 for why.
if [[ ! -f "${BOOT_PROFILE_CFG}" ]]; then
  echo "ERROR: Boot profile config not found at ${BOOT_PROFILE_CFG} (render failed?)" >&2
  exit 3
fi
if ! grep -qE '^provider:[[:space:]]*custom([[:space:]]|$)' "${BOOT_PROFILE_CFG}"; then
  echo "ERROR: ${BOOT_PROFILE_CFG} is missing top-level 'provider: custom'." >&2
  echo "       Without this pin, OPENROUTER_API_KEY in env will cause Hermes" >&2
  echo "       to silently cloud-route local inference. See FCT055 RC-1." >&2
  exit 3
fi

# 2. matrix-nio must be importable in the hermes-agent venv. Boot now uses
#    matrix-nio directly at runtime (gateway mode), so missing dep is a hard
#    startup failure — not a latent crash-import.
"${HERMES_AGENT_PY}" -c 'import nio' 2>/dev/null || {
  echo "ERROR: matrix-nio not installed in hermes-agent venv (${HERMES_AGENT_PY})" >&2
  echo "       Install with: uv tool install --with matrix-nio hermes-agent" >&2
  exit 4
}

# 3. Local model weights must be present on disk (FCT054: Boot shares
#    gemma-4-e4b-it-6bit via mlx-vlm-factory on :41961).
if [[ ! -f "${BOOT_MODEL_CONFIG}" ]]; then
  echo "ERROR: local model config missing at ${BOOT_MODEL_CONFIG}" >&2
  exit 5
fi

# 4. mlx-vlm-factory must be listening on :41961. 3s max.
if ! curl -sf --max-time 3 "${MLX_VLM_HEALTH_URL}" >/dev/null 2>&1; then
  echo "ERROR: mlx-vlm-factory not reachable at ${MLX_VLM_HEALTH_URL}" >&2
  echo "       Check: launchctl list | grep mlx-vlm-factory" >&2
  exit 6
fi

# Working directory for file/terminal toolsets. Hermes's file_tools reads
# TERMINAL_CWD from env (tools/terminal_tool.py:492), NOT from the profile
# config's terminal.cwd field. Export explicitly and `cd` so both the env
# var path and the os.getcwd() fallback land in the right place.
export TERMINAL_CWD="/Users/nesbitt/dev/factory/agents/boot"
cd "${TERMINAL_CWD}"

# FCT059: raise Hermes agent wall-clock from 600s default to 2h for autonomous workloads.
export HERMES_AGENT_TIMEOUT=7200

exec /Users/nesbitt/.local/bin/hermes \
  --profile boot \
  gateway run --replace
