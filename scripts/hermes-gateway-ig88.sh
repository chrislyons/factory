#!/bin/bash
# hermes-gateway-ig88.sh — launch IG-88 Hermes gateway with Matrix adapter
#
# IG-88 was migrated from coordinator-managed mode to a standalone Hermes
# gateway running matrix-nio directly. This wrapper is invoked by
# com.bootindustries.hermes-ig88-gateway.plist via Infisical, which already
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

cd /Users/nesbitt/dev/factory/agents/ig88

exec /Users/nesbitt/.local/bin/hermes \
  --profile ig88 \
  gateway run --replace
