#!/bin/bash
# hermes-kelk.sh — launch Kelk Hermes gateway with Matrix adapter
#
# FCT059: migrated from coordinator-dispatched HTTP mode (hermes-serve.py on
# :41972) to standalone `hermes gateway run`, matching the IG-88 pattern.
# Kelk now owns its Matrix connection via matrix-nio -> Pantalaimon rather
# than receiving dispatched prompts over HTTP from coordinator-rs.
#
# The coordinator remains the inter-agent conductor at the Matrix protocol
# level (room routing, allowlists, approvals), but no longer speaks HTTP
# to Kelk. Removes the hermes-serve.py shutdown race and eliminates the
# HTTP dispatch failure mode.
#
# Invoked by com.bootindustries.hermes-kelk.plist via infisical-env.sh,
# which already supplies MATRIX_TOKEN_PAN_KELK in the environment.

set -euo pipefail

# Required: Infisical-provided Pantalaimon access token for @sir.kelk.
if [[ -z "${MATRIX_TOKEN_PAN_KELK:-}" ]]; then
  echo "ERROR: MATRIX_TOKEN_PAN_KELK not set — Infisical injection failed" >&2
  exit 2
fi

# Map the Infisical variable name into what matrix-nio expects.
MATRIX_ACCESS_TOKEN=${MATRIX_TOKEN_PAN_KELK}
export MATRIX_ACCESS_TOKEN

# Matrix homeserver (Pantalaimon local proxy — handles E2EE for us).
export MATRIX_HOMESERVER="http://localhost:41200"
export MATRIX_USER_ID="@sir.kelk:matrix.org"
export MATRIX_ENCRYPTION="false"

# User allowlist. Kelk responds to Chris plus other agents for cross-agent
# coordination and the coordinator user for system messages/approvals.
# Matches coordinator's room allowlist semantics.
export GATEWAY_ALLOWED_USERS="@chrislyons:matrix.org,@coord:matrix.org,@boot.industries:matrix.org,@ig88bot:matrix.org"

# Hermes profile directory (isolates state, sessions, matrix store, logs).
export HERMES_HOME="/Users/nesbitt/.hermes/profiles/kelk"

# ---------------------------------------------------------------------------
# Preflight guards (FCT055 Phase 4 — structural defenses).
#
#   exit 2  — MATRIX_TOKEN_PAN_KELK missing (above)
#   exit 3  — profile missing or not pinned to `provider: custom`
#   exit 4  — matrix-nio not importable in hermes-agent venv
#   exit 5  — local model file missing
#   exit 6  — mlx-vlm-factory not reachable on :41961
# ---------------------------------------------------------------------------

KELK_PROFILE_CFG="${HERMES_HOME}/config.yaml"
KELK_PROFILE_TMPL="/Users/nesbitt/dev/factory/scripts/profiles/kelk-config.yaml.tmpl"
HERMES_AGENT_PY="/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3"
KELK_MODEL_CONFIG="/Users/nesbitt/models/gemma-4-e4b-it-6bit/config.json"
MLX_VLM_HEALTH_URL="http://127.0.0.1:41961/health"

# FCT060: render live profile config from the versioned template (same
# pattern as Boot and IG-88). Only WEBHOOK_SECRET_KELK is substituted;
# every other ${...} in the template stays literal.
if [[ ! -f "${KELK_PROFILE_TMPL}" ]]; then
  echo "ERROR: Kelk profile template not found at ${KELK_PROFILE_TMPL}" >&2
  exit 3
fi
if [[ -z "${WEBHOOK_SECRET_KELK:-}" ]]; then
  echo "ERROR: WEBHOOK_SECRET_KELK not set — Infisical injection failed" >&2
  exit 2
fi
mkdir -p "${HERMES_HOME}"
envsubst '${WEBHOOK_SECRET_KELK}' < "${KELK_PROFILE_TMPL}" > "${KELK_PROFILE_CFG}"
chmod 600 "${KELK_PROFILE_CFG}"

# 1. Profile must exist AND pin provider: custom. See FCT055 RC-1.
if [[ ! -f "${KELK_PROFILE_CFG}" ]]; then
  echo "ERROR: Kelk profile config not found at ${KELK_PROFILE_CFG} (render failed?)" >&2
  exit 3
fi
if ! grep -qE '^provider:[[:space:]]*custom([[:space:]]|$)' "${KELK_PROFILE_CFG}"; then
  echo "ERROR: ${KELK_PROFILE_CFG} is missing top-level 'provider: custom'." >&2
  echo "       Without this pin, OPENROUTER_API_KEY in env will cause Hermes" >&2
  echo "       to silently cloud-route local inference. See FCT055 RC-1." >&2
  exit 3
fi

# 2. matrix-nio must be importable in the hermes-agent venv. Kelk now uses
#    matrix-nio directly at runtime (gateway mode).
"${HERMES_AGENT_PY}" -c 'import nio' 2>/dev/null || {
  echo "ERROR: matrix-nio not installed in hermes-agent venv (${HERMES_AGENT_PY})" >&2
  echo "       Install with: uv tool install --with matrix-nio hermes-agent" >&2
  exit 4
}

# 3. Local model weights must be present on disk (FCT054: Kelk shares
#    gemma-4-e4b-it-6bit via mlx-vlm-factory on :41961).
if [[ ! -f "${KELK_MODEL_CONFIG}" ]]; then
  echo "ERROR: local model config missing at ${KELK_MODEL_CONFIG}" >&2
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
# config's terminal.cwd field — that field is only used by the terminal
# toolset's shell context. Without TERMINAL_CWD set, os.getcwd() returns
# whatever launchd started the process in (usually /), and the agent's
# file ops land in the wrong directory. Export explicitly and also `cd`
# so both paths are covered.
export TERMINAL_CWD="/Users/nesbitt/dev/factory/agents/kelk"
cd "${TERMINAL_CWD}"

# FCT059: raise Hermes agent wall-clock from 600s default to 2h for autonomous workloads.
export HERMES_AGENT_TIMEOUT=7200

exec /Users/nesbitt/.local/bin/hermes \
  --profile kelk \
  gateway run --replace
