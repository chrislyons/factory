# FCT091 vllm-mlx Bake-off and Production Selection

**Status:** Implemented
**Date:** 2026-05-02
**Machine:** Whitebox (Mac Studio M2 Max, 32 GB unified memory)
**Related:** FCT054 (E4B consolidation), FCT067 (vendor mlx-vlm patches), FCT070 (KV quant blockers on Gemma 4), FCT073 (optimization curriculum), FCT078 (dual SABER stress test), FCT083 (SABER raw vs adapter), FCT089 (model family baseline), FCT090 (this sprint's brief)

---

## Summary

Ran a four-model bake-off across architecturally distinct candidates under both *dialog coherence* tests and a new *autonomous agentic-loop* suite (autonomous, continuation, sprint, extended). The agentic suite proved decisive: **E4B-SABER raw via `mlx_lm.server` + `scripts/mlx-lm-factory-wrapper.py` is the only candidate that passes all four agentic gates** including the sprint test (multi-step task in a single user message, agent must continue autonomously after report-back). Nemostein passes the basic loops but **fails sprint** because qwen3 reasoning padding consumes the token budget before any tool call is emitted. Harmonic-9B **fails sprint and extended** with runaway repetition (older model, pre-agentic-RLHF generation).

**Production topology adopted:** dual E4B-SABER raw on `:41961` (Boot) and `:41962` (Kelk), each served by `mlx_lm.server` via the FCT078 wrapper (Metal cap 10 GB, wired cap 10 GB, 8-bit `QuantizedKVCache` patched in-process). Nemostein remains available on `:41966` (`.disabled` plist for hot-swap) as a fallback for non-sprint heavy-reasoning workloads. Operator instruction at sprint close: leave `:41966` dormant until dual-SABER is proven solid in production. Memory profile matches FCT078's documented stable dual-instance setup (~6.3 GB RSS per server, ~16 GB wired peak under concurrent inference).

---

## Headline Results

| Candidate | Server | Quality 6/6 | Dialog multi-turn | Short tok/s | 4K ctx | 8K ctx | 16K ctx | RAM wired | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **E4B-SABER raw** | mlx_lm wrapper | ✅ all `finish=stop` clean endings | ✅ PASS coherent | 35 tok/s | 19 | 13 | 8 | ~6 GB | **Production primary (dual-instance :41961+:41962)** |
| Nemostein 30B/3B | vllm-mlx | ✅ all `finish=length` (qwen3 reasoning padding — content correct) | ✅ PASS coherent | 60 tok/s | 16 | 9 | 5 | ~14 GB | Fallback for heavy reasoning (`:41966` `.disabled` plist) |
| Harmonic-9B | vllm-mlx | ✅ mix stop+length | ✅ PASS coherent | 47 tok/s | 11 | 6 | 3 | ~7 GB | Validated reserve |
| 27B-SABER (Qwen3.5) | vllm-mlx | partial (killed) | n/a | 15 tok/s | (slow) | (slow) | (slow) | ~14 GB | Shelved — too slow |
| 26B-A4B (Gemma4 MoE) | vllm-mlx | ❌ HTTP 500 | n/a | n/a | n/a | n/a | n/a | n/a | Blocked — see §3 |
| E4B-SABER under vllm-mlx | vllm-mlx | ❌ load failure | n/a | n/a | n/a | n/a | n/a | n/a | Blocked — see §3 |

(Context scaling shown in tok/s.)

### Two kinds of "multi-turn" measured

Initial benchmarks measured only **dialog coherence** (the table above) — model holds context across an 8-turn user/assistant exchange without tool use. All three viable candidates passed.

The decisive measurement is **autonomous agentic-loop discipline** — model picks a tool, calls it, reads the result, decides the next tool, calls that, etc. — for the durations a CLI/Matrix agent will see in production. The harness (`test-vllm-bench.py --include autonomous continuation sprint extended`) plays the tool runtime: parses model output for tool calls, executes via `fake_tool_runtime`, injects results back as `role=tool` messages.

Four tests cover the relevant failure modes:

| Test | What it probes | Pass criteria |
|---|---|---|
| **autonomous** | Basic 4-tool MCP loop (list → read → write → confirm) | Each tool called exactly once, correct order, file written, clean termination |
| **continuation** | 3 sequential user tasks with report-back between (Type A: explicit follow-up after report — the production failure pattern previously reported on E4B) | Each follow-up task actually executed (≥2 tool calls per task), end-state file mutations correct |
| **sprint** | Single user message with 3 steps; agent must work through ALL autonomously (Type B: self-direction without re-prompting — the CLI/Matrix workload) | All steps' tools called, both files written, ≤12 tool calls (no runaway) |
| **extended** | 3-file read + accumulate + write + verify, >7 iters (probes long-loop coherence) | All 3 reads, write to summary file, write contains keywords from all 3 sources, ≤15 tool calls |

### Agentic suite results (2026-05-02, all greedy `temperature=0.0`)

| Model | autonomous | continuation | **sprint** | extended | Verdict |
|---|---|---|---|---|---|
| **E4B-SABER raw** (`mlx_lm` wrapper, `:41961`) | ✅ 4 iters, 3 calls | ✅ 8 calls across 3 tasks | ✅ **5 iters, 4 calls** | ✅ 7 iters, 6 calls | **Production winner** — passes all four |
| Nemostein 30B (`vllm-mlx`, `:41966`) | ✅ 4 iters | ✅ all 3 tasks | ❌ **iter 1 dead — 1024t reasoning padding consumed budget before any tool emission** | ✅ 7 iters, 6 calls | Production-blocking sprint failure |
| Harmonic-9B (`vllm-mlx`) | ✅ 4 iters | (not measured) | ❌ **20/20 runaway repetition** (called list/read/write/delete in loop after task complete) | ❌ **20/20 runaway** | Older model, pre-agentic-RLHF gen — shelved for production |

Per-iter throughput on the agentic loop:
- **E4B-SABER:** ~3-5s/iter → SABER's full sprint completed in **~15s end-to-end**
- **Nemostein:** ~19s/iter → would be ~80s end-to-end if it didn't get stuck
- **Harmonic-9B:** ~10-16s/iter → 20-iter runaway = ~4 minutes wasted

### Why E4B-SABER wins the sprint test

SABER's tool-call discipline is excellent at greedy decoding: each iteration emits short content (none over 400 tokens), the tool call sits in the structured `tool_calls` field, the model knows to stop after the user's stated steps are complete. The training (abliteration + Hermes fine-tune) explicitly rewards "do work → confirm → stop". Nemostein and Harmonic-9B both lack this discipline at greedy temperatures — Nemostein over-thinks, Harmonic-9B over-acts.

### Why Nemostein fails the sprint test specifically

Nemostein under `--reasoning-parser qwen3` emits a long `<think>...</think>` block that vllm-mlx strips into `reasoning_content` but still counts against `max_tokens`. On a multi-step sprint user message, the model's first turn fills the entire 1024-token budget with reasoning *about* what it's going to do, never gets to the actual tool call. Capacity is there, but the parser configuration starves the action. Possible fixes (deferred to a future sprint): raise `max_tokens` to 4096+, or strip reasoning from the budget calculation, or use a different reasoning parser that's more terse.

### Why Harmonic-9B fails sprint and extended

Older Qwen3.5-architecture model from before agentic RLHF caught up. At greedy decoding it can't tell when a task is done — keeps calling tools to "verify" and "re-verify". Sampling at temperature 0.6 might break the loop (untested in this sprint). Not worth pursuing for production given SABER passes greedy outright. Held as a non-production reserve.

### Docs-corpus-review workload mechanics (the production sprint pattern)

Operator concern: Kelk's last large assignment was "review our entire docs corpus" — repeated read-doc → discuss → edit → next-doc cycles. Previous attempt choked. What the bake-off data implies for sustained workloads of this shape:

**Per-doc cost at SABER:** ~6 tool calls (read → discuss → maybe edit → maybe read another → confirm) at 35 tok/s. A 5K-token doc + 1K of model dialog = ~6K added to context per doc. Throughput at 8K context is ~13 tok/s, at 16K is ~8 tok/s. Decode rate degrades gracefully but accumulates.

**Context accumulation over a corpus:** 50 docs × 6K context-cost each = 300K accumulated tokens. SABER's nominal context is 128K but practical-quality drops sharply past 16K. **A naive single-conversation approach will choke around doc 5-8.** This is consistent with the previously reported failure.

**Mechanisms that make sustained sprints feasible** (the actual fix is upstream of inference — at the Hermes-gateway layer):

| Mechanism | Effect | Already in stack? |
|---|---|---|
| Per-doc session reset | Each doc starts fresh; loses cross-doc memory | Hermes-side; check current behavior |
| Rolling summary every N turns | Drop old turns, prepend a one-paragraph summary; preserves cross-doc knowledge at fraction of cost | Not currently configured |
| Persistent external memory (Qdrant, graphiti) | Each turn queries memory rather than re-loading prior docs | Yes — `mcp__qdrant-mcp` (projects-vault) and `mcp__graphiti` already in MCP toolchain |
| Two-model split | Cheap loop model (SABER) for bulk turns, heavy model (Nemostein) only for actual editing decisions | Topology supports it; routing logic is Hermes-side |
| `--prompt-cache-bytes` cap | Bounds the FCT078 wrapper's prompt cache so old session state evicts cleanly | Already set: 4 GB cap |

**Bottom line:** the inference layer (E4B-SABER + wrapper) does not crush us on context for sustained sprints. The docs-corpus failure pattern is a Hermes-side context-management issue (whether/how the gateway trims accumulated dialog) and an external-memory utilization issue (whether Qdrant/graphiti is being queried instead of re-loading docs into context). Both are out-of-scope for this sprint but well-defined as next-sprint targets.

### max_iters guidance for production

Based on measured iter counts (SABER finished autonomous in 4, sprint in 5, extended in 7):

| Workload | Recommended cap | Notes |
|---|---|---|
| Single discrete task ("read X, write Y") | **12** | ~70% headroom over the longest legit single-task workload measured |
| Multi-step sprint (one user message, multiple steps) | **36** | Covers a 6-doc review @ 5 iters/doc with cushion |
| Per-iter `max_tokens` | **1024** | Forces conciseness; reasoning padding fails fast at this cap (Nemostein sprint-fail signal) |
| **No-progress detector** | bail after 3 consecutive iters with the same `(tool_name, args)` | Catches Harmonic-style loops far earlier than the iter cap |

The no-progress detector is the most important addition — Harmonic-9B's runaway in our test would have been caught at iter ~6 instead of iter 20. The iter cap is a safety net, not a primary control.

---

## Final Production Configuration

### `:41966` — Nemostein-3-Hermes-Omni via vllm-mlx

`~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-nemostein.plist`

| Flag | Value | Why |
|---|---|---|
| Model | `~/models/Nemostein-3-Hermes-Omni-30b-a3b-MLX-mixed_3_4` | FCT089 winner |
| `--gpu-memory-utilization` | `0.65` | Tested 0.65 vs 0.75: identical tok/s, 0.75 cut free memory to 0.24 GB. 0.65 wins. |
| `--kv-cache-quantization-bits` | `4` | Tested 4 vs 8 on Nemostein: identical quality + tok/s. Nemotron-H is hybrid — only ~11/52 layers use KV cache (rest are Mamba SSM, fixed-size), so quant savings are marginal but harmless. 4-bit chosen for the marginal memory headroom. |
| `--enable-prefix-cache` | on | vllm-mlx feature; works with Nemostein/Mamba+attention. Hit rate measured at 0.0 in single-session tests — needs realistic Hermes traffic for meaningful warming. |
| `--enable-metrics` | on | `/metrics` endpoint scraped by `factory-status.sh`. |
| `--max-num-seqs` | `4` | Defensive cap. Boot+Kelk = 2 expected concurrent. |
| `--continuous-batching` | **OFF** | **Triggers `RuntimeError: There is no Stream(gpu, 3) in current thread`** in mlx-lm 0.31.3's batched generator. Documented vllm-mlx + mlx-lm bug under continuous batching for this model. Without it requests are sequentialized but stable. |
| `--specprefill` | **OFF** | Earlier disabled-state plist had this without the required `--specprefill-draft-model`, would crash on start. No matching draft model exists for Nemotron-H tokenizer. |
| `--reasoning-parser` | `qwen3` | Strips `<think>...</think>` into `reasoning_content`. Bug observed in mlx-lm with this model family ([mlx-lm #1050](https://github.com/ml-explore/mlx-lm/issues/1050)) is mitigated under vllm-mlx — verified the smoke test does not loop. |
| `--tool-call-parser` | `nemotron` | Matches the model's tool-call format. |
| Log path | `~/Library/Logs/factory/mlx-vllm-nemostein.log` | Was `mlx-lm-26b-boot.log` — wrong model name. |

Cold start: ~10 s. Quality 6/6 PASS, multi-turn 8/8 PASS, throughput 60 tok/s short-context.

### `:41961` — E4B-SABER raw via mlx_lm wrapper

`~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-boot.plist` (restored from FCT078 production config)

| Flag | Value | Why |
|---|---|---|
| Interpreter | `/opt/homebrew/Cellar/mlx-lm/0.31.3/libexec/bin/python` | Hard-coded — known-working version. |
| Wrapper | `scripts/mlx-lm-factory-wrapper.py` | FCT078 wrapper. **Patches `mlx_lm.models.cache.make_prompt_cache` to use 8-bit `QuantizedKVCache` *before* server starts**, sets `mx.set_memory_limit(10 GB)` and `mx.set_wired_limit(10 GB)`. This is the only reliable way to get KV quantization on Gemma 4 — all `--kv-bits` server flags are broken upstream (FCT070). |
| Model | `~/models/Gemma-4-E4B-SABER-MLX-6bit` | Raw SABER, no LoRA adapter (FCT083 found raw outperforms adapter 7/8 vs 6/8). |
| `--prompt-cache-bytes` | `4294967296` | 4 GB cap. FCT078 stress-tested up to 25K-token concurrent input; cap never reached. |
| `--prompt-concurrency` | `1` | Sequential per-server; concurrency comes from running two server instances on different ports. |
| `--prefill-step-size` | `2048` | FCT070 sweet spot for 4B-class models on M1 Max 400 GB/s bandwidth. 4096 caused Metal OOM under concurrent load. |
| `--max-tokens` | `16384` | Default cap. |

Cold start: ~4 s. Quality 6/6 PASS with `finish=stop` on every prompt, multi-turn 8/8 PASS coherent, throughput 35 tok/s sustained.

### Topology — adopted 2026-05-02 sprint close

```
                      ┌───────────────────────────────────────┐
Boot Hermes      ───► │  :41961   E4B-SABER raw              │ Boot's dedicated agentic loop
                      │           mlx_lm.server + wrapper     │
                      │           ~6 GB RSS / ~10 GB wired    │
                      └───────────────────────────────────────┘
                      ┌───────────────────────────────────────┐
Kelk Hermes      ───► │  :41962   E4B-SABER raw              │ Kelk's dedicated agentic loop
                      │           mlx_lm.server + wrapper     │
                      │           ~6 GB RSS / ~10 GB wired    │
                      └───────────────────────────────────────┘
                      ┌───────────────────────────────────────┐
                      │  :41966   Nemostein 30B/3B           │ DORMANT (.disabled plist)
                      │           vllm-mlx                    │ Hot-swap fallback for heavy
                      │                                       │ reasoning if SABER not enough
                      └───────────────────────────────────────┘
```

Per-instance config (both `:41961` and `:41962` are identical except for port + log path):
- Plist: `~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-{boot,kelk}.plist`
- Wrapper: `scripts/mlx-lm-factory-wrapper.py` (Metal limit 10 GB, wired limit 10 GB, KV 8-bit `QuantizedKVCache` patched in)
- Model: `~/models/Gemma-4-E4B-SABER-MLX-6bit` (raw, no adapter — FCT083 finding)
- Flags: `--prompt-cache-bytes 4294967296 --prompt-concurrency 1 --prefill-step-size 2048 --max-tokens 16384`

Total wired memory under both servers active + concurrent inference: **~16 GB** (matches FCT078 measurements). Within 32 GB budget with **~16 GB headroom** for OS + Hermes + MCP servers — generous, no pressure.

Operator decision (sprint close): **leave `:41966` (Nemostein) `.disabled` until dual-SABER is proven solid in real production traffic.** If SABER struggles on a real workload we can hot-swap by `mv` + `launchctl bootstrap` of the Nemostein plist, no other changes.

Rollback to dormant single-server (Nemostein-only on `:41966`):
```
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-{boot,kelk}.plist
mv ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-{boot,kelk}.plist{,.disabled}
mv ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-nemostein.plist{.disabled,}
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-nemostein.plist
```

---

## What changed in vllm-mlx production plist (vs disabled state at sprint start)

The plist on disk before the sprint was broken:
- `--specprefill` set without required `--specprefill-draft-model` → server failure on start.
- `--gpu-memory-utilization 0.78` → unsafe on 32 GB without measured headroom (free memory dropped to 0.24 GB under load at 0.75; 0.78 would OOM).
- Log path `mlx-lm-26b-boot.log` → wrong model name, confusing.
- Missing `--enable-metrics` → no way to measure prefix cache hit rate.

After the sprint:
- Removed `--specprefill`, set util to 0.65, added `--enable-metrics` and `--max-num-seqs 4`, fixed log path. Tested `--continuous-batching` and removed it after confirming the cross-thread stream bug. Tested 0.75 GPU util and 8-bit KV — neither improved on 0.65 / 4-bit so reverted.

---

## Optimization Findings

### 1. GPU memory utilization
Tested 0.65 → 0.75. **0.65 wins.** No throughput delta at 0.75; free memory dropped to 0.24 GB after concurrency, vs 5.2 GB at 0.65. 0.78 (the original disabled-plist value) would be unsafe.

### 2. KV cache quantization (Nemostein)
Tested 4-bit vs 8-bit. **Identical quality and throughput.** Nemotron-H is a hybrid Mamba+attention architecture: only ~11 of 52 layers use KV cache (the rest are SSM with fixed-size recurrent state). KV quant savings on this model are inherently small. Picked 4-bit for marginal memory savings.

### 3. KV cache quantization (Gemma 4)
**All `--kv-bits` flags broken upstream on Gemma 4** (FCT070): TurboQuant fails with `AttributeError: 'array' object has no attribute 'norms'` on MoE; uniform 4-bit hurts quality on 64-dim heads (Gemma 4's dimensionality) per the FCT070 quality matrix; RotatingKVCache is NYI for the model. The FCT078 wrapper's in-process `QuantizedKVCache` monkey-patch is the only working KV quantization for Gemma 4 — it bypasses the broken server-flag path entirely.

### 4. Continuous batching
**Broken under vllm-mlx + mlx-lm 0.31.3 for Nemotron-H and Gemma 4.** Triggers `RuntimeError: There is no Stream(gpu, N) in current thread` from `mlx_lm/generate.py` and `mlx_vlm/generate.py` when the batched generator's worker thread tries to eval cache state Arrays bound to a stream owned by a different thread. Tried two patches (`strict=False` weight loading, default-stream eval fallback) — both moved or hid the symptom but did not fix the root cause, which lives deep in mlx-lm's prompt cache lifecycle. Production runs sequential decode without continuous-batching; concurrency comes from running two server instances on separate ports (FCT078 pattern).

### 5. Prefix cache
Available in vllm-mlx and FCT078-wrapped mlx_lm.server (via `--prompt-cache-bytes`). Hit rate observed at 0.0 in synthetic single-session benchmarks. Realistic warming requires sustained Hermes traffic with shared system-prompt prefixes; deferred to ops measurement during normal use.

### 6. Sampling for multi-turn coherence
Hypothesis going in: greedy decoding (`temperature=0`) might cause loops on small/abliterated models, explaining the historical multi-turn failure of E4B-SABER. **Disconfirmed for E4B-SABER raw** — under the FCT078 wrapper with `temperature=0`, all 8 multi-turn turns produced coherent, on-topic, non-repetitive responses that referenced earlier turns correctly. The historical multi-turn failure attributed to E4B was not a sampling issue with raw SABER under the production wrapper; it may have been an adapter overfit (FCT083) or a Hermes-side context bug, but it is not a property of the model on this serving stack.

### 7. SpecPrefill
Not available — requires a small Nemotron-H draft model with the exact same tokenizer as Nemostein. None exists in `~/models/`. The "Nemostein-3-Nano-30b-a3b-MLX" sibling is the same size and can't act as a draft. Punted.

### 8. MTP
Nemostein config has no MTP heads. Skipped.

### 9. Warm-prompts
Hermes does not inject a long static system prompt at the gateway level (verified by inspecting `~/.hermes/profiles/{boot,kelk}/config.yaml`). The `--warm-prompts` lever's vendor-claimed 1.3–2.3x cold-TTFT speedup applies only when there is a long shared prefix to amortize. Not applicable to current Hermes traffic shape. Reconsider if Hermes adopts prefilled system prompts.

---

## What is broken (and why I'm not fixing it in this sprint)

### A. vllm-mlx + Gemma 4 family (26B-A4B, E4B-SABER)

Two distinct failures observed:

1. **Load-time:** `ValueError: Received 2 parameters not in model: language_model.model.per_layer_model_projection.{biases,scales}`. mlx-vlm 0.x's `Gemma4ForConditionalGeneration` declares this layer as `nn.Linear`, but SABER-quantized Gemma-4 weights ship it as a `QuantizedLinear` with biases+scales. Loading with `strict=False` (patched and reverted) lets the model load but produces a matmul shape error at first inference because the scales aren't dead — they're load-bearing for the quantized projection.

2. **Inference-time:** `RuntimeError: There is no Stream(gpu, N) in current thread` from both `mlx_vlm/generate.py:wired_limit` (cleanup) and `mlx_lm/generate.py:generate_step` (prompt cache eval). The cache state Arrays were created on a stream owned by the model-load thread; vllm-mlx's `to_thread` request handler runs eval from a different worker thread that doesn't have that stream registered. Tried `strict=False` and a default-stream fallback patch in the cleanup path; both either didn't fire or moved the error to a different line. Root cause is in mlx-lm's prompt cache lifecycle, not patchable in a session.

**Workaround in production:** route Gemma 4 to `mlx_lm.server` via the FCT078 wrapper (text-only path; multimodal Gemma vision/audio capability is not currently exercised by Hermes agents — defer to a separate sprint when vision is needed).

### B. 27B-SABER (Qwen3.5) decode speed

Loads and runs correctly under vllm-mlx. **Decode ceiling ~15 tok/s** on M1 Max for a 27B dense Qwen3.5 model — that's the model+hardware ceiling, not a server config issue. Long-context catastrophic: 0.9 tok/s @ 16K, would be ~30 minutes for 64K. Killed mid-bench-stress. Shelved.

### C. Restoration paths (recorded for future sprints)

To re-enable Gemma 4 under vllm-mlx, **upstream needs**:
- `mlx-vlm` to add the SABER quantization scheme to `Gemma4ForConditionalGeneration.per_layer_model_projection` (declare it as `QuantizedLinear` not `nn.Linear`)
- `mlx-lm` (or vllm-mlx's threading model) to ensure prompt cache state Arrays are stream-portable across worker threads

These are filable as upstream issues; not session-scope work.

---

## Files Modified This Sprint

| File | Change |
|---|---|
| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-nemostein.plist` | Removed `--specprefill`, set util `0.65`, added `--enable-metrics` and `--max-num-seqs 4`, fixed log path. Enabled (was `.disabled`). |
| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-boot.plist` | Restored from `.disabled` (was the FCT078 production wrapper config). |
| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-{26b-a4b,27b-saber,e4b-saber,harmonic-9b}.plist.disabled` | Created candidate plists (kept `.disabled` for archival/rollback). |
| `scripts/test-vllm-bench.py` | New. Model-agnostic harness: --model, --port, --label, --include stress\|concurrency\|multi-turn. Outputs `docs/fct/FCT090-bench-<label>.json`. |
| `scripts/factory-status.sh` | Updated for dual-server topology (:41961 + :41966) and added `/metrics` cache-hit-rate scrape. |

## Files NOT Modified

`scripts/benchmark_utils.py`, `scripts/hermes-boot.sh`, `scripts/hermes-kelk.sh`, anything in `~/models/`, `~/.config/pip/constraints.txt`, the vendored `~/dev/vendor/mlx-vlm/` patches.

## Attempted-and-Reverted Patches

For the record, these library-level patches were tried and **fully reverted**:
- `~/.local/share/uv/tools/vllm-mlx/lib/python3.12/site-packages/mlx_vlm/utils.py` — added `strict=False` to `model.load_weights`. Let SABER load past the missing-params check but exposed a downstream matmul shape error proving the params were load-bearing. Reverted.
- `~/.local/share/uv/tools/vllm-mlx/lib/python3.12/site-packages/mlx_vlm/generate.py` — wrapped `mx.synchronize(s)` in try/except for cross-thread stream cleanup. Did not affect the inference-time stream bug. Reverted.
- `~/.local/share/uv/tools/vllm-mlx/lib/python3.12/site-packages/mlx_lm/generate.py` — wrapped cache-state eval in try/except with default-stream fallback. The fallback hit the same error. Reverted.

Backups (`.bak-fct090`) of each file remain alongside the originals for forensic reference.

## Rollback

To revert to single-server-only on `:41966` (Nemostein only):
```
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-boot.plist
mv ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-boot.plist{,.disabled}
```

To swap to a different production primary on :41966:
```
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-nemostein.plist
mv ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-nemostein.plist{,.disabled}
mv ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-harmonic-9b.plist{.disabled,}
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-harmonic-9b.plist
```

Update Hermes profiles' `model:` field to match (`harmonic-9b` instead of `nemostein`).

---

## References

- [1] FCT054 — Local E4B Model Consolidation (vendored mlx-vlm patches, `provider: custom` requirement)
- [2] FCT067 — SSD Expert Streaming, Gemma Tool Call Parser Fix (vendor/mlx-vlm tool_parsers/gemma4.py patch list)
- [3] FCT070 — KV Quantization broken on Gemma 4 (TurboQuant MoE bug, RotatingKVCache NYI)
- [4] FCT073 — MLX Optimization Curriculum (mlx_vlm vs mlx_lm loader matrix, prefix-cache availability per stack)
- [5] FCT078 — Dual SABER E4B Stress Test Results (production-validated wrapper config; multi-turn ran for days)
- [6] FCT083 — SABER Adapter Test Results ("raw SABER outperforms SABER + adapter 7/8 vs 6/8")
- [7] FCT089 — Ornstein Model Family Comprehensive Benchmarks (baseline this sprint compared against)
- [8] FCT090 — Local Inference Optimization Handoff (this sprint's brief)
- [9] mlx-lm #1050 — Nemotron-Cascade-2 thinking-mode infinite loop on Apple Silicon
- [10] vllm-mlx (waybarrios) repo + Native LLM/MLLM Inference at Scale on Apple Silicon, arXiv:2601.19139v2
- [11] mlx-vlm #904 — TurboQuant broken on Gemma 4 MoE
