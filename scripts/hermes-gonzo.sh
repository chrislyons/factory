#!/bin/bash
# hermes-gonzo.sh — Launch Gonzo maintenance worker (CLI-only, no gateway)
#
# Invocation: hermes -p gonzo chat
# Or via infisical: infisical-env.sh factory -- hermes-gonzo.sh
#
# Gonzo uses Nous Mimo Pro via NOUS_MIMO_FACTORY_KEY (injected by Infisical).
# No Matrix gateway — Gonzo is headless, invoked interactively.

set -euo pipefail

export HERMES_HOME="/Users/nesbitt/.hermes/profiles/gonzo"

# Verify NOUS_MIMO_FACTORY_KEY is available
if [[ -z "${NOUS_MIMO_FACTORY_KEY:-}" ]]; then
  echo "ERROR: NOUS_MIMO_FACTORY_KEY not set — run via infisical-env.sh factory --" >&2
  exit 2
fi

# Prevent model confusion — unset any stray provider keys
unset ANTHROPIC_API_KEY 2>/dev/null || true
unset ANTHROPIC_AUTH_TOKEN 2>/dev/null || true
unset OPENAI_BASE_URL 2>/dev/null || true
unset OPENAI_API_BASE 2>/dev/null || true

exec /Users/nesbitt/.local/bin/hermes \
  --profile gonzo \
  chat "$@"
