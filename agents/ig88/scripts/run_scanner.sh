#!/usr/bin/env bash
# run_scanner.sh — Authenticate via Infisical CLI, inject secrets, run scanner.
# Uses infisical CLI (Go binary) which passes Cloudflare WAF.
# Credentials from macOS Keychain only. Nothing written to disk.

set -euo pipefail

SCANNER="/Users/nesbitt/dev/factory/agents/ig88/scripts/h3_scanner.py"
DOMAIN="https://eu.infisical.com"
PROJECT_ID="ff3f87f8-d97a-489f-b9f8-0cef268ee7c5"

CLIENT_ID=$(security find-generic-password -s "infisical-ig88" -a "client_id" -w 2>/dev/null)
CLIENT_SECRET=$(security find-generic-password -s "infisical-ig88" -a "client_secret" -w 2>/dev/null)

if [[ -z "$CLIENT_ID" || -z "$CLIENT_SECRET" ]]; then
    echo "ERROR: Infisical credentials not found in macOS Keychain" >&2
    exit 1
fi

# Get token via CLI (Go binary bypasses Cloudflare WAF that blocks Python urllib)
TOKEN=$(infisical login \
    --method=universal-auth \
    --client-id="$CLIENT_ID" \
    --client-secret="$CLIENT_SECRET" \
    --domain="$DOMAIN" \
    --plain --silent 2>/dev/null)

if [[ -z "$TOKEN" ]]; then
    echo "ERROR: Failed to obtain Infisical access token" >&2
    exit 1
fi

# Export secrets into current environment
eval "$(infisical export \
    --domain="$DOMAIN" \
    --projectId="$PROJECT_ID" \
    --env=dev \
    --token="$TOKEN" \
    --format=dotenv 2>/dev/null | sed 's/^/export /')"

exec /Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3 "$SCANNER" "$@"
