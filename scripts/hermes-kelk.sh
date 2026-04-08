#!/bin/bash
# hermes-kelk.sh — launch Kelk Hermes HTTP daemon with preflight guards
#
# Kelk runs in coordinator-dispatched mode: the coordinator posts to this
# daemon over HTTP (FCT052 Phase 4). The plist currently invokes
# hermes-serve.py directly; this wrapper is a drop-in replacement that adds
# the FCT055 Phase 4 structural defenses before exec'ing the same command.
#
# NOTE: The plist is not updated by this change. User decides deployment.
# To adopt: replace the hermes-serve.py ProgramArguments in
# com.bootindustries.hermes-kelk.plist with a single invocation of this
# script.

set -euo pipefail

# ---------------------------------------------------------------------------
# Preflight guards (FCT055 Phase 4)
#
#   exit 3  — profile missing or not pinned to `provider: custom`
#   exit 4  — matrix-nio not importable in hermes-agent venv (cheap sanity)
#   exit 5  — local model file missing
#   exit 6  — mlx-vlm-factory not reachable on :41961
# ---------------------------------------------------------------------------

KELK_PROFILE_CFG="/Users/nesbitt/.hermes/profiles/kelk/config.yaml"
HERMES_AGENT_PY="/Users/nesbitt/.local/share/uv/tools/hermes-agent/bin/python3"
HERMES_SERVE_PY="/Users/nesbitt/dev/factory/scripts/hermes-serve.py"
KELK_MODEL_CONFIG="/Users/nesbitt/models/gemma-4-e4b-it-6bit/config.json"
MLX_VLM_HEALTH_URL="http://127.0.0.1:41961/health"
HERMES_PORT="41972"

# 1. Profile must exist AND pin provider: custom. See FCT055 RC-1.
if [[ ! -f "${KELK_PROFILE_CFG}" ]]; then
  echo "ERROR: Kelk profile config not found at ${KELK_PROFILE_CFG}" >&2
  exit 3
fi
if ! grep -qE '^provider:[[:space:]]*custom([[:space:]]|$)' "${KELK_PROFILE_CFG}"; then
  echo "ERROR: ${KELK_PROFILE_CFG} is missing top-level 'provider: custom'." >&2
  echo "       Without this pin, OPENROUTER_API_KEY in env will cause Hermes" >&2
  echo "       to silently cloud-route local inference. See FCT055 RC-1." >&2
  exit 3
fi

# 2. matrix-nio must be importable in the shared hermes-agent venv.
"${HERMES_AGENT_PY}" -c 'import nio' 2>/dev/null || {
  echo "ERROR: matrix-nio not installed in hermes-agent venv (${HERMES_AGENT_PY})" >&2
  echo "       Install with: uv tool install --with matrix-nio hermes-agent" >&2
  exit 4
}

# 3. Local model weights must be present (FCT054: Kelk shares
#    gemma-4-e4b-it-6bit via mlx-vlm-factory on :41961).
if [[ ! -f "${KELK_MODEL_CONFIG}" ]]; then
  echo "ERROR: local model config missing at ${KELK_MODEL_CONFIG}" >&2
  exit 5
fi

# 4. mlx-vlm-factory must be listening on :41961.
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

exec "${HERMES_AGENT_PY}" "${HERMES_SERVE_PY}" --profile kelk --port "${HERMES_PORT}"
