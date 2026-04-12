#!/bin/bash
# goose-ig88.sh — Launch Goose agent for IG-88 via OpenRouter
# No local MLX dependency — IG-88 runs entirely on OpenRouter.
set -euo pipefail

if ! command -v goose >/dev/null 2>&1; then
  echo "  ✗ Goose not found. Install with: brew install block-goose-cli"
  exit 1
fi

export OPENAI_HOST="https://openrouter.ai/api/v1"

# Pull OPENROUTER_API_KEY from Infisical
OPENROUTER_KEY=$(/Users/nesbitt/dev/factory/scripts/infisical-env.sh factory -- env | grep OPENROUTER_API_KEY | cut -d= -f2-)
if [ -z "$OPENROUTER_KEY" ]; then
  echo "  ✗ OPENROUTER_API_KEY not found in Infisical"
  exit 1
fi
export OPENAI_API_KEY="$OPENROUTER_KEY"

cd /Users/nesbitt/dev/factory/agents/ig88

goose session start --model "google/gemma-4-31b-it" "$@"
