# FCT076 Flash-MoE 35B-A3B — Porting and Debug Log

**Status:** Complete | **Date:** 2026-04-28 | **Author:** Gonzo

---

## Summary

Successfully ported the flash-moe C/Metal inference engine from its original
Qwen3.5-397B-A17B target to DJLougen's Ornstein3.6-35B-A3B-MLX-6bit fine-tune.
The model now runs at ~7.2 tok/s on Whitebox (Mac Studio M1 Max, 32GB) with
coherent reasoning output via an OpenAI-compatible HTTP API.

## What Changed

### Architecture Constants (infer_35b.m)

| Constant | 397B Original | 35B-A3B | Notes |
|----------|--------------|---------|-------|
| HIDDEN_DIM | 4096 | 2048 | Half the width |
| NUM_LAYERS | 60 | 40 | 30 linear + 10 full attn |
| NUM_EXPERTS | 512 | 256 | Half the expert pool |
| NUM_EXPERTS_PER_TOK | 4 | **8** | Critical — model config specifies 8 |
| MOE_INTERMEDIATE | 1024 | 512 | |
| SHARED_INTERMEDIATE | 1024 | 512 | |
| FULL_ATTN_INTERVAL | 4 | 4 | Same pattern |
| LINEAR_NUM_V_HEADS | 64 | 32 | |
| LINEAR_NUM_K_HEADS | 16 | 16 | Same |
| LINEAR_KEY_DIM | 192 | 128 | |
| LINEAR_VALUE_DIM | 128 | 128 | Same |
| MAX_SEQ_LEN | 1048576 | 131072 | 128K context (was causing OOM) |

### Bugs Found and Fixed

#### Bug 1: NUM_EXPERTS_PER_TOK = 4 (should be 8)
- **Root cause:** Ported from 397B which uses K=4. 35B config says K=8.
- **Effect:** Only half the required experts activated per token. Garbage output.
- **Fix:** Changed #define and default --k to 8.

#### Bug 2: Chat template missing `<think>\n`
- **Root cause:** C tokenizer template ended at `<|im_start|>assistant\n` but
  Qwen3.6 thinking mode requires `<think>\n` after that.
- **Effect:** Model doesn't enter reasoning mode. Outputs generic completions.
- **Fix:** Added `<think>\n` to tokenize_chat_message, tokenize_user_turn, and
  tokenize_continuation_turn.

#### Bug 3: GPU 8-bit dequant kernel corrupts routing scores (CRITICAL)
- **Root cause:** flash-moe issue #10. MLX mixed-quantization models override
  specific tensors (mlp.gate, mlp.shared_expert_gate) to 8-bit while the rest
  is 6-bit. The GPU dequant kernel treats ALL weights uniformly as 6-bit,
  corrupting the 8-bit routing gate scores. Wrong experts selected every layer.
- **Effect:** Coherent-appearing but incorrect output. Routing completely wrong.
- **Fix:** After GPU batch matvec, recompute gate and shared_expert_gate scores
  on CPU using `cpu_dequant_matvec_8bit`. This matches Ma-Dan's approach.
- **Reference:** github.com/Ma-Dan/flash-moe/tree/Qwen3.6-35B-A3B

#### Bug 4: BatchMatvecSpec missing bits=8 field
- **Root cause:** Two locations in fused_layer_forward initialized
  BatchMatvecSpec with 8 fields but the struct has 9. The `bits` field
  defaulted to 0 (6-bit kernel) for 8-bit weights.
- **Fix:** Added explicit `bits=8` for gate_w and seg_w entries.

#### Bug 5: Wrong prompt tokenization
- **Root cause:** --prompt used raw tokenization instead of chat template.
- **Fix:** Changed to tokenize_chat_message() which applies system+user template.

### New Files

| File | Purpose |
|------|---------|
| `metal_infer/infer_35b.m` | 35B-A3B inference engine (~7200 lines, adapted from infer.m) |
| `repack_experts_35b.py` | Expert weight repacking for 35B architecture |
| `metal_infer/export_tokenizer.py` | Generate tokenizer.bin from tokenizer.json |

### KV Cache Configuration

The 35B-A3B model only has 10 full-attention layers (every 4th). The other 30
use GatedDeltaNet with O(1) fixed state. This means KV cache is small:

| Context | fp32 KV Cache |
|---------|---------------|
| 8K | 168 MB |
| 32K | 671 MB |
| 128K | 2.62 GB |

With 32GB RAM and ~5 GB used by weights+buffers, we have ~22 GB headroom.
fp32 KV cache is the right choice — no quantization needed for 35B-A3B.

For the 27B dense model (all 32 layers have KV cache), quantization becomes
essential. q5_1 or q4_0 would be needed for 128K+ context.

## Suggested GitHub Contributions

### 1. PR: Qwen3.6-35B-A3B support (danveloper/flash-moe)

**Title:** Add Qwen3.6-35B-A3B inference support

**Description:** Port flash-moe to the 35B-A3B architecture with:
- Updated architecture constants
- 6-bit dequant kernels for non-expert weights
- 8-bit CPU override for routing gates (workaround for issue #10)
- Chat template with thinking mode support
- New `infer_35b.m` and `repack_experts_35b.py`

This is the same approach as Ma-Dan's fork but with cleaner separation and
6-bit (not 4-bit) expert support.

### 2. Issue: GPU 8-bit dequant produces wrong results

**Title:** GPU dequant kernel produces wrong output for mixed 6-bit/8-bit models

**Description:** When MLX models use mixed quantization (e.g., 6-bit default
with 8-bit overrides for routing gates), the GPU dequant kernels treat all
weights as 6-bit. The routing gate scores are corrupted, causing wrong expert
selection every layer.

**Reproduction:** Run any MLX-quantized Qwen3.5/3.6 MoE model where
config.json has per-tensor `bits: 8` overrides.

**Workaround:** Recompute 8-bit gate weights on CPU after GPU batch matvec
using `cpu_dequant_matvec_8bit`.

**Proper fix:** Read `quantization_config` from config.json at startup, detect
per-tensor bit overrides, and dispatch to the correct dequant kernel for each
weight tensor in the batch matvec.

### 3. PR: config.json-aware quantization dispatch

**Title:** Auto-detect mixed quantization from config.json

**Description:** Parse `quantization_config` from the model's config.json to
detect per-tensor bit-width overrides. Build a lookup table mapping tensor
names to their bit width. During `build_layer_cache`, tag each weight pointer
with its actual bit width. In `gpu_batch_matvec` and `fast_batch_matvec`,
select the correct dequant kernel based on the tagged bit width instead of
relying on the `bits` field in BatchMatvecSpec.

This would fix issue #10 properly for all MLX-quantized MoE models without
requiring CPU fallback.

## Performance Notes

| Metric | Value |
|--------|-------|
| Decode speed | ~7.2 tok/s |
| Time to first token | ~5s (30-token prompt) |
| Expert I/O | ~1.1 ms/layer |
| GPU attention | ~1.5 ms/layer |
| Total per-layer | ~3.2 ms |

The 8-bit CPU override adds ~0.1 ms per layer (negligible). The main
bottleneck is SSD expert I/O (47% of time) and 6-bit dequant compute (22%).

## 27B Dense Model — KV Cache Benchmarks

**Run:** 2026-04-28 | Model: `Ornstein-Hermes-3.6-27b-MLX-6bit`

### Architecture Surprise

The 27B model is NOT a traditional dense model where every layer has a KV
cache. Like the 35B-A3B, it uses a **hybrid architecture**:

- **48 layers:** GatedDeltaNet linear attention (O(1) fixed-size state, no KV cache)
- **16 layers:** Full attention with KV cache (every 4th layer)

This means the KV cache is ~4x smaller per token than a standard 64-layer
dense model. The original assumption that "all 32 layers have KV cache" was
wrong — the text config says `num_hidden_layers: 64` but only 16 use
traditional KV caching.

### Architecture Details

| Parameter | Value |
|-----------|-------|
| Hidden size | 5120 |
| Total layers | 64 |
| KV cache layers | 16 (every 4th) |
| Linear attention layers | 48 (GatedDeltaNet) |
| Attention heads | 24 |
| KV heads | 4 (GQA 6:1) |
| Head dim | 256 |
| Max position | 262,144 |
| Vocab size | 248,320 |
| Quantization | 6-bit affine, group_size=64 |
| Model memory (loaded) | 21.9 GB |

### Analytical KV Cache Memory

Per token per KV layer: 2(K+V) × 4 heads × 256 dim = 2,048 bytes (fp16)
Per token all 16 KV layers: 32,768 bytes = 32 KB (fp16)

| Context | fp16 | q8 | q4 |
|---------|------|----|----|
| 8K | 268 MB | 134 MB | 67 MB |
| 32K | 1.07 GB | 537 MB | 268 MB |
| 64K | 2.15 GB | 1.07 GB | 537 MB |
| 128K | 4.29 GB | 2.15 GB | 1.07 GB |
| 262K | 8.59 GB | 4.29 GB | 2.15 GB |

Maximum context on 32GB system (model = 21.9 GB, ~10.1 GB available):

| KV Mode | Max Context |
|---------|------------|
| fp16 | ~309K tokens |
| q8 | ~619K tokens |
| q4 | ~1.2M tokens |

**fp16 KV cache handles 262K context with 1.5 GB headroom. No quantization
needed.**

### Decode Speed Benchmarks

| Context | fp16 prefill | fp16 decode | q8 decode | q4 decode |
|---------|-------------|-------------|-----------|-----------|
| 512 | 65.2 tok/s | 12.1 tok/s | 12.0 tok/s | 12.0 tok/s |
| 2048 | 67.2 tok/s | 12.0 tok/s | 11.7 tok/s | 11.8 tok/s |
| 8192 | 66.5 tok/s | 11.6 tok/s | 10.8 tok/s | 10.8 tok/s |

### Key Findings

1. **KV cache quantization provides ZERO speed benefit.** The model is
   compute-bound (6-bit dequant + matmul), not memory-bound. At 8K context,
   q8/q4 decode is actually *slightly slower* than fp16 due to
   dequantization overhead in the cache layer.

2. **FP16 KV cache works up to ~309K context on 32GB.** The hybrid
   architecture (48 linear attn + 16 full attn) makes KV cache a
   non-issue for memory. The original fear that "27B at 128K needs
   quantization" was based on wrong assumptions about the architecture.

3. **Decode speed is flat at ~12 tok/s regardless of context or KV mode.**
   This is the model's compute-bound speed on M1 Max at 6-bit.

4. **Prefill is flat at ~66 tok/s** regardless of context or KV mode.

5. **The tweet's situation does not apply.** The tweet described Qwen3.6
   27B dense on 24GB VRAM where q4 KV cache was needed to fit 262K.
   Our 27B has 4x fewer KV cache layers due to the hybrid architecture,
   so fp16 handles 262K easily. The KV cache quantization unlock is
   irrelevant for this model on this hardware.

### mlx_lm.server KV Cache Notes

mlx_lm 0.31.1's server CLI does NOT expose `--kv-bits` flags. The library's
`generate_step()` and `stream_generate()` DO accept `kv_bits`, `kv_group_size`,
and `quantized_kv_start` as kwargs, but the server never passes them through.
The `--prompt-cache-size` and `--prompt-cache-bytes` flags control prompt cache
pooling, not KV quantization.

Since fp16 handles all practical context lengths, this is a non-issue. If we
ever needed KV quant, a thin wrapper script using `stream_generate()` directly
would work.

## References

1. flash-moe issue #10: github.com/danveloper/flash-moe/issues/10
2. flash-moe issue #20: github.com/danveloper/flash-moe/issues/20
3. Ma-Dan's 35B fork: github.com/Ma-Dan/flash-moe/tree/Qwen3.6-35B-A3B
4. DJLougen model page: huggingface.co/DJLougen/Ornstein3.6-35B-A3B-MLX-6bit
5. Qwen3.6-35B-A3B config: huggingface.co/Qwen/Qwen3.6-35B-A3B
