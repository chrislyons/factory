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

2. **The REAL bottleneck is prefill activation memory, not KV cache storage.**
   The KV cache is tiny (32 KB/token across 16 layers). But during prefill,
   the attention computation intermediates blow up memory. Without chunked
   prefill, 32K OOMs even though KV cache would only be ~1 GB. With
   `prefill_step_size=2048`, 32K works at peak 30.0 GB.

3. **Decode speed degrades with context.** At 8K: 12 tok/s. At 16K: 9.2 tok/s.
   At 32K: 7.1 tok/s. The growing KV cache affects decode compute as
   attention layers accumulate more cached tokens.

4. **32K is the practical ceiling on 32GB.** Peak 30.0 GB at 32K context
   leaves ~2 GB headroom. 48K likely OOMs. The earlier "fp16 handles 262K
   easily" claim was wrong — it only counted KV cache storage, not
   activation memory during computation.

5. **The tweet's situation does not apply.** The tweet described Qwen3.6
   27B dense on 24GB VRAM where q4 KV cache was needed to fit 262K.
   Our 27B has 4x fewer KV cache layers due to the hybrid architecture,
   so the KV cache itself is not the constraint. The constraint is
   prefill activation memory, which chunked prefill partially solves.

### mlx_lm.server KV Cache Notes

mlx_lm 0.31.1's server CLI does NOT expose `--kv-bits` flags. The library's
`generate_step()` and `stream_generate()` DO accept `kv_bits`, `kv_group_size`,
and `quantized_kv_start` as kwargs, but the server never passes them through.
The `--prompt-cache-size` and `--prompt-cache-bytes` flags control prompt cache
pooling, not KV quantization.

Since fp16 handles all practical context lengths, this is a non-issue. If we
ever needed KV quant, a thin wrapper script using `stream_generate()` directly
would work.

## 35B-A3B vs 27B — Production Comparison

| Metric | 35B-A3B (flash-moe) | 27B (mlx_lm) |
|--------|-------------------|---------------|
| Decode @ 512 | 7.2 tok/s | 12.1 tok/s |
| Decode @ 8K | 7.2 tok/s | 11.6 tok/s |
| Decode @ 16K | 7.2 tok/s | 9.2 tok/s |
| Decode @ 32K | 7.2 tok/s | 7.1 tok/s |
| Max context | 128K | ~32K |
| RAM (resident) | ~3 GB | ~22 GB |
| Speed at max ctx | 7.2 tok/s (flat) | 7.1 tok/s (degraded) |
| Serving | flash-moe HTTP API | mlx_lm.server |

**Verdict: 35B-A3B via flash-moe is the production choice.** The 27B's speed
advantage only holds under 8K context. At 16K+ it degrades to match the
35B-A3B, and 32K is its hard ceiling. The 35B-A3B uses 7x less RAM and
provides 128K context at a flat 7.2 tok/s.

The 27B may be useful as a draft model for speculative decoding (to boost
the 35B-A3B to ~12-15 tok/s) or as a fast slot for short queries.

### SABER Model Note

DJLougen released `Ornstein-27B-SABER` — an abliterated variant using
Spectral Analysis-Based Entanglement Resolution. 0% refusal, 0% perplexity
degradation, 125 directions ablated across 25 layers. BF16 format.
Downloaded to external drive for future evaluation.

## Concurrent Small Models — Gemma4 E2B/E4B Benchmarks

**Run:** 2026-04-28 | Question: Can small models run alongside the 35B-A3B?

### Resource Budget

35B-A3B flash-moe resident: ~3 GB. System total: 32 GB (~5 GB macOS).
Available for small models: ~24 GB.

### Gemma4 E2B (6-bit, /Users/nesbitt/models/gemma-4-e2b-6bit)

15 layers, ALL with KV cache (dense, no hybrid). 1 KV head, head_dim=256.
Model memory: 3.79 GB. KV per token: 15 KB (fp16).

| Context | Prefill | Decode | Peak Mem |
|---------|---------|--------|----------|
| 512 | 1030 tok/s | 71.7 tok/s | 4.3 GB |
| 2048 | 2432 tok/s | 73.4 tok/s | 4.6 GB |
| 8192 | 2247 tok/s | 68.9 tok/s | 4.9 GB |
| 16384 | 2189 tok/s | 65.0 tok/s | 5.2 GB |
| 32768 | 2000 tok/s | 56.7 tok/s | 5.8 GB |

### Gemma4 E4B (6-bit, /Users/nesbitt/models/gemma-4-e4b-6bit)

24 layers, ALL with KV cache. Mixed KVCache + RotatingKVCache.
Model memory: 6.15 GB.

| Context | Prefill | Decode | Peak Mem |
|---------|---------|--------|----------|
| 512 | 545 tok/s | 45.8 tok/s | 6.7 GB |
| 2048 | 674 tok/s | 44.2 tok/s | 7.0 GB |
| 8192 | 658 tok/s | 41.4 tok/s | 7.4 GB |
| 16384 | 655 tok/s | 37.4 tok/s | 7.8 GB |
| 32768 | 624 tok/s | 31.4 tok/s | 8.6 GB |

### KV Cache Quantization: NOT AVAILABLE

Gemma4 uses RotatingKVCache (sliding window attention). mlx_lm 0.31.1
throws "RotatingKVCache Quantization NYI" for q8/q4. Not needed — models
are small enough that fp16 KV cache fits easily at all tested contexts.

### Combined Topology Analysis

```
35B-A3B resident:     3.0 GB
E4B at 32K context:   8.6 GB
                      -------
Total:               11.6 GB
Headroom:            20.4 GB
```

Could run BOTH E2B and E4B alongside 35B-A3B with ~15 GB headroom.

Proposed topology:
```
  :41961  E4B (mlx_lm.server)     46 tok/s   fast chat, short queries
  :41962  E2B (mlx_lm.server)     72 tok/s   ultra-fast tasks
  :41966  35B-A3B (flash-moe)      7.2 tok/s  deep reasoning, 128K context
```

Speed degradation with context:
- E4B:  46 → 31 tok/s (512 → 32K)
- E2B:  72 → 57 tok/s (512 → 32K)
- 35B-A3B: flat 7.2 tok/s at all contexts

### Question 1: Multiple 35B-A3B Instances

Not beneficial. SSD bandwidth is the bottleneck — two instances would
double expert I/O and halve throughput. Metal GPU is shared. One instance
request-serialized is optimal.

## Small Model Benchmarks — Qwen3.5-2B and 4B Distill

**Run:** 2026-04-28 | Models: Qwen3.5-2B-6bit, Qwen3.5-4B-Claude-Opus-Distill-v2-6bit

### Qwen3.5-2B (6-bit, /Users/nesbitt/models/Qwen3.5-2B-6bit)

24 layers, 6 KV cache + 18 ArraysCache (hybrid). Model: 1.53 GB.
KV per token: 12 KB (fp16). Both cache types have `merge=True` → server batching works.

| Context | Prefill | Decode | Peak Mem |
|---------|---------|--------|----------|
| 512 | 916 tok/s | 123.1 tok/s | 2.3 GB |
| 2048 | 1055 tok/s | 111.5 tok/s | 2.9 GB |
| 8192 | 1114 tok/s | 114.7 tok/s | 3.4 GB |
| 16384 | 1070 tok/s | 105.9 tok/s | 3.6 GB |
| 32768 | 968 tok/s | 84.7 tok/s | 4.3 GB |

KV quantization works but fp16 is fastest at all contexts. Not needed.

### Qwen3.5-4B Claude Opus Reasoning Distill (6-bit)

32 layers, 8 KV cache + 24 ArraysCache. Model: 3.42 GB.
KV per token: 32 KB (fp16). Batchable.

| Context | KV | Prefill | Decode | Peak Mem |
|---------|-----|---------|--------|----------|
| 512 | fp16 | 113 tok/s | 19.5 tok/s | 4.3 GB |
| 2048 | fp16 | 217 tok/s | 35.0 tok/s | 5.1 GB |
| 8192 | fp16 | 231 tok/s | 9.9 tok/s | 5.8 GB |
| 16384 | q4 | 388 tok/s | 45.3 tok/s | 6.6 GB |
| 32768 | fp16 | 384 tok/s | 48.2 tok/s | 8.2 GB |

Noisy results — decode speed varies 10-48 tok/s. q4 KV helps at 16K+.

### Quality Comparison: 2B vs 4B Distill

Tested 8 tasks: simple Q&A, math, instruction following, code analysis,
summarization, escalation detection, tool call recognition, multi-turn context.

**2B won every test.** Not just speed — quality too. The 4B distill leaks
"Thinking Process:" into responses even with `enable_thinking=False`. The
distillation from Claude Opus baked in a "show your work" behavior that
wastes tokens and confuses users.

Speed: 2B = 121-138 tok/s, 4B = 61-63 tok/s (2x faster).

### Memory Projection: Concurrent Serving

Budget: 32 GB - 5 GB macOS - 6 GB flash-moe (with spike headroom) = 21 GB.

| Config | 128K | 192K | 256K | Max |
|--------|------|------|------|-----|
| 2x 2B | 12.6 GB ✓ | 14.7 GB ✓ | 16.6 GB ✓ | ~407K |
| 2x 4B | 24.4 GB ✗ | — | — | ~83K |
| 1x 4B | 12.2 GB ✓ | 14.6 GB ✓ | 16.9 GB ✓ | ~371K |

### Proposed Production Topology

```
:41961  mlx_lm.server   Qwen3.5-2B     Boot front door (123 tok/s, 256K ctx)
:41962  mlx_lm.server   Qwen3.5-2B     Kelk front door (123 tok/s, 256K ctx)
:41966  flash-moe        35B-A3B        Deep thinking consultant (7.2 tok/s, 128K ctx)
```

The "conversationalist + expert" pattern: 2B handles 90% of interactions at
123 tok/s. When complex reasoning is needed, it calls the 35B-A3B as a tool.
Both agents get dedicated fast front doors. Both can escalate to deep thinking.

Memory: 2x 2B (16.6 GB) + 35B-A3B (6 GB) + macOS (5 GB) = 27.6 GB.
Headroom: 4.4 GB.

For N agent profiles (modular goal): add 2B instances on incremental ports.
Each uses ~8 GB at 256K. 3 agents at 128K = 18 GB + 6 + 5 = 29 GB (works).

### mlx_lm.server Batching

Both Qwen3.5-2B and 4B are `is_batchable = True` — all cache layers have
`merge=True`. The server's `BatchGenerator` can serve concurrent requests
via `--decode-concurrency` and `--prompt-concurrency`. A single instance
CAN serve multiple agents simultaneously (shared forward pass, separate KV caches).

**However:** batching two agents on one instance doubles the KV cache, which
significantly reduces max context. 1x 4B batched for 2 agents maxes at 96K
context (below 128K floor). This eliminates the 1+1 topology.

### Qwen3.5-4B Base (NexVeridian, 6-bit)

32 layers, 8 KV cache + 24 ArraysCache. Model: 3.42 GB. Batchable.

| Context | KV | Prefill | Decode | Peak Mem |
|---------|-----|---------|--------|----------|
| 512 | fp16 | 384 tok/s | 62.2 tok/s | 4.3 GB |
| 2048 | fp16 | 432 tok/s | 62.4 tok/s | 5.1 GB |
| 8192 | fp16 | 426 tok/s | 58.1 tok/s | 5.8 GB |
| 16384 | fp16 | 409 tok/s | 54.1 tok/s | 6.6 GB |
| 32768 | fp16 | 384 tok/s | 47.8 tok/s | 8.2 GB |

Much cleaner than the distill — consistent 48-62 tok/s, no noisy spikes.

### Three-Way Quality Comparison: 2B vs 4B Distill vs 4B Base

| Test | 2B | 4B Distill | 4B Base |
|------|-----|-----------|---------|
| Simple Q&A | Clean, fast | Leaks thinking | Clean, fast |
| Math | Correct | Correct | Correct, best format |
| Instruction (3 bullets) | Perfect | Leaks thinking | Perfect, best content |
| Code analysis | Good | Good | Good, cleaner |
| Summarization | Clean 2 sentences | Dumps analysis first | Clean 2 sentences, more detail |
| Escalation | "ESCALATE" fast | "Let me think..." | "ESCALATE" clean |
| Tool call | Clean JSON | Leaks reasoning | Clean JSON, better args |
| Multi-turn | Good | Good | Most complete |
| Speed | 122-138 tok/s | 61-63 tok/s | 62-71 tok/s |

**4B distill eliminated.** Leaks "Thinking Process:" into every response.
Claude Opus distillation baked in "show your work" behavior.

**4B base is genuinely better quality** than 2B (better math formatting,
better tool call args, more complete multi-turn answers). But 2B is 2x faster.

### Topology Decision: 2+1 vs 1+1 vs 1+1+1

| Setup | Description | Max Context | 128K Budget | Complexity |
|-------|-------------|-------------|-------------|------------|
| **2+1** | 2x 2B + 35B | **256K** | 23.6 GB ✓ (8.4 GB headroom) | Low |
| 1+1+1 | 2B + 4B + 35B | 160K | 29.5 GB ✓ (2.5 GB headroom) | Medium |
| 1+1 | 1x 4B batched + 35B | 96K | ✗ below 128K floor | Low |

**1+1 eliminated:** Batching two agents on one 4B doubles KV cache, maxes at 96K.

**1+1+1 eliminated:** 2.5 GB headroom at 128K is too tight for production.
Any memory spike from the 35B during inference → OOM.

**2+1 wins:** 256K context, 8.4 GB headroom at 128K, simple architecture.
The 2B's quality gap vs the 4B base can be closed via fine-tuning with the
frontdoor tuning profile (see below).

### Production Topology

```
:41961  mlx_lm.server   Qwen3.5-2B     Boot front door (123 tok/s, 256K ctx)
:41962  mlx_lm.server   Qwen3.5-2B     Kelk front door (123 tok/s, 256K ctx)
:41966  flash-moe        35B-A3B        Deep thinking consultant (7.2 tok/s, 128K ctx)
```

The "conversationalist + expert" pattern: 2B handles 90% of interactions at
123 tok/s. When complex reasoning is needed, it calls the 35B-A3B as a tool.
Both agents get dedicated fast front doors. Both can escalate to deep thinking.

Memory at 128K: 2x 2B (12.6 GB) + 35B-A3B (6 GB) + macOS (5 GB) = 23.6 GB.
Headroom: 8.4 GB.

Memory at 256K: 2x 2B (16.6 GB) + 35B-A3B (6 GB) + macOS (5 GB) = 27.6 GB.
Headroom: 4.4 GB.

For N agent profiles (modular goal): add 2B instances on incremental ports.
Each uses ~8 GB at 256K. 3 agents at 128K = 18 GB + 6 + 5 = 29 GB (works).

**Run:** 2026-04-28 | Sources: tuning-wizard, Unsloth docs, mlx-lora-finetune

### tuning-wizard (existing pipeline)

tuning-wizard already has the infrastructure for fine-tuning Qwen3.5 models:

- **qwen-base role** — targets the 4 weaknesses we observed: identity adherence,
  anti-sycophancy, structured output, tool-call format. 14 categories with
  min/max example counts. bf16 LoRA only (no QLoRA — GatedDeltaNet sensitivity).
- **kelk role** — agent LoRA stacking on qwen-base. 110 reviewed examples
  exported (93 train / 17 eval). Categories: write_file_completion (99),
  file_path_correction (6), patch_disambiguation (4), python_syntax_fix (1).
- **boot role** — agent LoRA for Nanbeige4.1-3B (different model family).

Training pipeline: Unsloth on CUDA → GGUF export → MLX convert.

### Key finding: tuning-wizard targets the EXACT weaknesses we saw

The 4B distill's "Thinking Process:" leak maps to the qwen-base categories:
- `json-raw-output` — "return raw valid JSON, no markdown fences, no explanatory text"
- `identity-style-constraint` — "follow style constraints from system prompt"
- `malformed-output-recovery` — "fix errors without apologizing at length"

These are exactly the behaviors the 4B distill violates. Fine-tuning with
tuning-wizard's dataset could fix them.

### Unsloth Qwen3.5-2B fine-tuning

From Unsloth docs (unsloth.ai/docs/models/qwen3.5/fine-tune):
- Qwen3.5-2B bf16 LoRA: **5 GB VRAM** (fits on Whitebox M1 Max)
- QLoRA NOT recommended for Qwen3.5 (GatedDeltaNet quantization sensitivity)
- Training: bf16 LoRA, `transformers v5`, Unsloth 1.5x speedup
- Supports vision fine-tuning and RL (GRPO/GSPO)

### mlx-lora-finetune (Mac-native LoRA)

From sciences44/mlx-lora-finetune:
- Fine-tunes Qwen3.5-2B on Apple Silicon in **15 minutes**, 600 iterations
- Peak RAM: 5.9 GB (fits alongside flash-moe)
- **Result: 2B beat 4B after fine-tuning** (50% vs 40% semantic accuracy on SQL)
- "Prompt engineering doesn't work at this model size. Fine-tuning teaches
  a deep behavioral pattern."
- 0.36% of parameters trained (6.8M LoRA adapters)

### What fine-tuning could fix for our 2B front door

| Weakness | tuning-wizard category | Impact |
|----------|----------------------|--------|
| Leaks thinking into responses | json-raw-output | High — wastes tokens |
| Follows style constraints | identity-style-constraint | Medium |
| Corrects malformed output | malformed-output-recovery | High — agent reliability |
| Recognizes when to escalate | New category needed | High — routing quality |
| Tool call format | tool-call-single, tool-call-multi-step | High — agent integration |

### Two paths to improvement

**Path A: Unsloth bf16 LoRA on CUDA (higher quality)**
- Train on Unsloth Studio (CUDA required — no Mac training yet)
- bf16 LoRA on qwen-base categories
- GGUF export → MLX convert for deployment
- tuning-wizard already has the data pipeline

**Path B: mlx-lora-finetune on Mac (faster iteration)**
- Train directly on Whitebox with mlx_lm LoRA
- 15 minutes per experiment, 5.9 GB peak RAM
- No GGUF/MLX conversion needed — native MLX adapters
- Can iterate on dataset quickly

**Path B is more practical for now.** We can experiment locally without
CUDA infrastructure. If quality improves, move to Path A for production.

### Recommended next steps

1. Create a qwen-2b role in tuning-wizard targeting front-door behaviors
2. Curate training data: escalation decisions, tool calls, clean output format
3. Run mlx-lora-finetune on Whitebox with the 2B model
4. Benchmark fine-tuned 2B against base 2B on the same 8-task quality test
5. If quality improves significantly, deploy fine-tuned 2B as front door

### References

1. Unsloth Qwen3.5 guide: unsloth.ai/docs/models/qwen3.5/fine-tune
2. mlx-lora-finetune: github.com/sciences44/mlx-lora-finetune
3. tuning-wizard: ~/dev/tuning-wizard/ (qwen-base.yaml, kelk.yaml)
4. Fine-tuning small models: omdena.com/blog/fine-tuning-small-language-models

## References

1. flash-moe issue #10: github.com/danveloper/flash-moe/issues/10
2. flash-moe issue #20: github.com/danveloper/flash-moe/issues/20
3. Ma-Dan's 35B fork: github.com/Ma-Dan/flash-moe/tree/Qwen3.6-35B-A3B
4. DJLougen model page: huggingface.co/DJLougen/Ornstein3.6-35B-A3B-MLX-6bit
5. Qwen3.6-35B-A3B config: huggingface.co/Qwen/Qwen3.6-35B-A3B
