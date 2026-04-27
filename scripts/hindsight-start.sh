#!/bin/bash
# Start Hindsight API daemon with local inference server
# Uses Whitebox mlx-vlm.server on :41961 (OpenAI-compatible API)
# Model: Ornstein3.6-35B-A3B-MLX-6bit (served via mmap, MoE)
# Provider: openai (OpenAI-compatible endpoint, dummy key for local server)

set -euo pipefail

export HINDSIGHT_API_LLM_PROVIDER=openai
export HINDSIGHT_API_LLM_MODEL=Ornstein3.6-35B-A3B-MLX-6bit
export HINDSIGHT_API_LLM_BASE_URL=http://127.0.0.1:41961/v1
export HINDSIGHT_API_LLM_API_KEY=sk-local-no-auth
export HINDSIGHT_EMBED_BANK_ID=hermes-default

exec uvx hindsight-api@0.5.4 --port 41930 --idle-timeout 0
