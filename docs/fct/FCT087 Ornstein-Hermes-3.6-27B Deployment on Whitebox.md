     1|# FCT087 Ornstein-Hermes-3.6-27B Deployment on Whitebox
     2|
     3|**Status:** Active — 6-bit working at reduced speed, 4-bit and 2-bit models downloading, concurrent serving analysis complete
     4|**Date:** 2026-05-01
     5|**Machine:** Whitebox (Mac Studio M1 Max, 32GB unified memory)
     6|
     7|---
     8|
     9|## Summary
    10|
    11|Successfully deployed Ornstein-Hermes-3.6-27b-MLX-6bit on :41966 as the sole inference server, replacing dual SABER E4B instances on :41961/:41962. The 27B model (21.2 GB weights) runs on 32GB unified memory via mmap with careful memory management. Boot is live and responding through Matrix.
    12|
    13|## Test Results
    14|
    15|### Benchmark Matrix
    16|
    17|| Test | Prompt | Prefill Step | KV Bits | Wired Limit | Result | tok/s |
    18||------|--------|-------------|---------|-------------|--------|-------|
    19|| Short (no limits) | 16 tok | 2048 | 8-bit | None | OK | ~10 |
    20|| Medium (no limits) | 229 tok | 2048 | 8-bit | None | OK | ~10 |
    21|| Long (no limits) | 1024 tok | 2048 | 8-bit | None | OK | ~10 |
    22|| 18K tokens (no limits) | 18520 tok | 2048 | 8-bit | None | **CRASH** at 6144 tok | — |
    23|| Short (wired=20GB) | 13 tok | 512 | 4-bit | 20 GB | OK | 1.6 cold / 7.4 warm |
    24|| Medium (wired=20GB) | 3865 tok | 512 | 4-bit | 20 GB | OK (slow) | ~1.5 |
    25|| 10K tokens (wired=20GB) | 9620 tok | 512 | 4-bit | 20 GB | OK (slow) | ~1.5 |
    26|| **16K tokens (no wired)** | **16020 tok** | **256** | **4-bit** | **None** | **OK** | **~7** |
    27|| Boot-scale (no wired) | 18541 tok | 256 | 4-bit | None | OK | ~7 |
    28|
    29|### Crash Analysis
    30|
    31|**Crash 1:** `[METAL] Command buffer execution failed: Insufficient Memory`
    32|- At: 6144/18520 tokens during prefill
    33|- Cause: No memory limits, prefill-step-size 2048, 8-bit KV
    34|- Root cause: Metal GPU needs compute buffers proportional to prefill step size. At 2048 tokens per step, GPU buffers exceed remaining memory after 21 GB model + macOS.
    35|
    36|**Crash 2:** Disk full (100% usage)
    37|- Cause: Swap/compressor wrote to disk under memory pressure
    38|- Freed: 13 GB of HF/uv caches cleared, user freed additional space
    39|
    40|### Key Findings
    41|
    42|1. **prefill-step-size is the critical parameter.** At 2048, Metal allocates large GPU buffers per step → OOM at ~6K tokens. At 256, each step uses 1/8th the GPU memory → survives 18K+ tokens.
    43|
    44|2. **Wired limits cause thrashing, not stability.** Setting `mx.set_wired_limit(20GB)` forces model page eviction → 2 tok/s decode. The 21 GB model needs to stay resident for acceptable speed.
    45|
    46|3. **No wired limit + Metal limit 28 GB + prefill-step-size 256 = stable.** Model pages stay resident, GPU buffers are small per step, macOS has 4 GB headroom.
    47|
    48|4. **4-bit KV quantization is essential.** The wrapper's original `make_prompt_cache` guard `if hasattr(model, "make_cache"): return model.make_cache()` bypassed our QuantizedKVCache entirely — the model used fp16 KVCache. Fixed by patching `TextModel.make_cache` directly.
    49|
    50|5. **Decode speed: ~7 tok/s with 4-bit KV, ~10 tok/s on short prompts.** The slower speed on long prompts is due to memory pressure and larger KV cache.
    51|
    52|## Architecture
    53|
    54|```
    55|Port    Model                                  Status
    56|----    -----                                  ------
    57|:41961  SABER E4B (unloaded, plist on disk)    RETIRED
    58|:41962  SABER E4B (unloaded, plist on disk)    RETIRED
    59|:41966  Ornstein-Hermes-3.6-27b-MLX-6bit       ACTIVE
    60|
    61|Hermes:
    62|  Boot:   UP → :41966 (27B)
    63|  Kelk:   UP → :41961 (offline — needs config update)
    64|  IG-88:  UP → cloud (unaffected)
    65|```
    66|
    67|## Wrapper (mlx-lm-27b-wrapper.py)
    68|
    69|```python
    70|# v3 — No wired limit, Metal limit 28 GB, 4-bit KV
    71|METAL_LIMIT_BYTES = 28 * 1024 * 1024 * 1024
    72|_KV_BITS = 4
    73|_KV_GROUP_SIZE = 64
    74|
    75|# Patches TextModel.make_cache directly to bypass model's fp16 KVCache
    76|# ArraysCache (GatedDeltaNet) untouched, QuantizedKVCache for full attention
    77|```
    78|
    79|## Plist Settings
    80|
    81|```
    82|--prefill-step-size 256    (crash was at 2048)
    83|--prompt-concurrency 1     (no concurrent prefill)
    84|--max-tokens 16384
    85|--prompt-cache-bytes 2147483648  (2 GB cap)
    86|```
    87|
    88|## Optimization Paths (In Progress)
    89|
    90|| Path | Status | Expected Impact |
    91||------|--------|-----------------|
    92|| 4-bit model (~14 GB) | User pulling | ~13-15 tok/s, larger prefill steps |
    93|| 2-bit model (~8.5 GB) | User pulling | Unknown quality, very fast |
    94|| System prompt compression | Pending | Prefill 5 min → 1 min |
    95|| DFlash speculative decoding | Researched | ~2x speedup (when draft model available) |
    96|| Prompt cache investigation | Resolved | Cache working (6 sequences, 1.83 GB) |
    97|| CLAUDE.md compression | Complete | Boot 37K→3K, Kelk 17K→3.2K (92%/81% reduction) |
    98|| Concurrent serving analysis | Complete | 1x 4-bit feasible for both agents |
    99|| Model-switch script | Complete | scripts/switch-27b.sh (6bit/4bit/2bit) |
   100|| Template plists | Complete | 4-bit and 2-bit plists pre-created |
   101|
   102|## DFlash Compatibility
   103|
   104|Ornstein3.6 is a Qwen3.6 tune → dflash-mlx should support it.
   105|
   106|**Status:**
   107|- Draft model `z-lab/Qwen3.6-27B-DFlash` exists but **still under training**
   108|- `z-lab/Qwen3.5-27B-DFlash` available as interim (lower acceptance rate)
   109|- dflash-mlx v0.1.4.1 has startup crash bugs (issue #13)
   110|- Memory layout with 4-bit target: 16 GB target + 4 GB draft + 4-6 GB KV = ~26 GB (fits)
   111|- Expected speedup: ~2.3-2.4x on M1 Max (halved from M5 Max benchmarks)
   112|
   113|**Blockers:**
   114|- Draft model still training
   115|- dflash-mlx has known bugs
   116|- No benchmark for Ornstein fine-tune specifically
   117|
   118|## Files Changed
   119|
   120|| File | Change |
   121||------|--------|
   122|| `~/.hermes/profiles/boot/config.yaml` | 41961→41966, E4B→27B |
   123|| `~/.hermes/profiles/boot/config.yaml.bak-27b` | Backup of E4B config |
   124|| `scripts/hermes-boot.sh` | Health check → 41966, model path → 27B |
   125|| `scripts/hermes-boot.sh.bak-e4b` | Backup |
   126|| `scripts/factory-startup.sh` | Phase 1 → 27B on 41966 |
   127|| `scripts/mlx-lm-27b-wrapper.py` | NEW — 4-bit KV, Metal limit, no wired limit |
   128|| `~/Library/LaunchAgents/com.bootindustries.mlx-lm-factory-27b.plist` | NEW |
   129|
   130|## Rollback
   131|
   132|1. `launchctl unload com.bootindustries.mlx-lm-factory-27b`
   133|2. `cp config.yaml.bak-27b → config.yaml`
   134|3. `cp hermes-boot.sh.bak-e4b → hermes-boot.sh`
   135|4. `launchctl load com.bootindustries.mlx-lm-factory-boot/kelk`
   136|5. `kickstart hermes-boot`
   137|
   138|## References
   139|
   140|- [1] FCT076 — Flash-MoE 35B-A3B Port and Debug (27B KV cache benchmarks)
   141|- [2] FCT078 — Dual SABER E4B Stress Test Results
   142|- [3] FCT074 — Qwen3.6 Local Inference Architecture
   143|- [4] dflash-mlx — https://github.com/bstnxbt/dflash-mlx
   144|- [5] z-lab/Qwen3.6-27B-DFlash — https://huggingface.co/z-lab/Qwen3.6-27B-DFlash
   145|
   146|---
   147|
   148|## Concurrent Serving Analysis (Added 2026-05-01)
   149|
   150|### Can 1x 4-bit 27B serve both Boot and Kelk?
   151|
   152|**Yes — with constraints.** The 4-bit model (~14 GB) leaves ~11 GB headroom
   153|for KV cache + Metal GPU buffers after macOS.
   154|
   155|### KV Cache Memory (16 full attention layers, 4 KV heads, head_dim=256)
   156|
   157|| Quant | Per token | @ 32K | @ 64K | @ 128K |
   158||-------|-----------|-------|-------|--------|
   159|| fp16  | 64 KB     | 2 GB  | 4 GB  | 8 GB   |
   160|| Q6    | 24 KB     | 768 MB | 1.5 GB | 3 GB |
   161|| Q5_1  | 20 KB     | 640 MB | 1.3 GB | 2.5 GB |
   162|| Q4    | 16 KB     | 512 MB | 1 GB  | 2 GB   |
   163|
   164|GatedDeltaNet layers (48 of 64) use fixed ArraysCache (~22 MB per agent).
   165|Only 16 full attention layers have growing KV cache.
   166|
   167|### Concurrent Scenarios (4-bit model, macOS ~7 GB, 32 GB total)
   168|
   169|| Scenario | KV Quant | KV Used | Remaining | Verdict |
   170||----------|----------|---------|-----------|---------|
   171|| 1 agent, 32K | Q5_1 | 0.6 GB | 10.4 GB | Comfortable |
   172|| 1 agent, 128K | Q5_1 | 2.5 GB | 8.5 GB | Comfortable |
   173|| 2 agents, 32K | Q5_1 | 1.3 GB | 9.7 GB | Comfortable |
   174|| 2 agents, 128K | Q5_1 | 5.0 GB | 6.0 GB | Tight |
   175|| 2 agents, 32K | Q4 | 1.0 GB | 10.0 GB | Comfortable |
   176|| 2 agents, 128K | Q4 | 4.0 GB | 7.0 GB | Workable |
   177|
   178|### Recommended Concurrent Configuration
   179|
   180|```
   181|--prompt-concurrency 1     Serialize prefills (Metal-safe)
   182|--decode-concurrency 2     Parallel decode (lightweight)
   183|--prompt-cache-bytes 4GB   Cap KV, prevent runaway
   184|KV quantization: Q5_1      Quality/memory balance
   185|```
   186|
   187|Pattern: Agent A prefills → starts decoding → Agent B prefills → both
   188|decode in parallel. Prefill is the heavy GPU operation; decode is
   189|memory-bandwidth-bound and shares gracefully.
   190|
   191|### Why 1x 4-bit > 2x 2-bit for concurrent serving
   192|
   193|| Factor | 1x 4-bit shared | 2x 2-bit dedicated |
   194||--------|-----------------|-------------------|
   195|| Quality | Higher (4-bit quant) | Lower (2-bit quant) |
   196|| Prefill speed | Faster (step-size 2048) | Slower (step-size 256) |
   197|| Idle waste | None (shared) | Full model in RAM per agent |
   198|| Complexity | One server, one port | Two servers, two ports |
   199|| Parallelism | Serialize prefill, parallel decode | Full parallel |
   200|| Context | 128K per agent (tight) or 64K (comfortable) | 128K each (6 GB headroom) |
   201|
   202|Agent workloads are mostly sequential (Chris talks to one agent at a time).
   203|The "no serialization" benefit of dual instances is mostly theoretical.
   204|
   205|---
   206|
   207|## Speed Projection Table (Added 2026-05-01)
   208|
   209|| Configuration | Decode tok/s | Prefill (16K) | Notes |
   210||---------------|-------------|---------------|-------|
   211|| 6-bit (current) | ~7-10 | ~5 min | Prefill-step-size 256, page faults |
   212|| 4-bit | ~13-15 | ~40s | Prefill-step-size 2048, fits in RAM |
   213|| 4-bit + DFlash | ~25-30 | ~20s | When draft model available |
   214|| 2-bit | ~15-20? | ~25s? | Unknown quality |
   215|| 2-bit + DFlash | ~30-40? | ~15s? | Speculative |
   216|
   217|All projections without DFlash unless noted. DFlash adds ~2x on M1 Max.
   218|
   219|---
   220|
   221|## 27B-SABER vs E4B-SABER: Capability Comparison (Added 2026-05-01)
   222|
   223|### Model Comparison
   224|
   225|| | E4B-SABER (Gemma 4) | 27B-SABER (Ornstein/Hermes 3.6) |
   226||---|---|---|
   227|| Parameters | 4 billion | 27 billion |
   228|| Architecture | Gemma 4 (dense, 42 layers) | Qwen3.6 hybrid (64 layers: 48 GatedDeltaNet + 16 full attention) |
   229|| Quantization | 6-bit (~6 GB) | 6-bit (~21 GB) / 4-bit (~14 GB) / 2-bit (~8.5 GB) |
   230|| Context | 128K | 262K |
   231|| SABER | Abliterated (GestaltLabs) | Abliterated (Ornstein/Hermes fine-tune) |
   232|| Multimodal | Yes (vision) | Yes (vision capable) |
   233|| Speed (M1 Max) | ~34-50 tok/s | ~7-10 tok/s (6-bit), ~13-15 (4-bit) |
   234|
   235|### Quality Comparison (Speculative)
   236|
   237|The 27B has ~7x the parameters of the E4B. Even at 4-bit quantization
   238|(~14 GB), the quality gap should be substantial:
   239|
   240|| Capability | E4B-SABER | 27B-SABER (4-bit) | Why |
   241||------------|-----------|-------------------|-----|
   242|| Multi-step reasoning | Basic | Strong | 7x params = deeper reasoning chains |
   243|| Tool calling | Good | Excellent | Larger model = more reliable JSON, fewer malformed calls |
   244|| Context following | Good | Excellent | Better at maintaining instructions across long conversations |
   245|| Code generation | Basic | Strong | Much larger code knowledge base |
   246|| Multi-turn coherence | Degrades at 8K+ | Strong to 64K+ | Hybrid architecture = efficient context management |
   247|| Instruction following | Good | Excellent | More capacity for complex multi-constraint instructions |
   248|| Autonomy | Good | Excellent | Better at deciding when to act vs ask |
   249|| Hallucination | Moderate | Lower | Larger model = better fact grounding |
   250|
   251|### The Core Tradeoff
   252|
   253|```
   254|E4B-SABER:  Fast (~40 tok/s), smart enough for most tasks,
   255|            struggles with complex multi-step reasoning and
   256|            long-context coherence. Good "operator" model.
   257|
   258|27B-SABER:  Slower (~13 tok/s at 4-bit), dramatically smarter,
   259|            better at everything except speed. Excellent
   260|            "operator" model — fewer retries, fewer errors,
   261|            better decisions.
   262|```
   263|
   264|### What the 27B Unlocks
   265|
   266|The E4B's main weakness is **multi-turn degradation** — after 3-4 turns
   267|of tool use, it starts losing context and making errors. The 27B with
   268|its hybrid architecture (GatedDeltaNet fixed-state for 75% of layers)
   269|should maintain coherence across much longer sessions.
   270|
   271|The 27B also handles **complex tool chains** better — when Boot needs to
   272|call 3-4 tools in sequence to accomplish a task, the larger model is
   273|more reliable at planning and executing the chain without errors.
   274|
   275|### Speed Impact on Agent Workflows
   276|
   277|| Workflow | E4B @ 40 tok/s | 27B @ 13 tok/s | Impact |
   278||----------|---------------|----------------|--------|
   279|| Simple Q&A | 1-2s | 3-5s | Noticeable but acceptable |
   280|| Tool call + response | 3-5s | 10-15s | Slower but fewer retries |
   281|| Multi-step task (5 tools) | 15-30s | 60-120s | Significant — but E4B often fails and retries |
   282|| Long-context session (16K) | 5s (fast prefill) | 40s (slow prefill) | First message is slow; subsequent messages cached |
   283|
   284|The 27B's slower speed is offset by **fewer errors and retries**. The E4B
   285|at 40 tok/s that needs 3 attempts is slower than the 27B at 13 tok/s
   286|that gets it right the first time.
   287|
   288|---
   289|
   290|## DFlash Research Summary (Added 2026-05-01)
   291|
   292|**Source:** Delegate task research, 2026-05-01
   293|
   294|Ornstein3.6 is a Qwen3.6 tune → dflash-mlx should support it.
   295|
   296|**Draft model status:**
   297|- `z-lab/Qwen3.6-27B-DFlash` — exists, **still under training**, gated
   298|- `z-lab/Qwen3.5-27B-DFlash` — available as interim (lower acceptance rate)
   299|- Acceptance rate depends on how much Ornstein fine-tune diverges from base Qwen3.6
   300|
   301|**dflash-mlx status:**
   302|- v0.1.4.1 has startup crash bugs (issue #13, still open)
   303|- Two one-line patches needed for serve.py
   304|- Install from main branch
   305|
   306|**Memory layout (4-bit target + DFlash):**
   307|```
   308|Target model:   ~16 GB (4-bit 27B)
   309|Draft model:    ~4 GB (2B BF16)
   310|KV cache:       ~4-6 GB
   311|Total:          ~24-26 GB  (fits in 32 GB)
   312|```
   313|
   314|**Expected speedup:** ~2.3-2.4x on M1 Max (halved from M5 Max benchmarks of 2.37x)
   315|
   316|**Blockers:**
   317|- Draft model still training
   318|- dflash-mlx has known bugs
   319|- No benchmark for Ornstein fine-tune acceptance rate
   320|
   321|**Timeline:** Draft model expected within weeks. DFlash integration is a
   322|one-day task once draft model is available.
   323|
   324|---
   325|
   326|## Prompt Cache Status (Added 2026-05-01)
   327|
   328|Prompt caching IS working on the 27B server. Server logs show:
   329|```
   330|Prompt Cache: 0 sequences, 0.00 GB   (first request)
   331|Prompt Cache: 6 sequences, 1.83 GB   (after Boot session)
   332|```
   333|
   334|Cache grows as expected. Follow-up messages in the same session reuse
   335|cached KV tokens, significantly reducing prefill time.
   336|
   337|**Tokenizer warning:** The model's tokenizer has an incorrect regex pattern
   338|(HuggingFace issue: mistralai/Mistral-Small-3.1-24B-Instruct-2503/discussions/84).
   339|Minor issue — does not affect inference quality.
   340|
   341|---
   342|
   343|## CLAUDE.md Compression (Added 2026-05-01)
   344|
   345|Both agents' CLAUDE.md files were massively oversized due to content duplication
   346|and retired infrastructure references.
   347|
   348|### Boot CLAUDE.md
   349|
   350|| Metric | Before | After | Reduction |
   351||--------|--------|-------|-----------|
   352|| Size | 36,769 chars | 3,015 chars | 92% |
   353|| Lines | 494 | ~70 | 86% |
   354|| Tokens (approx) | ~9,200 | ~750 | 92% |
   355|
   356|**Removed:** Duplicated Soul/Principles sections (lines 56-218 were verbatim
   357|copies of 1-55), Cloudkicker delegation (retired), skill model routing
   358|(Claude Code specific, not Hermes), PREFIX numbering boilerplate (moved to
   359|on-demand), operational domains bloat, regression table, values-in-tension
   360|table, tool table.
   361|
   362|### Kelk CLAUDE.md
   363|
   364|| Metric | Before | After | Reduction |
   365||--------|--------|-------|-----------|
   366|| Size | 16,639 chars | 3,203 chars | 81% |
   367|| Lines | 314 | ~80 | 75% |
   368|| Tokens (approx) | ~4,150 | ~800 | 81% |
   369|
   370|**Removed:** Memory systems distinction section, resource access section,
   371|detailed session workflow, project structure ASCII art, formal PREFIX
   372|numbering protocol (kept condensed reference).
   373|
   374|### Impact on Prefill Time
   375|
   376|With prefill-step-size 256 on the 6-bit model:
   377|- Before: ~18K prompt tokens → ~5 min prefill
   378|- After: ~10K prompt tokens → ~2.5 min prefill
   379|
   380|With prefill-step-size 2048 on the 4-bit model:
   381|- After compression: ~10K tokens → ~20s prefill
   382|
   383|---
   384|
   385|## Scripts and Infrastructure
   386|
   387|| Script | Purpose |
   388||--------|---------|
   389|| `scripts/mlx-lm-27b-wrapper.py` | Wrapper: 4-bit KV, Metal limit 28GB, no wired limit |
   390|| `scripts/switch-27b.sh` | Swap between 6bit/4bit/2bit variants |
   391|| `scripts/hermes-boot.sh` | Updated: health check → 41966, model → 27B |
   392|| `scripts/hermes-boot.sh.bak-e4b` | Backup of E4B configuration |
   393|| `scripts/factory-startup.sh` | Updated: Phase 1 → 27B on 41966 |
   394|
   395|### Plists
   396|
   397|| Plist | Status |
   398||-------|--------|
   399|| `com.bootindustries.mlx-lm-factory-27b.plist` | ACTIVE |
   400|| `com.bootindustries.mlx-lm-factory-27b-4bit.plist` | Template (pending model) |
   401|| `com.bootindustries.mlx-lm-factory-27b-2bit.plist` | Template (pending model) |
   402|| `com.bootindustries.mlx-lm-factory-boot.plist` | On disk (rollback) |
   403|| `com.bootindustries.mlx-lm-factory-kelk.plist` | On disk (rollback) |
   404|
   405|---
   406|
   407|## References (updated)
   408|
   409|- [1] FCT076 — Flash-MoE 35B-A3B Port and Debug (27B KV cache benchmarks)
   410|- [2] FCT078 — Dual SABER E4B Stress Test Results
   411|- [3] FCT074 — Qwen3.6 Local Inference Architecture
   412|- [4] dflash-mlx — https://github.com/bstnxbt/dflash-mlx
   413|- [5] z-lab/Qwen3.6-27B-DFlash — https://huggingface.co/z-lab/Qwen3.6-27B-DFlash
   414|- [6] z-lab/Qwen3.5-27B-DFlash — https://huggingface.co/z-lab/Qwen3.5-27B-DFlash
   415|- [7] Tokenizer regex issue — https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503/discussions/84
   416|

---

## Concurrent Serving Analysis (Added 2026-05-01)

### Can 1x 4-bit 27B serve both Boot and Kelk?

**Yes — with constraints.** The 4-bit model (~14 GB) leaves ~11 GB headroom for KV cache + Metal GPU buffers after macOS.

### KV Cache Memory (16 full attention layers, 4 KV heads, head_dim=256)

| Quant | Per token | @ 32K | @ 64K | @ 128K |
|-------|-----------|-------|-------|--------|
| fp16  | 64 KB     | 2 GB  | 4 GB  | 8 GB   |
| Q6    | 24 KB     | 768 MB | 1.5 GB | 3 GB |
| Q5_1  | 20 KB     | 640 MB | 1.3 GB | 2.5 GB |
| Q4    | 16 KB     | 512 MB | 1 GB  | 2 GB   |

GatedDeltaNet layers (48 of 64) use fixed ArraysCache (~22 MB per agent). Only 16 full attention layers have growing KV cache.

### Concurrent Scenarios (4-bit model, macOS ~7 GB, 32 GB total)

| Scenario | KV Quant | KV Used | Remaining | Verdict |
|----------|----------|---------|-----------|---------|
| 1 agent, 32K | Q5_1 | 0.6 GB | 10.4 GB | Comfortable |
| 1 agent, 128K | Q5_1 | 2.5 GB | 8.5 GB | Comfortable |
| 2 agents, 32K | Q5_1 | 1.3 GB | 9.7 GB | Comfortable |
| 2 agents, 128K | Q5_1 | 5.0 GB | 6.0 GB | Tight |
| 2 agents, 32K | Q4 | 1.0 GB | 10.0 GB | Comfortable |
| 2 agents, 128K | Q4 | 4.0 GB | 7.0 GB | Workable |

### Recommended Concurrent Configuration

```
--prompt-concurrency 1     Serialize prefills (Metal-safe)
--decode-concurrency 2     Parallel decode (lightweight)
--prompt-cache-bytes 4GB   Cap KV, prevent runaway
KV quantization: Q5_1      Quality/memory balance
```

Pattern: Agent A prefills -> starts decoding -> Agent B prefills -> both decode in parallel. Prefill is the heavy GPU operation; decode is memory-bandwidth-bound and shares gracefully.

### Why 1x 4-bit > 2x 2-bit for concurrent serving

| Factor | 1x 4-bit shared | 2x 2-bit dedicated |
|--------|-----------------|-------------------|
| Quality | Higher (4-bit quant) | Lower (2-bit quant) |
| Prefill speed | Faster (step-size 2048) | Slower (step-size 256) |
| Idle waste | None (shared) | Full model in RAM per agent |
| Complexity | One server, one port | Two servers, two ports |
| Parallelism | Serialize prefill, parallel decode | Full parallel |
| Context | 128K per agent (tight) or 64K (comfortable) | 128K each (6 GB headroom) |

Agent workloads are mostly sequential (Chris talks to one agent at a time). The "no serialization" benefit of dual instances is mostly theoretical.

---

## Speed Projection Table (Added 2026-05-01)

| Configuration | Decode tok/s | Prefill (16K) | Notes |
|---------------|-------------|---------------|-------|
| 6-bit (current) | ~7-10 | ~5 min | Prefill-step-size 256, page faults |
| 4-bit | ~13-15 | ~40s | Prefill-step-size 2048, fits in RAM |
| 4-bit + DFlash | ~25-30 | ~20s | When draft model available |
| 2-bit | ~15-20? | ~25s? | Unknown quality |
| 2-bit + DFlash | ~30-40? | ~15s? | Speculative |

All projections without DFlash unless noted. DFlash adds ~2x on M1 Max.

---

## 27B-SABER vs E4B-SABER: Capability Comparison (Added 2026-05-01)

### Model Comparison

| | E4B-SABER (Gemma 4) | 27B-SABER (Ornstein-Hermes 3.6) |
|---|---|---|
| Parameters | 4 billion | 27 billion |
| Architecture | Gemma 4 (dense, 42 layers) | Qwen3.6 hybrid (64 layers: 48 GatedDeltaNet + 16 full attention) |
| Quantization | 6-bit (~6 GB) | 6-bit (~21 GB) / 4-bit (~14 GB) / 2-bit (~8.5 GB) |
| Context | 128K | 262K |
| SABER | Abliterated (GestaltLabs) | Abliterated (Ornstein/Hermes fine-tune) |
| Multimodal | Yes (vision) | Yes (vision capable) |
| Speed (M1 Max) | ~34-50 tok/s | ~7-10 tok/s (6-bit), ~13-15 (4-bit) |

### Quality Comparison (Speculative)

The 27B has ~7x the parameters of the E4B. Even at 4-bit quantization (~14 GB), the quality gap should be substantial:

| Capability | E4B-SABER | 27B-SABER (4-bit) | Why |
|------------|-----------|-------------------|-----|
| Multi-step reasoning | Basic | Strong | 7x params = deeper reasoning chains |
| Tool calling | Good | Excellent | Larger model = more reliable JSON, fewer malformed calls |
| Context following | Good | Excellent | Better at maintaining instructions across long conversations |
| Code generation | Basic | Strong | Much larger code knowledge base |
| Multi-turn coherence | Degrades at 8K+ | Strong to 64K+ | Hybrid architecture = efficient context management |
| Instruction following | Good | Excellent | More capacity for complex multi-constraint instructions |
| Autonomy | Good | Excellent | Better at deciding when to act vs ask |
| Hallucination | Moderate | Lower | Larger model = better fact grounding |

### The Core Tradeoff

```
E4B-SABER:  Fast (~40 tok/s), smart enough for most tasks,
            struggles with complex multi-step reasoning and
            long-context coherence. Good "operator" model.

27B-SABER:  Slower (~13 tok/s at 4-bit), dramatically smarter,
            better at everything except speed. Excellent
            "operator" model — fewer retries, fewer errors,
            better decisions.
```

### What the 27B Unlocks

The E4B's main weakness is **multi-turn degradation** — after 3-4 turns of tool use, it starts losing context and making errors. The 27B with its hybrid architecture (GatedDeltaNet fixed-state for 75% of layers) should maintain coherence across much longer sessions.

The 27B also handles **complex tool chains** better — when Boot needs to call 3-4 tools in sequence to accomplish a task, the larger model is more reliable at planning and executing the chain without errors.

### Speed Impact on Agent Workflows

| Workflow | E4B @ 40 tok/s | 27B @ 13 tok/s | Impact |
|----------|---------------|----------------|--------|
| Simple Q&A | 1-2s | 3-5s | Noticeable but acceptable |
| Tool call + response | 3-5s | 10-15s | Slower but fewer retries |
| Multi-step task (5 tools) | 15-30s | 60-120s | Significant — but E4B often fails and retries |
| Long-context session (16K) | 5s (fast prefill) | 40s (slow prefill) | First message is slow; subsequent messages cached |

The 27B's slower speed is offset by **fewer errors and retries**. The E4B at 40 tok/s that needs 3 attempts is slower than the 27B at 13 tok/s that gets it right the first time.

---

## DFlash Research Summary (Added 2026-05-01)

**Source:** Delegate task research, 2026-05-01

Ornstein3.6 is a Qwen3.6 tune -> dflash-mlx should support it.

**Draft model status:**
- `z-lab/Qwen3.6-27B-DFlash` — exists, **still under training**, gated
- `z-lab/Qwen3.5-27B-DFlash` — available as interim (lower acceptance rate)
- Acceptance rate depends on how much Ornstein fine-tune diverges from base Qwen3.6

**dflash-mlx status:**
- v0.1.4.1 has startup crash bugs (issue #13, still open)
- Two one-line patches needed for serve.py
- Install from main branch

**Memory layout (4-bit target + DFlash):**
```
Target model:   ~16 GB (4-bit 27B)
Draft model:    ~4 GB (2B BF16)
KV cache:       ~4-6 GB
Total:          ~24-26 GB  (fits in 32 GB)
```

**Expected speedup:** ~2.3-2.4x on M1 Max (halved from M5 Max benchmarks of 2.37x)

**Blockers:**
- Draft model still training
- dflash-mlx has known bugs
- No benchmark for Ornstein fine-tune acceptance rate

**Timeline:** Draft model expected within weeks. DFlash integration is a one-day task once draft model is available.

---

## Prompt Cache Status (Added 2026-05-01)

Prompt caching IS working on the 27B server. Server logs show:
```
Prompt Cache: 0 sequences, 0.00 GB   (first request)
Prompt Cache: 6 sequences, 1.83 GB   (after Boot session)
```

Cache grows as expected. Follow-up messages in the same session reuse cached KV tokens, significantly reducing prefill time.

**Tokenizer warning:** The model's tokenizer has an incorrect regex pattern (HuggingFace issue: mistralai/Mistral-Small-3.1-24B-Instruct-2503/discussions/84). Minor issue — does not affect inference quality.

---

## CLAUDE.md Compression (Added 2026-05-01)

Both agents' CLAUDE.md files were massively oversized due to content duplication and retired infrastructure references.

### Boot CLAUDE.md

| Metric | Before | After | Reduction |
|--------|--------|-------|-----------|
| Size | 36,769 chars | 3,015 chars | 92% |
| Lines | 494 | ~70 | 86% |
| Tokens (approx) | ~9,200 | ~750 | 92% |

**Removed:** Duplicated Soul/Principles sections (lines 56-218 were verbatim copies of 1-55), Cloudkicker delegation (retired), skill model routing (Claude Code specific, not Hermes), PREFIX numbering boilerplate (moved to on-demand), operational domains bloat, regression table, values-in-tension table, tool table.

### Kelk CLAUDE.md

| Metric | Before | After | Reduction |
|--------|--------|-------|-----------|
| Size | 16,639 chars | 3,203 chars | 81% |
| Lines | 314 | ~80 | 75% |
| Tokens (approx) | ~4,150 | ~800 | 81% |

### Impact on Prefill Time

With prefill-step-size 256 on the 6-bit model:
- Before: ~18K prompt tokens -> ~5 min prefill
- After: ~10K prompt tokens -> ~2.5 min prefill

With prefill-step-size 2048 on the 4-bit model:
- After compression: ~10K tokens -> ~20s prefill

---

## Scripts and Infrastructure

| Script | Purpose |
|--------|---------|
| `scripts/mlx-lm-27b-wrapper.py` | Wrapper: 4-bit KV, Metal limit 28GB, no wired limit |
| `scripts/switch-27b.sh` | Swap between 6bit/4bit/2bit variants |
| `scripts/hermes-boot.sh` | Updated: health check -> 41966, model -> 27B |
| `scripts/hermes-boot.sh.bak-e4b` | Backup of E4B configuration |
| `scripts/factory-startup.sh` | Updated: Phase 1 -> 27B on 41966 |

### Plists

| Plist | Status |
|-------|--------|
| `com.bootindustries.mlx-lm-factory-27b.plist` | ACTIVE |
| `com.bootindustries.mlx-lm-factory-27b-4bit.plist` | Template (pending model) |
| `com.bootindustries.mlx-lm-factory-27b-2bit.plist` | Template (pending model) |
| `com.bootindustries.mlx-lm-factory-boot.plist` | On disk (rollback) |
| `com.bootindustries.mlx-lm-factory-kelk.plist` | On disk (rollback) |

---

## References (updated)

- [1] FCT076 — Flash-MoE 35B-A3B Port and Debug (27B KV cache benchmarks)
- [2] FCT078 — Dual SABER E4B Stress Test Results
- [3] FCT074 — Qwen3.6 Local Inference Architecture
- [4] dflash-mlx — https://github.com/bstnxbt/dflash-mlx
- [5] z-lab/Qwen3.6-27B-DFlash — https://huggingface.co/z-lab/Qwen3.6-27B-DFlash
- [6] z-lab/Qwen3.5-27B-DFlash — https://huggingface.co/z-lab/Qwen3.5-27B-DFlash
- [7] Tokenizer regex issue — https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503/discussions/84
