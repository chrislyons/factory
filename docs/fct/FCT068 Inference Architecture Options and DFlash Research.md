# FCT068 Inference Architecture Options and DFlash Research

**Status:** Research / Parked
**Date:** 2026-04-15
**Related:** FCT054 (local E4B consolidation), FCT067 (native E2EE, Nous Mimo Pro)

---

## 1. Current Architecture (Stable as of FCT068)

| Port | Model | Backend | Resident RAM | Serves |
|------|-------|---------|-------------|--------|
| :41961 | gemma-4-e4b-it-6bit | mlx_vlm | ~7.3GB (unified) | Boot primary |
| :41962 | gemma-4-e4b-it-6bit | mlx_vlm | ~7.3GB (unified) | Kelk primary |
| :41966 | gemma-4-26b-a4b-it-6bit | flash-moe | ~26MB (SSD streaming) | Shared aux (Boot + Kelk) |

**Total inference RAM:** ~14.6GB + 26MB. Stable at ~22GB system-wide on M1 Max 32GB.

**Startup:** `factory-startup.sh` orchestrator sequences Boot E4B → Kelk E4B → flash-moe 26B → Hermes gateways. Survives reboots.

---

## 2. Option A — Flash-MoE Primary + E2B Sidecar

**Concept:** Promote the 26B to primary inference for both agents. Demote to a smaller model (E2B, ~5.2GB) for low-complexity auxiliary tasks (approvals, MCP routing, memory flushes).

| Port | Model | Backend | Resident RAM | Serves |
|------|-------|---------|-------------|--------|
| :41966 | 26B-A4B | flash-moe | ~3GB | Boot primary |
| :41967 | 26B-A4B | flash-moe | ~3GB | Kelk primary |
| :41961 | E2B | mlx_vlm | ~5.2GB | Boot sidecar |
| :41962 | E2B | mlx_vlm | ~5.2GB | Kelk sidecar |

**Total:** ~16.4GB + 4GB macOS = ~20.4GB. **11.6GB headroom.**

**Pros:**
- Every response gets 26B quality — fewer errors, fewer retries
- Independent 26B instances per agent (no serialization)
- E2B is overpowered for yes/no classification tasks
- Expert files are mmap'd — OS page cache deduplicates across both flash-moe instances

**Cons:**
- 5.4 tok/s as primary is slow (vs ~15 tok/s E4B)
- Two flash-moe instances competing for NVMe bandwidth under concurrent load
- SSD expert streaming = random-access I/O; under simultaneous generation, both agents degrade
- Boot's autonomous loops and cron jobs will be noticeably slower

**Risk:** SSD contention under concurrent load. Needs benchmarking before committing.

---

## 3. Option B — 2x E4B + Shared Flash-MoE (Current)

This is the current architecture. Proven stable.

**Pros:**
- E4B at ~15 tok/s is responsive for interactive use
- 26B quality available for complex auxiliary tasks
- No SSD contention (E4B is fully in unified memory)
- Both agents fully independent

**Cons:**
- 14.6GB for two copies of the same model is expensive on 32GB
- ~7GB headroom (comfortable but not generous)
- 26B is serialized (single shared instance)

---

## 4. Option C — DFlash Speculative Decoding (Qwen3.5)

**Discovery:** [bstnxbt/dflash-mlx](https://github.com/bstnxbt/dflash-mlx) — lossless speculative decoding using block diffusion drafting. A ~1B draft model generates 16 tokens in parallel, the target model verifies in one pass.

### Benchmarks (M5 Max 64GB, MLX 0.31.1)

| Model | Baseline | DFlash | Speedup |
|-------|----------|--------|---------|
| Qwen3.5-4B | 53 tok/s | 197 tok/s | 3.69x |
| Qwen3.5-9B | 31 tok/s | 127 tok/s | 4.10x |
| Qwen3.5-27B-4bit | 33 tok/s | 66 tok/s | 1.98x |
| Qwen3.5-35B-A3B-4bit (MoE) | 140 tok/s | 243 tok/s | 1.74x |

### Key Technical Details

- `dflash-serve` is a drop-in replacement for `mlx_lm.server` (OpenAI-compatible API)
- Lossless — every emitted token is verified against the target model
- Tape-replay rollback for recurrent architectures (GatedDeltaNet)
- Custom Metal kernels for long-context verify
- ~89% acceptance rate across all benchmarks

### Applicability to Whitebox

**Blocker: Gemma not supported.** Only Qwen3.5 models have DFlash drafts. Our Gemma 4 E4B and 26B-A4B cannot use dflash-mlx.

**If we switched to Qwen3.5:** The MoE variant `Qwen3.5-35B-A3B-4bit` is particularly interesting:
- 35B total params, 3B active (MoE) — low resident memory
- 140 tok/s baseline on M5 Max → estimated ~70 tok/s on M1 Max (half memory bandwidth)
- With DFlash: ~120 tok/s estimated on M1 Max
- Quality comparable to Qwen3.5-27B at fraction of the compute

**Concerns:**
- M1 Max has 400 GB/s memory bandwidth (vs 800 GB/s M5 Max) — all benchmarks need halving
- 32GB total RAM constrains how many models can coexist
- Qwen3.5 tool-use format compatibility with Hermes needs validation
- Memory leak reported in `dflash-serve` (GitHub issue open)

### What Would Need to Change

1. Download Qwen3.5 target + DFlash draft models
2. Validate Hermes tool-use compatibility (function calling, structured output)
3. Benchmark on M1 Max 32GB (actual hardware, not extrapolated)
4. Update Hermes configs: `model.default`, `base_url`, `custom_providers`
5. Update flash-moe-server.py or replace with `dflash-serve`
6. Update SOUL.md, skills, ports.csv

---

## 5. Recommendation

**Stay on current architecture (Option B) for now.** It's stable, well-tested, and the reboot resilience work in this sprint has made it production-ready.

**Park Option A** (flash-moe primary) for when we need the headroom — e.g., if a third local agent needs inference capacity.

**Park Option C** (DFlash) pending:
- Gemma DFlash draft model availability (watch HuggingFace z-lab org)
- Or a deliberate decision to switch to Qwen3.5
- Memory leak fix in `dflash-serve`

**Revisit when:** New model releases, hardware upgrade (M-series with more RAM), or if current 5.4 tok/s aux speed becomes a bottleneck.

---

## References

- [1] Chen, J., Liang, Y., Liu, Z. "DFlash: Block Diffusion for Flash Speculative Decoding." arXiv:2602.06036, 2026.
- [2] bstnxbt/dflash-mlx. GitHub. https://github.com/bstnxbt/dflash-mlx
- [3] FCT054 — Local E4B Consolidation (2026-04-08)
- [4] FCT067 — Native E2EE, Nous Mimo Pro Migration (2026-04-14)
