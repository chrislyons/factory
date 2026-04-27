# FCT073 MLX Inference Optimization Curriculum — Whitebox M1 Max

**Date:** 2026-04-26
**Status:** Planning / Active Curriculum
**Machine:** Mac Studio M1 Max (32GB, 400 GB/s bandwidth)
**Related:** FCT067 (SSD expert streaming), FCT068 (DFlash research), FCT070 (KV cache + prefill tuning)

---

## 1. Current Baseline

| Port | Model | Backend | tok/s | RAM |
|------|-------|---------|-------|-----|
| :41961 | Gemma 4 E4B 6-bit | mlx_vlm | ~30 | ~7.5GB |
| :41962 | Gemma 4 E4B 6-bit | mlx_vlm | ~30 | ~7.5GB |
| :41966 | Gemma 4 26B-A4B 6-bit | flash-moe (Rust) | ~5.4 | ~3GB resident |
| — | macOS baseline | — | — | ~4-5GB |

**Steady-state:** ~22GB used, ~10GB free.
**Prefill:** 4.8-6.2x improvement from `--prefill-step-size 2048` (FCT070).
**KV quantization:** Blocked on Gemma 4 (RotatingKVCache NYI + TurboQuant MoE bug).

## 2. What CUDA Techniques Transfer to Apple Silicon

The GPU inference optimization tweet lists a learning path built around NVIDIA tooling.
Here's what actually maps to MLX on Metal:

| CUDA Concept | MLX/Metal Equivalent | Status |
|-------------|---------------------|--------|
| PagedAttention / KV cache mgmt | RotatingKVCache, QuantizedKVCache | **Partially blocked** (FCT070) |
| Prefix caching | mlx-lm prompt caching, vllm-mlx content-based prefix cache | Available in mlx-lm, not mlx-vlm |
| Continuous batching | vllm-mlx (community), mlx-lm concurrent decode | vllm-mlx exists but untested here |
| Speculative decoding (EAGLE/MTP) | MTP layers (Qwen3.6 native), DFlash-MLX | **Qwen3.6 only** |
| MoE kernel optimization | flash-moe Rust binary (SSD expert streaming) | Active — our custom solution |
| FP8/FP4 quantization | 4-bit/6-bit MLX quantization (GPTQ, Unsloth Dynamic) | Active |
| FlashAttention | Metal-native fused attention in MLX core | Baked into mlx framework |
| CUDA graphs | MLX lazy evaluation + Metal command buffers | Transparent (framework-level) |
| Triton custom kernels | Metal Shading Language (MSL) custom kernels | DFlash-MLX uses verify_qmm Metal kernel |
| Nsight profiling | Metal System Trace, Instruments.app | Manual — need to instrument |

## 3. Optimization Curriculum

### Phase 0: Measurement Infrastructure (1-2 days)
**Goal:** Stop guessing. Build a benchmark harness.

- [ ] Create `scripts/mlx-bench.sh` — automated tok/s + TTFT measurement
  - Single-turn prompt (fixed, ~500 tokens) for reproducibility
  - Measure: prefill TTFT, generation tok/s, peak RSS
  - Test both cold (fresh load) and warm (cached) states
- [ ] Capture baseline numbers for all three servers (:41961, :41962, :41966)
- [ ] Document M1 Max specifics: 400 GB/s bandwidth, 32-core GPU, unified memory topology

**Why first:** Every subsequent phase needs before/after numbers. FCT070's prefill improvement (4.8x) was only discoverable because we measured.

### Phase 1: Model Selection & Quantization Audit (1 week)
**Goal:** Determine if Gemma 4 is still the right choice, and if 6-bit is optimal.

#### 1a. Qwen3.6-35B-A3B Evaluation

Qwen3.6-35B-A3B is the most interesting candidate for Whitebox:
- 35B total params, **3B active** (MoE) — low per-token compute
- Multimodal (vision + text) — same as Gemma 4
- 262K native context, extensible to 1M
- MLX 8-bit available (mlx-community/Qwen3.6-35B-A3B-8bit)
- Unsloth 6-bit available (unsloth/Qwen3.6-27B-UD-MLX-6bit for dense variant)
- **DFlash-MLX v0.1.4.1 supports it** (draft model on HuggingFace)
- MTP layers built-in (multi-token prediction, no external drafter needed)
- Benchmarks: SWE-bench Verified 73.4, TerminalBench 51.5 — competitive with Gemma 4 31B

**Estimated fit on M1 Max 32GB:**
- 4-bit: ~18GB model, ~3B active per token → likely 50-80 tok/s
- 6-bit: ~24GB model → tight with 2 E4B instances, may need to drop one
- 8-bit: ~35GB → won't fit alongside anything else

**Action items:**
- [ ] Download Qwen3.6-35B-A3B MLX 4-bit and 8-bit
- [ ] Benchmark on :41988 (IG-88 port, currently unused)
- [ ] Test Hermes tool-use compatibility (function calling format)
- [ ] Test Matrix integration (chat template, E2EE compatibility)
- [ ] Compare quality vs Gemma 4 E4B on representative agent tasks

#### 1b. Gemma 4 Quantization Re-evaluation

Current: 6-bit for both E4B and 26B-A4B.
- [ ] Benchmark E4B at 4-bit (if MLX quantization available)
- [ ] Check if Unsloth has Gemma 4 E4B at 4-bit with acceptable quality
- [ ] Measure: does 4-bit E4B fit two instances + 26B aux comfortably?

#### 1c. Model Decision Matrix

| Option | Model | Bits | RAM | tok/s est. | DFlash? | Fits 2 agents? |
|--------|-------|------|-----|------------|---------|----------------|
| A (status quo) | Gemma 4 E4B x2 + 26B-A4B | 6-bit | ~18GB | 30 + 5.4 | No | Yes |
| B | Qwen3.6-35B-A3B + E4B aux | 4-bit | ~26GB | 60-80 + 30 | Yes | Tight |
| C | Qwen3.6-35B-A3B x2 | 4-bit | ~36GB | 60-80 | Yes | **No — exceeds 32GB** |
| D | Qwen3.6-35B-A3B (shared) + 26B-A4B | 4-bit | ~21GB | 60-80 + 5.4 | Yes | Yes (shared) |

**Option D is most promising:** Replace both E4B instances with a single shared Qwen3.6-35B-A3B. The MoE architecture means 3B active params — fast enough for interactive use. DFlash could push it to 100+ tok/s. Keep flash-moe 26B for aux.

### Phase 2: Speculative Decoding (1-2 weeks)
**Goal:** Get DFlash-MLX running for whichever model we select.

#### 2a. DFlash-MLX Setup

If we go with Qwen3.6-35B-A3B:
- [ ] Install dflash-mlx (pip install dflash-mlx)
- [ ] Download draft model for Qwen3.6-35B-A3B
- [ ] Run `dflash-serve` as drop-in replacement for mlx_vlm.server
- [ ] Benchmark: baseline vs DFlash tok/s on M1 Max (expect ~1.7-2x for MoE)
- [ ] Test streaming mode (dflash-mlx v0.1.4 added streaming token yield)
- [ ] Monitor memory leak (reported in FCT068 — check if v0.1.4 fixed it)

#### 2b. MTP vs DFlash Comparison

Qwen3.6 has built-in MTP (multi-token prediction) layers. These are a simpler form of speculative decoding — the model itself predicts multiple tokens, then verifies.
- [ ] Benchmark MTP-only mode vs DFlash mode
- [ ] Reddit reports MTP gives 4-5 token acceptance vs DFlash's ~2 token acceptance on 27B
- [ ] DFlash may be better for the 35B-A3B MoE variant (different architecture)

#### 2c. Gemma 4 Path (Fallback)

If we stay on Gemma 4:
- [ ] Watch HuggingFace z-lab org for Gemma 4 DFlash draft models
- [ ] Watch mlx-lm issue for MTP support on Gemma 4
- [ ] No speculative decoding path currently available for Gemma 4

### Phase 3: KV Cache Optimization (ongoing — blocked upstream)
**Goal:** Reduce KV memory footprint to enable longer contexts and more concurrent sessions.

**Current blocker:** Two upstream bugs prevent ANY KV quantization on Gemma 4 (FCT070).

#### 3a. Monitor Upstream Fixes
- [ ] RotatingKVCache.to_quantized() — mlx-lm cache.py:550
- [ ] TurboQuant MoE support — mlx-vlm issue #904
- [ ] When either fixes: deploy `--kv-bits 4 --kv-quant-scheme turboquant`

#### 3b. If Switching to Qwen3.6

Qwen3.6 uses GatedDeltaNet (recurrent) for 3/4 of its layers, with standard attention only in 1/4. This means:
- KV cache is much smaller (recurrent state vs full KV)
- KV quantization may work out-of-box (no RotatingKVCache dependency)
- TurboQuant compatibility needs testing

### Phase 4: Serving Infrastructure (1 week)
**Goal:** Get the most out of the serving layer itself.

#### 4a. vllm-mlx Evaluation

vllm-mlx (arxiv:2601.19139) claims 21-87% higher throughput than llama.cpp on Apple Silicon.
- [ ] Install and test vllm-mlx on Whitebox
- [ ] Benchmark vs mlx_vlm.server for our models
- [ ] Test continuous batching (4.3x aggregate throughput at 16 concurrent requests)
- [ ] Test content-based prefix caching (28x speedup on repeated images)
- [ ] Evaluate: is it stable enough for production agent serving?

#### 4b. flash-moe Expert Tuning

The flash-moe Rust binary has unexplored optimization surface:
- [ ] Run `flash-moe generate --calibrate 1000` to build co-occurrence predictor
- [ ] Add `--warm-set` to launch config (pre-load frequent expert combinations)
- [ ] Benchmark tok/s before/after calibration
- [ ] Investigate: can we increase tok/s from 5.4? What's the bottleneck — SSD I/O or compute?

#### 4c. Prefix Caching for Agent Workloads

Agent conversations have long system prompts + tool schemas that repeat every turn.
- [ ] Investigate if mlx_vlm.server supports prompt caching (mlx-lm does)
- [ ] If not, evaluate switching to mlx-lm.server for text-only agents (Boot, Kelk don't use vision often)
- [ ] Potential: 2-3x TTFT improvement on turn 2+ of a conversation

### Phase 5: Advanced (When Ready)
**Goal:** Custom Metal kernels and profiling for the last 2x.

#### 5a. Metal System Trace Profiling
- [ ] Profile mlx_vlm.server with Instruments.app
- [ ] Identify: is decode bottlenecked by attention, FFN, or memory bandwidth?
- [ ] For flash-moe: profile SSD I/O patterns, page cache hit rates

#### 5b. Custom Kernel Exploration (Research Only)
- [ ] Study DFlash-MLX's verify_qmm.py — custom int4 quantized matmul Metal kernel
- [ ] Study how flash-moe does per-expert pread vs mmap
- [ ] Evaluate: is there a fused dequant-matmul kernel opportunity for KV cache?

#### 5c. Quantization Frontier
- [ ] Monitor TurboQuant (PolarQuant) progress — 3-bit KV with 4.6x compression
- [ ] Evaluate GGUF quantization for specific models (llama.cpp Metal sometimes wins)
- [ ] Track Unsloth Dynamic 2.0 quantization improvements

## 4. Priority Order

```
Phase 0 (measurement)     ← Do first. Everything depends on this.
Phase 1a (Qwen3.6 eval)  ← Highest impact. DFlash + MoE is the big win.
Phase 2a (DFlash-MLX)     ← If Qwen3.6 looks good, this is the multiplier.
Phase 4b (flash-moe tune) ← Low effort, may improve aux from 5.4 → 7+ tok/s
Phase 4c (prefix caching) ← Free TTFT improvement if available
Phase 3 (KV quant)        ← Blocked upstream. Monitor.
Phase 1b (Gemma 4 4-bit)  ← Only if staying on Gemma 4
Phase 4a (vllm-mlx)       ← Evaluate but may not be worth switching
Phase 5 (advanced)        ← When everything else is done
```

## 5. Key Decision Points

**Decision 1: Stay on Gemma 4 or switch to Qwen3.6?**
- Trigger: Phase 1a benchmark results
- If Qwen3.6-35B-A3B at 4-bit gives 50+ tok/s with good tool-use → switch
- If tool-use is broken or quality is worse → stay on Gemma 4

**Decision 2: Single shared model or two independent instances?**
- Trigger: Phase 1a memory measurements
- If Qwen3.6 4-bit + flash-moe 26B fits in 32GB → Option D (shared Qwen + aux)
- If not → keep current topology, add DFlash for Gemma 4 when available

**Decision 3: DFlash or MTP?**
- Trigger: Phase 2b comparison
- MTP is simpler (built-in), DFlash is more powerful (custom Metal kernels)
- Use whichever gives higher acceptance rate on our hardware

## 6. References

- [1] FCT067 — SSD Expert Streaming, E2EE Migration (2026-04-14)
- [2] FCT068 — Inference Architecture Options and DFlash Research (2026-04-15)
- [3] FCT070 — MLX Inference Optimization: KV Cache + Prefill Tuning (2026-04-23)
- [4] bstnxbt/dflash-mlx — https://github.com/bstnxbt/dflash-mlx (v0.1.4.1, 2026-04-18)
- [5] vllm-mlx paper — arXiv:2601.19139v2 (2026-01-28)
- [6] TurboQuant KV cache — mlx-lm PR #1059, ICLR 2026 paper arXiv:2504.19874
- [7] Qwen3.6-35B-A3B — https://huggingface.co/mlx-community/Qwen3.6-35B-A3B-8bit
- [8] mlx-vlm issue #904 — TurboQuant broken on Gemma 4 MoE
- [9] mlx-lm cache.py:550 — RotatingKVCache.to_quantized() NotImplementedError
