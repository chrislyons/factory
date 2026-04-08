#!/bin/bash
# infisical-env.sh — Infisical secret injection wrapper for launchd services
# Replaces mcp-env.sh (BWS). Authenticates via Machine Identity, injects all
# project secrets as env vars, then exec's the wrapped command.
#
# Usage:
#   infisical-env.sh <project> [RENAME:NEW=OLD ...] -- command [args...]
#
# Arguments:
#   <project>           One of: factory, bootindu, ig88
#   RENAME:NEW=OLD      Optional env var rename (e.g. RENAME:MATRIX_ACCESS_TOKEN=MATRIX_TOKEN_PAN_BOOT)
#   --                  Separator
#   command [args...]   The service command to exec
#
# Examples:
#   infisical-env.sh factory -- /path/to/coordinator-rs
#   infisical-env.sh factory RENAME:MATRIX_ACCESS_TOKEN=MATRIX_TOKEN_PAN_BOOT -- node server.js

set -euo pipefail

PROJECT="$1"; shift

# Collect rename mappings until we hit "--"
declare -a RENAMES=()
while [[ $# -gt 0 && "$1" != "--" ]]; do
    RENAMES+=("$1"); shift
done
[[ "${1:-}" == "--" ]] && shift  # consume "--"

if [[ $# -eq 0 ]]; then
    echo "infisical-env.sh: no command specified after --" >&2
    exit 1
fi

# Project configuration
# Project IDs are not secrets — they are stable identifiers safe to hardcode
case "$PROJECT" in
    factory)
        KEYCHAIN_SERVICE="infisical-factory"
        PROJECT_ID="${INFISICAL_FACTORY_PROJECT_ID:-231d309b-b29b-44c2-a2e7-d7482ccc2871}"
        ENV="${INFISICAL_FACTORY_ENV:-dev}"
        ;;
    bootindu)
        KEYCHAIN_SERVICE="infisical-bootindu"
        PROJECT_ID="${INFISICAL_BOOTINDU_PROJECT_ID:-0310a939-7983-4b83-8f91-d1498818524c}"
        ENV="${INFISICAL_BOOTINDU_ENV:-dev}"
        ;;
    ig88)
        KEYCHAIN_SERVICE="infisical-ig88"
        PROJECT_ID="${INFISICAL_IG88_PROJECT_ID:-ff3f87f8-d97a-489f-b9f8-0cef268ee7c5}"
        ENV="${INFISICAL_IG88_ENV:-dev}"
        ;;
    *)
        echo "infisical-env.sh: unknown project '$PROJECT' (expected: factory, bootindu, ig88)" >&2
        exit 1
        ;;
esac

DOMAIN="${INFISICAL_API_URL:-https://eu.infisical.com/api}"

# Fetch machine identity credentials — keychain first, launchd env vars as fallback
# (launchd background services may not have keychain access)
PROJECT_UPPER=$(echo "$PROJECT" | tr '[:lower:]' '[:upper:]')
ENV_CLIENT_ID_VAR="INFISICAL_${PROJECT_UPPER}_CLIENT_ID"
ENV_CLIENT_SECRET_VAR="INFISICAL_${PROJECT_UPPER}_CLIENT_SECRET"

CLIENT_ID=$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "client_id" -w 2>/dev/null \
    || echo "${!ENV_CLIENT_ID_VAR:-}")
CLIENT_SECRET=$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "client_secret" -w 2>/dev/null \
    || echo "${!ENV_CLIENT_SECRET_VAR:-}")

if [[ -z "$CLIENT_ID" || -z "$CLIENT_SECRET" ]]; then
    echo "infisical-env.sh: no credentials found for project '$PROJECT'" \
         "(tried keychain '$KEYCHAIN_SERVICE' and env vars ${ENV_CLIENT_ID_VAR}/${ENV_CLIENT_SECRET_VAR})" >&2
    exit 1
fi

# Authenticate and get access token
AUTH_ERR=$(/opt/homebrew/bin/infisical login --method=universal-auth \
    --client-id="$CLIENT_ID" \
    --client-secret="$CLIENT_SECRET" \
    --domain="$DOMAIN" \
    --silent --plain 2>&1)
TOKEN=$(echo "$AUTH_ERR" | grep -v '^\[' | head -1)
if [[ -z "$TOKEN" ]]; then
    echo "infisical-env.sh: authentication failed for project '$PROJECT' domain='$DOMAIN' client_id_len=${#CLIENT_ID} err=$AUTH_ERR" >&2
    exit 1
fi

# Clear credentials from memory
unset CLIENT_ID CLIENT_SECRET

# If renames are needed, use --command to apply them before exec
if [[ ${#RENAMES[@]} -gt 0 ]]; then
    RENAME_CMDS=""
    for R in "${RENAMES[@]}"; do
        # Strip RENAME: prefix if present
        R="${R#RENAME:}"
        NEW="${R%%=*}"
        OLD="${R##*=}"
        RENAME_CMDS+="export ${NEW}=\${${OLD}}; "
    done
    # Build the command string for exec
    CMD_STR="${RENAME_CMDS}exec"
    for arg in "$@"; do
        # Quote args to preserve spaces
        CMD_STR+=" \"$arg\""
    done
    exec /opt/homebrew/bin/infisical run \
        --token="$TOKEN" \
        --projectId="$PROJECT_ID" \
        --env="$ENV" \
        --domain="$DOMAIN" \
        --silent \
        --command "$CMD_STR"
else
    exec /opt/homebrew/bin/infisical run \
        --token="$TOKEN" \
        --projectId="$PROJECT_ID" \
        --env="$ENV" \
        --domain="$DOMAIN" \
        --silent \
        -- "$@"
fi
