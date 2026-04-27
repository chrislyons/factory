# FCT074 Qwen3.6 Local Inference Architecture

**Date:** 2026-04-26
**Status:** Approved — ready for implementation
**Machine:** Mac Studio M1 Max (32GB, 400 GB/s bandwidth)
**Related:** FCT068 (DFlash research), FCT070 (KV cache + prefill tuning), FCT073 (optimization curriculum)

---

## 1. Architecture Decision

**Decision:** Replace all local inference (2× Gemma 4 E4B + flash-moe 26B-A4B) with Qwen3.6-35B-A3B as the default model, with Qwen3.6-27B available for intensive sessions.

### Why 35B-A3B (not 27B dense)

The 27B dense model is objectively smarter (74 vs 67 BenchLM) and faster (15-20 vs 5-10 tok/s). But at 6-bit it's 22.8GB — leaving only 1.5GB for KV cache on 32GB. That's not enough for multi-agent long-context work.

The 35B-A3B MoE model has only ~5GB resident via mmap (attention/routing/embeddings). Expert weights (~24GB) stream from SSD on demand. This leaves ~19GB for KV cache — enough for 2 agents at 128K fp16 with 3.9GB headroom.

| | Gemma 4 E4B | Gemma 4 26B-A4B | **Qwen3.6-35B-A3B** | Qwen3.6-27B |
|---|---|---|---|---|
| Quality (BenchLM) | ~52 | ~60 | **67** | 74 |
| Active params | 4B | 4B | **3B** | 27B |
| RAM resident | 7.5GB | 3GB | **~5GB** | 22.8GB |
| Speed | 30 tok/s | 5.4 tok/s | **5-10 tok/s** | 15-20 tok/s |
| With DFlash | N/A | N/A | **8-17 tok/s** | limited |
| KV budget | ~2.5GB | ~3GB | **~19GB** | 1.5GB |
| Context (2 agents) | 32K kv4 | 64K kv4 | **128K fp16** | 50K |
| Multi-agent | 2 fixed | 1 shared | **5+** | 1 |

### Dual-Model Configuration

**Default mode: Qwen3.6-35B-A3B**
- Both Boot and Kelk served from :41961
- 128K context per agent, fp16 KV
- 5+ agents possible (with kv4: more)
- 5-10 tok/s base, 8-17 tok/s with DFlash
- Quality: 67 BenchLM (massive upgrade from E4B at ~52)

**Intensive mode: Qwen3.6-27B**
- Deep sessions: coding, research, complex reasoning
- 32-50K context (1.5GB KV budget)
- 15-20 tok/s
- Quality: 74 BenchLM
- Switch on demand: `factory model switch 27b`

Both model files on disk simultaneously (51.9GB total, fits after removing old models).

---

## 2. MLX vs GGUF

MLX is the correct format for Apple Silicon:

| Factor | MLX | GGUF (llama.cpp) |
|--------|-----|-------------------|
| Throughput (tok/s) | **+20-40% higher** on large models | Baseline |
| KV cache overhead | Zero-copy in unified memory | Copy overhead between CPU/GPU |
| Long context | Better (no copy tax) | Worse (copy scales with context) |
| Quantization formats | 4/6/8-bit MLX | Q2-Q8 K-quants, IQ formats |
| Continuous batching | vllm-mlx (native) | llama-server (limited) |
| Python API | First-class (Apple maintained) | llama-cpp-python (community) |
| Multimodal | mlx-vlm (native) | llava (separate project) |
| Ecosystem size | Growing (Apple-backed) | Mature (universal) |
| Portability | Apple Silicon only | Everything (CUDA, ROCm, CPU) |

MLX was designed from scratch for Apple Silicon's unified memory architecture. The key advantage: zero-copy between CPU and GPU. On GGUF, the KV cache is copied between CPU and GPU memory on every operation — this tax scales with context length and eliminates any speed advantage GGUF might have on short prompts.

The 20-40% throughput advantage is real and measurable on M-series hardware. For a model served 24/7, this compounds.

**GGUF would only be preferred if:** we needed to run on non-Apple hardware (CUDA) or if a model only had GGUF quants available. Neither applies here — Qwen3.6-35B-A3B has MLX 6-bit available from mlx-community and Unsloth.

vllm-mlx uses MLX format exclusively. It cannot load GGUF files.

---

## 3. Hybrid Architecture Deep-Dive

Qwen3.6-27B and Qwen3.6-35B-A3B share the same hybrid architecture. This is NOT a standard transformer — it uses a mixture of recurrent and attention layers, which is critical for memory-constrained devices.

### Layer Breakdown (64 layers total)

- **45× GatedDeltaNet** (recurrent linear attention) — FIXED-size state, does NOT grow with context
- **15× Gated Attention** (standard) — KV cache GROWS linearly with context

A standard dense model with 64 full-attention layers would have 4.3× larger KV cache. The hybrid architecture is a major advantage for memory-constrained devices.

### KV Cache Math

**Standard attention layers (15 of 64):**
- 4 KV heads × 256 head_dim × 2 (K+V) × 2 bytes (fp16) = 4,096 bytes/token/layer
- 15 layers × 4KB = 60KB per token (linear with context)

**GatedDeltaNet layers (45 of 64):**
- 16 QK heads × 128 × 128 state × 2 bytes = 512KB per layer
- 45 layers × 512KB = **22.5MB FIXED** (does NOT grow with context)

**Per-token KV growth:** 60KB (fp16), 15KB (kv4)
**DeltaNet state:** 22.5MB fixed (does not grow)

**Total KV cache at various context lengths (fp16):**

| Context | Attention KV (15 layers) | DeltaNet State (45 layers) | Total KV |
|---------|--------------------------|---------------------------|----------|
| 8K | 480MB | 22.5MB | **503MB** |
| 32K | 1.92GB | 22.5MB | **1.94GB** |
| 64K | 3.84GB | 22.5MB | **3.86GB** |
| 128K | 7.68GB | 22.5MB | **7.70GB** |
| 262K | 15.36GB | 22.5MB | **15.38GB** |

---

## 4. Memory Budget — The Real Math

### Actual macOS Baseline (measured)

From system analysis on Whitebox:
- Wired (kernel): 2.2GB
- Hermes agent gateways: 1.6GB
- Sublime Text: 0.2GB (user preference)
- Obsidian: 0.25GB (user preference)
- tmux: 0.45GB
- System processes: ~3GB
- **Total macOS + apps: ~7.7GB**

LM Studio (1.3GB) and Claude Code instances (2GB) are temporary bloat — excluded from baseline.

### 35B-A3B via mmap on mlx-vlm.server

The model is loaded via mmap — 29.1GB file mapped into virtual address space, pages loaded on demand.

```
Physical RAM allocation (35B-A3B at 6-bit, 128K context, 2 agents):

  macOS + apps:              7.7GB
  Model (attention/routing): ~5GB   (always resident — accessed every token)
  Expert page cache:         ~3GB   (OS-managed, elastic)
  KV cache (2 × 128K fp16): 15.36GB
  ─────────────────────────────────
  Total:                     ~31GB  (tight but within 32GB)
```

The expert page cache is elastic: it grows when RAM is free and shrinks when KV cache needs space. The OS manages this automatically via LRU page eviction.

**Key insight:** MoE models are designed for this. Only 3B of 35B params are active per token. The rest are on disk, faulted in on demand. The model was built for hardware where the full weights don't fit in RAM.

| Component | RAM | Notes |
|-----------|-----|-------|
| macOS + apps | 7.7GB | Measured baseline |
| Model attention/routing | ~5GB | Always resident (accessed every token) |
| Expert page cache | variable | OS-managed, elastic, evicted under pressure |
| DeltaNet recurrent state | 0.02GB | Fixed size |
| **Subtotal (fixed)** | **~12.7GB** | |
| **Available for KV + expert cache** | **~19.3GB** | |

### KV Cache Math (35B-A3B)

| Context | Per agent (fp16) | Per agent (kv4) | 2 agents (fp16) | 2 agents (kv4) |
|---------|------------------|-----------------|-----------------|-----------------|
| 32K | 1.92GB | 480MB | 3.84GB | 960MB |
| 64K | 3.84GB | 960MB | 7.68GB | 1.92GB |
| 128K | 7.68GB | 1.92GB | 15.36GB | 3.84GB |
| 262K | 15.36GB | 3.84GB | 30.72GB | 7.68GB |

### What Fits at 128K Context

2 agents at 128K fp16: 15.36GB KV
Remaining for expert page cache: 19.3 - 15.36 = 3.94GB

3.94GB is enough for the most frequently accessed expert pages. Rarely-accessed experts page-fault from SSD — slower but functional. Performance degrades gracefully, not catastrophically.

With kv4 (when vllm-mlx supports it): 3.84GB KV, 15.46GB for expert cache. No contention at all.

### Context Feasibility Summary (35B-A3B)

| Context | 2 agents fp16 | 2 agents kv4 | 5 agents kv4 |
|---------|---------------|--------------|--------------|
| 32K | ✅ | ✅ | ✅ |
| 64K | ✅ | ✅ | ✅ |
| 128K | ✅ (3.9GB expert cache) | ✅ | ✅ |
| 262K | ❌ | ✅ | ❌ |
| 1M | ❌ | ❌ | ❌ |

### 27B Dense Memory Budget (Intensive Mode)

```
Physical RAM allocation (27B at 6-bit, 50K context, 1 agent):

  macOS + apps:              7.7GB
  Model (all weights):       22.8GB (fully resident — dense model, all params active)
  KV cache (50K fp16):       ~3GB
  ─────────────────────────────────
  Total:                     ~33.5GB → exceeds 32GB

  With kv4: KV = 750MB → Total = 31.2GB → fits
```

At 6-bit, the 27B is a tight fit. Max context with kv4: ~50K for 1 agent. Without kv4: ~32K.

### Context Length Feasibility (27B)

| Context | Without KVQ | With 4-bit KVQ | With 3-bit KVQ |
|---------|-------------|----------------|----------------|
| 32K | ✅ | ✅ | ✅ |
| 64K | ❌ | ✅ | ✅ |
| 128K | ❌ | ✅ | ✅ |
| 262K | ❌ | ❌ | ⚠️ (0.28GB headroom) |
| 1M | ❌ | ❌ | ❌ |

---

## 5. TurboQuant Feasibility (27B Intensive Mode)

TurboQuant compresses only the attention KV cache (15 layers), not the DeltaNet state (already compact).

| Context | Attention KV (fp16) | Attention KV (4-bit) | Attention KV (3-bit) | Total (4-bit) | Total (3-bit) |
|---------|---------------------|---------------------|---------------------|---------------|---------------|
| 32K | 1.92GB | 480MB | 360MB | 0.50GB | 0.38GB |
| 64K | 3.84GB | 960MB | 720MB | 0.98GB | 0.74GB |
| 128K | 7.68GB | 1.92GB | 1.44GB | 1.94GB | 1.46GB |
| 262K | 15.36GB | 3.84GB | 2.88GB | 3.86GB | 2.90GB |

**With TurboQuant 4-bit KV:**
- 128K: 1.94GB total KV → **fits** (1.24GB headroom)
- 262K: 3.86GB total KV → **doesn't fit** (exceeds 3.18GB budget)

**With TurboQuant 3-bit KV:**
- 128K: 1.46GB total KV → **fits** (1.72GB headroom)
- 262K: 2.90GB total KV → **fits** (0.28GB headroom — razor thin)

**262K is technically possible at 3-bit KV but requires:**
1. TurboQuant upstream fixes (RotatingKVCache + MoE support)
2. macOS memory usage lean (~5GB instead of 6GB)
3. No other memory pressure (no concurrent processes)
4. Acceptance of quality trade-off at 3-bit KV

**Recommendation:** Deploy 27B at 32K initially. When TurboQuant lands, enable 128K. 262K is a stretch goal that depends on upstream fixes and aggressive memory management.

---

## 6. DFlash — Speed Multiplier

DFlash-MLX v0.1.4.1 supports Qwen3.6-35B-A3B. Block diffusion speculative decoding:

- Draft model generates K candidates in one forward pass
- Target model verifies all K in one pass
- ~1.7x speedup for MoE models (confirmed by dflash-mlx benchmarks)
- Lossless — every emitted token is verified

**Estimated speeds on M1 Max:**

| Mode | Baseline | With DFlash |
|------|----------|-------------|
| 35B-A3B | 5-10 tok/s | 8-17 tok/s |
| 27B | 15-20 tok/s | limited benefit (dense) |

DFlash makes the 35B-A3B competitive with the 27B on speed while preserving the context/multi-agent advantages.

---

## 7. Flash-Context — SSD-Backed KV Pool

### Concept

For more agents than fit in RAM, excess agents' KV caches live on SSD. When an SSD-resident agent is called, its KV loads in ~500ms. The pool is transparent — hot agents in RAM, cold agents on SSD.

### Existing Implementations

**A) agent-memory (arxiv:2603.04428)**
- Open source: https://github.com/yshk-mxim/agent-memory
- Persists Q4 KV cache to disk in safetensors format
- Reload latency: ~577ms (warm disk), ~719ms (hot memory) at 4K context
- Evaluated on Gemma 3 12B, DeepSeek-Coder-V2 16B, Llama 3.1 8B
- Q4 quantization: -0.7% perplexity (Gemma), +2.8% (Llama), +3.0% (DeepSeek)
- Key insight: "multi-agent systems naturally interleave — one agent generates while the next one loads"
- **Directly applicable to our use case** (Boot + Kelk alternating)

**B) LMCache (NVMe offloading for vLLM)**
- Production-grade, used with vLLM on GPU servers
- Three-tier hierarchy: GPU HBM → CPU DRAM → NVMe SSD
- Not designed for Apple Silicon (uses CUDA)
- Concept is transferable, implementation is not

**C) SwapAttention / FlexGen**
- Academic papers on KV cache swap to CPU/SSD
- Not implemented for MLX

### How Flash-Context Would Work on Whitebox

```
Agent A generates (KV cache in RAM)
  ↓
Agent B needs to generate
  ↓
Agent A's KV cache written to SSD (Q4 quantized, ~1/4 size)
  ↓
Agent B's KV cache loaded from SSD (if previously cached)
  ↓
Agent B generates
  ↓
Agent A's KV cache reloaded from SSD when needed (~500ms-1s)
```

**Per-agent KV cache on disk (Q4 quantized):**

| Context | fp16 KV | Q4 KV on disk |
|---------|---------|---------------|
| 32K | 1.94GB | ~480MB |
| 128K | 7.70GB | ~1.94GB |
| 262K | 15.38GB | ~3.86GB |

Two agents at 128K: 2 × 1.94GB = 3.88GB on disk. Trivial.

**Reload time estimate (M1 Max SSD, ~3-4 GB/s):**
- 480MB at 4GB/s: ~120ms
- 1.94GB at 4GB/s: ~485ms

This is fast enough to be invisible — the other agent's generation phase takes 10-30 seconds, hiding the reload latency entirely.

**With 35B-A3B + kv4 + flash-context:**
- 5 agents hot in RAM at 128K (9.6GB)
- N agents cold on SSD (unlimited)
- Swap latency ~500ms, hidden by interleaving

### Flash-Context vs Flash-MoE: Architectural Parallel

| | Flash-MoE | Flash-Context |
|---|-----------|---------------|
| What's on SSD | Expert weights | KV cache blocks |
| What's in RAM | Attention + routing | Model weights + hot KV |
| Pages in/out per token | Expert FFN weights | KV blocks for attention |
| Benefit | Run models > RAM size | Run contexts > RAM size |
| Applicable to | MoE models only | Any model |
| Existing implementation | danveloper/flash-moe | agent-memory (research) |

### Status

- agent-memory exists (open source)
- Does not yet support Qwen3.6's hybrid GatedDeltaNet architecture
- Adaptation needed: only offload 15 attention layers' KV, keep 45 DeltaNet layers' recurrent state resident (22.5MB, trivial)
- Implementation path: Phase 3, after baseline deployment is stable

---

## 8. Infrastructure

### Default mode (35B-A3B)

| Component | Value |
|-----------|-------|
| Model | mlx-community/Qwen3.6-35B-A3B-6bit (29.1GB) |
| Server | mlx-vlm.server (mmap-based, kv4 when ready) |
| Port | :41961 |
| Context | 128K (fp16 KV) |
| Agents | Boot + Kelk (sequential requests) |
| Speed | 5-10 tok/s baseline, 8-17 with DFlash |

### Intensive mode (27B)

| Component | Value |
|-----------|-------|
| Model | mlx-community/Qwen3.6-27B-6bit (22.8GB) |
| Server | vllm-mlx (continuous batching) |
| Port | :41961 |
| Context | 32-50K (kv4) |
| Agents | Single session |
| Speed | 15-20 tok/s |

### Switching

```bash
# Switch to 35B-A3B (default, multi-agent)
factory model switch 35b

# Switch to 27B (intensive, single session)
factory model switch 27b
```

Script stops current server, starts target server. ~10-20s for 35B-A3B (mmap warmup), ~30-60s for 27B (full load).

---

## 9. Disk Space

| Item | Size |
|------|------|
| Current Gemma 4 models (to remove) | -26.6GB |
| Qwen3.6-35B-A3B 6-bit | +29.1GB |
| Qwen3.6-27B 6-bit (Phase 5) | +22.8GB |
| Net (after both) | +25.3GB |

Internal SSD: 460GB, 48GB free. After removing old models: 74.6GB free. Both new models: 51.9GB. Fits with 22.7GB remaining.

---

## 10. Deployment Roadmap

### Phase 1: Clean Up and Download (today)
- Remove Gemma 4 E4B models (6.6GB freed)
- Remove Gemma 4 26B-A4B split model (20GB freed)
- Download Qwen3.6-35B-A3B MLX 6-bit (29.1GB)
- Disk: 48GB free → 48 + 26.6 - 29.1 = 45.5GB remaining

### Phase 2: Test and Benchmark (today/tomorrow)
- Load model via mlx-vlm.server on :41988 (unused port)
- Verify: model loads without OOM (mmap handles 29GB on 32GB)
- Benchmark: tok/s at 8K, 32K, 64K, 128K context
- Measure: resident RSS, page fault rate, expert cache behavior
- Test Hermes tool-use compatibility (function calling format)
- Test Matrix chat template

### Phase 3: Deploy as Default (after benchmarks)
- Update com.bootindustries.mlx-vlm-boot.plist for Qwen3.6-35B-A3B on :41961
- Update Boot and Kelk Hermes configs to route to :41961
- Decommission :41962 (Kelk E4B) and :41966 (flash-moe 26B)
- Update AGENTS.md, ports.csv, wrapper scripts

### Phase 4: DFlash (when baseline is stable)
- Install dflash-mlx
- Download draft model for Qwen3.6-35B-A3B
- Benchmark: baseline vs DFlash tok/s
- Expected: 1.7x speedup for MoE → 8-17 tok/s

### Phase 5: Intensive Mode (optional)
- Download Qwen3.6-27B MLX 6-bit (22.8GB)
- Create model switching script
- Test: switch between 35B-A3B and 27B
- Deploy as on-demand option

### Phase 6: Flash-Context (future)
- Adapt agent-memory for Qwen3.6-35B-A3B hybrid architecture
- Enable SSD-backed KV pool for 5+ agents
- Target: 262K+ context with kv4 + SSD offloading

---

## 11. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| mmap page faults at 128K slow inference | Medium | Medium | kv4 reduces KV, freeing expert cache space; flash-moe adaptation |
| Qwen3.6 tool-use format incompatible with Hermes | Low | High | Test in Phase 2 before deployment |
| 5-10 tok/s too slow for agent workloads | Medium | Medium | DFlash brings to 8-17; E4B was 30 but much dumber |
| mmap causes OOM under concurrent load | Low | High | Monitor RSS; OS handles pressure via page eviction |
| DFlash memory leak (FCT068) not fixed | Low | Low | Benchmark before deploying; skip if unstable |
| 27B intensive mode switching is too slow (30-60s) | Low | Low | Acceptable for planned intensive sessions |
| TurboQuant upstream fixes delayed | Medium | Low | fp16 KV works at 128K; kv4 is optimization, not blocker |
| vllm-mlx doesn't support Qwen3.6-27B | Low | High | Fall back to mlx-vlm.server (lose continuous batching) |
| Continuous batching degrades per-agent tok/s | Low | Medium | Benchmark concurrent load; fall back to 2 instances if needed |
| Flash-context never implemented for Qwen3.6 | Medium | Low | 128K via TurboQuant is sufficient for most tasks |

---

## 12. References

- [1] FCT068 — Inference Architecture Options and DFlash Research (2026-04-15)
- [2] FCT070 — MLX Inference Optimization: KV Cache + Prefill Tuning (2026-04-23)
- [3] FCT073 — MLX Inference Optimization Curriculum (2026-04-26)
- [4] Qwen3.6-35B-A3B — https://huggingface.co/Qwen/Qwen3.6-35B-A3B
- [5] mlx-community/Qwen3.6-35B-A3B-6bit — https://huggingface.co/mlx-community/Qwen3.6-35B-A3B-6bit
- [6] vllm-mlx — https://github.com/waybarrios/vllm-mlx
- [7] agent-memory: Persistent Q4 KV Cache — arXiv:2603.04428
- [8] agent-memory GitHub — https://github.com/yshk-mxim/agent-memory
- [9] danveloper/flash-moe — https://github.com/danveloper/flash-moe
- [10] DFlash-MLX — https://github.com/bstnxbt/dflash-mlx (v0.1.4.1)
- [11] TurboQuant KV cache — mlx-lm PR #1059, arXiv:2504.19874
- [12] LMCache / NVMe KV offloading — Spheron (2026)
- [13] BenchLM: Qwen3.6-27B vs Qwen3.6-35B-A3B — https://benchlm.ai
- [14] Contra Collective: llama.cpp vs MLX vs Ollama vs vLLM (2026)
- [15] famstack: Same Engine, 37% Slower: MLX vs llama.cpp on Apple Silicon
