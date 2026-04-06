# FCT002 Factory Agent Architecture — Roles, Models, and Autonomous Loop Design

**Prefix:** FCT
**Repo:** `~/dev/factory/`
**Date:** 2026-03-16
**Revised:** 2026-03-16 (post architecture review + model inventory pass); 2026-03-31 (port re-plumb — all MLX-LM ports updated)
**Status:** Living document — open questions explicitly marked
**Related:** FCT001, BKX074, BKX078, BKX079, BKX080, ATR001, ATR002

---

## 1. Executive Summary

This document synthesizes three research passes (projects-vault Qdrant search across BKX/FCT/OLM/KLK/IG88 prefixes, research-vault practitioner literature, and the ATR001/ATR002 autoresearch/autoscope docs) plus a full model inventory of `/Volumes/CL T04/` into a consolidated architecture for Factory's agent system. It supersedes the agent architecture sections of FCT001 and BKX078 where they conflict.

**What is decided:** Hardware (Mac Studio M1 Max, "Whitebox"), inference backend (MLX-LM primary, Ollama for model serving and embeddings), four permanent agents (Boot, IG-88, Kelk, Nan), model assignments per agent (see section 3), SRE monitoring folded into coordinator-rs Phase 3F (no SRE agent), and the Nan/Researcher relationship (Nan observes, Researcher executes ephemerally).

**What is new from this revision:** Model assignments resolved using the actual `/Volumes/CL T04/` inventory. Boot model inconsistency resolved. SRE question closed. Nan role clarified as always-on lightweight observer. 9B reasoning tier confirmed (Qwen3.5-9B-Opus-Distilled) as on-demand with managed eviction. Solo intensive session model identified (Qwen3.5-27B-Opus-Distilled). Expert subagent pool confirmed as single shared Qwen3.5-4B instance. LFM2.5-3B does not exist — Kelk upgrade path revised.

**Critical path (in order):** Resolve IG-88 trading backtest → define IG-88 metrics precisely → benchmark Whitebox on arrival → implement LFM2.5 tool-call adapter → run autoscope before any autonomous loop goes live.

---

## 2. Hardware and Inference Stack

### 2.1 Whitebox Specification

| Property | Value |
|---|---|
| Machine | Mac Studio M1 Max |
| Unified memory | 32GB |
| Effective inference budget | ~24GB (sysctl `iogpu.wired_limit_mb=24576` required; default cap is ~22GB) |
| Memory bandwidth | 400 GB/s |
| CPU | 10-core |
| GPU | 24-core |
| Storage | 512GB SSD |
| Cooling | Active — sustained 24/7 workloads without throttling |
| Acquisition | Open box, Best Buy Canada, ~$1,270 CAD |
| Role | Primary inference server, replaces Blackbox (RP5) and Greybox (2012 Mac Mini) |

LLM inference is memory-bandwidth-bound, not compute-bound [1]. At 400 GB/s unified memory bandwidth, Whitebox can sustain multiple concurrent small model instances without the host-to-device transfer bottleneck present in discrete GPU setups. macOS imposes a ~70% GPU wiring limit by default (~22GB on 32GB); the sysctl override raises this to ~24GB. Models that overflow the GPU budget fall to CPU memory bandwidth (~68 GB/s) — still functional but roughly 5-6x slower.

### 2.2 Inference Backend

**Primary: MLX-LM** — Apple's native inference framework, direct Metal GPU utilization. Confirmed compatible with Qwen3.5, LFM2.5, and Nanbeige4.1 series. Optimal for Apple Silicon. All agent models use MLX format.

**Model serving: MLX-LM** — per-agent dedicated server instances on reserved ports (see section 2.3). Multiple agent sessions can share one loaded model instance without loading separate weights. This is the key mechanism enabling the Nanbeige weight-sharing pattern (section 3).

**Embeddings: nomic-embed-text via Ollama** — retained for Qdrant semantic retrieval.

**Rejected: vLLM** — datacenter architecture, incompatible with unified memory model. Confirmed failure on MoE architectures in practitioner testing [2].

**Note: LFM2.5 tool-call format blocker.** Liquid's tool-call format is a Pythonic list structure, not the JSON schema coordinator-rs dispatches. A coordinator-side adapter must be implemented before any LFM2.5 model enters an agent slot that issues tool calls. This is a bounded code task, not a research task. Affects Boot and any LFM2.5-based expert subagent. Does not affect Nan (observer role, Matrix messages only).

### 2.3 Memory Budget

**Always-on permanent stack:**

| Component | Port | Model | Quant | Size | Notes |
|---|---|---|---|---|---|
| Boot | 41961 | Nanbeige4.1-3B Deep Sea | 8bit MLX | ~4.3GB | Dedicated instance |
| IG-88 | 41988 | Qwen3.5-4B | 8bit MLX | ~4.6GB | Local filter only — cloud primary (IG88004). Scans, classification, triage. |
| Kelk / Xamm | 41962 | Qwen3.5-4B | 8bit MLX | ~4.6GB | Always-on; Xamm shares slot (WHB025) |
| Nan | 41963 | LFM2.5-1.2B Thinking | 8bit MLX | ~1.3GB | Always-on observer; `<think>` traces visible |
| Expert pool | 41962 | Qwen3.5-4B | 8bit MLX | ~4.6GB | Shares Kelk/Xamm instance; identities injected per-task |
| LFM2.5-VL-1.6B | — | Shared vision module | 6bit MLX | ~1.4GB | Charts (IG-88), documents (Boot) |
| LFM2.5-Audio-1.5B | — | Shared audio module | 6bit MLX | ~1.3GB | Voice (Kelk), alerts (IG-88) |
| nomic-embed-text | 11434 | Embeddings | — | ~0.1GB | Qdrant retrieval (Ollama) |
| **Always-on total** | | | | **~19.0GB** | |

**Port block reference (2026-03-31 re-plumb):**

| Port | Agent | Model | Status |
|------|-------|-------|--------|
| 41960 | Coordinator | (reserved, no model) | Reserved |
| 41961 | Boot | Nanbeige4.1-3B-8bit | ACTIVE |
| 41962 | Kelk / Xamm + Expert pool | Qwen3.5-4B-MLX-8bit | ACTIVE |
| 41963 | Nan | LFM2.5-1.2B-Thinking-MLX-8bit | ACTIVE |
| 41910–41919 | Coding agents block | (reserved) | Reserved |
| 41966 | On-demand reasoning | Qwen3.5-9B-MLX-6bit | ACTIVE |
| 41977 | Research | (reserved) | Reserved |
| 41988 | IG-88 (local filter) | Qwen3.5-4B-MLX-8bit | ACTIVE |

**On-demand reasoning tier (evicts expert pool when loading):**

| Component | Port | Model | Quant | Size | Trigger |
|---|---|---|---|---|---|
| Reasoning | 41966 | Qwen3.5-9B-MLX-6bit | 6bit MLX | ~7.2GB | Routed by Nan/Boot when task exceeds 4B capability |

With expert pool evicted (~3.4GB freed): 19.0 − 3.4 + 7.2 = **~22.8GB peak** — within the 24GB cap with ~1.2GB KV cache headroom. Tight but viable; monitor in practice.

**Solo intensive session (suspends all except coordinator):**

| Model | Quant | Size | Use case |
|---|---|---|---|
| Qwen3.5-27B-Opus-Distilled | 6bit MLX | ~16.7GB | Deep reasoning, complex strategy sessions |
| LFM2-24B-A2B | 6bit MLX | ~18GB | LFM architecture at scale — test on Whitebox arrival |

Solo mode: coordinator-rs remains running. All agent sessions suspended. One large model serves the intensive session. Restore permanent stack on completion.

**Throughput estimates (not yet benchmarked — Whitebox arrives this week):**
Qwen3.5-4B Q6 single instance on M1 Max: ~40–50 tok/s (extrapolated from BKX074 [3]). Measure on arrival and update this section. The 9B Opus distill: ~25–35 tok/s estimated.

---

## 3. Permanent Agent Roster

Four permanent agents with persistent identity (soul/principles/agents.md), dedicated model assignments, and always-on session presence. SRE monitoring is handled by coordinator-rs Phase 3F — no fifth agent.

| Agent | Model | Quant | Trust | Role | Status |
|---|---|---|---|---|---|
| Boot | Nanbeige4.1-3B Deep Sea | 8bit MLX | L2 Advisor | Business project management, ops, delegation, tool chains | Live |
| IG-88 | Nanbeige4.1-3B Deep Sea | 8bit MLX | L3 Operator | Trading, market analysis, sequential scanner sessions | Live |
| Kelk | Qwen3.5-4B | Q6 MLX | L2 Advisor | Personal assistant, conversational continuity | Live |
| Nan | LFM2.5-1.2B Thinking | 6bit MLX | TBD | Always-on observer of Chris-Boot-Kelk interactions; triage and routing | Placeholder |

**Boot and IG-88 each have dedicated Nanbeige instances.** Both start from the same base weights, but fine-tuning is a near-term priority for both — IG-88 for trading signal schemas, Boot for coordinator tool-call reliability. Fine-tuned variants must never be shared between agents; shared weights would cause domain bias to bleed across agent boundaries. Dedicated instances from day one avoids a migration when fine-tuning begins. Memory cost: ~8.4GB for both, well within budget.

**Why Nanbeige4.1-3B for Boot and IG-88 (interim):** Arena-Hard-v2 score of 73.2 at 3B parameters (vs. Qwen3-32B at 56.0). Documented 600-turn tool-calling stability. Deep Sea Instruct variant specifically trained for long agentic workflows and deep-search workloads. IG-88's 50+ data source scanner sessions are exactly this use case — this assignment is high confidence. Boot's assignment is lower confidence: Boot's multi-week project management, delegation judgment, and narrative state accumulation are better suited to LFM2.5's linear recurrent architecture (O(1) memory complexity across long sessions). Nanbeige is Boot's best available option until LFM2.5-3B/4B releases, at which point Boot migrates alongside Kelk. Consider testing Qwen3.5-4B vs. Nanbeige for Boot early — the stronger general reasoning of Qwen3.5-4B may suit Boot's judgment work better than Nanbeige's tool-chain specialization.

**Why Qwen3.5-4B for Kelk (interim):** LFM2.5-3B does not exist and has no documented release date. Kelk's interim model is Qwen3.5-4B — Qwen3.5's weakness (factual recall) is mitigated by Graphiti and Qdrant RAG retrieval, which Kelk already uses heavily. When LFM2.5-3B (or 4B) releases, Kelk migrates immediately — the linear recurrent architecture's O(1) memory complexity is the natural fit for Kelk's long-session conversational continuity.

**Why LFM2.5-1.2B Thinking for Nan:** Nan's role is observation, pattern detection, and triage — not heavy generation. LFM2.5-1.2B Thinking scores MATH-500: 88 at 1.2B scale, produces explicit `<think>` traces (observable reasoning), and runs at ~239 tok/s on AMD CPU (substantially faster on Apple Silicon Metal). Sub-1GB at 4bit. Always-on without meaningfully impacting the memory budget. Nan does not issue tool calls — output is Matrix messages only — so the LFM2.5 tool-call format blocker does not apply.

**The Nan–Researcher relationship (resolved):** Nan is the always-on observer. Researcher is the ephemeral execution arm. Nan watches the Chris-Boot-Kelk interaction stream, notices when something warrants investigation, and triggers a Researcher delegate session. Nan does not do the research — Nan recognizes when research is warranted and dispatches. This keeps Nan's model small (1.2B is sufficient for recognition and triage) and Researcher's execution genuinely ephemeral.

**SRE closed — coordinator-rs Phase 3F handles infra monitoring.** coordinator-rs already implements: publishAgentHealthStatus() every 10 seconds, alertInfrastructure() warnings, docker/systemd/tailscale health checks, flap suppression (2 consecutive failures), and live-updating System Status HUD. Adding an SRE agent would duplicate this with LLM overhead and session management cost. The coordinator handles infra monitoring deterministically. No SRE agent will be created.

**FCT001 "@coord is Python" correction.** The coordinator is coordinator-rs, a Rust binary (~6,046 lines, 13 modules), live in production since 2026-03-08 (BKX085–087). coordinator-rs has zero LLM involvement — deterministic routing, session lifecycle, approval pipeline, infra health checks. FCT001's "Python" framing was incorrect.

---

## 4. Expert Subagent Architecture

### 4.1 Persistent Role vs. Ephemeral Loop

Expert subagents use a hybrid model: persistent role identity on disk, ephemeral execution at runtime.

- **Persistent role identity:** Each expert subagent has soul/principles/agents.md files defining who it is and what it does. These exist on disk and load at spawn time. They do not consume model slots or session resources when idle.
- **Ephemeral execution:** Expert subagents are not running processes. They spawn as delegate sessions for a specific task, produce a durable artifact (file, Graphiti fact, git commit), post a summary to Matrix, and terminate.
- **Shared model pool:** All expert subagents run on one shared Qwen3.5-4B instance. Identity is injected via system prompt per-task. Memory footprint: ~3.4GB regardless of how many expert identities exist.
- **Loop Spec governs autonomous operation:** Any expert subagent running a loop requires a Loop Spec produced by autoscope before deployment (section 4.3).

This aligns with the OpenClaw two-tier pattern [4]: persistent orchestrator (coordinator-rs + Boot) holds business context; ephemeral subagents hold task context and terminate with artifacts.

### 4.2 Expert Subagent Roster

**Autonomous expert subagents (machine-readable metrics possible):**

| Subagent | Purpose | Loop Type | Loop Spec | Approval Gate |
|---|---|---|---|---|
| Researcher | Deep research, horizon scanning, Qdrant ingestion | scope-researcher-loop | Not yet designed | None |
| Coder | Code changes, test-pass-delta optimization (Ralph Loop) | scope-coding-loop | Not yet designed | Human every 5 iterations |
| Admin | Config experiments, auto-approve pattern tuning | scope-infra-loop | Not yet designed | Human before merge |
| Policy | Agent constitution review, principle drift detection | TBD | Not yet designed | Human required |

**Creative subagents (human-gated — no autonomous loop):**

| Subagent | Purpose | Why No Autonomous Loop |
|---|---|---|
| Audio | Audio generation, voice synthesis | No ungameable scalar metric for subjective quality |
| Video | Video analysis, generation assistance | No ungameable scalar metric |
| Music | Composition, arrangement | No ungameable scalar metric |
| Writing | Long-form text, editing, style | No ungameable scalar metric |

Creative subagents operate as single-task delegates. Human reviews output before any artifact is promoted. An agent optimizing "word count" pads; an agent optimizing "readability score" simplifies to incoherence. Subjective quality cannot be made machine-readable without introducing a gameable proxy.

### 4.3 The Loop Spec Requirement

Every expert subagent operating autonomously requires a Loop Spec before deployment. autoscope (ATR002) is a meta-agent that runs before any loop, validates the proposal against integrity rules, and produces a Loop Spec YAML that becomes the loop agent's operating constitution.

**Core principle from ATR002:** "The frozen harness is more important than the metric. It is possible to run a useful loop with an imperfect metric. It is not possible to run a safe loop without a well-defined harness."

**Loop Spec schema:**
```yaml
loop_type:
agent:
objective:
metric:
  name:
  formula:
  baseline:
  direction:
  machine_readable:
frozen_harness: []
mutable_surface: []
budget:
  per_iteration:
  max_iterations:
rollback_mechanism:
  method:
  command:
  scope:
approval_gate:
invocation:
worker_cwd:
loop_spec_path:
```

**Auto-reject rules (any of these invalidates a Loop Spec):**
- Metric is gameable — agent can improve it without improving the system
- coordinator-rs missing from frozen harness
- `soul.md` / `principles.md` missing from frozen harness
- No rollback defined
- Mutable surface overlaps security files
- Loop Spec itself is in the mutable surface
- Budget is unbounded
- Infra-improve loop has no `observed_failure` citation

**First three Loop Specs to produce (in order):**
1. Researcher → scope-researcher-loop (metric: `research_signal_density`, no gate)
2. IG-88 Narrative → scope-narrative-loop (metric: `narrative_accuracy_rate` — see operationalization note below)
3. Coder → scope-coding-loop / Ralph Loop (metric: `test_pass_delta`, human gate every 5 iterations)

**narrative_accuracy_rate operationalization (required before Loop Spec is valid):**
The current definition ("correct directional calls / total calls") is gameable as written. The metric requires: (1) a specific time horizon per call (e.g., 4-hour window post-signal), (2) a minimum confidence threshold to register as a "call" at all — outputs below threshold do not count, (3) "no signal" outputs explicitly excluded from both numerator and denominator, (4) a baseline comparison period to establish what "correct" means. Without these constraints, the agent can improve the metric by only making high-confidence calls on obvious signals and suppressing borderline ones — gaming the denominator. autoscope must validate this operationalization before the Loop Spec is issued.

**autoscope deployment:** Register autoscope in coordinator agent-config.yaml. Add to Boot's skill routing table (Sonnet, medium effort) — Boot calls autoscope before dispatching any new autonomous loop.

---

## 5. Model Strategy

### 5.1 Specialization: Prompting vs. Fine-Tuning

ExpertPrompting (EMNLP 2024) achieves 8.69% improvement in truthfulness via prompting alone over the best prior method, with simultaneous toxicity reductions [5]. The key finding: "The model is better at designing the expert it needs to become than you are at writing it."

**Default approach: prompting-first.** Ship soul/principles/agents.md files with strong role identity. Validate baseline performance empirically. Fine-tuning is an optimization, not a prerequisite — invest in LoRA only after hitting a specific, measurable capability ceiling. This significantly reduces the urgency of the training data pipeline.

Fine-tuning is warranted only when:
- A narrow task has large amounts of domain-specific training data available
- Latency constraints require removing identity prompting overhead
- Structured output schema reliability is a hard requirement (coordinator tool-calling schemas specifically)

Soul/identity files must be **first** in the system prompt. The "Lost in the Middle" paper documents a U-shaped LLM attention pattern — highest weight on first and last tokens, degrading in the middle [6]. Every token placed before the soul file dilutes it. This is architecture, not preference.

### 5.2 LoRA Fine-Tuning Priority

Fine-tuning is deferred until prompting-first baselines are validated on Whitebox. When the time comes:

| Priority | Agent | Base Model | Target Capability |
|---|---|---|---|
| 1 | Kelk | Qwen3.5-4B | Conversational style, personal context vocabulary |
| 2 | Boot | Nanbeige4.1-3B | Tool-call schema reliability for coordinator tools |
| 3 | IG-88 | Nanbeige4.1-3B | Signal schema recognition, deep-search prompting |

**Hard rule: fine-tuned variants are never shared between agents.** A Nanbeige fine-tuned on IG-88's trading signal schemas carries domain bias that would corrupt Boot's tool-calling behavior if shared. Each fine-tuned model is named and served as a distinct Ollama instance (`nanbeige-ig88-ft`, `nanbeige-boot-ft`). This is a configuration rule, not an infrastructure constraint.

**Blocker: no training data pipeline exists.** Per-agent data collection and curation pipelines must be designed before any LoRA work begins. OLM-series fine-tuning work (OLM039) was OLMo-specific — not applicable to Nanbeige or Qwen3.5. MLX-LM LoRA training on M1 Max is confirmed feasible in hours for small models. Infrastructure is not the blocker; training data is.

### 5.3 Model Families

**Nanbeige4.1-3B (BOSS Zhipin, Feb 2026):** Arena-Hard-v2: 73.2, AIME 2026: 87.4, Deep Search: 69.9. 600-turn documented tool-calling stability. Deep Sea Instruct variant targets long agentic workflows. 8bit MLX: ~4.2GB. Primary model for Boot and IG-88.

**Qwen3.5 dense small series (0.8B–27B):** Hybrid gated DeltaNet, 262K native context, strong tool-calling and structured output. Weakness: factual recall — always pair with Qdrant RAG. Primary family for Kelk (4B), expert subagent pool (4B), and reasoning tier (9B Opus distill, 27B Opus distill).

**LFM2.5 linear recurrent (1.2B, and future 3B/4B):** O(1) memory complexity, superior sequential and streaming tasks, IFEval: 86.23 (highest in 1B class). Thinking variant: MATH-500: 88 at 1.2B. Tool-call format incompatible with coordinator-rs without adapter. Currently used for Nan (observer) and coordinator routing triage. **LFM2.5-3B does not exist yet** — no release date, no roadmap entry in any vault. When a 3B or 4B LFM2.5 variant releases, Boot and Kelk migrate immediately — this is the intended long-term model family for both relational agents. Monitor Liquid AI releases.

**LFM2 (previous generation, 24B-A2B variant):** 24B total weights, ~2B active parameters per token. ~18GB at 6bit MLX. Intensive session candidate. LFM2.5 represents a significant improvement over LFM2 — evaluate on Whitebox arrival before assigning a role.

**Qwen3.5-9B-Opus-Distilled:** Qwen3.5-9B fine-tuned to replicate Claude Opus 4.6 reasoning patterns. On-demand reasoning tier. ~7.2GB at 6bit MLX. Loads on-demand, evicts expert pool to maintain headroom.

**Qwen3.5-27B-Opus-Distilled:** 27B dense, Opus 4.6 distillation. Solo intensive session model. ~16.7GB at 6bit MLX. Requires suspending all agent sessions except coordinator-rs.

---

## 6. Reasoning Tier and Escalation Chain

Tasks are triaged by Nan (LFM2.5-1.2B Thinking) and routed to the appropriate tier:

```
Tier 0 — Coordinator (deterministic, no LLM):
  Routing, lifecycle, approvals, infra health

Tier 1 — Permanent agents (Nanbeige 3B / Qwen3.5-4B):
  Normal operational tasks, tool chains, conversational requests

Tier 2 — On-demand reasoning (Qwen3.5-9B-Opus-Distilled):
  Complex multi-step reasoning, ambiguous decisions, strategic synthesis
  Trigger: Nan flags task as exceeding Tier 1 capability
  Memory: evicts expert pool (~3.4GB freed), loads 9B (~7.2GB), peak ~18.6GB

Tier 3 — Anthropic API (Claude Sonnet/Opus):
  Genuinely novel problems, rare high-stakes decisions
  Trigger: 9B reasoning tier unable to resolve
  Cost-limiting: API tier should be rare — frequent use signals Tier 1/2 misconfiguration

Tier 4 — Solo intensive session (Qwen3.5-27B-Opus-Distilled):
  Deep strategic sessions, complex system design, long-form analysis
  Trigger: explicit user invocation
  Memory: suspend all agent sessions, load 27B solo
```

The Anthropic API is not a fallback — it is a deliberate high-capability tier for genuinely hard problems. Frequent API calls indicate that local models are being asked to do work above their tier. Monitor API usage as a health signal.

---

## 7. Memory Architecture

### 7.1 Current Stack

- **Qdrant** (port 41450): Semantic retrieval over large corpus (PREFIX docs, research vault). Embedding model: nomic-embed-text.
- **Graphiti** (port 41440): Temporal facts, entity relationships, conversation memory with context evolution. Entity extraction: Haiku 4.5. Note: Haiku extraction errors compound over time — monitor entity quality, especially for IG-88 signal facts where precision matters.
- **FalkorDB** (port 41430): Graph database backend for Graphiti.

### 7.2 Hybrid Retrieval Upgrade

Current Qdrant-only (pure vector) retrieval leaves accuracy on the table. Hybrid BM25 + vector retrieval with reciprocal rank fusion: +26% accuracy, 91% faster retrieval, 90% fewer tokens vs. pure vector baseline [7]. Pure vector loses exact-match facts — a critical gap for IG-88 where precise signal recall matters. Schedule for Whitebox migration.

### 7.3 Working Memory

For per-session agent working memory (in-flight state, not long-term facts), plain markdown files outperform specialized vector DBs — 74.0% vs. 68.5% on LoCoMo benchmark [8]. Use Qdrant for corpus-scale semantic search; use structured markdown for session working memory.

### 7.4 Context Compaction Warning

As context fills, compaction silently destroys in-flight working state — including MEMORY.md content loaded at session start. Any information only present in conversation is lost on compaction. **Rule: write to persistent memory proactively, not at session end.** Enforce in each agent's `agents.md` operational rules — not left to agent discretion.

---

## 8. Autonomous Loop Integration

### 8.1 Phase 1 — Researcher Agent (no coordinator-rs changes required)

Invocation: Nan detects research-warranted signal → triggers `@boot research: <question>` → Boot's researcher-dispatch skill → coordinator spawns delegate session.

**Loop protocol:**
1. Decompose question into 3–5 sub-queries
2. WebSearch each → WebFetch top 2 results per query
3. Synthesize → briefing schema (frontmatter + Summary + Key Findings + Gaps + Sources)
4. Write to `~/projects/research-vault/inbox/{date}-{slug}.md`
5. Post 2–3 line summary to originating Matrix room
6. Terminate

**Metric:** `research_signal_density` = (new Qdrant docs + new Graphiti facts) / token budget
**Approval gate:** None
**Budget:** `delegate_timeout_ms: 2700000` treated as wall-clock budget — session terminates and produces artifact regardless of completion state

### 8.2 Phase 1 — IG-88 Narrative Data Loop (no coordinator-rs changes required)

Self-scheduling via timer files in `~/factory/coordinator/timers/`. `timer.rs` fires the loop.

**Metric:** `narrative_accuracy_rate` — see operationalization note in section 4.3. Loop Spec is blocked until metric is operationalized.
**Approval gate:** None

### 8.3 Phase 2 — Boot Self-Improvement Loop (human approval required)

Propose-then-execute. Boot proposes config changes on `experiment/boot-YYYYMMDD-N` git branches. Human approval via Matrix reaction before merge.

**Frozen:** coordinator-rs binary, security validator, pretool-approval.sh, all soul/principles files, HMAC infrastructure, token files
**Mutable:** `agents.md` operational sections (conditional), auto_approve_patterns, timer cadences
**Metric:** `approval_friction_rate` = matrix_approved / total_tool_calls
**Approval gate:** Human before merge — hard requirement, no exceptions

### 8.4 Phase 3 — Research Swarm (requires coordinator-rs changes, deferred)

Parallel delegate sessions via `tokio::spawn`. Deferred until Whitebox migration stabilizes.

**Metric:** `synthesis_coverage` = unique findings / sum of branch findings
**Approval gate:** Human before promoting from `inbox/` to `notes/`

---

## 9. Open Questions and Next Steps

### Critical Path (ordered)
- [ ] **Backtest IG-88 momentum continuation strategy** — this is the only revenue-generating component and it is running on an unvalidated strategy. Everything else is infrastructure. This is the critical path blocker for live trading.
- [ ] **Operationalize narrative_accuracy_rate** — define time horizon, confidence threshold, no-signal handling, baseline period. Required before IG-88 Narrative Loop Spec can be issued.
- [ ] **Benchmark Whitebox on arrival** — measure tok/s for Nanbeige4.1-3B, Qwen3.5-4B Q6, and LFM2.5-1.2B Thinking. Update section 2.3. Test LFM2-24B-A2B as intensive session candidate.
- [ ] **Implement LFM2.5 tool-call format adapter** — Pythonic list → JSON schema translation layer in coordinator-rs. Bounded code task. Prerequisite for Boot's LFM2.5 routing tier and any LFM2.5 expert subagent.

### Architecture
- [ ] **Register autoscope in coordinator agent-config.yaml** — add to Boot's skill routing table (Sonnet, medium effort)
- [ ] **Run autoscope on Researcher loop** — produce first real Loop Spec YAML
- [ ] **Run autoscope on IG-88 Narrative loop** — after metric operationalization
- [ ] **Implement hybrid BM25 + vector retrieval** — schedule for Whitebox migration
- [ ] **Monitor Graphiti entity extraction quality** — Haiku 4.5 errors compound; establish a periodic quality check, especially for IG-88 signal facts

### Model and Identity
- [ ] **Monitor LFM2.5-3B/4B release** — when available, migrate Boot and Kelk immediately. This is the intended long-term architecture for both relational agents. No action until release.
- [ ] **Test Boot: Nanbeige vs. Qwen3.5-4B** — empirically validate which model better suits Boot's judgment/delegation work vs. tool-chain execution. Run both for 2 weeks post-Whitebox, compare.
- [ ] **Validate prompting-first baselines on Whitebox** — before committing to LoRA training data pipeline work, confirm whether strong soul files achieve acceptable performance. This may substantially reduce fine-tuning scope.
- [ ] **Design training data pipeline** — only after prompting-first validation. Per-agent strategy: Kelk (conversational examples), Boot (tool-call schema examples), IG-88 (signal schema examples).
- [ ] **Assign Nan trust level** — currently TBD. Nan's observer role with Matrix-only output suggests L1 or L2; define before activating.
- [ ] **Test LFM2-24B-A2B on Whitebox** — evaluate as intensive session alternative to Qwen3.5-27B-Opus-Distilled. LFM2 is prior generation to LFM2.5; benchmark before assigning role.

### Infrastructure
- [ ] **Whitebox service migration plan** — coordinator-rs, MLX-LM, Ollama, Qdrant, FalkorDB, Graphiti, Pantalaimon. Sequence and rollback plan needed before Whitebox arrives.
- [ ] **Decide RP5 post-Whitebox role** — options: (a) coordinator-rs + Pantalaimon watchdog, Whitebox handles all inference; (b) full retirement, everything on Whitebox. Security tradeoff: RP5 lacks macOS Secure Enclave; Whitebox consolidation simplifies threat surface.

---

## 10. References

[1] N. Shazeer, "Fast Transformer Decoding: One Write-Head is All You Need," arXiv:1911.02150, 2019. Memory bandwidth as primary inference bottleneck.

[2] sudoingX, "Claude Code on Local 80B Qwen MoE — Two RTX 3090s, No API," practitioner account, 46K views, February 2026. vLLM and SGLang failure on MoE architectures. Cited in `docs/tx/TX260224_0000-7075`, research-vault.

[3] BKX074, "Greybox 2.0 Hardware Recommendations," internal architecture decision record, February 2026. Confirmed 40–50 tok/s for Qwen3.5-4B on M1 Max 32GB.

[4] elvissun (OpenClaw), "OpenClaw as Orchestration Layer," practitioner case study, 4.5M views, February 2026. Two-tier persistent-orchestrator / ephemeral-subagent pattern. Cited in `docs/tx/TX260223_1758-0AAE`, research-vault.

[5] Y. Xu et al., "ExpertPrompting: Instructing Large Language Models to be Distinguished Experts," EMNLP 2024. 8.69% truthfulness improvement on TruthfulQA via expert identity prompting.

[6] N. F. Liu et al., "Lost in the Middle: How Language Models Use Long Contexts," TACL, 2024. U-shaped attention pattern; identity file position affects agent behavioral consistency.

[7] Mem0 team, "Mem0 Memory System Benchmarks," technical report, 2025. +26% accuracy, 91% faster retrieval vs. pure vector baseline on LoCoMo benchmark.

[8] R. Modarressi et al., "MemoryOS: A Scalable Memory Architecture for Long-Term Agent Interactions," 2025. Markdown-native memory 74.0% vs. specialized tools 68.5% on LoCoMo.
