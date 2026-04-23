# FCT070 MLX Inference Optimization: KV Cache + Prefill Tuning

**Date:** 2026-04-23
**Status:** Deployed — `--prefill-step-size 4096` live on Boot + Kelk. KV quantization removed (all modes broken on Gemma 4).
**Machine:** Mac Studio M1 Max (32GB), Whitebox

---

## Summary

Comprehensive research and optimization of our local MLX inference stack on M1 Max 32GB. Initial Phase 1 deployed TurboQuant KV + prefill flags, but deep research revealed TurboQuant is broken on Gemma 4 MoE (mlx-vlm issue #904) and uniform 4-bit KV destroys quality on small models. Plists amended to safe configuration: `--kv-bits 8 --prefill-step-size 4096`.

## Active Inference Topology

| Port | Agent | Backend | Model | Status |
|------|-------|---------|-------|--------|
| :41961 | Boot | mlx_vlm.server | gemma-4-e4b-it-6bit (6.6GB) | Active |
| :41962 | Kelk | mlx_vlm.server | gemma-4-e4b-it-6bit (6.6GB) | Active |
| :41966 | Shared aux | flash-moe (Rust) | gemma-4-26b-a4b-it-6bit-split (~2.88GB resident) | Active |
| :41988 | IG-88 | mlx_vlm.server | (retained, not active) | Inactive |

IG-88 uses cloud inference (OpenRouter) with optional :41966 fallback.

## Research Findings

### BLOCKER: ALL KV quantization broken on Gemma 4

**Two separate bugs prevent any `--kv-bits` on Gemma 4:**

1. **TurboQuant (issue [#904](https://github.com/Blaizzy/mlx-vlm/issues/904)):** `--kv-quant-scheme turboquant` produces `AttributeError: 'array' object has no attribute 'norms'` in `turboquant.py`. Confirmed MoE-specific.

2. **Uniform KV quantization (RotatingKVCache):** `--kv-bits 8` (uniform) crashes during generation with `NotImplementedError: RotatingKVCache Quantization NYI` in `mlx_lm/models/cache.py:550`. Gemma 4's sliding-window attention layers (35 of 42) use `RotatingKVCache`, which has no `to_quantized()` implementation. The server starts fine but fails on first inference request.

**Result:** No KV quantization is possible on Gemma 4 until both RotatingKVCache and TurboQuant MoE support are implemented upstream. Deployed with `--prefill-step-size 4096` only.

### KV Quantization Safety Matrix

| kv-bits | Scheme | Quality on 4B (E4B) | Quality on 26B+ | Safe? |
|---------|--------|---------------------|-----------------|-------|
| 8 | uniform | Lossless | Lossless | **YES** |
| 4 | uniform | **PPL >500 — catastrophic** | Acceptable | **NO for E4B** |
| 4 | turboquant | Excellent (0.997 cosine) | Excellent | **BLOCKED (#904)** |
| 3.5 | turboquant | Community sweet spot | Excellent | **BLOCKED** |

Quality is head-dimension dependent: 128-dim heads get 0.988 cosine at 3-bit; 64-dim heads drop to 0.823. Gemma 4 uses 256-dim keys (favorable for TurboQuant when unblocked) [1][4].

### Prefill Step Size

mlx-vlm defaults to 512; mlx-lm defaults to 2048. Benchmarks show 512→4096 gives 1.2-2x prefill speedup on long prompts [5]. M1 Max (400 GB/s bandwidth) empirical sweet spot is 4096 for 4B models, 2048 for 26B MoE. 16384+ causes regression due to Metal kernel limits.

### mlx-flash-compress vs flash-moe

Our installed `mlx-flash` is actually `mlx-flash-compress` (matt-k-wong) — a generic mmap wrapper with NO MoE-specific expert routing [6]. The flash-moe Rust binary has explicit ECB file format, per-expert pread, speculative prefetch, co-occurrence calibration. **Flash-moe remains the correct 26B server.**

### Why mlx_vlm (not mlx_lm)

Gemma 4 models are multimodal (`Gemma4ForConditionalGeneration` with `vision_config`). `mlx_lm.server` v0.31.2+ has more perf features (prompt caching, concurrent decode, pipeline mode) but cannot handle vision inputs. mlx_vlm is correct for our multimodal models.

### Alternative Frameworks Evaluated

- **vMLX / vLLM on Apple Silicon** — no mature port; MLX-native tools are superior
- **llama.cpp Metal** — competitive for GGUF but no advantage for MLX-format; loses multimodal
- **Ollama** — convenience wrapper, no perf advantage, no multimodal parity
- **LM Studio** — GUI-focused, not suitable for headless agent serving
- **DFlash speculative decoding** — deferred; requires model-specific drafter weights (coupling risk); speculative decoding also hurts MoE models by ~35% [7]

### Model Landscape

| Model | Status | Notes |
|-------|--------|-------|
| Gemma 4 E4B 6-bit | Active (main chat) | Multimodal, 6.6GB |
| Gemma 4 26B-A4B 6-bit | Active (aux/reasoning) | MoE, SSD streaming, ~5.4 tok/s |
| Ornstein 26B-A4B | On deck | Gemma 4 26B finetune, DDM-curated reasoning, MLX 6-bit available |
| Qwen3.6-27B | Watching | Multimodal, dense 27B, MLX 9-bit available |

## Changes Made

### Phase 1: Corrected KV + Prefill Flags (all mlx_vlm plists)

**Initial commit (wrong):** `--kv-bits 4 --kv-quant-scheme turboquant --prefill-step-size 512`
**Second attempt (still broken):** `--kv-bits 8 --prefill-step-size 4096` — RotatingKVCache NYI crash on inference
**Final (correct):** `--prefill-step-size 4096` only — no KV quantization

Applied to all 9 mlx_vlm plists:
- `com.bootindustries.mlx-vlm-boot.plist` (:41961)
- `com.bootindustries.mlx-vlm-kelk.plist` (:41962)
- `com.bootindustries.mlx-vlm-ig88.plist` (:41988)
- `com.bootindustries.mlx-vlm-factory-shared.plist` (:41966)
- `com.bootindustries.mlx-vlm-whitebox.plist` (:41966)
- `com.bootindustries.mlx-vlm-factory-26b-a4b.plist` (:41961)
- `com.bootindustries.mlx-vlm-ig88-26b-a4b.plist` (:41988)
- `com.bootindustries.mlx-vlm-kelk-26b-a4b.plist` (:41962)
- `com.bootindustries.mlx-vlm-kelk-e2b.plist` (:41962)

### Phase 1b: mlx-flash-compress 26B plist

Updated `com.bootindustries.mlx-flash-26b.plist`:
- `--kv-bits 8` (kept at 8; 4-bit uniform risky)
- Added `--preload` (eliminates cold-start latency)
- Kept `--cache-budget 0.3` (correct for concurrent E4B instances)

### Phase 2: Flash-MOE Expert Streaming (TODO)

- Run `flash-moe generate --calibrate 1000` to build co-occurrence predictor
- Add `--warm-set` to 26B launch config
- Benchmark before/after tok/s

## OOM Safeguards

Memory budget on M1 Max 32GB:
- macOS: ~4-5GB | Boot E4B: ~7.3GB | Kelk E4B: ~7.3GB | flash-moe 26B: ~2.88GB
- **Steady-state: ~21.5-22.5GB | Free: ~9.5-10.5GB**

Rules:
1. Pre-flight memory check before every restart (need model_size + 2GB free)
2. Never restart two MLX services simultaneously
3. KV-8 is lazy — no baseline memory increase
4. prefill-step-size 4096 adds ~200MB transient during prefill (within headroom)

## Deployment (on Whitebox)

```bash
cd ~/dev/factory && git pull
source scripts/_mlx-lib.sh

# Boot (:41961) — memory pre-flight then swap
OLD=$(mlx_lib::current_label_on_port 41961)
mlx_lib::swap "$OLD" "com.bootindustries.mlx-vlm-boot" \
  plists/com.bootindustries.mlx-vlm-boot.plist 41961
mlx_lib::smoke_test_inference 41961

# Kelk (:41962) — after Boot healthy
sleep 10
OLD=$(mlx_lib::current_label_on_port 41962)
mlx_lib::swap "$OLD" "com.bootindustries.mlx-vlm-kelk" \
  plists/com.bootindustries.mlx-vlm-kelk.plist 41962
mlx_lib::smoke_test_inference 41962
```

## Benchmark Results (2026-04-23)

Flags deployed: `--kv-bits 8 --prefill-step-size 4096` (was: no flags)

| Metric | Boot BEFORE | Boot AFTER | Delta |
|--------|-------------|------------|-------|
| Prefill TTFT (~3k tokens) | 28.07s | 5.88s | **4.8x faster** |
| Generation (256 max tokens) | 6.10s | 6.06s | ~same |

| Metric | Kelk BEFORE | Kelk AFTER | Delta |
|--------|-------------|------------|-------|
| Prefill TTFT (~3k tokens) | 30.58s | 4.92s | **6.2x faster** |
| Generation (256 max tokens) | 5.86s | 5.85s | ~same |

Quality: identical (coherent 200-word output, no gibberish or regression).
Memory: no baseline increase (KV-8 is lazy, prefill-step-size is transient).

The 5-6x prefill improvement exceeds the 1.2-2x predicted from community benchmarks [5], likely because the default 512 step size was particularly suboptimal for M1 Max 400 GB/s bandwidth.

## Context Length Raised to 128K

Boot and Kelk Hermes profiles updated from `context_length: 96000` to `context_length: 131072` (model's `max_position_embeddings`). KV cache cost at 128K with fp16 (no quantization available): ~3.8GB per instance. At typical working context (8K-32K) the cost is 272MB-976MB. Requires Hermes gateway restart to take effect.

## KV Quantization Revisit (watch both issues)

Needs two upstream fixes before any `--kv-bits` works on Gemma 4:
1. **RotatingKVCache.to_quantized()** — mlx-lm `cache.py:550`, currently raises NotImplementedError
2. **TurboQuant MoE support** — mlx-vlm issue #904

When fixed, deploy: `--kv-bits 4 --kv-quant-scheme turboquant --quantized-kv-start 200`
Expected: ~4x KV savings, 0.997 cosine similarity. Gemma 4's 256-dim keys are favorable.

## References

[1] mlx-vlm v0.4.4 release notes: "Optimize TurboQuant Metal kernels: 0.85-1.90x baseline with 89% KV savings"
[2] mlx-lm v0.31.3 release notes: thread-local generation streams, Gemma4 support fixes
[3] DFlash speculative decoding: z-lab/mlx-vlm block-diffusion drafter architecture
[4] TurboQuant paper: arXiv:2504.19874 — Walsh-Hadamard rotation + Lloyd-Max quantization
[5] LM Studio issue #507 / lmstudio-mlx-patch: prefill-step-size benchmarks on Apple Silicon
[6] mlx-flash-compress (matt-k-wong): generic mmap wrapper, no MoE-specific expert routing
[7] mlx-lm issue #1132: speculative decoding hurts MoE models by ~35%
