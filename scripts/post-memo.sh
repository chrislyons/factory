#!/bin/bash
# post-memo.sh — Factory Conductor webhook memo poster (FCT060)
#
# Sends an HMAC-SHA256-signed memo to one of the Hermes agents via its local
# webhook platform. The agent treats the memo as a normal user turn in its
# reasoning loop and (per the prompt template) posts its reply back in the
# Chris<>agent Matrix DM room after processing.
#
# Usage:
#   scripts/infisical-env.sh factory -- scripts/post-memo.sh <agent> "<memo body>"
#   scripts/infisical-env.sh factory -- scripts/post-memo.sh <agent> -  # read body from stdin
#
# Agents: boot | kelk | ig88
#
# The outer infisical-env.sh wrapper injects WEBHOOK_SECRET_BOOT,
# WEBHOOK_SECRET_KELK, and WEBHOOK_SECRET_IG88 into the process env. This
# script reads the appropriate one based on the <agent> argument, computes
# the HMAC of the JSON body, and POSTs to the localhost webhook endpoint.
#
# The secret value is never printed, never logged, never written to disk.
# It exists only as a shell variable inside the invocation and is passed to
# openssl via stdin (not argv) to avoid exposure in `ps` output.
#
# Exit codes:
#   0  — POST succeeded (HTTP 202 Accepted)
#   1  — usage error (wrong argument count, unknown agent)
#   2  — WEBHOOK_SECRET_<AGENT> not set in env (infisical-env.sh not wrapping?)
#   3  — openssl missing or HMAC computation failed
#   4  — curl missing or POST failed (network, not HTTP status)
#   5  — Hermes webhook returned non-2xx (agent gateway down, invalid sig, etc.)

set -euo pipefail

# --- Argument parsing ---------------------------------------------------

if [[ $# -lt 2 ]]; then
    cat >&2 <<'USAGE'
Usage: post-memo.sh <agent> "<memo body>"
       post-memo.sh <agent> -          # read body from stdin

  <agent>  — boot | kelk | ig88

Example:
  scripts/infisical-env.sh factory -- \
    scripts/post-memo.sh boot "Count to 20 via terminal, then summarize your env in 3 bullets."
USAGE
    exit 1
fi

AGENT="$1"
BODY_ARG="$2"

case "$AGENT" in
    boot)
        PORT=41951
        SECRET_VAR="WEBHOOK_SECRET_BOOT"
        ;;
    kelk)
        PORT=41952
        SECRET_VAR="WEBHOOK_SECRET_KELK"
        ;;
    ig88)
        PORT=41977
        SECRET_VAR="WEBHOOK_SECRET_IG88"
        ;;
    *)
        echo "post-memo.sh: unknown agent '$AGENT' (expected: boot, kelk, ig88)" >&2
        exit 1
        ;;
esac

# --- Body ---------------------------------------------------------------

if [[ "$BODY_ARG" == "-" ]]; then
    BODY_TEXT=$(cat)
else
    BODY_TEXT="$BODY_ARG"
fi

if [[ -z "$BODY_TEXT" ]]; then
    echo "post-memo.sh: memo body is empty" >&2
    exit 1
fi

# --- Secret (indirect expansion) ----------------------------------------
# Use ${!VAR} indirect expansion to read the secret WITHOUT ever placing
# it on a command line. The value stays in shell memory only, and is
# piped to openssl via stdin (via a file descriptor, not argv) below.

SECRET_VALUE="${!SECRET_VAR:-}"
if [[ -z "$SECRET_VALUE" ]]; then
    echo "post-memo.sh: $SECRET_VAR not set in environment." >&2
    echo "  Did you forget to wrap the invocation in 'infisical-env.sh factory --'?" >&2
    exit 2
fi

# --- Dependency checks --------------------------------------------------

command -v curl >/dev/null 2>&1 || {
    echo "post-memo.sh: curl not found on PATH" >&2
    exit 4
}
command -v python3 >/dev/null 2>&1 || {
    echo "post-memo.sh: python3 not found on PATH (used for JSON body construction)" >&2
    exit 4
}

# --- JSON body construction ---------------------------------------------
# Construct the JSON payload via python3 rather than string interpolation
# so special characters in the memo body (quotes, backslashes, newlines)
# are correctly escaped. The prompt template on the agent side reads
# `{message}` from this JSON payload.

JSON_BODY=$(BODY_TEXT="$BODY_TEXT" python3 -c '
import json, os, sys
sys.stdout.write(json.dumps({"message": os.environ["BODY_TEXT"]}))
')

# --- HMAC-SHA256 signature ---------------------------------------------
# Use Python's hmac module rather than `openssl dgst -hmac` because openssl's
# key argument is passed via argv and is therefore visible to `ps` during
# the (brief) signing window. Python's hmac reads the key as a function
# argument — never touches argv — so there is no ps-visibility leak.
# The secret is passed to python3 via the environment (a subprocess-private
# channel on macOS/Linux, not visible in ps output).

SIGNATURE=$(SECRET_VALUE="$SECRET_VALUE" BODY_JSON="$JSON_BODY" python3 -c '
import hmac, hashlib, os
key = os.environ["SECRET_VALUE"].encode()
body = os.environ["BODY_JSON"].encode()
print(hmac.new(key, body, hashlib.sha256).hexdigest())
')

if [[ -z "$SIGNATURE" ]]; then
    echo "post-memo.sh: HMAC computation failed" >&2
    exit 3
fi

# Clear the secret from this shell's env before the curl POST, so even a
# subprocess spawned by curl can't see it.
unset SECRET_VALUE
# The indirect reference is also cleared by unsetting the original var name:
unset "$SECRET_VAR"

# --- POST ---------------------------------------------------------------
# Send the signed POST. Hermes's generic signature check reads the
# X-Webhook-Signature header as a bare hex string (no sha256= prefix).

URL="http://127.0.0.1:${PORT}/webhooks/memo"

echo "post-memo.sh: POST $URL  (${#BODY_TEXT} bytes)" >&2

HTTP_RESPONSE=$(
    curl -sS -X POST "$URL" \
        -H "Content-Type: application/json" \
        -H "X-Webhook-Signature: $SIGNATURE" \
        --data-binary "$JSON_BODY" \
        --write-out '\n---HTTP_STATUS:%{http_code}' \
        --max-time 10 \
        2>&1
) || {
    echo "post-memo.sh: curl failed to connect to $URL" >&2
    echo "  Is the $AGENT hermes gateway running? Check: launchctl list | grep hermes-$AGENT" >&2
    exit 4
}

HTTP_STATUS=$(echo "$HTTP_RESPONSE" | tail -n 1 | sed 's/.*HTTP_STATUS://')
HTTP_BODY=$(echo "$HTTP_RESPONSE" | sed '$d')

if [[ "$HTTP_STATUS" =~ ^2[0-9][0-9]$ ]]; then
    echo "post-memo.sh: accepted (HTTP $HTTP_STATUS)" >&2
    echo "$HTTP_BODY"
    exit 0
else
    echo "post-memo.sh: rejected (HTTP $HTTP_STATUS)" >&2
    echo "$HTTP_BODY" >&2
    exit 5
fi
