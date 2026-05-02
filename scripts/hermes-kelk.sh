#!/bin/bash
# hermes-kelk.sh — launch Kelk Hermes gateway with Matrix adapter
#
# FCT067: Standalone Hermes gateway with native E2EE (python-olm + matrix-nio[e2e]).
# Direct to matrix.org — Pantalaimon retired.
# Invoked by com.bootindustries.hermes-kelk.plist via infisical-env.sh factory.

set -euo pipefail

# Required: Infisical-provided Matrix access token for @sir.kelk.
if [[ -z "${MATRIX_TOKEN_KELK:-}" ]]; then
  echo "ERROR: MATRIX_TOKEN_KELK not set — Infisical injection failed" >&2
  exit 2
fi

# Map the Infisical variable name into what matrix-nio expects.
MATRIX_ACCESS_TOKEN=${MATRIX_TOKEN_KELK}
export MATRIX_ACCESS_TOKEN

# Matrix homeserver (direct — native E2EE via python-olm + matrix-nio[e2e]).
export MATRIX_HOMESERVER="https://matrix.org"
export MATRIX_USER_ID="@sir.kelk:matrix.org"
export MATRIX_ENCRYPTION="true"

# Recovery key enables mautrix to self-sign the device on startup via SSSS.
if [[ -n "${MATRIX_RECOVERY_KEY_KELK:-}" ]]; then
  export MATRIX_RECOVERY_KEY="${MATRIX_RECOVERY_KEY_KELK}"
  unset MATRIX_RECOVERY_KEY_KELK
fi

# User allowlist. Kelk responds to Chris plus other agents for cross-agent
# coordination.
export GATEWAY_ALLOWED_USERS="@chrislyons:matrix.org,@boot.industries:matrix.org,@ig88bot:matrix.org"

# Hermes profile directory (isolates state, sessions, matrix store, logs).
export HERMES_HOME="/Users/nesbitt/.hermes/profiles/kelk"

# ---------------------------------------------------------------------------
# Preflight guards (FCT055 Phase 4 — structural defenses).
#
#   exit 2  — MATRIX_TOKEN_KELK missing (above)
#   exit 3  — profile missing or not pinned to `provider: custom`
#   exit 4  — matrix-nio not importable in hermes-agent venv
#   exit 5  — local model file missing
#   exit 6  — mlx-lm-factory-kelk not reachable on :41967
#   exit 6  — mlx-lm-factory-kelk not reachable on :41967
# ---------------------------------------------------------------------------

KELK_PROFILE_CFG="${HERMES_HOME}/config.yaml"
HERMES_AGENT_PY="/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3"
KELK_MODEL_CONFIG="/Users/nesbitt/models/Ornstein-26B-A4B-it-MLX-4bit/config.json"
MLX_VLM_HEALTH_URL="http://127.0.0.1:41967/v1/models"

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

# 2. mautrix must be importable in the hermes-agent venv. Hermes 0.9.0 uses
#    mautrix[encryption] for native Matrix E2EE (not matrix-nio).
"${HERMES_AGENT_PY}" -c 'import mautrix' 2>/dev/null || {
  echo "ERROR: mautrix not installed in hermes-agent venv (${HERMES_AGENT_PY})" >&2
  echo "       Install with: uv pip install --python ${HERMES_AGENT_PY} 'mautrix[encryption]' aiosqlite asyncpg Markdown" >&2
  exit 4
}

# 3. Local model weights must be present on disk (FCT074: Kelk shares
#    26B-A4B via mlx-lm-factory-26b-kelk on :41967).
if [[ ! -f "${KELK_MODEL_CONFIG}" ]]; then
  echo "ERROR: local model config missing at ${KELK_MODEL_CONFIG}" >&2
  exit 5
fi

# 4. mlx-lm-factory-kelk must be listening on :41967. 15s max.
if ! curl -sf --max-time 15 "${MLX_VLM_HEALTH_URL}" >/dev/null 2>&1; then
  echo "ERROR: mlx-lm-factory-kelk not reachable at ${MLX_VLM_HEALTH_URL}" >&2
  echo "       Check: launchctl list | grep mlx-lm-factory-kelk" >&2
  exit 6
fi

# Working directory — v0.11.0 reads from config.yaml terminal.cwd, not env.
# TERMINAL_CWD env var deprecated in v0.11.0 (was tools/terminal_tool.py:492).
# Keep `cd` so the process CWD matches (launchd defaults to /).
cd "/Users/nesbitt/dev/factory/agents/kelk"

# FCT059: raise Hermes agent wall-clock from 600s default to 2h for autonomous workloads.
export HERMES_AGENT_TIMEOUT=7200

# FCT064: raise stream read timeout from 60s default to 10 min. Local mlx-vlm
# prefills take 60-120s for large contexts — the default 60s triggers spurious
# "Connection to provider dropped (ReadTimeout)" retries on every turn.
export HERMES_STREAM_READ_TIMEOUT=600
export HERMES_STREAM_STALE_TIMEOUT=600

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
unset NOUS_MIMO_FACTORY_KEY

# Ensure /opt/homebrew/bin (rg, node, etc.) is first in PATH — Python/uv
# prepends its own bin dir at startup, pushing homebrew below it. Set PATH
# explicitly here so tool subprocesses always find homebrew binaries first.
export PATH="/opt/homebrew/bin:$PATH"

# FCT071: Enable HTTP API server for Hermes Workspace frontend.
# Binds localhost only — no API key needed for loopback.
# Workspace connects here for live chat, SSE streaming, tool execution.
export API_SERVER_ENABLED=true
export API_SERVER_HOST=127.0.0.1
export API_SERVER_PORT=8643


exec /Users/nesbitt/.local/bin/hermes \
  --profile kelk \
  gateway run --replace
