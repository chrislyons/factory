#!/bin/bash
# goose-ig88.sh — Launch Goose agent for IG-88 via OpenRouter
# No local MLX dependency — IG-88 runs entirely on OpenRouter.
set -euo pipefail

if ! command -v goose >/dev/null 2>&1; then
  echo "  ✗ Goose not found. Install with: brew install block-goose-cli"
  exit 1
fi

export GOOSE_PROVIDER="openrouter"
export GOOSE_MODEL="xiaomi/mimo-v2-omni"
export OPENROUTER_API_KEY=$(/Users/nesbitt/dev/factory/scripts/infisical-env.sh factory -- printenv OPENROUTER_API_KEY 2>/dev/null)

if [ -z "$OPENROUTER_API_KEY" ]; then
  echo "  ✗ OPENROUTER_API_KEY not found in Infisical"
  exit 1
fi

cd /Users/nesbitt/dev/factory/agents/ig88
exec goose session "$@"
