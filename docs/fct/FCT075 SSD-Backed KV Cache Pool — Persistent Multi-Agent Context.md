# FCT075 SSD-Backed KV Cache Pool - Persistent Multi-Agent Context

**Date:** 2026-04-26
**Status:** Research complete - implementation pending
**Machine:** Mac Studio M1 Max (32GB, 400 GB/s)
**Related:** FCT074 (dual-model architecture)

## 1. Problem

32GB RAM limits agents x context length. Every agent's KV cache competes for the same RAM pool alongside model weights and macOS overhead.

With Ornstein3.6-35B-A3B (FCT074):
- Model resident: ~5GB
- macOS: ~7.7GB
- Available for KV: ~19GB

Two agents at 128K fp16: 15.36GB. Fits. Five agents at 128K: 38.4GB. Does not fit.

The dream: every agent's full conversation history persisted to disk, loaded on demand, zero re-prefill cost. Agents can have unlimited context. The system supports N agents beyond RAM capacity.

## 2. Existing Work

This is NOT new ground. Three independent research efforts have solved this.

### 2.1 agent-memory (KEY FINDING)

GitHub: https://github.com/yshk-mxim/agent-memory
Paper: arXiv:2603.04428 "Agent Memory Below the Prompt"
Author: Yakov Pyotr Shkolnikov (Feb 2026)
License: MIT

A working implementation built specifically for Apple Silicon that does exactly what we need.

**Architecture: Three-tier caching**
- Hot Cache: KV in GPU/RAM (immediate access)
- Warm Cache: Metadata in RAM (rapid reloading)
- Cold Cache: Q4-quantized KV persisted as safetensors on disk

**Performance (Apple Silicon):**
- Gemma 3 12B at 4K context: 27.3x TTFT speedup (15.7s cold -> 0.58s warm)
- Llama 3.1 8B at 4K context: 35.3x TTFT speedup
- DeepSeek-Coder-V2 at 4K context: 14.6x TTFT speedup
- At 32K context: up to 136x speedup
- Q4 quantization: only ~3% perplexity impact

**Key features:**
- Built on mlx-lm 0.30.4
- OpenAI-compatible API (port 8000)
- Block Pool Batch Engine for memory budgeting
- Concurrent scheduler (batch=2): interleaves chunked prefill with token-by-token decoding
- Disk save: synchronous, ~50-100ms stall once per completed request

**Configuration:**
- SEMANTIC_MLX_CACHE_BUDGET_MB: max GPU memory for KV caches (default 8192)
- SEMANTIC_MLX_MAX_BATCH_SIZE: max concurrent sequences (default 2)

**Tested models:** Gemma 3 12B, Llama 3.1 8B, DeepSeek-Coder-V2 (standard transformers)

**NOT tested:** Qwen3.6 hybrid architecture (GatedDeltaNet + attention)

### 2.2 KVSwap (arXiv:2511.11907, ACM MobiSys 2026)

"KVSwap: Disk-aware KV Cache Offloading for Long-Context On-device Inference"
Authors: Huawei Zhang, Chunwei Xia, Zheng Wang

Framework for disk-based KV cache offloading on mobile/embedded devices.

Key innovations:
- Full cache disk storage (entire KV on disk, not just overflow)
- Compact in-memory metadata for tracking
- Predictive preloading (predicts which KV entries needed next)
- Computation/I/O overlap (hides disk latency behind compute)
- Orchestrated read patterns (aligned with flash storage characteristics)

Designed for unified memory architectures (Apple Silicon, mobile SoCs).

### 2.3 llm-d (llm-d.ai)

Production-grade KV cache offloading to any filesystem.
Designed for data centers (Kubernetes, shared storage).
Not directly applicable to our single-machine setup, but architecturally instructive.

## 3. Adaptation Required

agent-memory does 90% of what we need. The remaining 10% is Qwen3.6-specific.

### 3.1 Hybrid Architecture Challenge

Qwen3.6-35B-A3B uses:
- 45 GatedDeltaNet layers: fixed recurrent state (22.5MB total), NOT KV cache
- 15 Gated Attention layers: standard KV cache (grows with context)

agent-memory assumes all layers have KV cache. For Qwen3.6:
- Only 15 of 60 layers need KV persistence
- GatedDeltaNet recurrent state is fixed-size, stays in RAM (22.5MB, negligible)
- Q4 KV serialization must handle partial-layer persistence

Adaptation:
- Modify block pool to only allocate KV storage for attention layers
- Skip GatedDeltaNet layers in save/load path
- Recurrent state stays in RAM always

### 3.2 MoE Compatibility

The 35B-A3B is MoE. agent-memory was tested on dense models and one MoE (DeepSeek-Coder-V2). KV cache structure is identical for MoE and dense - only FFN layers differ (expert routing). Attention layers that generate KV cache work identically.

agent-memory should work for 35B-A3B attention layers without MoE-specific modification.

### 3.3 Serving Backend Integration

Three options:

**Option A:** Use agent-memory's server directly (port 8000)
- Simplest. Point Hermes at it.
- Problem: agent-memory uses mlx-lm (text-only), not mlx-vlm (multimodal).
- The 35B-A3B is multimodal. Vision would not work.

**Option B:** Fork agent-memory, add vision support
- More work but complete.
- Integrates mlx-vlm with agent-memory's KV persistence.

**Option C:** Extract agent-memory's KV persistence layer, integrate into vllm-mlx
- Most work, best long-term result.
- Continuous batching + KV persistence + vision.

Recommendation: Phase 1 uses Option A (text-only, fast validation). Phase 2 moves to Option B or C.

## 4. Memory Budget Modeling

### 4.1 Q4 KV Storage on Disk

fp16 KV at 128K (15 attention layers): 15.36GB per agent
Q4 KV at 128K: 15.36 / 4 = 3.84GB per agent on disk

Disk capacity (1TB external):
- 100 agents at 128K Q4: 384GB (fits)
- 260 agents at 128K Q4: ~1TB (fills the drive)

### 4.2 RAM Budget with agent-memory

Same ~19GB KV budget. Hot agents in RAM, cold on disk.

Optimal config:
- 5 agents hot at 128K kv4 in RAM: 9.6GB (9.4GB headroom)
- N agents cold at 128K Q4 on disk: unlimited
- Swap time per agent: 3.84GB / 3.5GB/s = 1.1 seconds

### 4.3 Real-World Agent Workload

Factory Whitebox scenario:
- Kelk (personal assistant): HOT always (interactive, needs instant response)
- Boot (operations): WARM (loaded on demand, 1.1s swap acceptable for cron)
- IG88 (trading): cloud-only, no local KV
- Agent 4 (future): COLD (loaded when called)
- Agent 5 (future): COLD (loaded when called)

Kelk at 128K kv4: 1.92GB (always hot)
Boot at 64K kv4: 0.96GB (loaded when active)
Total hot: 2.88GB (leaves 16.12GB for burst agents)

Swap latency (1.1s) is hidden by:
1. Natural gaps between agent requests
2. Predictive preloading (KVSwap-style)
3. Concurrent scheduler (interleave prefill with decode)

## 5. SSD Write Endurance

From community discussion: writes accelerate SSD wear.

Risk:
- KV cache updated every token (new K,V appended)
- At 30 tok/s: 30 writes/second/agent x 60KB = ~1.8MB/s
- Daily write: ~155GB/agent/day

Internal SSD (Apple NVMe): rated ~150-300 TBW
- At 155GB/day: 1000-2000 days (3-6 years)
- Acceptable

Mitigation:
- agent-memory writes at session end, not every token (batch saves)
- Reduces daily writes by orders of magnitude
- Only active agent sessions generate disk writes

## 6. Implementation Plan

### Phase 1: Evaluation (1-2 days)

1. Clone agent-memory repo
2. Install deps (mlx-lm 0.30.4)
3. Test with Gemma 3 12B to verify functionality
4. Attempt to load Ornstein3.6-35B-A3B
5. Document what works, what breaks

### Phase 2: Adaptation (3-5 days)

If Qwen3.6 hybrid not supported:
1. Fork agent-memory
2. Modify block pool for partial-layer persistence (15 attention layers only)
3. Skip GatedDeltaNet in save/load path
4. Test at 32K, 64K, 128K contexts
5. Benchmark TTFT speedup (cold vs warm)

### Phase 3: Integration (2-3 days)

1. Point Hermes Boot + Kelk at agent-memory server
2. Test tool-use compatibility
3. Test multi-agent concurrent requests
4. Measure behavior under load

### Phase 4: Production (1-2 days)

1. Create launchd plist for agent-memory server
2. Update factory-startup.sh, Hermes configs, CLAUDE.md
3. Deploy and monitor

### Phase 5: Optimization (ongoing)

1. KVSwap-style predictive preloading
2. Computation/I/O overlap
3. Integration with vllm-mlx (when kv4 support arrives)
4. Flash-moe + agent-memory combined optimization

## 7. Decision Matrix

| Approach | Agents at 128K | Swap Latency | Complexity | Status |
|----------|---------------|--------------|------------|--------|
| Current (fp16, mmap) | 2 | N/A (all hot) | Low | Ready (FCT074) |
| kv4 (vllm-mlx) | 5 | N/A (all hot) | Low | Blocked upstream |
| agent-memory (Q4 persist) | 20+ on disk | ~1.1s | Medium | Exists, needs adaptation |
| KVSwap (predictive) | 20+ on disk | ~0.5s | High | Research only |

Progression: FCT074 (now) -> agent-memory (Phase 1-2) -> KVSwap optimization (Phase 5).

## 8. Conclusion

SSD-backed KV cache is NOT a dead end. It is proven technology (agent-memory, KVSwap, llm-d) that has not been adapted for Qwen3.6 hybrid architecture on Apple Silicon.

agent-memory is the key finding: a working, open-source, MIT-licensed implementation built for Apple Silicon that achieves 27-136x TTFT speedup by persisting Q4 KV caches to disk.

The adaptation is Qwen3.6-specific: handling the hybrid GatedDeltaNet + attention architecture where only 15 of 60 layers need KV persistence. This is manageable - the core infrastructure is already built.

This unlocks unlimited agents x unlimited context, bounded only by disk space. The 1TB external drive can hold ~260 agent sessions at 128K Q4 KV each.
