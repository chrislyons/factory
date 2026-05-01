# FCT087 Ornstein-Hermes-3.6-27B Deployment on Whitebox

**Status:** Active — 6-bit working at reduced speed, 4-bit and 2-bit models pending
**Date:** 2026-05-01
**Machine:** Whitebox (Mac Studio M1 Max, 32GB unified memory)

---

## Summary

Successfully deployed Ornstein-Hermes-3.6-27b-MLX-6bit on :41966 as the sole inference server, replacing dual SABER E4B instances on :41961/:41962. The 27B model (21.2 GB weights) runs on 32GB unified memory via mmap with careful memory management. Boot is live and responding through Matrix.

## Test Results

### Benchmark Matrix

| Test | Prompt | Prefill Step | KV Bits | Wired Limit | Result | tok/s |
|------|--------|-------------|---------|-------------|--------|-------|
| Short (no limits) | 16 tok | 2048 | 8-bit | None | OK | ~10 |
| Medium (no limits) | 229 tok | 2048 | 8-bit | None | OK | ~10 |
| Long (no limits) | 1024 tok | 2048 | 8-bit | None | OK | ~10 |
| 18K tokens (no limits) | 18520 tok | 2048 | 8-bit | None | **CRASH** at 6144 tok | — |
| Short (wired=20GB) | 13 tok | 512 | 4-bit | 20 GB | OK | 1.6 cold / 7.4 warm |
| Medium (wired=20GB) | 3865 tok | 512 | 4-bit | 20 GB | OK (slow) | ~1.5 |
| 10K tokens (wired=20GB) | 9620 tok | 512 | 4-bit | 20 GB | OK (slow) | ~1.5 |
| **16K tokens (no wired)** | **16020 tok** | **256** | **4-bit** | **None** | **OK** | **~7** |
| Boot-scale (no wired) | 18541 tok | 256 | 4-bit | None | OK | ~7 |

### Crash Analysis

**Crash 1:** `[METAL] Command buffer execution failed: Insufficient Memory`
- At: 6144/18520 tokens during prefill
- Cause: No memory limits, prefill-step-size 2048, 8-bit KV
- Root cause: Metal GPU needs compute buffers proportional to prefill step size. At 2048 tokens per step, GPU buffers exceed remaining memory after 21 GB model + macOS.

**Crash 2:** Disk full (100% usage)
- Cause: Swap/compressor wrote to disk under memory pressure
- Freed: 13 GB of HF/uv caches cleared, user freed additional space

### Key Findings

1. **prefill-step-size is the critical parameter.** At 2048, Metal allocates large GPU buffers per step → OOM at ~6K tokens. At 256, each step uses 1/8th the GPU memory → survives 18K+ tokens.

2. **Wired limits cause thrashing, not stability.** Setting `mx.set_wired_limit(20GB)` forces model page eviction → 2 tok/s decode. The 21 GB model needs to stay resident for acceptable speed.

3. **No wired limit + Metal limit 28 GB + prefill-step-size 256 = stable.** Model pages stay resident, GPU buffers are small per step, macOS has 4 GB headroom.

4. **4-bit KV quantization is essential.** The wrapper's original `make_prompt_cache` guard `if hasattr(model, "make_cache"): return model.make_cache()` bypassed our QuantizedKVCache entirely — the model used fp16 KVCache. Fixed by patching `TextModel.make_cache` directly.

5. **Decode speed: ~7 tok/s with 4-bit KV, ~10 tok/s on short prompts.** The slower speed on long prompts is due to memory pressure and larger KV cache.

## Architecture

```
Port    Model                                  Status
----    -----                                  ------
:41961  SABER E4B (unloaded, plist on disk)    RETIRED
:41962  SABER E4B (unloaded, plist on disk)    RETIRED
:41966  Ornstein-Hermes-3.6-27b-MLX-6bit       ACTIVE

Hermes:
  Boot:   UP → :41966 (27B)
  Kelk:   UP → :41961 (offline — needs config update)
  IG-88:  UP → cloud (unaffected)
```

## Wrapper (mlx-lm-27b-wrapper.py)

```python
# v3 — No wired limit, Metal limit 28 GB, 4-bit KV
METAL_LIMIT_BYTES = 28 * 1024 * 1024 * 1024
_KV_BITS = 4
_KV_GROUP_SIZE = 64

# Patches TextModel.make_cache directly to bypass model's fp16 KVCache
# ArraysCache (GatedDeltaNet) untouched, QuantizedKVCache for full attention
```

## Plist Settings

```
--prefill-step-size 256    (crash was at 2048)
--prompt-concurrency 1     (no concurrent prefill)
--max-tokens 16384
--prompt-cache-bytes 2147483648  (2 GB cap)
```

## Optimization Paths (In Progress)

| Path | Status | Expected Impact |
|------|--------|-----------------|
| 4-bit model (~14 GB) | User pulling | ~13-15 tok/s, larger prefill steps |
| 2-bit model (~8.5 GB) | User pulling | Unknown quality, very fast |
| System prompt compression | Pending | Prefill 5 min → 1 min |
| DFlash speculative decoding | Researched | ~2x speedup (when draft model available) |
| Prompt cache investigation | Pending | Faster follow-up messages |

## DFlash Compatibility

Ornstein3.6 is a Qwen3.6 tune → dflash-mlx should support it.

**Status:**
- Draft model `z-lab/Qwen3.6-27B-DFlash` exists but **still under training**
- `z-lab/Qwen3.5-27B-DFlash` available as interim (lower acceptance rate)
- dflash-mlx v0.1.4.1 has startup crash bugs (issue #13)
- Memory layout with 4-bit target: 16 GB target + 4 GB draft + 4-6 GB KV = ~26 GB (fits)
- Expected speedup: ~2.3-2.4x on M1 Max (halved from M5 Max benchmarks)

**Blockers:**
- Draft model still training
- dflash-mlx has known bugs
- No benchmark for Ornstein fine-tune specifically

## Files Changed

| File | Change |
|------|--------|
| `~/.hermes/profiles/boot/config.yaml` | 41961→41966, E4B→27B |
| `~/.hermes/profiles/boot/config.yaml.bak-27b` | Backup of E4B config |
| `scripts/hermes-boot.sh` | Health check → 41966, model path → 27B |
| `scripts/hermes-boot.sh.bak-e4b` | Backup |
| `scripts/factory-startup.sh` | Phase 1 → 27B on 41966 |
| `scripts/mlx-lm-27b-wrapper.py` | NEW — 4-bit KV, Metal limit, no wired limit |
| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-27b.plist` | NEW |

## Rollback

1. `launchctl unload com.bootindustries.mlx-lm-factory-27b`
2. `cp config.yaml.bak-27b → config.yaml`
3. `cp hermes-boot.sh.bak-e4b → hermes-boot.sh`
4. `launchctl load com.bootindustries.mlx-lm-factory-boot/kelk`
5. `kickstart hermes-boot`

## References

- [1] FCT076 — Flash-MoE 35B-A3B Port and Debug (27B KV cache benchmarks)
- [2] FCT078 — Dual SABER E4B Stress Test Results
- [3] FCT074 — Qwen3.6 Local Inference Architecture
- [4] dflash-mlx — https://github.com/bstnxbt/dflash-mlx
- [5] z-lab/Qwen3.6-27B-DFlash — https://huggingface.co/z-lab/Qwen3.6-27B-DFlash
