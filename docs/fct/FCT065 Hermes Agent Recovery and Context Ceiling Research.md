# FCT065 Hermes Agent Recovery and Context Ceiling Research

**Date:** 2026-04-10
**Session:** Morning / Afternoon, Whitebox (M1 Max 32GB)
**Scope:** Bug resolution, context ceiling uplift, fine-tuning pipeline research, agent handoffs
**Agents Affected:** Boot, Kelk, IG-88

---

## Summary

Three blocking defects were resolved this session: a gateway preflight regression that had crashed IG-88 for 6.5 hours overnight (RC6), stream timeout values that were too conservative for local MLX prefills, and a shell alias bypass that prevented timeout env vars from taking effect. Context ceiling was raised from 22k to 96k after proper Gemma 4 E4B architecture analysis disproved the original crash diagnosis. All three agents were restored to autonomous operation. Parallel research covered the full local fine-tuning pipeline — from dataset curation through RL refinement to BF16→6bit deployment.

---

## Issues Resolved

### RC6 — IG-88 Gateway Preflight Regression

**Crash window:** 03:51–10:18 UTC (6.5 hours)

`hermes-ig88.sh` line 70 used a `^provider:` grep to detect the active provider in the agent YAML config. After the dict-form config migration (`provider:` was moved to a key indented under `model:`), the anchored grep no longer matched any line, returned a non-zero exit, and caused the preflight check to exit with code 3. IG-88 entered a crash loop for the full overnight window.

**Fix:** Updated the grep pattern to `^[[:space:]]*provider:` — accepts both the new dict-indented form and the legacy top-level scalar form. This change is forward- and backward-compatible.

**Commit:** `45835b5`

---

### Stream Timeout Errors

**Root cause:** `HERMES_STREAM_READ_TIMEOUT` defaults to 60s. Local MLX prefill for large context inputs takes 60–120s. Connections were timing out before the first token was emitted.

**Compounding factor:** `HERMES_STREAM_STALE_TIMEOUT` defaults to 180s. The watchdog was killing connections that had no token activity during a long prefill, even if the connection itself was still alive.

**Both values set to 600s** across all three agent profiles.

**Alias bypass:** The `h-boot`, `h-kelk`, and `h-ig88` shell aliases invoked `infisical-env.sh` directly, bypassing the wrapper scripts where the timeout env vars were set. The env vars never reached Hermes. Both the wrapper scripts and the aliases were updated to ensure consistent env injection.

**Commit:** `2a01ff1`

**Note:** Hermes documentation states that when the target host is `localhost`, read timeout auto-adjusts to 1800s and stale timeout is disabled. An explicit env var always wins over the auto-detection logic, so the explicit 600s values are authoritative regardless of host detection.

---

### Context Ceiling Raised: 22k → 96k

**Previous ceiling rationale (incorrect):** A Metal GPU crash at 12k tokens was diagnosed as a context size limit, leading to a conservative 22k ceiling.

**Correct analysis:** The crash was caused by large batch Metal dispatches, not by context size. Chunked prefill (`step_size=2048`) keeps individual Metal GPU dispatches within safe bounds regardless of total context length.

**Gemma 4 E4B architecture facts:**
- `max_position_embeddings`: 128k
- GQA topology: 2 KV heads + 18 shared layers → very small KV footprint
- KV cache at 96k context ≈ 1.6GB on M1 Max 32GB — well within available unified memory
- Chunked prefill already active; no additional configuration required

**All three profiles updated:**

| Setting | Before | After |
|---|---|---|
| `context_length` | 22,000 | 96,000 |
| Compression threshold | 11k | 48k (50% of 96k) |

---

## Agent Handoffs

- Reviewed 15 hours of logs across Boot, Kelk, and IG-88 following overnight disruptions.
- Crafted targeted handoff prompts summarizing lost context and current operational state.
- Kelk and IG-88 handoffs delivered; Boot handoff pending.
- IG-88 resumed autonomous H3 research: 7 tasks, all completed in 1h 31m, compression fired correctly at 59,873 tokens.
- IG-88 Python import bug fixed: `PYTHONPATH=/Users/nesbitt/dev/factory/agents/ig88 python3 ...` required for module resolution.

---

## Research Findings

### Gemma 4 E4B Architecture

- **Parameter topology:** 12B total parameters, 4B active per token (MoE). "E4B" = Effective 4B.
- **Generation throughput:** ~30 tok/s on M1 Max (memory-bandwidth-bound, near theoretical ceiling for this hardware tier).
- **Prefill throughput:** ~650–690 tok/s with chunked prefill active.
- **E2B consideration:** Running 3–4 E2B instances at 4.8GB each is under consideration as a parallel inference option for agent workloads.

### Auxiliary Model Architecture

Aux tasks (vision, web_extract, compression, session_search, skills_hub, mcp, flush_memories) are dispatched as concurrent HTTP calls — but only if the aux endpoint differs from the main model endpoint. At present all aux tasks are serialized on the same MLX server because no separate endpoint is configured.

**Resolution path:**
- Route aux to a dedicated endpoint once OpenRouter access is restored.
- Target aux model: `google/gemma-4-31b-it` via OpenRouter (account locked; user pursuing recovery).
- `claude-sonnet-4-6` was evaluated and rejected: observed cost ~$90/day.
- Local E2B instance on `:41960` (4.8GB) as a fallback aux option — RAM feasibility and stability deferred pending agent idle window.

### Fine-Tuning Pipeline

Three sequential phases identified for local Gemma 4 E4B fine-tuning:

#### Phase 1 — tuning-wizard SFT

- **Repo:** `~/dev/tuning-wizard`
- **Version:** v0.1.0, 80 tests
- **Function:** Dataset curation CLI for agent SFT. Produces JSONL for Unsloth Studio.
- **Status:** 48 seeded examples pending human review before SFT export.
- **Scope:** Not superseded by Atropos — SFT provides the base adapter; RL refines it.

#### Phase 2 — Atropos RL Refinement

- **Approach:** Nous Research Atropos framework for trajectory collection + RL training.
- **Feasibility on Apple Silicon:** Trajectory collection via Atropos API + Hermes environment → scored JSONL → mlx-lm LoRA fine-tune.
- **Blocker:** Full GRPO closed-loop requires CUDA IPC — not available on Apple Silicon.
- **Practical path:** Collect trajectories locally with Atropos, train adapter with mlx-lm.
- **Timeline:** Planned for tuning-wizard v0.3.0+.

#### Phase 3 — BF16→6bit Deployment

- **Pipeline:**
  1. Merge LoRA adapter in PyTorch (full precision)
  2. `mlx_lm.convert` — format conversion only, output BF16
  3. `convert_gemma4.py` — PLE-safe 6-bit quantization

- **Critical constraint:** Standard `mlx_lm.convert` produces non-functional weights for Gemma 4 due to `ScaledLinear`/PLE layer handling. Must use the `mlx-gemma4` PLE-safe script for the quantization step.
- **Hardware requirements:** ~28–32GB peak RAM (tight on 32GB M1 Max — all other processes must be shut down). Duration: ~45–90 min.

---

## Current Operational State

| Agent | Endpoint | Context | Timeouts | Notes |
|---|---|---|---|---|
| Boot | :41966 (shared E4B) | 96,000 | 600s | Handoff pending |
| Kelk | :41966 (shared E4B) | 96,000 | 600s | Handoff delivered |
| IG-88 | :41988 (dedicated E4B) | 96,000 | 600s | Autonomous research active |

All agents: compression threshold 48k, `max_tokens` 32,768, `DEFAULT_MAX_TOKENS` vendor patch active (256 → 32,768).

---

## Open Items

| Item | Priority | Notes |
|---|---|---|
| Boot handoff delivery | High | Crafted, not yet delivered |
| `fact_promoter.py` failure | High | IG-88 research findings not promoted to `fact/trading.md` |
| IG-88 research output restructuring | Medium | Organizational pass per user feedback, in progress |
| E2B stability test | Low | Deferred — requires all agents idle |
| OpenRouter account unlock | Blocker for aux routing | Prerequisite for `gemma-4-31b-it` aux model |
| tuning-wizard: 48 example human review | Medium | Gate for SFT export |

---

## Related Documents

- FCT062 Hermes v0.8.0 Provider Routing Resolution
- FCT063 Local Model Restoration and Routing Guide
- FCT064 Factory Profile Rotation and Aux-Route Hardening
- Memory: `project_finetuning_pipeline.md`
