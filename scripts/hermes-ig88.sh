#!/bin/bash
# hermes-ig88.sh — launch IG-88 Hermes gateway with Matrix adapter
#
# FCT067: Standalone Hermes gateway with native E2EE (python-olm + matrix-nio[e2e]).
# Direct to matrix.org — Pantalaimon retired. Main model: Nous Mimo Pro.
# Invoked by com.bootindustries.hermes-ig88.plist via infisical-env.sh factory.
#
# Room isolation: IG-88 has no room allowlist in the Hermes Matrix adapter.
# We rely on GATEWAY_ALLOWED_USERS=@chrislyons:matrix.org to silently drop
# any message whose sender isn't Chris, regardless of room. This is safe
# because (a) group-chat unauthorized senders are silently ignored by
# GatewayRouter._handle_message(), and (b) no pairing prompts are offered
# (unauthorized_dm_behavior: ignore).

set -euo pipefail

# Required: Infisical-provided Matrix access token for @ig88bot.
if [[ -z "${MATRIX_TOKEN_IG88:-}" ]]; then
  echo "ERROR: MATRIX_TOKEN_IG88 not set — Infisical injection failed" >&2
  exit 2
fi

# Map the Infisical variable name into what matrix-nio expects.
MATRIX_ACCESS_TOKEN=${MATRIX_TOKEN_IG88}
export MATRIX_ACCESS_TOKEN

# Matrix homeserver (direct — native E2EE via python-olm + matrix-nio[e2e]).
export MATRIX_HOMESERVER="https://matrix.org"
export MATRIX_USER_ID="@ig88bot:matrix.org"
export MATRIX_ENCRYPTION="true"

# Recovery key enables mautrix to self-sign the device on startup via SSSS.
if [[ -n "${MATRIX_RECOVERY_KEY_IG88:-}" ]]; then
  export MATRIX_RECOVERY_KEY="${MATRIX_RECOVERY_KEY_IG88}"
  unset MATRIX_RECOVERY_KEY_IG88
fi

# User allowlist — the primary room-isolation mechanism. Only Chris can
# address IG-88. Any other sender (Boot, Kelk, other Matrix users) is
# silently dropped. This is the only defense against responding in shared
# rooms like Backrooms.
export GATEWAY_ALLOWED_USERS="@chrislyons:matrix.org"

# Hermes profile directory (isolates state, sessions, matrix store, logs).
export HERMES_HOME="/Users/nesbitt/.hermes/profiles/ig88"

# OpenRouter cloud inference (already in Infisical env).
# OPENROUTER_API_KEY is passed through by infisical-env.sh.

# ---------------------------------------------------------------------------
# Preflight guards (FCT055 Phase 4 — structural defenses against the overnight
# failure class). All checks must complete in <5s total so launchd start is
# not delayed. Distinct exit codes so errors are grep-able in launchd logs.
#
#   exit 2  — MATRIX_TOKEN_IG88 missing (above)
#   exit 3  — profile missing or not pinned to `provider: custom`
#   exit 4  — matrix-nio not importable in hermes-agent venv
#   exit 5  — local model file missing
#   exit 6  — mlx-vlm-ig88 not reachable on :41988
# ---------------------------------------------------------------------------

IG88_PROFILE_CFG="${HERMES_HOME}/config.yaml"
HERMES_AGENT_PY="/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3"
IG88_MODEL_CONFIG="/Users/nesbitt/models/gemma-4-e4b-it-6bit/config.json"
MLX_VLM_HEALTH_URL="http://127.0.0.1:41988/health"

# 1. Profile must exist AND declare an explicit provider (not missing/auto).
#    FCT066: accepts openrouter (31B main) or custom (local fallback).
#    Without an explicit provider, Hermes auto-detect can silently mis-route.
if [[ ! -f "${IG88_PROFILE_CFG}" ]]; then
  echo "ERROR: IG-88 profile config not found at ${IG88_PROFILE_CFG}" >&2
  exit 3
fi
if ! grep -qE '^[[:space:]]*provider:[[:space:]]*(custom|openrouter|nous-nemotron)' "${IG88_PROFILE_CFG}"; then
  echo "ERROR: ${IG88_PROFILE_CFG} is missing explicit provider (custom, custom:*, or openrouter)." >&2
  echo "       Without this, Hermes auto-detect may mis-route inference. See FCT055/FCT066. Valid: custom, custom:*, openrouter, nous-nemotron." >&2
  exit 3
fi

# 2. mautrix must be importable in the hermes-agent venv. Hermes 0.9.0 uses
#    mautrix[encryption] for native Matrix E2EE (not matrix-nio).
"${HERMES_AGENT_PY}" -c 'import mautrix' 2>/dev/null || {
  echo "ERROR: mautrix not installed in hermes-agent venv (${HERMES_AGENT_PY})" >&2
  echo "       Install with: uv pip install --python ${HERMES_AGENT_PY} 'mautrix[encryption]' aiosqlite asyncpg Markdown" >&2
  exit 4
}

# 3. Local model weights must be present on disk. Cheap stat only — no load.
if [[ ! -f "${IG88_MODEL_CONFIG}" ]]; then
  echo "ERROR: local model config missing at ${IG88_MODEL_CONFIG}" >&2
  echo "       IG-88 runs gemma-4-e4b-it-6bit (FCT054). Re-download model." >&2
  exit 5
fi

# 4. mlx-vlm-ig88 on :41988 is now the AUX model (FCT066 — main is OpenRouter).
#    Downgraded from hard exit to warning: a crashed aux server should not
#    prevent the gateway from starting. Main inference will still work.
if ! curl -sf --max-time 3 "${MLX_VLM_HEALTH_URL}" >/dev/null 2>&1; then
  echo "WARN: mlx-vlm-ig88 not reachable at ${MLX_VLM_HEALTH_URL} — aux tasks will fail" >&2
  echo "      Check: launchctl list | grep mlx-vlm-ig88" >&2
fi

# Working directory — v0.11.0 reads from config.yaml terminal.cwd, not env.
# TERMINAL_CWD env var deprecated in v0.11.0 (was tools/terminal_tool.py:492).
# Keep `cd` so the process CWD matches (launchd defaults to /).
cd "/Users/nesbitt/dev/factory/agents/ig88"

# FCT059: raise Hermes agent wall-clock from 600s default to 2h for autonomous workloads.
export HERMES_AGENT_TIMEOUT=7200

# FCT064: raise stream read timeout from 60s default to 5 min. Local mlx-vlm
# prefills take 60-120s for large contexts — the default 60s triggers spurious
# "Connection to provider dropped (ReadTimeout)" retries on every turn.
export HERMES_STREAM_READ_TIMEOUT=600
# FCT064: stale stream detector — kills connection if no tokens arrive within
# this window. Default 180s is too short for large prefills (37k = ~2 min of
# silence before first token). Set to match HERMES_STREAM_READ_TIMEOUT.
export HERMES_STREAM_STALE_TIMEOUT=600

# FCT066: OpenRouter recovered. OPENROUTER_API_KEY flows through from Infisical
# to authenticate the Gemma-4-31B main model. HERMES_INFERENCE_PROVIDER=custom
# removed — profile now specifies provider: openrouter explicitly.
# OPENAI_API_KEY still scrubbed to prevent aux auto-detect from escaping.
unset OPENAI_API_KEY

# FCT064 (2026-04-09): close remaining cloud-escape paths. See hermes-boot.sh
# for the full explanation — same set of scrubs for consistency. IG-88 is
# especially sensitive: its profile was wedged in a half-unwound FCT062
# OpenRouter pivot and every inference call was escaping to OR/Anthropic
# until the profile was reverted. See FCT064 Root Cause 2.
unset ANTHROPIC_API_KEY
unset ANTHROPIC_AUTH_TOKEN
unset OPENAI_BASE_URL
unset OPENAI_API_BASE

exec /Users/nesbitt/.local/bin/hermes \
  --profile ig88 \
  gateway run --replace
