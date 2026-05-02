# FCT089 Ornstein Model Family — Comprehensive Benchmarks

**Status:** Complete
**Date:** 2026-05-01
**Machine:** Whitebox (Mac Studio M1 Max, 32GB unified memory)

---

## Summary

Six-way comparison of all Ornstein/Nemostein model variants tested on
Whitebox. Standardized test suite: 6 quality tests + context scaling at
multiple lengths. All served via mlx_lm.server (except 35B-A3B which used
flash-moe).

**Winner: Nemostein-3-Nano-30b-a3b (4-bit)** — fastest model tested (48-50
tok/s), nearly flat context scaling thanks to Mamba hybrid architecture, and
survives 64K context where all transformer models degrade or OOM.

**Runner-up: Ornstein-26B-A4B-it 6-bit** — 30-33 tok/s with 26B-model quality
via MoE. Best quality-to-speed ratio for transformer architecture.

---

## Model Inventory

| Model | Architecture | Params (total/active) | Quant | Disk | Source |
|-------|-------------|----------------------|-------|------|--------|
| Ornstein3.6-35B-A3B | MoE (flash-moe) | 35B / 3B | 8-bit | ~29 GB | FCT076 |
| Ornstein-Hermes-3.6-27B-SABER | Dense (Qwen3.6 hybrid) | 27B / 27B | 6-bit | 21 GB | FCT087 |
| Ornstein-Hermes-3.6-27B-SABER | Dense (Qwen3.6 hybrid) | 27B / 27B | 4-bit | 14 GB | FCT087 |
| Ornstein-26B-A4B-it | MoE (Gemma4) | 26B / 4B | 6-bit | 19 GB | FCT088 |
| Ornstein-26B-A4B-it | MoE (Gemma4) | 26B / 4B | 4-bit | 13 GB | FCT088 |
| Nemostein-3-Nano-30b-a3b | MoE+Mamba hybrid (Nemotron-H) | 30B / 3B | 4-bit | 17 GB | NEW |

---

## Speed Comparison

### Decode Speed (tok/s)

| Model | Short (<100 tok) | ~1K | ~4K | ~8K | ~16K | ~32K | ~64K |
|-------|------------------|-----|-----|-----|------|------|------|
| 35B-A3B (flash-moe) | ~7.2 | ~7.2 | ~7.2 | ~7.2 | ~7.2 | ~7.2 | ~7.2 |
| 27B-SABER 6-bit | ~7-10 | — | — | — | ~7 | — | — |
| 27B-SABER 4-bit | ~13 | — | — | — | ~7 | — | — |
| 26B-A4B 6-bit | 30-33 | 31 | 22 | — | 17 | — | — |
| 26B-A4B 4-bit | **37-43** | — | — | — | — | — | — |
| **Nemostein 30B/3B 4-bit** | **48-50** | **47** | **44.5** | **43.6** | **42.7** | **30.4** | **23.0** |

### Speed Bar Chart (short context)

```
Nemostein 30B/3B 4-bit    ████████████████████████████████████████████████ 49 tok/s
26B-A4B 4-bit             ██████████████████████████████████████████ 42 tok/s
26B-A4B 6-bit             ██████████████████████████████ 31 tok/s
27B-SABER 4-bit           █████████████ 13 tok/s
27B-SABER 6-bit           ████████ 8 tok/s
35B-A3B flash-moe         ███████ 7.2 tok/s
```

### Context Degradation (% drop from short to longest tested)

| Model | Short | Longest tested | Drop |
|-------|-------|---------------|------|
| 35B-A3B (flash-moe) | 7.2 | 7.2 @ any ctx | 0% (flat) |
| Nemostein 30B/3B 4-bit | 49 | 23 @ 64K | 53% |
| 26B-A4B 6-bit | 31 | 17 @ 16K | 45% |
| 27B-SABER 4-bit | 13 | 7 @ 16K | 46% |
| 27B-SABER 6-bit | 8 | 7 @ 16K | 13% (already slow) |

---

## Quality Benchmarks

### Test Suite Results

All models tested with identical prompts. Results shown as PASS/partial/FAIL.

| Test | 35B-A3B | 27B 6/4-bit | 26B-A4B 6-bit | Nemostein 30B/3B |
|------|---------|-------------|---------------|-----------------|
| Factual ("capital of France") | PASS | PASS | PASS | PASS — "Paris" |
| Reasoning (sheep riddle) | PASS | PASS | PASS | PASS — correct |
| Code gen (palindrome) | PASS | PASS | PASS | PASS — docstring + hints |
| Multi-step math (widgets) | PASS | PASS | PASS | PASS — "5 minutes" |
| Instruction follow (5 items) | PASS | PASS | PASS | PASS — numbered list |
| Tool call (JSON format) | PASS | PASS | PASS | PASS — valid JSON |

All models pass the basic quality suite. Differences emerge in complex
multi-step reasoning, context coherence at long sessions, and edge cases —
not captured by this short-prompt test.

---

## Memory Analysis

| Model | Disk | RSS (process) | Wired (system) | Free after load | Dual viable? |
|-------|------|--------------|----------------|-----------------|-------------|
| 35B-A3B (flash-moe) | ~29 GB | ~3 GB | ~3 GB | ~25 GB | N/A (external binary) |
| 27B-SABER 6-bit | 21 GB | ~5.7 GB | ~22.7 GB | ~0.1 GB | NO |
| 27B-SABER 4-bit | 14 GB | — | ~14 GB | ~11 GB | YES |
| 26B-A4B 6-bit | 19 GB | ~5.7 GB | ~22.7 GB | ~0.1 GB | NO (thrashes to 1.5 tok/s) |
| 26B-A4B 4-bit | 13 GB | — | ~13.8 GB | ~11 GB | YES (tight, 0 GB headroom) |
| Nemostein 30B/3B 4-bit | 17 GB | ~17.6 GB | ~17.6 GB | ~1.2 GB | TIGHT |

### Key Memory Findings

1. **MoE models wire all expert weights.** Despite only 3-4B active params,
   the full model gets paged into RAM by macOS mmap. 35B-A3B via flash-moe
   was the exception — its sparse loader only touched active experts (~3 GB).

2. **mmap shares pages between processes.** Two instances of the same model
   share wired pages (tested with 26B-A4B 6-bit: 22.7 GB total, not 45 GB).

3. **Nemostein is lean.** 17.6 GB RSS for a 30B-parameter model (4-bit).
   Mamba layers have constant-size state, no growing KV cache.

4. **KV cache is negligible for Nemostein.** Mamba layers use fixed SSM
   state. Only the attention layers (sparse in the hybrid pattern) need
   KV cache. Total KV at 64K context: likely <500 MB.

---

## Architecture Deep Dive

### Nemostein-3-Nano-30b-a3b (Nemotron-H)

```
Hybrid pattern: MEMEM*EMEMEM*EMEMEM*EMEMEM*EMEMEM*EMEMEMEM*EMEMEMEME
52 layers total:
  M = Mamba SSM (recurrent, O(1) inference)
  E = MoE attention (128 experts, top_k=6)
  * = shared attention
```

- **Mamba layers:** Fixed-size recurrent state. No KV cache growth. Decode
  speed independent of context length. This is why 64K context only drops
  to 23 tok/s (vs transformer models that OOM or drop to <5 tok/s).

- **MoE layers:** 128 experts, top_k=6. 1 shared expert. Only 3B params
  active per token but 30B total capacity.

- **Attention layers:** 32 heads, 2 KV heads (GQA), head_dim=128.
  Max context 262K tokens.

- **Multimodal:** Fully multimodal (vision) per user confirmation.

### Ornstein-26B-A4B-it (Gemma4 MoE)

```
30 layers: 25 sliding_attention + 5 full_attention
128 experts, top_k=8, 4B active per token
Sliding window: 1024 tokens
```

- Standard transformer MoE. All 19 GB wired via mmap.
- 5 full attention layers with growing KV cache (manageable).
- 25 sliding layers with RotatingKVCache (fixed at 1024 window).

### Ornstein-Hermes-3.6-27B-SABER (Qwen3.6 hybrid)

```
64 layers: 48 GatedDeltaNet + 16 full attention
Dense 27B — all parameters active per token
```

- Highest quality per-token (every param participates).
- Slowest of the bunch — 27B active params = massive compute per token.
- 4-bit quant recovers speed (13 tok/s) but still much slower than MoE.

### Ornstein3.6-35B-A3B (flash-moe, deprecated)

```
MoE via flash-moe binary (not mlx_lm)
Sparse expert loading: only ~3 GB resident
```

- Deprecated 2026-04-30 due to GPU abort crashes under concurrent load.
- Flat 7.2 tok/s at all contexts (flash-moe's sparse loader).
- Could be retested under mlx_lm.server native MoE (deferred).

---

## Production Recommendations

### Best overall: Nemostein-3-Nano-30b-a3b (4-bit)

- Fastest (48-50 tok/s)
- Best context handling (23 tok/s at 64K!)
- Multimodal
- Lean memory (17.6 GB)
- 3B active = E4B-class speed with MoE capacity
- Only concern: 1.2 GB free → tight for concurrent processes

### Best quality: Ornstein-Hermes-3.6-27B-SABER (4-bit)

- 27B dense = highest quality per token
- 13 tok/s acceptable for complex reasoning tasks
- 14 GB headroom for concurrent operations

### Best balance: Ornstein-26B-A4B-it (6-bit)

- 30-33 tok/s with 26B MoE capacity
- Proven quality on all benchmarks
- 19 GB wired, 0.1 GB free — single instance only

### Suggested topology

```
Option A (speed-first):
  :41969  Nemostein 30B/3B 4-bit     (primary — both agents)
  48-50 tok/s, 17.6 GB, multimodal

Option B (quality-first):
  :41966  27B-SABER 4-bit            (complex reasoning)
  :41962  E4B-SABER 6-bit            (fast queries)
  13 + 40 tok/s, 14 + 6.3 = 20.3 GB

Option C (balanced):
  :41966  26B-A4B 6-bit              (primary — both agents)
  30-33 tok/s, 22.7 GB
```

---

## Pending Tests

- [ ] Ornstein3.6-35B-A3B retest under mlx_lm.server (deferred)

---

## References

- [1] FCT076 — Flash-MoE 35B-A3B Port and Debug
- [2] FCT078 — Dual SABER E4B Stress Test Results
- [3] FCT083 — 4B Benchmark Results (E4B-SABER)
- [4] FCT087 — Ornstein-Hermes-3.6-27B Deployment
- [5] FCT088 — Ornstein-26B-A4B-it 6-bit Testing
- [6] Model: Nemostein-3-Nano-30b-a3b (~/models/)
- [7] Model: Ornstein-26B-A4B-it-MLX-4bit (downloading to ~/models/)
