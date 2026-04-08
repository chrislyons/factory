#!/bin/bash
# hermes-ig88.sh — launch IG-88 Hermes gateway with Matrix adapter
#
# IG-88 was migrated from coordinator-managed mode to a standalone Hermes
# gateway running matrix-nio directly. This wrapper is invoked by
# com.bootindustries.hermes-ig88.plist via Infisical, which already
# supplies MATRIX_TOKEN_PAN_IG88 in the environment.
#
# Room isolation: IG-88 has no room allowlist in the Hermes Matrix adapter.
# We rely on GATEWAY_ALLOWED_USERS=@chrislyons:matrix.org to silently drop
# any message whose sender isn't Chris, regardless of room. This is safe
# because (a) group-chat unauthorized senders are silently ignored by
# GatewayRouter._handle_message(), and (b) no pairing prompts are offered
# (unauthorized_dm_behavior: ignore).

set -euo pipefail

# Required: Infisical-provided Pantalaimon access token for @ig88bot.
if [[ -z "${MATRIX_TOKEN_PAN_IG88:-}" ]]; then
  echo "ERROR: MATRIX_TOKEN_PAN_IG88 not set — Infisical injection failed" >&2
  exit 2
fi

# Map the Infisical variable name into what matrix-nio expects.
MATRIX_ACCESS_TOKEN=${MATRIX_TOKEN_PAN_IG88}
export MATRIX_ACCESS_TOKEN

# Matrix homeserver (Pantalaimon local proxy — handles E2EE for us).
export MATRIX_HOMESERVER="http://localhost:41200"
export MATRIX_USER_ID="@ig88bot:matrix.org"
export MATRIX_ENCRYPTION="false"

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
#   exit 2  — MATRIX_TOKEN_PAN_IG88 missing (existing)
#   exit 3  — profile missing or not pinned to `provider: custom`
#   exit 4  — matrix-nio not importable in hermes-agent venv
#   exit 5  — local model file missing
#   exit 6  — mlx-vlm-ig88 not reachable on :41988
# ---------------------------------------------------------------------------

IG88_PROFILE_CFG="${HERMES_HOME}/config.yaml"
HERMES_AGENT_PY="/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3"
IG88_MODEL_CONFIG="/Users/nesbitt/models/gemma-4-e4b-it-6bit/config.json"
MLX_VLM_HEALTH_URL="http://127.0.0.1:41988/health"

# 1. Profile must exist AND pin provider: custom (top-level key). If the pin
#    is removed, Hermes's runtime_provider.py will auto-detect OPENROUTER_API_KEY
#    from env and silently cloud-route the local filesystem model path — the
#    exact failure mode that bit us overnight 2026-04-07 (FCT055 RC-1).
if [[ ! -f "${IG88_PROFILE_CFG}" ]]; then
  echo "ERROR: IG-88 profile config not found at ${IG88_PROFILE_CFG}" >&2
  exit 3
fi
if ! grep -qE '^provider:[[:space:]]*custom([[:space:]]|$)' "${IG88_PROFILE_CFG}"; then
  echo "ERROR: ${IG88_PROFILE_CFG} is missing top-level 'provider: custom'." >&2
  echo "       Without this pin, OPENROUTER_API_KEY in env will cause Hermes" >&2
  echo "       to silently cloud-route local inference. See FCT055 RC-1." >&2
  exit 3
fi

# 2. matrix-nio must be importable in the hermes-agent venv. Missing dep was
#    the cause of the 00:32 KeepAlive respawn loop during FCT054 cutover.
"${HERMES_AGENT_PY}" -c 'import nio' 2>/dev/null || {
  echo "ERROR: matrix-nio not installed in hermes-agent venv (${HERMES_AGENT_PY})" >&2
  echo "       Install with: uv tool install --with matrix-nio hermes-agent" >&2
  exit 4
}

# 3. Local model weights must be present on disk. Cheap stat only — no load.
if [[ ! -f "${IG88_MODEL_CONFIG}" ]]; then
  echo "ERROR: local model config missing at ${IG88_MODEL_CONFIG}" >&2
  echo "       IG-88 runs gemma-4-e4b-it-6bit (FCT054). Re-download model." >&2
  exit 5
fi

# 4. mlx-vlm-ig88 must be listening on :41988. 3s max so launchd start is
#    not delayed. If the inference server is down there is no point bringing
#    the gateway up — it will just 000-retry on every Matrix message.
if ! curl -sf --max-time 3 "${MLX_VLM_HEALTH_URL}" >/dev/null 2>&1; then
  echo "ERROR: mlx-vlm-ig88 not reachable at ${MLX_VLM_HEALTH_URL}" >&2
  echo "       Check: launchctl list | grep mlx-vlm-ig88" >&2
  exit 6
fi

# Working directory for file/terminal toolsets. Hermes's file_tools reads
# TERMINAL_CWD from env (tools/terminal_tool.py:492), NOT from the profile
# config's terminal.cwd field — that field is only used by the terminal
# toolset's shell context. Export explicitly so the file toolset lands in
# the right place too. The `cd` below covers terminal-toolset shell state.
export TERMINAL_CWD="/Users/nesbitt/dev/factory/agents/ig88"
cd "${TERMINAL_CWD}"

# FCT059: raise Hermes agent wall-clock from 600s default to 2h for autonomous workloads.
export HERMES_AGENT_TIMEOUT=7200

# FCT059: IG-88 has no cloud fallback (fallback_providers: []); defeat auxiliary routing poisoning at the env-var source.
unset OPENROUTER_API_KEY

# FCT060: Factory Conductor Webhook Memo Protocol.
# Bridge WEBHOOK_SECRET_IG88 (from Infisical) into Hermes's generic
# WEBHOOK_SECRET env var. IG-88's Matrix ACL is @chrislyons-only per FCT055,
# so the webhook is the only non-Matrix channel into IG-88's reasoning loop.
# HMAC replaces the Matrix user ACL as the trust boundary for this path.
# See docs/fct/FCT060 for architecture.
if [[ -z "${WEBHOOK_SECRET_IG88:-}" ]]; then
  echo "ERROR: WEBHOOK_SECRET_IG88 not set — Infisical injection failed" >&2
  exit 2
fi
export WEBHOOK_ENABLED=true
export WEBHOOK_PORT=41977
# Unquoted intentional: see hermes-boot.sh for rationale.
export WEBHOOK_SECRET=$WEBHOOK_SECRET_IG88
unset WEBHOOK_SECRET_IG88

exec /Users/nesbitt/.local/bin/hermes \
  --profile ig88 \
  gateway run --replace
