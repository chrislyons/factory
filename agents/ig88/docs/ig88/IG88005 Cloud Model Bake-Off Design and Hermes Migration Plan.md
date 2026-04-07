---
prefix: IG88005
title: "Cloud Model Bake-Off Design and Hermes Migration Plan"
status: active
created: 2026-04-05
updated: 2026-04-05
author: Chris + Claude (Opus 4.6)
depends_on: IG88004, FCT046, FCT047
---

# IG88005 Cloud Model Bake-Off Design and Hermes Migration Plan

## Purpose

IG88004 established model recommendations based on published benchmarks. This document translates those into an empirical evaluation using IG-88's actual task prompts against real Polymarket data, and defines the migration path from Claude CLI to Hermes runtime.

**Principle:** Published benchmarks are proxies. The only scores that matter are the ones measured on IG-88's actual T1 prompt template against real markets with real evidence and real price-blinding.

---

## 1. Prerequisites

### 1.1 IG-88 Hermes Migration (Direct — No Boot Gate)

IG-88 goes directly to Hermes runtime. The FCT047 Boot trial is a separate concern — it validates Hermes for Boot's dev workload. IG-88's bake-off serves double duty: it validates both the model selection AND the Hermes runtime on IG-88's actual financial reasoning workload. If Hermes fails during the bake-off, fallback to `runtime: claude-cli` is a one-line YAML change.

**Rationale for skipping Boot gate:**
- IG-88 is not live-trading — worst case is bad eval data, not lost money
- Boot's dev workload tests different failure modes than financial reasoning + multi-provider routing
- Testing on Claude CLI then migrating would invalidate bake-off results ("same model behaves differently in different harnesses")
- The bake-off IS the validation — controlled, comprehensive, zero capital risk

**Config change (IG-88 agent-config.yaml):**
```yaml
runtime: hermes
hermes_profile: ig88
hermes_port: 41971
scoped_env:
  ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"
  OPENROUTER_API_KEY: "${OPENROUTER_API_KEY}"
```

**Hermes ig88 profile configuration (`~/.hermes/profiles/ig88/`):**

Three providers, all via existing API keys:

| Provider | Key Source | Models Available | Role |
|---|---|---|---|
| Anthropic (direct) | `ANTHROPIC_API_KEY` (Keychain → BWS → coordinator → scoped_env) | Sonnet 4.6, Opus 4.6 | Tier 2 primary, Tier 3 escalation |
| OpenRouter | `OPENROUTER_API_KEY` (BWS → coordinator → scoped_env) | Gemini 3.1 Pro, o4-mini, Qwen3.6 Plus, Gemma 4, Llama 4, Flash Lite | Ensemble members, Tier 1 fan-out |

**Cost firewalls:**
- Anthropic: per-key spend limit (set by Chris)
- OpenRouter: credit-based billing with per-model cost tracking

No new API keys, services, or infrastructure required.

---

## 2. Bake-Off Design

### 2.1 Objective

Measure each candidate model's T1 (probability assessment) performance on IG-88's actual prompt template, with price-blinding enforced, against resolved Polymarket markets with known outcomes.

### 2.2 Market Selection

Select 20-30 resolved Polymarket markets meeting these criteria:
- Resolved within the last 60 days (evidence still accessible)
- Mix of categories: politics (8-10), economics (4-6), crypto (4-6), sports (2-4), other (2-4)
- Mix of difficulty: some where market price was well-calibrated, some where it was wrong
- Resolution outcome known (YES or NO confirmed)
- Exclude markets where resolution was ambiguous or disputed

**Data to collect per market:**
- Market question and resolution criteria
- Resolution date and outcome (YES=1, NO=0)
- Market price at time of assessment (for post-hoc anchoring analysis — NOT shown to model)
- Evidence context (news, data, background) available at assessment time

### 2.3 Models Under Test

| Model | Provider | Via | Role Being Tested |
|---|---|---|---|
| Claude Sonnet 4.6 | Anthropic | Direct API | Tier 2 primary |
| Gemini 3.1 Pro | Google | OpenRouter | Ensemble member |
| o4-mini | OpenAI | OpenRouter | Ensemble member |
| Claude Opus 4.6 | Anthropic | Direct API | Tier 3 escalation (optional — expensive) |
| Grok 4.20 | xAI | OpenRouter | Monitoring candidate (if budget allows) |

### 2.4 Protocol

For each market × model combination:

1. Construct the T1 prompt using IG-88's template (evidence + resolution criteria, NO market price)
2. Call the model via Hermes with structured output (JSON: `{ probability: float, reasoning: string, confidence: float }`)
3. Record: model, market_id, probability estimate, confidence, reasoning, latency_ms, token_count, cost
4. Each model sees each market exactly once (no retries for variance measurement — that comes in Phase 2 if needed)

**Price-blinding enforcement (§4.1 from IG88004):**
- Prompt template must NOT contain `current_price`, `market_price`, `yes_price`, `no_price`
- Post-hoc: compute Pearson correlation between each model's estimates and actual market prices. If r > 0.3 for any model, investigate evidence leakage.

### 2.5 Metrics

**Per model:**

| Metric | Formula | Target |
|---|---|---|
| Brier score | `mean((probability - outcome)^2)` | < 0.15 |
| Calibration curve | Reliability diagram (binned predicted vs actual) | Monotonic, close to diagonal |
| Anchoring correlation | Pearson r(model_estimate, market_price) | < 0.3 |
| Schema compliance | % of calls returning valid JSON | > 97% |
| Mean latency | avg(latency_ms) | < 10s for Tier 2, < 30s for Tier 3 |
| Cost per assessment | tokens × price_per_token | Track, no threshold |

**Ensemble (computed post-hoc from individual outputs):**

| Metric | Method |
|---|---|
| Simple average Brier | mean(model_probabilities) → Brier |
| Weighted average Brier | accuracy-weighted mean → Brier |
| Platt-scaled Brier | Platt scaling on aggregated mean → Brier |
| Decorrelation check | Pairwise correlation of model errors — lower is better |

### 2.6 Decision Criteria

| Outcome | Action |
|---|---|
| Ensemble Brier < best single model Brier by >0.01 | Adopt ensemble for T1 |
| Ensemble Brier ≈ best single model (within 0.01) | Use single model — ensemble cost not justified |
| Any model anchoring r > 0.3 | Investigate evidence leakage, do NOT use for T1 until resolved |
| Any model schema compliance < 95% | Do NOT use for pipeline tasks (T2/T3) |
| Sonnet 4.6 is not the best single model | Switch primary to winner (update IG88004 §3.1) |

---

## 3. Bake-Off Execution Script

A Python script that:
1. Loads the market test set (YAML/JSON with evidence, criteria, outcome)
2. For each market × model: calls the model via Hermes (or OpenAI SDK with base_url)
3. Logs all outputs to a JSONL file
4. Computes Brier scores, calibration curves, correlations
5. Outputs a summary table

**Location:** `~/dev/factory/agents/ig88/scripts/bakeoff.py`
**Dependencies:** `openai` SDK (already installed), `scikit-learn` (for Platt scaling), `numpy`
**No new dependencies to install** — check with Chris before adding anything (supply chain policy).

---

## 4. Timeline

| Phase | What | Blocked By | Est. Duration |
|---|---|---|---|
| **1** | IG-88 Hermes migration | Nothing — start now | 30 min config |
| **2** | Collect 20-30 resolved markets + evidence | Nothing — start in parallel with Phase 1 | 1-2 days |
| **3** | Run bake-off | Phases 1 + 2 | 1-2 days (API calls + analysis) |
| **4** | Ensemble analysis + recommendation | Phase 3 data | 1 day |
| **5** | Update IG88004 with empirical results | Phase 4 | 1 hour |
| **6** | Begin paper trading with the winner | Phase 5 | Ongoing |

**Critical path:** Phase 1 (Hermes migration) → Phase 3 (bake-off).
**Parallel work:** Phase 2 (market collection) starts immediately alongside Phase 1.

---

## 5. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Boot Hermes trial fails | Delays by 1-2 weeks while debugging | Run bake-off via direct API calls (bypass Hermes) as fallback |
| OpenRouter rate limits during bake-off | Incomplete data | Spread calls over 24h; use batch API if available |
| 20-30 markets insufficient for statistical significance | Cannot distinguish models | This is a directional filter, not a final verdict. 200+ paper trades are the real validation. |
| Evidence context too stale for old markets | Model can't reason well about expired context | Prefer markets resolved within 30 days; document evidence quality per market |
| Platt scaling overfits on 20-30 samples | Calibration appears better than it is | Use leave-one-out cross-validation; treat Platt results as directional only |

---

## References

[1] IG88004 Cloud Model Evaluation Framework for Trading Tasks, 2026-04-05.

[2] FCT046 Provider Failover Chain and Hermes Integration Architecture, 2026-04-02.

[3] FCT047 Hermes Runtime Integration Phase 3 Implementation, 2026-04-02.

[4] NousResearch, "Hermes Agent v0.7.0 Release Notes," GitHub, April 2026.

[5] zostaff, "Provider-agnostic design via OpenAI SDK with base_url swap," research-vault TX260403_0000-9407.
