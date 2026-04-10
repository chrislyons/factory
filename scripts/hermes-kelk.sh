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
#   exit 6  — mlx-vlm-kelk not reachable on :41966
# ---------------------------------------------------------------------------

KELK_PROFILE_CFG="${HERMES_HOME}/config.yaml"
HERMES_AGENT_PY="/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3"
KELK_MODEL_CONFIG="/Users/nesbitt/models/gemma-4-e4b-it-6bit/config.json"
MLX_VLM_HEALTH_URL="http://127.0.0.1:41966/health"

# 1. Profile must exist AND pin provider: custom. See FCT055 RC-1.
# FCT064: provider: custom may be top-level or indented under model: dict.
if [[ ! -f "${KELK_PROFILE_CFG}" ]]; then
  echo "ERROR: Kelk profile config not found at ${KELK_PROFILE_CFG}" >&2
  exit 3
fi
if ! grep -qE '^[[:space:]]*provider:[[:space:]]*custom([[:space:]]|$)' "${KELK_PROFILE_CFG}"; then
  echo "ERROR: ${KELK_PROFILE_CFG} is missing 'provider: custom'." >&2
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
#    gemma-4-e4b-it-6bit via mlx-vlm-kelk on :41966).
if [[ ! -f "${KELK_MODEL_CONFIG}" ]]; then
  echo "ERROR: local model config missing at ${KELK_MODEL_CONFIG}" >&2
  exit 5
fi

# 4. mlx-vlm-kelk must be listening on :41966. 3s max.
if ! curl -sf --max-time 3 "${MLX_VLM_HEALTH_URL}" >/dev/null 2>&1; then
  echo "ERROR: mlx-vlm-factory not reachable at ${MLX_VLM_HEALTH_URL}" >&2
  echo "       Check: launchctl list | grep mlx-vlm-kelk" >&2
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

# FCT060 (drive-by fix): defeat auxiliary routing poisoning at the env-var
# source, same as IG-88's wrapper. See hermes-boot.sh for rationale. Kelk's
# errors.log at 17:26:13 shows the exact OpenRouter HTTP 400 signature this
# unset prevents.
unset OPENROUTER_API_KEY

# FCT061: harden against Hermes issue #5358 (provider routing bypass).
# Force HERMES_INFERENCE_PROVIDER so runtime_provider.py uses the explicit
# 'requested' arg at both gateway/run.py::_resolve_runtime_agent_kwargs() and
# runtime_provider.py::_resolve_openrouter_runtime(). Also unset OPENAI_API_KEY
# which auth.py:872 treats identically to OPENROUTER_API_KEY for provider
# auto-detection (presence-only check, not value validation).
export HERMES_INFERENCE_PROVIDER=custom
unset OPENAI_API_KEY

# FCT064 (2026-04-09): close remaining cloud-escape paths. See hermes-boot.sh
# for the full explanation — same set of scrubs for consistency.
unset ANTHROPIC_API_KEY
unset ANTHROPIC_AUTH_TOKEN
unset OPENAI_BASE_URL
unset OPENAI_API_BASE

# FCT060: Factory Conductor Webhook Memo Protocol.
# Bridge WEBHOOK_SECRET_KELK (from Infisical) into Hermes's generic
# WEBHOOK_SECRET env var. See docs/fct/FCT060 for architecture.
if [[ -z "${WEBHOOK_SECRET_KELK:-}" ]]; then
  echo "ERROR: WEBHOOK_SECRET_KELK not set — Infisical injection failed" >&2
  exit 2
fi
export WEBHOOK_ENABLED=true
export WEBHOOK_PORT=41952
# Unquoted intentional: see hermes-boot.sh for rationale.
export WEBHOOK_SECRET=$WEBHOOK_SECRET_KELK
unset WEBHOOK_SECRET_KELK

exec /Users/nesbitt/.local/bin/hermes \
  --profile kelk \
  gateway run --replace
