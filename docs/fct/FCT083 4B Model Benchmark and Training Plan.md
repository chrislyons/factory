# FCT083 4B Model Benchmark and Training Plan

**Date:** 2026-04-29 | **Author:** Gonzo | **Status:** Approved

---

## Context

The 2B models (Qwen3.5-2B + v4v2 adapter) are failing at autonomous agent behavior.
Matrix logs show zero tool calls across sessions — both Boot and Kelk collapse into
repetitive loops ("I'll check the systems"). The Gemma-era sessions (Apr 14-16) had
27 tool calls across 77 messages, but the current Qwen 2B sessions have none.

Root cause: 2B parameter models lack the capacity for autonomous multi-step reasoning
and tool-calling behavior required by Hermes agents.

---

## Model Benchmark: Gemma4-e4b vs Qwen3.5-4B

| Spec | Gemma4-e4b-6bit | Qwen3.5-4B-6bit | Winner |
|------|----------------|-----------------|--------|
| Disk size | 7.1 GB | 3.4 GB | Qwen (2× smaller) |
| Layers | 42 | 32 | — |
| Hidden size | 2560 | 2560 | Tie |
| Intermediate | 10240 | 9216 | — |
| Attention heads | 8 | 16 | — |
| KV heads | 2 | 4 | — |
| Context window | 128K | 262K | Qwen (2× larger) |
| Vocab | 262K | 248K | — |
| Hybrid attention | No | Yes (GatedDeltaNet) | Qwen |
| Vision | Yes (multimodal) | No | — |
| LoRA training | Standard | bf16 only (no QLoRA) | Gemma |
| Existing pipeline | No | Yes (mlx-lora-finetune) | Qwen |
| Role definitions | None | kelk.yaml targets it | Qwen |

### Decision: Qwen3.5-4B

**Rationale:**
1. 2× smaller disk footprint (3.4 vs 7.1 GB) — critical on 96% full drive
2. 2× larger context (262K vs 128K) — agents accumulate long conversations
3. Same architecture family as the 2B we already trained on
4. Training pipeline exists (mlx-lora-finetune, scripts/train.sh)
5. Tuning-wizard role definitions already target Qwen3.5-4B (kelk.yaml)
6. Hybrid attention (GatedDeltaNet + full attention every 4th layer) is designed
   for long-context reasoning — ideal for agent workloads

**Tradeoffs:**
- bf16 LoRA only (no QLoRA) — acceptable for local training on 32GB
- No vision — not needed for text-based agent work (vision routes to Ornstein 35B)

---

## Training Architecture

Per tuning-wizard CLAUDE.md: two-layer approach (validated by Brainstacks research):

1. **Base capability fine-tune** — identity adherence, tool calling, structured output
   - Shared across agents
   - Generic system prompts
   - ~500-800 examples

2. **Agent-specific LoRA** — persona, decision patterns, domain behavior
   - One adapter per agent (Boot ≠ Kelk)
   - Canonical system prompt
   - ~250-400 examples each

### Boot Adapter (Manager archetype)

System prompt: "You are Boot. You are the operational backbone — given intent, you
plan, execute, and deliver outcomes."

Categories (from boot.yaml):
- identity (40), tool_call (40), escalation (40), conciseness (40)
- direct_answer (40), json_format (40), delegation (30)
- cross_repo_coordination (25), job_registry (20), session_lifecycle (20)
- blocker_workaround (15), trust_tier_execution (15)

### Kelk Adapter (Oracle archetype)

System prompt: "You are Kelk. You help Chris understand himself through pattern
recognition, honest observation, and thoughtful questioning."

Categories (from kelk.yaml):
- identity (40), listening (40), pattern_recognition (40), reflection (30)
- emotional_register (30), direct_observation (25), complexity_holding (20)
- anti_sycophancy (20), productive_flaw (15), memory_first (15)
- narrative_pacing (15), reframe_precision (15)

---

## Training Parameters

Based on v4v2 success (8/8 tests) scaled for 4B:

| Param | v4v2 (2B) | Boot 4B | Kelk 4B |
|-------|-----------|---------|---------|
| LoRA rank | 8 | 16 | 16 |
| LoRA layers | 8 | 12 | 12 |
| Learning rate | 2e-5 | 1e-5 | 1e-5 |
| Iters | 500 | 800 | 800 |
| Batch size | 1 | 1 | 1 |
| Max seq len | 2048 | 2048 | 2048 |
| Optimizer | adam | adam | adam |
| Grad checkpoint | true | true | true |
| Mask prompt | true | true | true |
| Save every | 50 | 100 | 100 |
| Seed | 42 | 42 | 42 |

**Why these changes:**
- Rank 8→16: 4B model has more capacity, adapter needs more expressiveness
- Layers 8→12: More layers to influence (4B has 32 vs 2B's 30)
- LR 2e-5→1e-5: Larger model needs gentler updates to avoid catastrophic forgetting
- Iters 500→800: More steps for convergence with larger model + more layers

---

## Execution Plan

### Phase 1: Data Preparation
1. Build Boot training data from tuning-wizard reviewed examples
2. Build Kelk training data from tuning-wizard reviewed examples
3. Include 10-15% base-category replay (anti-catastrophic forgetting)
4. Split 85/10/5 train/valid/test

### Phase 2: Base Fine-tune (optional — test without first)
- Can we skip base fine-tune and go straight to agent LoRA?
- The 4B model may already have sufficient base capabilities
- Test: run inference without adapter, check tool calling works

### Phase 3: Agent LoRA Training
1. Train Boot adapter: `python -m mlx_lm lora --model Qwen3.5-4B-6bit ...`
2. Train Kelk adapter: same pipeline, different data
3. Test each adapter: 8/8 test suite (same as v4v2)

### Phase 4: Deployment
1. Stop 2B servers
2. Update launchd plists to use 4B model + adapter paths
3. Update Hermes configs (model paths, context lengths)
4. Start 4B servers
5. Test in Matrix

---

## References

- tuning-wizard role definitions: ~/dev/tuning-wizard/roles/
- mlx-lora-finetune pipeline: ~/dev/mlx-lora-finetune/scripts/train.sh
- v4v2 adapter config: ~/dev/mlx-lora-finetune/adapters-frontdoor-v4v2/adapter_config.json
- Training data: ~/dev/mlx-lora-finetune/data/frontdoor_v4_ninja_v2/
- Brainstacks research: arXiv:2604.01152
