#!/bin/bash
# hermes-gonzo.sh — launch Gonzo Hermes gateway with Matrix adapter
#
# FCT067: Standalone Hermes gateway with native E2EE (python-olm + matrix-nio[e2e]).
# Direct to matrix.org — Pantalaimon retired.
# Invoked via: h-gonzo or manually with infisical-env.sh factory --
#
# NOTE: Gonzo is a chat agent (trading/market analysis). Uses Factory project
# secrets (NOUS_FACTORY_API_KEY for OpenRouter/Nous Portal routing).

set -euo pipefail

# Required: Infisical-provided Matrix access token for @gonzo.
if [[ -z "${MATRIX_TOKEN_GONZO:-}" ]]; then
  echo "ERROR: MATRIX_TOKEN_GONZO not set — Infisical injection failed" >&2
  exit 2
fi

# Map Infisical var name into what matrix-nio expects.
MATRIX_ACCESS_TOKEN=${MATR...GONZO}
export MATRIX_ACCESS_TOKEN

# Matrix homeserver
export MATRIX_HOMESERVER="https://matrix.org"
export MATRIX_USER_ID="@gonzo:matrix.org"
export MATRIX_ENCRYPTION="true"

# Recovery key for SSSS device self-sign
if [[ -n "${MATRIX_RECOVERY_KEY_GONZO:-}" ]]; then
  export MATRIX_RECOVERY_KEY="${MATRIX_RECOVERY_KEY_GONZO}"
  unset MATRIX_RECOVERY_KEY_GONZO
fi

# User allowlist
export GATEWAY_ALLOWED_USERS="@chrislyons:matrix.org"

# Hermes profile directory
export HERMES_HOME="/Users/nesbitt/.hermes/profiles/gonzo"

# ---------------------------------------------------------------------------
# Preflight guards
#   exit 2  — MATRIX_TOKEN_GONZO missing
#   exit 3  — profile missing or not pinned to provider: custom
#   exit 4  — matrix-nio not importable
# ---------------------------------------------------------------------------

GONZO_PROFILE_CFG="${HERMES_HOME}/config.yaml"
HERMES_AGENT_PY="/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3"

# 1. Profile must exist AND pin provider: custom
if [[ ! -f "${GONZO_PROFILE_CFG}" ]]; then
  echo "ERROR: Gonzo profile config not found at ${GONZO_PROFILE_CFG}" >&2
  exit 3
fi
if ! grep -qE '^[[:space:]]*provider:[[:space:]]*custom([[:space:]]|$)' "${GONZO_PROFILE_CFG}"; then
  echo "ERROR: ${GONZO_PROFILE_CFG} is missing 'provider: custom'." >&2
  echo "       Without this pin, OPENROUTER_API_KEY in env will cause Hermes" >&2
  echo "       to silently cloud-route local inference. See FCT055 RC-1." >&2
  exit 3
fi

# 2. mautrix must be importable
"${HERMES_AGENT_PY}" -c 'import mautrix' 2>/dev/null || {
  echo "ERROR: mautrix not installed in hermes-agent venv (${HERMES_AGENT_PY})" >&2
  exit 4
}

# Working directory
cd "/Users/nesbitt/dev/factory/agents/gonzo"

# Timeouts for autonomous workloads
export HERMES_AGENT_TIMEOUT=7200
export HERMES_STREAM_READ_TIMEOUT=600
export HERMES_STREAM_STALE_TIMEOUT=600

# FCT061+: defeat auxiliary routing poisoning by scrubbing cloud keys that
# would trigger Hermes auto-detection (issue #5358). Force HERMES_INFERENCE_PROVIDER
# so runtime_provider.py uses explicit 'requested' args at both gateway and
# runtime layer.
export HERMES_INFERENCE_PROVIDER=custom
unset OPENROUTER_API_KEY
unset OPENAI_API_KEY
unset ANTHROPIC_API_KEY
unset ANTHROPIC_AUTH_TOKEN
unset OPENAI_BASE_URL
unset OPENAI_API_BASE

exec /Users/nesbitt/.local/bin/hermes \
  --profile gonzo \
  gateway run --replace
