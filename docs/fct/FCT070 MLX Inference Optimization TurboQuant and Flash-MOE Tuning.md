# FCT070 MLX Inference Optimization: TurboQuant and Flash-MOE Tuning

**Date:** 2026-04-23
**Status:** Implemented (Phase 1), Partial (Phase 2)

---

## Summary

Comprehensive research and optimization of our local MLX inference stack. Discovered that mlx_vlm v0.4.4 — already installed — ships with TurboQuant KV cache quantization, DFlash speculative decoding, vision feature caching, and prefill tuning, none of which were enabled in our launchd plists.

## Current Stack (Pre-Optimization)

| Component | Version | Port(s) | Model |
|-----------|---------|---------|-------|
| mlx_vlm.server | 0.4.4 | :41961 (Boot), :41962 (Kelk), :41988 (IG-88) | gemma-4-e4b-it-6bit (6.6GB) |
| mlx-flash | - | :41966 | gemma-4-26b-a4b-it-6bit (20GB split) |
| flash-moe (Rust) | custom | (via subprocess wrapper) | gemma-4-26b-a4b-it-6bit-split |
| mlx core | 0.31.1 | - | - |
| mlx_lm | 0.31.2 | (experiments only) | Hermes-4-14B, Harmonic-9B |

## Research Findings

### Why mlx_vlm (not mlx_lm)

Gemma 4 E4B and 26B-A4B are multimodal models (`Gemma4ForConditionalGeneration` with `vision_config`). `mlx_lm.server` has more performance features (prompt caching, concurrent decode, pipeline mode) but cannot handle vision inputs. `mlx_vlm` is the correct server for our multimodal models.

### Untapped mlx_vlm v0.4.4 Features

1. **TurboQuant KV cache** (`--kv-bits 4 --kv-quant-scheme turboquant`) — 89% KV memory savings, 0.85-1.90x speed [1]
2. **DFlash speculative decoding** (`--draft-model`, `--draft-kind dflash`) — 2-3x throughput, but requires model-specific drafter weights (deferred)
3. **Vision feature caching** (`--vision-cache-size N`) — avoids re-encoding images in multi-turn
4. **Prefill step size** (`--prefill-step-size 512`) — tunable prompt processing chunk size

### DFlash Status (Deferred)

DFlash requires model-specific drafter weights. No Gemma 4 E4B DFlash drafter exists (only `RedHatAI/gemma-4-31B-it-speculator.dflash` for the 31B variant). 76 DFlash models exist on HuggingFace across Qwen, Gemma, LLaMA families. Deferred until we can investigate wrapping our own universal drafter.

### Alternative Frameworks Evaluated

- **vMLX / vLLM on Apple Silicon** — no mature port; MLX-native tools are superior
- **llama.cpp Metal** — competitive for GGUF but no advantage over MLX-format models; loses multimodal support
- **Ollama** — convenience wrapper, no performance advantage, no multimodal parity
- **LM Studio** — GUI-focused, not suitable for headless agent serving

### Model Landscape

| Model | Status | Notes |
|-------|--------|-------|
| Gemma 4 E4B 6-bit | Active (main chat) | Multimodal, 6.6GB |
| Gemma 4 26B-A4B 6-bit | Active (aux/reasoning) | MoE, SSD streaming, ~5.4 tok/s |
| Ornstein 26B-A4B | On deck | Gemma 4 26B finetune, DDM-curated reasoning, MLX 6-bit available |
| Qwen3.6-27B | Watching | Multimodal, dense 27B, MLX 9-bit available, no DFlash yet |

## Changes Made

### Phase 1: TurboQuant KV + Prefill Tuning (all mlx_vlm plists)

Added `--kv-bits 4 --kv-quant-scheme turboquant --prefill-step-size 512` to all 8 mlx_vlm plists:

- `com.bootindustries.mlx-vlm-boot.plist` (:41961)
- `com.bootindustries.mlx-vlm-kelk.plist` (:41962)
- `com.bootindustries.mlx-vlm-ig88.plist` (:41988)
- `com.bootindustries.mlx-vlm-factory-shared.plist` (:41966)
- `com.bootindustries.mlx-vlm-whitebox.plist` (:41966)
- `com.bootindustries.mlx-vlm-factory-26b-a4b.plist` (:41961)
- `com.bootindustries.mlx-vlm-ig88-26b-a4b.plist` (:41988)
- `com.bootindustries.mlx-vlm-kelk-26b-a4b.plist` (:41962)
- `com.bootindustries.mlx-vlm-kelk-e2b.plist` (:41962)

### Phase 1b: mlx-flash 26B tuning

Updated `com.bootindustries.mlx-flash-26b.plist`:
- `--kv-bits` 8 → 4 (more aggressive KV compression)
- Added `--preload` (eliminates cold-start latency)

### Phase 2: Flash-MOE Expert Streaming (TODO)

- Run `flash-moe generate --calibrate 1000` to build co-occurrence predictor
- Add `--warm-set` to 26B launch config
- Benchmark before/after tok/s

## Deployment

Plists are gitignored — changes are on disk in `plists/`. To deploy:

```bash
# For each modified plist:
install -m 644 plists/<label>.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/<label>
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist

# Or use _mlx-lib.sh helpers:
source scripts/_mlx-lib.sh
mlx_lib::swap "old_label" "new_label" "plists/<label>.plist" <port>
```

## References

[1] mlx-vlm v0.4.4 release notes: "Optimize TurboQuant Metal kernels: 0.85-1.90x baseline with 89% KV savings"
[2] mlx-lm v0.31.3 release notes: thread-local generation streams, Gemma4 support fixes
[3] DFlash speculative decoding: z-lab/mlx-vlm block-diffusion drafter architecture
