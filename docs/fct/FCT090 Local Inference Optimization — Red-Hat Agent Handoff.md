# FCT090 Local Inference Optimization — Red-Hat Agent Handoff

**Status:** Active — optimization sprint open
**Date:** 2026-05-02
**Machine:** Whitebox (Mac Studio M2 Max, 32 GB unified memory, Apple Silicon)
**Scope:** Maximum throughput and quality from local small models under hardware constraints

---

## Mission

Extract the maximum practical performance from Whitebox's local inference stack. The production model (Nemostein-3-Hermes-Omni, 30B/3B, Mamba+MoE hybrid) is now served via **vllm-mlx** — a server with continuous batching, prefix caching, and structured output support that mlx_lm.server lacks. We have benchmark data on the models but have not yet characterized vllm-mlx's behavior, tuned its parameters, or explored the remaining headroom on the hardware. That is your job.

Red-hat posture: assume every default is wrong until proven otherwise. Look for configuration gaps, unexplored levers, and performance cliffs. Report what you find, propose concrete changes, implement only what is approved.

---

## Current Production State

### Model Server

| Item | Value |
|------|-------|
| Server | vllm-mlx (installed at `~/.local/share/uv/tools/vllm-mlx/`) |
| Model | Nemostein-3-Hermes-Omni-30b-a3b-MLX-mixed_3_4 |
| Architecture | Nemotron-H: Mamba SSM + MoE (30B total / 3B active per token) |
| Quantization | mixed_3_4 (13 GB disk) |
| Port | :41966 (shared by Boot and Kelk) |
| Reasoning parser | qwen3 (strips `<think>` → `reasoning_content`) |
| Tool call parser | nemotron |
| KV cache | 4-bit quantized |
| Prefix caching | enabled |
| GPU memory utilization | 65% (~21 GB) |
| Plist label | `com.bootindustries.mlx-lm-factory-nemostein` (currently `.disabled` — vllm-mlx plist not yet deployed) |

**Note:** As of 2026-05-02, :41966 is down. The vllm-mlx plist for Nemostein has not been deployed yet. This is the primary gap to address.

### Hermes Gateways

Both Boot and Kelk route through Hermes gateways pointed at :41966 with `model=nemostein`. Scripts: `scripts/hermes-boot.sh`, `scripts/hermes-kelk.sh`.

### Benchmark Scripts

Located in `scripts/`. All currently test against `mlx_lm.server` — they need vllm-mlx variants before they reflect production behavior.

| Script | Purpose |
|--------|---------|
| `benchmark_utils.py` | Shared utilities: `find_mlx_python()`, `get_mem()`, `wait_server()`, `write_wrapper()`, `query()` |
| `test-27b-saber-v2.py` | 6 quality tests + memory (6bit/4bit via `VARIANT` env) |
| `test-27b-saber-stress.py` | Context scaling 1K–32K + memory profiling |
| `test-27b-saber-dual.py` | Dual instance viability (4bit only) |
| `test-26b-a4b-v2.py` | 6 quality tests + memory |
| `test-26b-a4b-stress.py` | Context scaling |
| `test-26b-a4b-4bit-dual.py` | Dual instance viability |

`benchmark_utils.py` is clean and reusable. All new vllm-mlx benchmark scripts must import from it.

---

## What Was Done in This Session (2026-05-02)

The benchmark scripts were audited and refactored before this handoff. Agents reading this doc start with a clean harness. Key changes committed to `main`:

### `benchmark_utils.py` (new)

Extracted all shared logic out of the individual scripts into a single module. Previously, each script maintained its own copy of server-wait logic, memory parsing, and (in the 27B scripts) an identical `make_quantized_cache` wrapper — meaning any fix had to be applied in three places.

The module provides:

- **`find_mlx_python()`** — resolves the mlx-lm Python interpreter without hardcoding the version. Searches Homebrew Cellar by glob (sorted, newest wins), falls back to the PATH shim, then `sys.executable`. Previously every script had `/opt/homebrew/Cellar/mlx-lm/0.31.3/libexec/bin/python` hardcoded — one `brew upgrade` away from a silent breakage.

- **`get_vm_stats()` / `get_mem()`** — key-based `vm_stat` parsing. The old v1 script (`test-26b-a4b.py`) parsed `vm_stat` by line index (lines 1, 2, 7) — brittle against any macOS update that adds or reorders output fields. The 27B scripts had already fixed this; `get_mem()` in `test-26b-a4b-v2.py` had not, and also contained a dead `requests.get()` call inside the memory function left over from debugging.

- **`wait_server(port, timeout, proc)`** — unified health poller with early-exit on process death. If the server crashes before the timeout, it reads stdout and prints it before returning `False`. Previously, two scripts (26B stress, 27B stress) used a bare `for _ in range(180): ... time.sleep(1)` loop that fell through silently if the server never started — subsequent queries would all return errors with no clear diagnosis.

- **`make_wrapper_script()` / `write_wrapper()`** — single canonical copy of the `make_quantized_cache` KV cache patch for Qwen3.5 hybrid models. Was copy-pasted verbatim across all three 27B scripts. A fix to the GatedDeltaNet detection or KV bit depth previously required touching three files.

### Per-script fixes

- **All six scripts:** Hardcoded Cellar Python path replaced with `find_mlx_python()`.

- **`test-27b-saber-stress.py`, `test-26b-a4b-stress.py`:** Bare server-start loop replaced with `wait_server(..., proc=proc)`.

- **`test-27b-saber-dual.py`, `test-26b-a4b-4bit-dual.py`:** Magic baseline constants (`wired - 3.1`, `active - 3.5`) replaced with a captured pre-load baseline subtracted at runtime. The constants assumed a fixed OS wired memory overhead that will not hold across reboots or different system load.

- **`test-26b-a4b-v2.py`:** Removed dead `requests.get("localhost:41967/v1/models")` call inside `get_mem()`. Replaced fragile line-index `vm_stat` parsing with the key-based version.

- **`test-27b-saber-v2.py`, `test-27b-saber-stress.py`, `test-27b-saber-dual.py`:** `WRAPPER_SCRIPT` constant removed; replaced with `write_wrapper()` from `benchmark_utils.py`.

### What the scripts do NOT yet cover

The scripts still use `mlx_lm.server` as the server backend. They will not test vllm-mlx behavior, continuous batching, or prefix caching. A new script (`test-nemostein-vllm-v1.py`) is needed. See Immediate Priorities.

---

## Hardware Constraints

- **RAM:** 32 GB unified memory (CPU + GPU share the same pool)
- **Model footprint:** Nemostein wires ~17.6 GB; ~1.2 GB free at idle after single instance
- **vllm-mlx GPU memory target:** 65% → ~21 GB. This leaves ~11 GB for OS + Hermes + other services
- **No swap for inference:** macOS will page compress, not swap to SSD — OOM kills are hard stops
- **Single GPU device:** No multi-GPU scheduling, no tensor parallelism possible
- **Concurrency model:** Both agents (Boot, Kelk) share one server instance. Sequential decode unless vllm-mlx continuous batching allows true overlap

---

## Benchmark Baseline (mlx_lm.server, FCT089)

These numbers are from mlx_lm.server and serve as the comparison floor for vllm-mlx. Any vllm-mlx benchmark should be run against the same prompt suite to be directly comparable.

| Metric | Nemostein 30B/3B mixed_3_4 |
|--------|---------------------------|
| Short context tok/s | 48–50 |
| ~1K context tok/s | 47 |
| ~4K context tok/s | 44.5 |
| ~8K context tok/s | 43.6 |
| ~16K context tok/s | 42.7 |
| ~32K context tok/s | 30.4 |
| ~64K context tok/s | 23.0 |
| RAM after load | ~17.6 GB wired, ~1.2 GB free |
| All 6 quality tests | PASS |

Key property: Mamba layers give near-flat decode speed up to ~16K. Speed only drops meaningfully at 32K+ where attention layers' KV cache begins to dominate. This is the architectural advantage of the Nemotron-H hybrid — pure transformer models OOM or drop to <5 tok/s at these context lengths.

---

## Known Unknowns — Optimization Surface

These are the specific gaps and levers that have not been characterized. Each is a candidate optimization target.

### 1. vllm-mlx vs mlx_lm.server delta

We do not yet know what vllm-mlx buys us for this specific model. Theoretical gains:

- **Continuous batching:** Requests from Boot and Kelk can be interleaved mid-decode rather than queuing behind each other
- **Prefix caching:** Shared system prompts cached at the KV level — relevant since both agents have identical context file structure
- **PagedAttention:** Better KV memory management under concurrent load, fewer evictions
- **Structured outputs:** Native JSON schema enforcement without prompt engineering

What we don't know: whether continuous batching applies cleanly to Mamba layers (recurrent state must be maintained per-sequence — unclear if it batches the way attention does), whether prefix caching works with quantized KV, and what the scheduler overhead cost is relative to mlx_lm's simpler model.

vllm-mlx may also be slower than mlx_lm.server in single-request latency due to scheduler overhead. That would be acceptable if concurrent throughput improves. It must be measured, not assumed.

**Target:** Benchmark Nemostein under vllm-mlx with the same test suite as FCT089. Determine if tok/s is higher, lower, or equivalent. Measure latency under concurrent load (2 simultaneous requests, one per agent).

### 2. GPU memory utilization target

Currently set to 65% (~21 GB). This is conservative — chosen to leave headroom for OS and Hermes processes, but not calibrated against actual measured peak.

- **Pushing higher (70–75%):** More KV cache headroom, better prefix cache hit rate under long sessions. Risk: less room for OS/Hermes under memory pressure events.
- **Pulling lower (55–60%):** More stable under agent load spikes. Risk: prefix cache evictions on longer sessions.

The right number is empirical — profile actual peak during realistic Boot+Kelk concurrent load, then set the ceiling at measured peak + ~10% margin.

**Target:** Profile peak memory under concurrent load. Find highest stable utilization without OOM under realistic workload.

### 3. Prefix cache effectiveness

Both agents load a `context.md` file at conversation start — a structured prompt of several KB covering the agent's persona, current projects, and tool inventory. If both agents share a common prefix (system prompt header, boilerplate), vllm-mlx's prefix cache should amortize that prefill cost across all turns.

We have not measured cache hit rate. The per-agent customization (name, role, persona) may break the prefix match early enough that caching provides no benefit. Or the common structure may be long enough that it dominates. Not known.

**Target:** Inspect Boot and Kelk context files. Identify the longest common prefix. Measure cache hit rate via vllm-mlx metrics endpoint. If the common prefix is short, consider restructuring context files to front-load shared boilerplate.

### 4. KV cache quantization for Nemostein

Current: 4-bit KV. This setting was carried over from the mlx_lm wrapper scripts developed for the 27B-SABER (Qwen3.5 hybrid) and 26B-A4B (Gemma4 MoE) models — both pure-transformer architectures with large KV caches.

Nemostein's Mamba layers use fixed-size recurrent SSM state — not a KV cache. Only the attention layers (sparse in the MEMEM* hybrid pattern, roughly 25% of layers) accumulate a KV cache. This means:

- The KV footprint is far smaller than for a pure-transformer model of equivalent size
- Aggressive 4-bit KV quantization may be buying very little memory savings at possible quality cost
- Testing 8-bit KV or fp16 KV costs minimal additional RAM and may improve output quality on reasoning-heavy tasks

**Target:** Run quality benchmarks at 4-bit vs 8-bit KV. Measure memory delta. Determine if there is a quality/memory tradeoff worth taking given Nemostein's hybrid architecture.

### 5. mixed_3_4 quantization vs alternatives

Nemostein is running `mixed_3_4` (mixed 3-bit and 4-bit per-layer, 13 GB). This was selected on speed and memory grounds in FCT089 where it won the benchmark comparison. But the tradeoff space hasn't been fully explored:

- Is there a `mixed_4_6` or pure 4-bit variant? Higher quality at ~4 GB additional cost — viable on 32 GB?
- Is there a 3-bit or 2-bit variant that fits in ~9 GB, enabling dual-instance serving or headroom for additional services?
- Does the mixed quantization apply uniformly, or selectively (attention heads at higher precision, Mamba at lower)? The latter would be architecturally sound.

**Target:** Inventory available Nemostein quantization variants in `~/models/`. If only `mixed_3_4` is present, assess whether building an alternative is worthwhile given current performance. Quantize-on-demand tooling is available via mlx-lm.

### 6. Concurrent agent load behavior

Boot and Kelk share one server with no explicit prioritization. Under concurrent load:

- Does vllm-mlx's scheduler give equal throughput to both requests, or does one starve?
- What is per-request latency at P50 and P99 under 2-request concurrency?
- Does Mamba's recurrent state complicate batching? (SSM state is sequence-specific — each sequence in a batch needs independent state vectors. This is different from attention where KV is the per-sequence state and batching is well-understood.)

**Target:** Simulate concurrent Boot+Kelk load. Measure per-request latency distribution. Confirm neither agent degrades unacceptably. If one agent starves, investigate vllm-mlx priority or fairness parameters.

### 7. Hermes gateway timeouts and retry config

Hermes gateways route to :41966 with a timeout configuration inherited from earlier mlx_lm deployments. If vllm-mlx has higher first-token latency (scheduler overhead before decode begins), existing timeouts may be too tight and cause spurious retries. Conversely, if prefix caching reduces common-turn latency, timeouts can be tightened.

**Target:** Review Hermes gateway configs for timeout values (without printing credentials). Calibrate against measured vllm-mlx P50/P99 first-token latency.

---

## Immediate Priorities (ordered)

1. **Deploy the vllm-mlx plist.** The server is installed at `~/.local/share/uv/tools/vllm-mlx/` but has no active plist. Write `plists/com.bootindustries.mlx-lm-factory-nemostein.plist` using the parameters from commit `e0b8717` (model path, port :41966, reasoning parser `qwen3`, tool parser `nemotron`, KV 4-bit, prefix caching, 65% GPU memory). Bootstrap it. Confirm :41966 responds to `/v1/models`.

2. **Write `test-nemostein-vllm-v1.py`** using `benchmark_utils.py`. Run the same 6-quality + context-scaling suite used in FCT089. This is the apples-to-apples comparison against the mlx_lm.server baseline. Save results to `FCT090-nemostein-vllm-benchmark.json`.

3. **Measure concurrent load.** Send 2 simultaneous requests (simulating Boot and Kelk). Record per-request latency (first token + total) and throughput. Compare to single-request baseline to quantify the cost of sharing.

4. **Profile prefix cache hit rate** for Boot and Kelk. Inspect context files, identify common prefix length. Check if vllm-mlx exposes a metrics endpoint (`/metrics` Prometheus scrape or similar). Report cache hit rate under realistic multi-turn conversation load.

5. **Tune GPU memory utilization target.** Profile peak during concurrent load. Set the ceiling empirically. Increment in 5% steps, stress test at each step, stop before the first OOM.

6. **Assess KV quantization for Nemostein.** Given the hybrid architecture (only ~25% attention layers), test 8-bit KV. Report quality delta and memory cost. Recommend whether to change the production setting.

7. **Calibrate Hermes timeouts.** Measure P99 first-token latency from vllm-mlx under both single and concurrent load. Compare to current Hermes timeout values. Propose adjustments if warranted.

---

## Constraints and Rules

- **Do NOT restart the model server without operator approval.** It serves both agents.
- **Do NOT modify `hermes-boot.sh` or `hermes-kelk.sh`** without reading the current config first — they contain production credentials injected via Infisical. Never print or echo credential values.
- **Do NOT install litellm** — supply chain attack. Pip-blocked via `~/.config/pip/constraints.txt`.
- **Do NOT modify model files** in `~/models/`.
- **Do NOT modify `benchmark_utils.py`** without understanding what all six existing scripts depend on. Changes to `wait_server()` or `get_mem()` signatures will break callers.
- **All benchmark results saved to** `docs/fct/FCT090-*.json`.
- **All code changes committed** with `type(scope): description` + `Co-Authored-By` trailer.
- **Document findings** in follow-up FCT docs (FCT091+) per the PREFIX convention.

---

## File Map

```
factory/
├── scripts/
│   ├── benchmark_utils.py              # Shared benchmark utilities — import this, don't copy it
│   ├── test-27b-saber-v2.py            # mlx_lm quality benchmark (27B)
│   ├── test-27b-saber-stress.py        # mlx_lm context scaling (27B)
│   ├── test-27b-saber-dual.py          # mlx_lm dual instance (27B 4bit)
│   ├── test-26b-a4b-v2.py             # mlx_lm quality benchmark (26B)
│   ├── test-26b-a4b-stress.py         # mlx_lm context scaling (26B)
│   ├── test-26b-a4b-4bit-dual.py      # mlx_lm dual instance (26B 4bit)
│   ├── factory-startup.sh             # Sequenced boot (Phase 1 = nemostein on :41966)
│   ├── hermes-boot.sh                 # Boot Hermes gateway launch (read-only — has credentials)
│   └── hermes-kelk.sh                 # Kelk Hermes gateway launch (read-only — has credentials)
├── plists/
│   └── (nemostein plist not yet present — Priority 1)
├── docs/fct/
│   ├── FCT087 Ornstein-Hermes-3.6-27B Deployment on Whitebox.md   # wrapper script design, KV cache patch
│   ├── FCT088 Ornstein-26B-A4B-it-MLX-6bit Testing.md             # MoE memory behavior, mmap page sharing
│   └── FCT089 Ornstein Model Family Comprehensive Benchmarks.md   # primary baseline ← start here
└── infra/
    └── ports.csv                       # Port assignments
```

---

## References

- [1] FCT089 — Ornstein Model Family Comprehensive Benchmarks (primary baseline, all model comparisons)
- [2] FCT087 — 27B-SABER Deployment (KV cache patch for Qwen3.5 hybrid, wrapper script design)
- [3] FCT088 — 26B-A4B Testing (MoE memory behavior, mmap page sharing between instances)
- [4] commit `e0b8717` — vllm-mlx + Nemostein production switch decision and parameters
- [5] vllm-mlx binary: `~/.local/bin/vllm-mlx` | install: `~/.local/share/uv/tools/vllm-mlx/`
- [6] Model: `~/models/Nemostein-3-Hermes-Omni-30b-a3b-MLX-mixed_3_4/`
- [7] Benchmark harness refactor: this session (2026-05-02) — see git log for `scripts/benchmark_utils.py`
