# Ornstein3.6-35B-A3B Flash-MoE Status

## STATUS: WORKING ✅

The flash-moe C/Metal binary now produces correct, coherent output from
Ornstein3.6-35B-A3B-MLX-6bit on M1 Max 32GB at ~7.2 tok/s.

## What Was Wrong
Three bugs, all in infer_35b.m:

1. **NUM_EXPERTS_PER_TOK was 4, not 8** (line 80)
   - Config says num_experts_per_tok=8
   - Binary had K=4 → selecting wrong experts

2. **Chat template missing `<think>\n`** (lines 5916, 5934, 5978)
   - Qwen3.6 thinking mode requires `<think>\n` after `<|im_start|>assistant\n`
   - Without it, model doesn't enter reasoning mode

3. **GPU 8-bit kernel produces wrong routing scores** (line 5091)
   - Gate and shared_expert_gate are 8-bit quantized
   - GPU dequant kernel gives wrong values
   - Fix: override on CPU after GPU batch matvec
   - Reference: Ma-Dan's fork (github.com/Ma-Dan/flash-moe/tree/Qwen3.6-35B-A3B)

## How to Run

CLI:
```bash
cd /Users/nesbitt/dev/vendor/flash-moe/metal_infer
./infer_35b \
  --weights /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/model_weights.bin \
  --manifest /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/model_weights.json \
  --vocab /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/vocab.bin \
  --prompt "What is 2+2?" --tokens 200
```

Server (OpenAI-compatible API):
```bash
./infer_35b \
  --weights /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/model_weights.bin \
  --manifest /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/model_weights.json \
  --vocab /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/vocab.bin \
  --serve 41965
```

Endpoints: POST /v1/chat/completions, GET /v1/models, GET /health

## Performance
- ~7.2 tok/s on M1 Max 32GB
- TTFT ~5s for 30-token prompt
- Produces coherent reasoning with step-by-step thinking

## Remaining Work
- Port 41961 is occupied by existing mlx_vlm.server (do not touch without operator)
- When ready to switch: stop mlx-vlm-ornstein, start flash-moe on 41961
- Update Hermes configs to point to flash-moe endpoint

## Key Files
- Binary: /Users/nesbitt/dev/vendor/flash-moe/metal_infer/infer_35b
- Source: /Users/nesbitt/dev/vendor/flash-moe/metal_infer/infer_35b.m
- Shaders: /Users/nesbitt/dev/vendor/flash-moe/metal_infer/shaders.metal
- Model: /Users/nesbitt/models/Ornstein3.6-35B-A3B-MLX-6bit/
