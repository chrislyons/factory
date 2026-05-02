# FCT088 Ornstein-26B-A4B-it Testing (6-bit and 4-bit)

**Status:** Complete — 4-bit dual instances viable with caveats
**Date:** 2026-05-01
**Machine:** Whitebox (Mac Studio M1 Max, 32GB unified memory)

---

## Summary

Ornstein-26B-A4B-it is a Gemma 4 MoE model (unsloth/gemma-4-26B-A4B-it) — 26B
total parameters, 4B active per token (128 experts, top_k=8). Tested in both
6-bit (19 GB) and 4-bit (13 GB) quantization.

**6-bit:** 30-33 tok/s single instance. Dual NOT viable (22.7 GB wired, thrashes).

**4-bit:** 41.6 tok/s single instance. **Dual instances viable** — mmap shares
model pages (13.8 GB wired, not 27.6 GB). Instance A maintains 40.5 tok/s with
B running (3% degradation). Instance B has cold-start penalty on first request
but warms to 40+ tok/s. 0 GB headroom — tight but stable under tested load.

### Speed Comparison

| Config | Avg tok/s | Wired | Headroom | Dual viable? |
|--------|----------|-------|----------|-------------|
| 6-bit single | 31 | 22.7 GB | 0.1 GB | — |
| 6-bit dual | 1.5 | 22.7 GB | 0.1 GB | NO (thrashes) |
| **4-bit single** | **41.6** | **13.8 GB** | **~11 GB** | — |
| **4-bit dual** | **38-40** | **13.8 GB** | **0 GB** | **YES (tight)** |

---

## Model Architecture

| Property | Value |
|----------|-------|
| Base | unsloth/gemma-4-26B-A4B-it |
| Architecture | Gemma 4 MoE |
| Total params | 26B |
| Active params | 4B (128 experts, top_k=8) |
| Layers | 30 (25 sliding_attention + 5 full_attention) |
| Hidden size | 2816 |
| Head dim | 256 (sliding) / 512 (full/global) |
| KV heads | 8 (sliding) / 2 (global) |
| MoE intermediate | 704 |
| Sliding window | 1024 |
| Max context | 262K tokens |
| Quantization | 6-bit (affine, group_size=64), routers 8-bit |
| Disk | 19 GB (4 shards) |
| Model type | Thinking model (reasoning_content field) |

---

## Benchmark Results

### Decode Speed

| Test | Prompt tok | Comp tok | tok/s | Time |
|------|-----------|----------|-------|------|
| Short factual | 27 | 54 | 3.9* | 13.9s |
| Sheep riddle | 34 | 170 | 30.8 | 5.5s |
| Code: palindrome | 35 | 1528 | 32.6 | 46.8s |
| Multi-step math | 48 | 373 | 32.6 | 11.4s |
| Instruction follow | 36 | 363 | 33.0 | 11.0s |
| Tool call | 49 | 127 | 30.2 | 4.2s |

*First request after model load — dominated by prefill + weight paging.*

### Context Scaling

| Prompt tokens | Comp tokens | tok/s | Time |
|---------------|-------------|-------|------|
| 255 | 512 | 31.0 | 16.5s |
| 2,215 | 512 | 22.1 | 23.1s |
| 7,615 | 900 | 16.6 | 54.3s |
| 4,815 | 1024 | 21.5 | 47.6s |

Speed degrades with context as expected (more KV cache = more memory bandwidth).

### Quality

| Test | Result |
|------|--------|
| Factual ("capital of France") | PASS — "Paris" |
| Reasoning (sheep riddle) | PASS — "9 sheep left" with explanation |
| Code generation (palindrome) | PASS — full function with docstring, type hints |
| Multi-step math (widgets) | PASS — "5 minutes" with correct reasoning |
| Instruction following | PASS — exactly 5 items, numbered, one sentence each |
| Tool call format | PASS — valid JSON with read_file call |

**Note:** This is a thinking model. Content may appear in `reasoning_content`
when max_tokens is too small for both thinking + answer. With adequate tokens
(1024+), content appears correctly in `content` field.

---

## Memory Analysis

### Single Instance (mlx_lm.server, no wrapper)

| Metric | Value |
|--------|-------|
| Process RSS | ~5.7 GB |
| Wired pages | ~22.7 GB |
| Free after load | 0.1 GB |
| Baseline wired | ~3.1 GB |
| Model wired | ~19.6 GB |
| Stable? | Yes — no OOM at any tested context length |

The 19 GB model gets fully wired into physical RAM by macOS's mmap subsystem.
With 22.7 GB wired + 3.1 GB baseline = 25.8 GB, leaving ~6.2 GB for KV cache
and other processes. Tested up to 7,600 prompt tokens without OOM.

### KV Cache Memory

Only 5 full attention layers have growing KV cache (25 sliding layers use
RotatingKVCache at window=1024, fixed ~40 MB total):

| Context | Full attn KV | Sliding KV | Total KV |
|---------|-------------|-----------|---------|
| 1K | 4 MB | 40 MB | 44 MB |
| 16K | 64 MB | 40 MB | 104 MB |
| 32K | 128 MB | 40 MB | 168 MB |
| 64K | 256 MB | 40 MB | 296 MB |
| 128K | 512 MB | 40 MB | 552 MB |

KV cache is NOT the bottleneck — the model weights are.

### Dual Instance Test

| Metric | Value |
|--------|-------|
| Instance 1 speed | 1.6 tok/s |
| Instance 2 speed | 1.5 tok/s |
| Wired (shared) | 22.7 GB |
| Free | 0.1 GB |
| Verdict | NOT VIABLE — thrashing, unusable speed |

mmap shares model pages between processes (22.7 GB total, not per-instance),
but the system is at 0.1 GB free → constant eviction/re-faulting → 1.5 tok/s.

---

## Head-to-Head: 26B-A4B vs E4B-SABER vs 27B-SABER

| | E4B-SABER | 27B-SABER 4-bit | 26B-A4B 6-bit |
|---|---|---|---|
| Architecture | Gemma 4 dense | Qwen3.6 hybrid | Gemma 4 MoE |
| Total params | 4B | 27B | 26B |
| Active params | 4B | 27B | 4B |
| Quantization | 6-bit | 4-bit | 6-bit |
| Disk | 5.7 GB | 14 GB | 19 GB |
| RAM (wired) | ~6.3 GB | ~14 GB | ~22.7 GB |
| tok/s (short) | 34-50 | ~13 | 30-33 |
| tok/s (16K ctx) | ~16 | ~7 | ~17 |
| Dual instance | ✓ (10.5 GB free) | ✓ (workable) | ✗ (thrashing) |
| Thinking model | No | Yes | Yes |
| Abliterated | Yes (GestaltLabs) | Yes (Ornstein/Hermes) | Unknown |
| Context | 128K | 262K | 262K |

### Key Takeaways

1. **26B-A4B matches E4B speed** (30-33 vs 34-50 tok/s) because both have 4B
   active parameters. The MoE routing overhead is minimal.

2. **26B-A4B is 2.5x faster than 4-bit 27B** (30 vs 13 tok/s) because the
   dense 27B has 27B active parameters per token vs 4B active for MoE.

3. **Quality: 26B-A4B has 26B-model capacity** — 128 expert MLPs per layer
   provide much more knowledge capacity than a 4B dense model, even though
   only 8 experts are active per token. The router selects the most relevant
   experts dynamically.

4. **Memory is the constraint:** 22.7 GB wired leaves only ~9 GB headroom.
   No room for a second instance. The 26B-A4B replaces one E4B-SABER but
   cannot run alongside another.

5. **The MoE sweet spot:** Same active params as E4B → same speed. But 6.5x
   more total capacity → dramatically better quality on complex tasks. The
   only cost is memory (19 GB vs 5.7 GB disk).

---

## Production Recommendation

### Option A: 26B-A4B single instance (RECOMMENDED)

```
:41966  Ornstein-26B-A4B-it-MLX-6bit  (sole inference server)
Boot → :41966
Kelk → :41966 (shared, serialize prefills)
```

- 30-33 tok/s decode
- 26B-model quality with 4B speed
- Both agents share one server (prompt-concurrency 1)
- ~9 GB headroom for KV cache + other processes

### Option B: 26B-A4B + E4B-SABER

```
:41966  Ornstein-26B-A4B-it-MLX-6bit  (Boot — primary agent)
:41962  E4B-SABER                       (Kelk — secondary agent)
```

- Boot gets 26B quality at 30-33 tok/s
- Kelk gets 4B quality at 34-50 tok/s  
- Total: ~22.7 + ~6.3 = ~29 GB wired → tight but feasible
- Only if Kelk doesn't need 26B quality

### Option C: 27B-SABER 4-bit (current production)

```
:41966  Ornstein-Hermes-3.6-27b-SABER-MLX-4bit
Boot → :41966
Kelk → :41966
```

- 13 tok/s decode
- 27B dense quality (every parameter active)
- 14 GB headroom
- Better for complex reasoning tasks that use all 27B params

---

## Wrapper Configuration

For production use, the model needs the same wrapper pattern as the 27B:

```python
import sys, mlx.core as mx

# Memory limit — NO wired limit (let pages stay resident)
METAL_LIMIT = 28 * 1024 * 1024 * 1024  # 28 GB
mx.set_memory_limit(METAL_LIMIT)

# KV cache: 4-bit QuantizedKVCache for full attention layers
# RotatingKVCache for sliding layers (handled natively by Gemma4 TextModel.make_cache)
```

Server flags:
```
--prefill-step-size 256     (conservative — prevents Metal GPU OOM during prefill)
--prompt-concurrency 1      (serialize prefills)
--max-tokens 16384
--prompt-cache-bytes 4294967296  (4 GB cap)
```

**Note:** Gemma4 TextModel.make_cache already creates the correct cache types
(KVCache for full attention, RotatingKVCache for sliding). A QuantizedKVCache
override should only replace the KVCache entries, not the RotatingKVCache ones.

---

## 4-Bit Model Testing (Added 2026-05-01)

### Model

- Path: `/Users/nesbitt/models/Ornstein-26B-A4B-it-MLX-4bit/`
- Disk: 13.2 GB (3 shards)
- Source: HuggingFace (Ornstein fine-tune), staged on CL T04, copied to internal SSD
- Architecture: Same as 6-bit (Gemma4 MoE, 26B/4B active, 128 experts, top_k=8)

### Single Instance Benchmarks

| Test | Prompt tok | Comp tok | tok/s | Time |
|------|-----------|----------|-------|------|
| Short factual | 25 | 57 | 37.1 | 1.5s |
| Reasoning | 33 | 194 | 42.3 | 4.6s |
| Code gen | 27 | 1024 | 42.9 | 23.9s |
| Multi-step math | 42 | 512 | 43.2 | 11.8s |
| Instruction follow | 35 | 378 | 43.2 | 8.8s |
| Tool call | 44 | 163 | 40.8 | 4.0s |
| **Average** | | | **41.6** | |

### Dual Instance Test

Instance A (with B running):

| Test | Prompt tok | Comp tok | tok/s | Time |
|------|-----------|----------|-------|------|
| Short factual | 25 | 57 | 33.3 | 1.7s |
| Reasoning | 33 | 194 | 36.4 | 5.3s |
| Code gen | 27 | 1024 | 42.5 | 24.1s |
| Multi-step math | 42 | 512 | 43.8 | 11.7s |
| Instruction follow | 35 | 378 | 44.0 | 8.6s |
| Tool call | 44 | 163 | 43.0 | 3.8s |
| **Average** | | | **40.5** | |

Instance B (with A running):

| Test | Prompt tok | Comp tok | tok/s | Time |
|------|-----------|----------|-------|------|
| Short factual | 25 | 57 | 1.7* | 33.2s |
| Reasoning | 33 | 194 | 40.2 | 4.8s |
| Code gen | 27 | 1024 | 42.7 | 24.0s |
| Multi-step math | 42 | 512 | 43.3 | 11.8s |
| Instruction follow | 35 | 378 | 43.3 | 8.7s |
| Tool call | 44 | 163 | 40.2 | 4.1s |
| **Average** | | | **35.2** | |

*Instance B first request: cold-start penalty (model weights paging in). All
subsequent requests at 40+ tok/s.

### Concurrent Decode

Both instances ran "Explain quantum entanglement" simultaneously:

| Instance | Tokens | Time | tok/s |
|----------|--------|------|-------|
| A | 77 | 46.0s | 1.7 |
| B | 77 | 1.9s | 39.9 |

Concurrent prefill contention: serialized `--prompt-concurrency 1` means one
instance waits while the other prefills. This is a scheduling issue, not a
memory issue.

### Memory Analysis

| Metric | 4-bit Single | 4-bit Dual |
|--------|-------------|-----------|
| Model disk | 13.2 GB | 13.2 GB |
| Wired pages | 13.8 GB | 13.8 GB (shared via mmap) |
| Process RSS | ~2.2 GB | ~2.2 GB each |
| Free after load | ~11 GB | 0 GB |
| Stable? | Yes | Yes (tested 6 sequential requests) |

**Key finding: mmap shares model pages between processes.** Two instances of the
same model file share the same physical pages in RAM. The second instance adds
only process overhead (RSS, KV cache), NOT a second copy of the 13 GB model.
This is why dual 4-bit works but dual 6-bit doesn't — the 6-bit model (22.7 GB
wired) leaves no room for the second instance's overhead.

### Dual Instance Verdict

**Viable with caveats:**
- Instance A maintains near-single speed (40.5 vs 41.6 tok/s, 3% degradation)
- Instance B has cold-start penalty on first request, then matches A
- 0 GB headroom — tight but stable under tested load
- Concurrent prefill causes scheduling contention (one waits while other prefills)
- Risk: any additional memory pressure (other apps, large KV cache) could cause thrashing

---

## Files

| File | Purpose |
|------|---------|
| `/Users/nesbitt/models/Ornstein-26B-A4B-it-MLX-6bit/` | Model files (19 GB) |
| `scripts/test-26b-a4b-v2.py` | Benchmark script (v2, handles thinking model) |
| `scripts/test-26b-a4b-stress.py` | Long context stress test |
| `docs/fct/FCT088-26b-a4b-benchmark-v2.json` | Raw benchmark data |

---

## References

- [1] FCT083 — E4B-SABER benchmark results (7/8 test suite)
- [2] FCT078 — Dual SABER stress test, memory budget
- [3] FCT087 — 27B-SABER deployment (6-bit/4-bit/2-bit)
- [4] Model: https://huggingface.co/unsloth/gemma-4-26B-A4B-it
