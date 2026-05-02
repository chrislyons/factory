# FCT092 — Auxiliary Inference Tier: E2B-SABER on :41963

**Date:** 2026-05-02
**Status:** Production (live)
**Supersedes:** FCT091 §"Nemostein dormant fallback" — Nemostein plist now `.deprecated`
**Depends on:** FCT078 (mlx-lm wrapper), FCT091 (E4B-SABER production selection)

---

## Summary

A third MLX inference instance has been added to the production tier on `:41963`, serving **Gemma-4-E2B-SABER-MLX-6bit (DJLougen rev)** through the same FCT078 wrapper used by Boot/Kelk. This is the **Coord aux tier** — a fast, lightweight auxiliary worker callable by Boot, Kelk, or any Hermes aux slot for bounded-scope subroutines (conversation compaction, summarization, classification, intent triage).

The Nemostein hot-swap fallback on `:41966` is mutually exclusive with this tier on memory grounds (32 GB unified) and has been deprecated. Hot-swap recipe is preserved below for the hypothetical case of a heavy-reasoning workload that justifies trading away the Coord tier.

---

## Topology

| Port | Model | Tier | RSS | Wired | Use |
|------|-------|------|-----|-------|-----|
| :41961 | Gemma-4-E4B-SABER-MLX-6bit | Primary | ~6 GB | ~10 GB | Boot agentic loop |
| :41962 | Gemma-4-E4B-SABER-MLX-6bit | Primary | ~6 GB | ~10 GB | Kelk agentic loop |
| :41963 | Gemma-4-E2B-SABER-MLX-6bit (DJLougen) | Aux | ~3 GB | ~6 GB | Coord aux subroutines |
| :41966 | DEPRECATED (was Nemostein 30B/3B) | — | — | — | Hot-swap recipe in §Rollback |

**Total wired peak under concurrent load:** ~26 GB. Headroom for OS + Hermes + MCP: ~6 GB. Tight but stable; matches the bench profile (free=3.6 GB at end of agentic suite).

All three instances run through `scripts/mlx-lm-factory-wrapper.py`, which:
- Sets `mx.set_memory_limit(10 GB)` and `mx.set_wired_limit(10 GB)` per process
- Patches `mlx_lm.models.cache.make_prompt_cache` with `QuantizedKVCache(group_size=64, bits=8)` *before* `mlx_lm.server.main()` initializes (the only working KV quant for Gemma 4 — server `--kv-bits` flags are broken upstream, FCT070).

---

## Why E2B-SABER (DJLougen rev)

The earlier E2B test (different SABER rev) failed agentic discipline — echoed prompts, hallucinated continuations, no `<end_of_turn>` discipline. **DJLougen's rev (rebrand of GestaltLabs) fixed it.** Same q6/g64 quantization scheme as E4B-SABER, identical FCT078 wrapper, identical agentic harness — no per-model tuning was needed.

### Agentic suite results (greedy decoding, temp=0)

| Gate | Result | Iters used | Tool calls | Notes |
|------|--------|------------|------------|-------|
| Autonomous (4-tool MCP loop) | **PASS** | 4/8 | 3 | Clean termination |
| Continuation (3 sequential tasks) | **PASS** | 3/8 per task | 3+2+2 | All tasks made calls, summary file persisted across tasks |
| Sprint (single user msg, multi-step) | **PASS** | 5/20 | 4 | summary.md + followup.md both written, no runaway |
| Extended loop (>8 turn capacity) | **PASS** | 7/20 | 6 | architecture.md written, mentioned database+cache+proxy correctly |

E2B-SABER is the **only sub-3B model in the bake-off to pass all four gates**. Quality suite: 6/6, decode 36-55 tok/s.

### Context-length stress (8-bit KV, FCT078 wrapper defaults)

| Context | Prefill+decode total | Decode tok/s | Wired Δ vs cold | Suitable for |
|---------|---------------------|--------------|------------------|--------------|
| 1K | 5.8s | 44.1 | baseline | All aux roles |
| 4K | 7.3s | 35.0 | +0.3 GB | All aux roles |
| 8K | 8.9s | 28.7 | +0.7 GB | Compaction, summarization |
| 16K | 12.7s | 20.2 | +1.5 GB | Compaction (large convo) |
| 32K | 21.8s | 11.7 | +2.6 GB | Marginal — batch jobs only |
| 64K | 45.0s | 5.7 | +4.1 GB | Avoid — route to E4B (Boot/Kelk) |

Wired memory grows linearly with context (KV cache scaling). At 64K the model is still functional but slow enough to break interactive UX. Compaction inputs in production should stay ≤16K; longer corpora go to Boot/Kelk on E4B.

### KV bit-width decision

Coord runs the FCT078 wrapper default of **8-bit KV cache** (`QuantizedKVCache(group_size=64, bits=8)`), same as Boot and Kelk. Considered alternatives:

- **4-bit KV:** Would halve KV memory at 64K (~2 GB savings). Rejected because SABER ablation is sensitive to quant noise; KV cache noise compounds across decode steps, and a 30-iter sprint at 4-bit risks breaking tool-call format coherence (same failure mode observed for Harmonic-9B at temp=0.6 in FCT091). 8-bit at 64K only consumes 4 GB total — well within the box budget — so the saving isn't load-bearing.
- **Q5_1 / GGUF-style mixed quant:** Not supported by mlx-lm. `QuantizedKVCache` accepts `bits ∈ {2, 3, 4, 6, 8}` only. Q5_1 is a llama.cpp/GGUF format from a different inference stack.

Keeping 8-bit across all three instances also means one wrapper, one config, one set of behaviors to reason about.

### Why aux, not primary

E2B is **not faster** than E4B in tok/s on Apple Silicon — Gemma 4's shared embedding layer and similar attention head count flatten the throughput difference. The win is **memory** (~40% lighter), which is exactly what makes it tractable as a third concurrent instance on a 32 GB box.

E2B should not replace E4B for primary agentic work. E4B has more depth in long-horizon reasoning, longer effective context utilization, and better instruction layering. E2B is suited for **bounded subroutines** where:
- Input is finite (conversation buffer, doc chunk, user message)
- Output is finite (summary, classification, structured tool args)
- Quality bar is forgiving (compression, not creation)
- Latency matters more than depth

---

## Workloads suited to the Coord aux tier

| Workload | Suited? | Why |
|----------|---------|-----|
| **Conversation compaction** | ✓ | Bounded input/output, forgiving quality bar, latency-blocking |
| **Long-doc summarization** | ✓ | Single-shot, structured output |
| **Intent classification / routing** | ✓ | Tiny output (one label), high call frequency |
| **Tool-call argument shaping** | ✓ | "Format raw user intent into structured args" |
| **Entity extraction / keyword harvest** | ✓ | Embedding-adjacent, no multi-step needed |
| **Quick-fact lookup pre-filter** | ✓ | "Does the user need a search?" before delegating |
| Multi-step agentic loops | ✗ | Use Boot/Kelk on E4B |
| Document-grounded reasoning over corpora | ✗ | Use Boot/Kelk on E4B with external memory |
| Code generation > 200 lines | ✗ | E4B handles, E2B may but quality drops |
| Inputs > 16K context | ✗ | Stress test shows decode drops to 20 tok/s at 16K, 5.7 tok/s at 64K — route long inputs to E4B |

The clearest single use case is **conversation compaction**. Compaction is structurally trivial vs the agentic suite that E2B already passes (a 1199-token palindrome implementation, 875-token multi-step math, both single-shot). Promoting compaction calls from Claude/Hermes to local E2B saves cloud spend with no perceivable quality loss for the user.

---

## Hermes integration

Hermes already supports multi-provider routing. The Coord aux tier is exposed as another `provider: custom` endpoint:

```yaml
providers:
  - name: coord-aux
    base_url: http://127.0.0.1:41963/v1
    model: /Users/nesbitt/models/Gemma-4-E2B-SABER-MLX-6bit
    provider_type: custom
```

Aux slots inside Boot's and Kelk's Hermes configs that previously routed to cloud (compaction, summarization, classification) can be re-pointed at the `coord-aux` provider. Each Hermes config decides per-slot which provider serves which sub-task.

The `@coord` Matrix profile (originally created for the deprecated coordinator-rs binary) is repurposed as the aux tier's identity for any Matrix-visible aux work, though most aux calls will be in-process and never appear on Matrix.

---

## LaunchAgent

`~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-coord.plist`:

```
ProgramArguments:
  /opt/homebrew/Cellar/mlx-lm/0.31.3/libexec/bin/python
  /Users/nesbitt/dev/factory/scripts/mlx-lm-factory-wrapper.py
  --model /Users/nesbitt/models/Gemma-4-E2B-SABER-MLX-6bit
  --host 127.0.0.1 --port 41963
  --prefill-step-size 2048
  --prompt-concurrency 1
  --max-tokens 16384
  --prompt-cache-bytes 4294967296
KeepAlive: true
RunAtLoad: true
ThrottleInterval: 15
StandardOut/ErrorPath: ~/Library/Logs/factory/mlx-lm-factory-coord.log
```

Identical structure to `mlx-lm-factory-{boot,kelk}.plist`, only the model path and port differ. Same wrapper guarantees same memory caps and same KV quant scheme.

---

## Source model

**Original HF checkpoint:** `DJLougen/gemma-4-E2B-it-saber` (HuggingFace, ~5 GB FP16)
- Author note: DJLougen is the rebrand of GestaltLabs (same lab as E4B-SABER, 27B-SABER)
- HF cache preserved at `~/.cache/huggingface/hub/models--DJLougen--gemma-4-E2B-it-saber/`
- HF copy at `~/models/Gemma-4-E2B-SABER-HF/` (broken symlinks from initial copy attempt — the cache itself is the canonical source)

**MLX conversion command:**

```
SRC=/Users/nesbitt/.cache/huggingface/hub/models--DJLougen--gemma-4-E2B-it-saber/snapshots/8641be6cf18751c9adcf43578b3c59eb4ec319d0/

/opt/homebrew/Cellar/mlx-lm/0.31.3/libexec/bin/python \
  -m mlx_lm convert \
  --hf-path "$SRC" \
  --mlx-path ~/models/Gemma-4-E2B-SABER-MLX-6bit \
  -q --q-bits 6 --q-group-size 64
```

- ~30 seconds on M2 Max
- Output: 3.5 GB on disk (includes vision tower from Gemma 4 multimodal arch — text-only inference doesn't load it)
- Quantization: 6.501 bits/weight effective
- No DWQ, no LoRA, no specialization — vanilla q6/g64 to keep it apples-to-apples with E4B-SABER and reproducible

---

## Memory math

- 32 GB unified
- Wired allocations:
  - mlx-lm-factory-boot   ~10 GB
  - mlx-lm-factory-kelk   ~10 GB
  - mlx-lm-factory-coord  ~6 GB
  - **Subtotal:** ~26 GB
  - OS + Hermes (3 gateways) + MCP servers (qdrant, research, matrix-mcp-boot, graphiti) + portal-caddy + GSD: ~5–6 GB
- **Total target ceiling:** ~32 GB. Live state at end of bench: 3.6 GB free, no swap pressure.

The Nemostein 30B/3B fallback on :41966 needed ~16 GB wired by itself. Cannot coexist with the Coord aux tier; one or the other.

---

## Rollback (if heavy reasoning ever needed via Nemostein)

```
# 1. Bring down the Coord aux tier
launchctl bootout gui/$(id -u)/com.bootindustries.mlx-lm-factory-coord
mv ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-coord.plist \
   ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-coord.plist.disabled

# 2. Re-enable Nemostein
mv ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-nemostein.plist.deprecated \
   ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-nemostein.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-nemostein.plist

# 3. Update Hermes aux slots that pointed at :41963 to point at :41966 (or fall back to cloud)
# 4. Verify
curl -s http://127.0.0.1:41966/v1/models | jq .data[0].id
```

This is not a hot operation — it requires shutting down aux, ~2 min for Nemostein to load, and Hermes config edits. Reserve for genuine heavy-reasoning workloads (e.g. multi-hour deep-research sessions) where E4B is provably insufficient.

---

## Verification

- All three ports respond on `/v1/models`:
  - `:41961` → `/Users/nesbitt/models/Gemma-4-E4B-SABER-MLX-6bit` (Boot)
  - `:41962` → `/Users/nesbitt/models/Gemma-4-E4B-SABER-MLX-6bit` (Kelk)
  - `:41963` → `/Users/nesbitt/models/Gemma-4-E2B-SABER-MLX-6bit` (Coord)
- `:41966` returns connection refused (deprecated plist not loaded)
- `factory-status.sh` shows tri-server topology with cache-hit-rate scrape per slot
- `factory-startup.sh` Phase 1 brings up all three on boot, requires 22 GB free pre-flight
- Bench artifact: `docs/fct/FCT090-bench-e2b-saber-djlougen.json`

---

## Follow-ups

- **Per-Hermes-aux-slot wiring:** identify which slots in `hermes-boot.sh` / `hermes-kelk.sh` configs should route to coord-aux vs. cloud. Compaction is the obvious first one.
- **Compaction prompt template:** small system-prompt prefix optimized for E2B, cached as a warm prefix on :41963.
- **Real-traffic monitoring:** watch `top` and the wrapper log for the first 48 h. If wired peak exceeds 27 GB sustained, reduce `--prompt-cache-bytes` on Coord from 4 GB to 2 GB.
- **DWQ revisit:** if E2B-SABER turns out to be load-bearing for compaction quality, consider a DWQ recalibration pass against a small compaction corpus. Adds 10–30 min, no production change required.

---

## Sources

- FCT078 — Dual SABER E4B Stress Test Results (in-repo): wrapper architecture and KV quant patch
- FCT091 — vllm-mlx Bake-off and Production Selection (in-repo): agentic suite definition, E4B-SABER selection
- FCT070 — KV quantization upstream broken in mlx-lm server (in-repo): justification for in-process patch
- DJLougen, "gemma-4-E2B-it-saber", HuggingFace, 2026
