#!/bin/bash
# hermes-boot.sh — launch Boot Hermes gateway with Matrix adapter
#
# FCT067: Standalone Hermes gateway with native E2EE (python-olm + matrix-nio[e2e]).
# Direct to matrix.org — Pantalaimon retired.
# Invoked by com.bootindustries.hermes-boot.plist via infisical-env.sh factory.

set -euo pipefail

# Required: Infisical-provided Matrix access token for @boot.industries.
if [[ -z "${MATRIX_TOKEN_BOOT:-}" ]]; then
  echo "ERROR: MATRIX_TOKEN_BOOT not set — Infisical injection failed" >&2
  exit 2
fi

# Map the Infisical variable name into what matrix-nio expects.
MATRIX_ACCESS_TOKEN=${MATRIX_TOKEN_BOOT}
export MATRIX_ACCESS_TOKEN

# Matrix homeserver (direct — native E2EE via python-olm + matrix-nio[e2e]).
export MATRIX_HOMESERVER="https://matrix.org"
export MATRIX_USER_ID="@boot.industries:matrix.org"
export MATRIX_ENCRYPTION="true"

# Recovery key enables mautrix to self-sign the device on startup via SSSS.
if [[ -n "${MATRIX_RECOVERY_KEY_BOOT:-}" ]]; then
  export MATRIX_RECOVERY_KEY="${MATRIX_RECOVERY_KEY_BOOT}"
  unset MATRIX_RECOVERY_KEY_BOOT
fi

# User allowlist. Boot responds to Chris plus other agents for cross-agent
# coordination (teammate tagging, handoffs).
export GATEWAY_ALLOWED_USERS="@chrislyons:matrix.org,@ig88bot:matrix.org,@sir.kelk:matrix.org"

# Hermes profile directory (isolates state, sessions, matrix store, logs).
export HERMES_HOME="/Users/nesbitt/.hermes/profiles/boot"

# ---------------------------------------------------------------------------
# Preflight guards (FCT055 Phase 4 — structural defenses).
#
#   exit 2  — MATRIX_TOKEN_BOOT missing (above)
#   exit 3  — profile missing or not pinned to `provider: custom`
#   exit 4  — matrix-nio not importable in hermes-agent venv
#   exit 5  — local model file missing
#   exit 6  — mlx-lm not reachable on :41966
# ---------------------------------------------------------------------------

BOOT_PROFILE_CFG="${HERMES_HOME}/config.yaml"
HERMES_AGENT_PY="/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3"
BOOT_MODEL_CONFIG="/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit/config.json"
MLX_VLM_HEALTH_URL="http://127.0.0.1:41966/v1/models"

# 1. Profile must exist AND pin provider: custom. See FCT055 RC-1 for why.
# FCT064: provider: custom may be top-level (legacy) or indented under model:
# dict (Hermes docs canonical form). Accept both.
if [[ ! -f "${BOOT_PROFILE_CFG}" ]]; then
  echo "ERROR: Boot profile config not found at ${BOOT_PROFILE_CFG}" >&2
  exit 3
fi
if ! grep -qE '^[[:space:]]*provider:[[:space:]]*custom([[:space:]]|$)' "${BOOT_PROFILE_CFG}"; then
  echo "ERROR: ${BOOT_PROFILE_CFG} is missing 'provider: custom'." >&2
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

# 3. Local model weights must be present on disk (Boot uses
#    Ornstein-Hermes-3.6-27b via mlx-lm on :41966).
BOOT_MODEL_CONFIG="/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit/config.json"
if [[ ! -f "${BOOT_MODEL_CONFIG}" ]]; then
  echo "ERROR: local model config missing at ${BOOT_MODEL_CONFIG}" >&2
  exit 5
fi

# 4. mlx-lm must be listening on :41966. 15s max.
if ! curl -sf --max-time 3 "${MLX_VLM_HEALTH_URL}" >/dev/null 2>&1; then
  echo "ERROR: mlx-lm not reachable at ${MLX_VLM_HEALTH_URL}" >&2
  echo "       Check: launchctl list | grep mlx-vlm-boot" >&2
  exit 6
fi

# Working directory — v0.11.0 reads from config.yaml terminal.cwd, not env.
# TERMINAL_CWD env var deprecated in v0.11.0 (was tools/terminal_tool.py:492).
# Keep `cd` so the process CWD matches (launchd defaults to /).
cd "/Users/nesbitt/dev/factory/agents/boot"

# FCT059: raise Hermes agent wall-clock from 600s default to 2h for autonomous workloads.
export HERMES_AGENT_TIMEOUT=7200

# FCT064: raise stream read timeout from 60s default to 10 min. Local mlx-vlm
# prefills take 60-120s for large contexts — the default 60s triggers spurious
# "Connection to provider dropped (ReadTimeout)" retries on every turn.
export HERMES_STREAM_READ_TIMEOUT=600
export HERMES_STREAM_STALE_TIMEOUT=600

# FCT060 (drive-by fix): defeat auxiliary routing poisoning at the env-var
# source, same as IG-88's wrapper. infisical-env.sh factory -- injects
# OPENROUTER_API_KEY into this process environment because it exists in the
# factory Infisical project. If any Hermes auxiliary slot is not explicitly
# pinned to provider: custom (and new slots get added upstream faster than
# we enumerate them), runtime_provider.py auto-detects OPENROUTER_API_KEY
# and silently cloud-routes auxiliary calls — sending the local model's
# filesystem path as the model ID and producing HTTP 400. The earlier
# FCT059 A2 reasoning ("Boot/Kelk may need cloud fallback for face-consultant
# MCP later") does not justify keeping the env var live at the gateway level;
# any cloud-fallback code path can re-export it at its own point of use.
unset OPENROUTER_API_KEY

# FCT061: harden against Hermes issue #5358 (provider routing bypass).
# Force HERMES_INFERENCE_PROVIDER so runtime_provider.py uses the explicit
# 'requested' arg at both gateway/run.py::_resolve_runtime_agent_kwargs() and
# runtime_provider.py::_resolve_openrouter_runtime(). Also unset OPENAI_API_KEY
# which auth.py:872 treats identically to OPENROUTER_API_KEY for provider
# auto-detection (presence-only check, not value validation). Boot's profile
# .env contains OPENAI_API_KEY=not-needed as a placeholder which would
# otherwise trigger the same auto-detect path.
export HERMES_INFERENCE_PROVIDER=custom
unset OPENAI_API_KEY

# FCT064 (2026-04-09): close remaining cloud-escape paths. Two failure modes
# were observed in ~/.hermes/profiles/*/logs/errors.log:
#   (a) aux calls (session_search, compression) escaping to Anthropic via
#       _resolve_auto chain Step-2 payment-fallback after an OpenRouter 402
#   (b) _resolve_custom_runtime resolving via OPENAI_BASE_URL which, if set
#       to an Anthropic-compat proxy from Infisical, routes "custom" provider
#       calls to Anthropic without touching the profile's base_url
# Anthropic budget is exhausted until 2026-05-01 and OpenRouter is locked
# out; the safe posture is to make every non-local provider impossible to
# reach until explicitly re-enabled.
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
export API_SERVER_PORT=8642

exec /Users/nesbitt/.local/bin/hermes \
  --profile boot \
  gateway run --replace
