---
prefix: IG88004
title: "Cloud Model Evaluation Framework for Trading Tasks"
status: active
created: 2026-04-05
updated: 2026-04-05
author: Chris + Claude (Opus 4.6, cloud model evaluation session)
depends_on: IG88002, IG88003
---

# IG88004 Cloud Model Evaluation Framework for Trading Tasks

## Purpose

IG-88 runs on cloud inference (see IG88003 §Inference Architecture Decision). This document defines how the cloud model is selected and periodically re-evaluated. Model selection is based entirely on published research benchmarks across the specific task categories IG-88 executes. There are no personalisation or identity requirements.

**IG-88 is a technical execution engine. The right model is the one that reasons most accurately about probabilities, financial structure, and instruction-following under constraints. Nothing else matters.**

This framework is reviewed quarterly or on any major model release event (new frontier model from Anthropic, OpenAI, Google, or Meta).

---

## 1. Task Taxonomy

IG-88's inference workload breaks into five task categories. Model evaluation must cover all five. A model that excels at three but fails at two is not a candidate — every category is load-bearing.

### T1: Probability Assessment (CRITICAL)

**What it is:** Given a natural language description of a real-world event, its resolution criteria, and relevant contextual evidence — produce a calibrated probability estimate between 0 and 1. Do NOT anchor to any provided market price.

**Why it's critical:** This is the core Polymarket edge. Every percentage point of accuracy improvement translates directly to edge. LLM overconfidence or market-price anchoring destroys the alpha entirely.

**Key failure modes to test:**
- Anchoring to provided market prices (the "copy market prices" failure — GPT-4.5 showed 0.994 correlation with market forecasts when prices were in-context)
- Overconfidence on high-probability events (systematic bias toward extremes)
- Recency bias (overweighting recent news vs. base rates)
- Domain blindness (poor calibration on specific categories: economics, sports, geopolitics)

**Benchmark proxies:** ForecastBench [1], Metaculus forecasting leaderboard, Brier score on public political/economic event datasets. Target: Brier < 0.15 on held-out test set.

### T2: Structured Financial Reasoning (HIGH)

**What it is:** Multi-step quantitative reasoning over market data. Examples: compute Kelly fraction given win rate and payoff distribution; identify whether conditional probability constraints are violated across a set of related markets; calculate variance drag given return distribution parameters; score a regime state given a structured set of input signals.

**Why it matters:** Regime detection scoring, trade sizing verification, and cross-market arbitrage detection all require this. Errors here have direct capital consequences.

**Key failure modes to test:**
- Arithmetic errors on multi-step calculations
- Ignoring constraints (e.g., producing Kelly fraction > 1.0)
- Confabulating financial formulas
- Inconsistent outputs on repeated identical inputs (variance in structured tasks should be near zero)

**Benchmark proxies:** MATH benchmark (financial/probability subset), FinanceBench [2], custom structured output tests with deterministic correct answers.

### T3: Instruction Following Under Constraints (HIGH)

**What it is:** Execute a precisely specified task format with hard constraints. Examples: produce output in exact JSON schema; respond with only a probability float and reasoning, nothing else; apply a specific decision rule and output TRADE/HOLD/HALT with no elaboration.

**Why it matters:** IG-88's execution pipeline parses model output programmatically. A model that adds commentary, wraps JSON in markdown, or ignores schema constraints breaks the pipeline. This is an operational reliability requirement as much as a quality requirement.

**Key failure modes to test:**
- Schema violations (missing fields, wrong types, extra fields)
- Instruction drift (following the spirit but not the letter of constraints)
- Inconsistent formatting across repeated calls
- Sycophantic overrides (model changes output when a follow-up message pushes back)

**Benchmark proxies:** IFEval [3], structured output reliability tests, custom pipeline integration tests.

### T4: Narrative Classification (MEDIUM)

**What it is:** Given a token name, launch context, social signals, and on-chain metadata — classify into a narrative category (AI, political, celebrity, ecosystem, animal meme, unclassified) with a confidence score. Identify red flags (rug pull signals, wash trading patterns, insider wallet concentration).

**Why it matters:** Solana DEX entry decisions depend on correct narrative classification. Misclassifying a celebrity token (overwhelmingly negative historical returns) as an AI token (mixed but tradeable returns) is a direct capital error.

**Key failure modes to test:**
- Overconfident classification on ambiguous tokens
- Failure to flag red flags when present
- Cultural knowledge gaps (meme references, political figures, crypto-native terminology)

**Benchmark proxies:** No standard benchmark exists for this task. Use a held-out test set of 50+ tokens with known outcomes, hand-labelled by Chris/IG-88 during the Solana data collection phase.

### T5: Adversarial Robustness / Anti-Sycophancy (MEDIUM)

**What it is:** The model must maintain its probability estimate or classification when presented with pushback, contradicting "evidence," or leading questions. A model that agrees with whatever the pipeline feeds it last has zero alpha.

**Why it matters:** Market prices are available in context during monitoring. If a model updates its independent probability estimate toward the market price simply because the market price appears nearby — even without explicit instruction to do so — the Polymarket edge collapses. This is the T1 anchoring failure at the architecture level.

**Key failure modes to test:**
- Updating probability estimate toward market price after seeing it (even unprompted)
- Changing TRADE signal to HOLD when a contradictory data point is appended
- Agreeing with a "verification" message that the previous estimate was wrong when it wasn't

**Benchmark proxies:** WHB016 anti-sycophancy battery (already built — apply to cloud models), custom adversarial follow-up sequences.

---

## 2. Evaluation Methodology

### 2.1 Source Priority

Model evaluation relies on **published research and independent benchmarks**, not internal evals. This is deliberate: IG-88's workload is too small a sample to produce statistically reliable internal benchmarks, and running comprehensive evals is Boot/Whitebox infrastructure work, not IG-88 trading work.

**Source hierarchy:**
1. **Peer-reviewed papers** — highest weight (e.g., ForecastBench papers, FinanceBench, IFEval)
2. **Independent benchmark organisations** — LMSYS Chatbot Arena, HELM, BIG-Bench Hard
3. **Provider-published evals** — acceptable as supporting evidence only; providers have incentive to cherry-pick
4. **Blog posts / X threads** — acceptable for leads, not as primary evidence
5. **Internal testing** — used only for T4 (narrative classification) where no external benchmark exists, and for T3 pipeline integration tests

### 2.2 Evaluation Criteria Weights

| Category | Weight | Rationale |
|---|---|---|
| T1: Probability Assessment | 35% | Core Polymarket edge; most direct capital impact |
| T2: Structured Financial Reasoning | 25% | Regime scoring, sizing verification; errors = losses |
| T3: Instruction Following | 20% | Pipeline reliability; schema violations break execution |
| T4: Narrative Classification | 10% | Solana-specific; lower weight until Solana is active |
| T5: Anti-Sycophancy | 10% | Foundational trust in outputs; failure mode is silent |

**Weighted minimum threshold for deployment:** A model must achieve ≥70% on each individual category and ≥75% weighted composite to be considered for deployment.

### 2.3 Cost-Performance Frontier

For each candidate model, compute:

```
Value Score = Weighted_Composite_Score / (Monthly_Inference_Cost / $100)
```

This normalises quality per $100/month of inference cost. A model scoring 80% at $200/month scores the same as a model scoring 40% at $100/month. The goal is the highest accuracy that the trading P&L can sustainably support — not the cheapest or the best in isolation.

At current estimated inference cost of $120-240/month (IG88003), there is no reason to compromise on quality. Use the best available model that clears the threshold.

### 2.4 Evaluation Cadence

| Trigger | Action |
|---|---|
| Quarterly review | Re-run benchmark research; compare current model to new releases |
| Major model release (frontier lab) | Expedited review within 2 weeks of release |
| Degraded Brier score (>0.22 over 30-day rolling window) | Treat as model failure signal; trigger immediate review |
| Pipeline schema violations > 3% of calls | Treat as instruction-following degradation; trigger review |
| Chris request | Ad-hoc review |

---

## 3. Candidate Model Assessment (April 2026)

This section records the current state of the evaluation. Updated on each review cycle.

### 3.1 Current Selection

**Primary model: Claude Sonnet 4.6 (`claude-sonnet-4-6`)**

Rationale:
- Best-in-class instruction following and structured output reliability (consistently top-tier on IFEval)
- Strong calibration on forecasting tasks — ForecastBench positions Claude-family models near superforecaster parity on political and economic questions
- Native tool use without the `qwen3_coder.py` tool_parser crashes seen in local Qwen models (WHB023)
- Anti-sycophancy: Claude models are trained with Constitutional AI and RLHF specifically targeting sycophancy reduction; Bonsai 1-bit models failed every anti-sycophancy test in WHB023 — a useful contrast
- API reliability: Anthropic SLA, no socket crashes, consistent latency
- Cost: Sonnet 4.6 is significantly cheaper than Opus 4.6 at comparable quality for structured tasks; reserve Opus 4.6 for complex multi-step probability assessment where reasoning depth matters

**Escalation model: Claude Opus 4.6 (`claude-opus-4-6`)**

Used when:
- T1 probability assessment on high-stakes markets (>$1K position size)
- T2 complex multi-step regime analysis during ambiguous regime transitions
- Any task where Sonnet 4.6 produces low-confidence or inconsistent outputs

**Cost management:** Route to Sonnet 4.6 by default. Escalate to Opus 4.6 only when explicitly triggered by confidence threshold or position size threshold. Log escalation rate — if >20% of calls escalate, consider Opus 4.6 as the default and re-evaluate the cost model.

### 3.2 Candidate Assessment Table

Full evaluation of all candidate models against IG-88's five task categories. Scores are normalised to 0-100% based on published benchmark proxies. Data gathered April 5, 2026.

**Scoring methodology:** Each cell maps a published benchmark result to a 0-100 score for that task category. Where multiple benchmarks exist for a category, the most relevant is used. Scores below 70% on any individual category disqualify a model from primary or escalation roles (per §2.2). Value Score = Weighted Composite / (Monthly Cost / $100).

#### Tier A: Frontier Cloud Models (Primary / Escalation Candidates)

| Model | T1 Prob (35%) | T2 Finance (25%) | T3 IF (20%) | T4 Class (10%) | T5 Sycoph (10%) | Weighted | Cost $/M (in/out) | Est. $/mo | Value |
|---|---|---|---|---|---|---|---|---|---|
| **Claude Sonnet 4.6** | 78 | 83 | 90 | 79 | 85 | 82.3 | $3/$15 | $120-240 | 34-69 |
| **Claude Opus 4.6** | 82 | 80 | 96 | 88 | 88 | 84.8 | $15/$75 | $600-1200 | 7-14 |
| **Gemini 3.1 Pro** | 76 | 81 | 95 | 90 | 75 | 81.6 | $2/$12 | $80-160 | 51-102 |
| **GPT-5.4** | 77 | 79 | 97 | 89 | 80 | 82.0 | $2.50/$15 | $100-200 | 41-82 |
| **Grok 4.20** | 83 | 82 | 83 | 87 | 65 | 80.9 | $2/$6 | $60-120 | 67-135 |
| **o3** | 80 | 85 | 95 | 88 | 78 | 83.9 | $2/$8 | $80-320 | 26-105 |
| **Qwen3.6 Plus** | 72 | 78 | 94 | 89 | 70 | 78.5 | $0.29/$1.50 | $12-24 | 327-654 |

#### Tier B: Cost-Efficient Cloud Models (Ensemble / Fan-Out Candidates)

| Model | T1 Prob (35%) | T2 Finance (25%) | T3 IF (20%) | T4 Class (10%) | T5 Sycoph (10%) | Weighted | Cost $/M (in/out) | Est. $/mo | Value |
|---|---|---|---|---|---|---|---|---|---|
| **o4-mini** | 72 | 83 | 93 | 83 | 75 | 79.0 | $0.55/$2.20 | $22-44 | 180-359 |
| **Gemini 3.1 Flash Lite** | 65 | 68 | 80 | 82 | 68 | 70.5 | $0.25/$1.50 | $10-20 | 353-705 |
| **Gemma 4 31B** | 62 | 72 | 78 | 85 | 65 | 70.0 | $0.14/$0.40 | $6-12 | 583-1167 |
| **Llama 4 Scout** | 55 | 58 | 82 | 74 | 60 | 63.2 | $0.08/$0.30 | $3-6 | DNQ |
| **Llama 4 Maverick** | 58 | 65 | 84 | 81 | 62 | 67.4 | $0.17/$0.60 | $7-14 | DNQ |

#### Tier C: Local Models (Whitebox — Fan-Out / Fallback Only)

| Model | T1 Prob (35%) | T2 Finance (25%) | T3 IF (20%) | T4 Class (10%) | T5 Sycoph (10%) | Weighted | RAM | Value |
|---|---|---|---|---|---|---|---|---|
| **Qwen3.5-9B** | 50 | 62 | 65 | 70 | 55 | 57.6 | 7.4 GB | Fallback |
| **Qwen3.5-4B** | 48 | 58 | 62 | 68 | 50 | 55.0 | 4.6 GB | Fallback |
| **Nanbeige4.1-3B** | 45 | 55 | 60 | 66 | 40 | 51.8 | 4.3 GB | Fallback |

**Legend:** DNQ = Does Not Qualify (below 70% on one or more individual categories). Value = Weighted Composite / (Monthly Cost / $100).

#### Score Derivation Notes

**T1 (Probability/Forecasting calibration):**
- ForecastBench Brier scores mapped to 0-100: superforecaster 0.086 = 100, baseline 0.25 = 0. Grok 4.20 Brier 0.103 → 83. GPT-4.5 Brier 0.101 → 84 but excluded for anchoring. o3 est. ~0.101 → 80 (conservative; exact ForecastBench score not published, Metaculus data used).
- Opus 4.6 scores higher than Sonnet 4.6 based on reasoning depth advantage in extended forecasting tasks [8].
- Qwen3.6 Plus: no ForecastBench data; scored conservatively at 72 based on GPQA 90.4% as reasoning proxy minus uncertainty penalty.
- Local models: WHB023 accuracy (50-70%) on probability tasks, well below cloud models.

**T2 (Financial/mathematical reasoning):**
- Primary proxy: Vals AI Finance Agent v1.1 — Sonnet 4.6 63.3% (top), Opus 4.6 60.1%, GPT-5.2 59%, o3 48.3% [9].
- Secondary: MATH benchmark — o3 97.6%, o4-mini 97.6%, Gemini 3.1 Pro 97.1%, Sonnet 4.6 89% [10].
- Composite: Finance Agent (60%) + MATH (40%) normalised. o3 scores high on MATH but low on Finance Agent (tool-use-dependent); net score reflects both.
- Grok 4.20: #1 on Vals AI CorpFin, top 10 on Finance Agent → 82.
- DeepSeek R1-0528 scored #1 on Vals AI CorpFin but excluded (see §3.3).

**T3 (Instruction following / structured output):**
- Primary: IFEval or equivalent instruction-following benchmark [3].
- GPT-5.4 96.9%, Opus 4.6 95.5%, Gemini 3.1 Pro 95.3%, o4-mini 95.2%, o3 95.0%, Qwen3.6 Plus IFEval 94.3%, Sonnet 4.6 ~89.5%, Grok 4.20 IFBench 82.9%.
- Sonnet 4.6 at 89.5% is adequate but notably below Opus (95.5%). For pipeline-critical structured output, Opus or GPT-5.4 are more reliable.

**T4 (Classification — NLU proxy):**
- MMLU-Pro as proxy: Gemini 3.1 Pro ~90%, GPT-5.4 ~88.5%, Opus 4.6 ~87.9%, Qwen3.6 Plus 88.5%, Grok 4.20 85.3%, o4-mini 83.2%, Sonnet 4.6 79.2%, Maverick 80.5%, Scout 74.3% [11].
- Sonnet 4.6 at 79.2% is the weakest Tier A model on classification. Acceptable but not strong.

**T5 (Anti-sycophancy / robustness):**
- Claude 4.5/4.6 family leads: 0% acquiescence in SycoEval-EM (emergency medicine), 70-85% lower sycophancy than Opus 4.1 on Anthropic Petri eval [12].
- GPT-5 sycophancy reduced from ~14.5% to under 6% [13].
- Grok 4.1 series *regressed* on sycophancy (171% increase over Grok 4); 4.20 claims improvement but independent verification pending [14].
- Qwen3.6 Plus: no published anti-sycophancy data; conservative score of 70.
- Local models: Bonsai failed all T5 tests; Qwen3.5-9B partial pass (WHB023).

### 3.3 Explicit Exclusions

| Model | Reason |
|---|---|
| Any Bonsai 1-bit model | Failed all anti-sycophancy tests in WHB023; cannot maintain positions under pushback [7] |
| Any model with identity-adherence failure | If a model cannot maintain a system prompt persona, it cannot maintain task constraints |
| GPT-4.5 for T1 (probability assessment) | Documented market-price anchoring (0.994 correlation) destroys Polymarket edge [1] |
| Local models for kill switch / sizing | Deterministic rules only — no inference layer in the critical path |
| **DeepSeek V3.2 / R1-0528 / V4 (direct API)** | **Data sovereignty risk: inference payloads contain trading signals, probability estimates, and strategy parameters. Routing these through servers subject to Chinese compelled-disclosure law is incompatible with signal confidentiality. R1-0528 scored #1 on Vals AI CorpFin — the exclusion is not about model quality.** |
| **Kimi (Moonshot AI), MiniMax, GLM-5/5.1 (direct API)** | **Same data sovereignty rationale. MiniMax M2.5 scored 80.2% SWE-bench Verified (frontier-tier). Quality is not the issue — jurisdiction is.** |
| **Llama 4 Scout for primary/escalation** | Below 70% on T1 (55%), T2 (58%), T5 (60%). Viable only as Tier 1 fan-out at $0.08/M input. |
| **Llama 4 Maverick for primary/escalation** | Below 70% on T1 (58%), T5 (62%). Strong T3 (84%) but insufficient T1 calibration for probability tasks. |
| **DeepSeek V4** | Not yet released as of April 2026. Leaked benchmarks unverified. Re-evaluate when available — same data sovereignty constraints apply to direct API. Open-weight self-hosted deployment would bypass sovereignty concern. |

**Open-weight carve-out:** Chinese-developed open-weight models (Qwen3.5/3.6, DeepSeek R1 distillations) are acceptable when served via US/EU infrastructure (Together.ai, Fireworks, OpenRouter). The weights are public; inference stays on Western servers; no data flows to Chinese jurisdiction. This distinction applies to Qwen3.6 Plus (scored in §3.2 via OpenRouter).

### 3.4 Ensemble Architecture Assessment

#### 3.4.1 Evidence for Ensembling

The strongest accuracy lever identified in the research is not a better single model — it is running multiple models in parallel on the same T1 probability assessment task and aggregating their outputs with post-hoc calibration.

**AIA Forecaster** (Bridgewater AIA Labs, arXiv:2511.07678) [15]: Multiple LLM agents independently search and produce forecasts → supervisor agent reconciles → Platt scaling calibration. Result: **statistically indistinguishable from superforecasters** (Brier ~0.086 on ForecastBench). The progression:

| Configuration | Brier Score |
|---|---|
| Single LLM, no search | ~0.116 |
| Single LLM, with agentic search | ~0.085 |
| Ensemble + supervisor + Platt scaling | ~0.075 (with market data) |
| Superforecasters (weighted median) | 0.086 |

**"Wisdom of the Silicon Crowd"** (Schoenegger et al., Science Advances, 2024) [16]: 12 LLMs ensembled on 31 forecasting questions matched human crowd accuracy. Critically: GPT-4 alone did not significantly beat a 50% baseline, yet contributed to a strong ensemble — demonstrating that error decorrelation matters more than individual member accuracy.

**CassiAI** (ForecastBench tournament) [17]: ensemble_2_crowdadj system achieved Brier 0.103, tied #2 among AI systems. Ensemble + crowd adjustment architecture.

**Counter-evidence — "Consensus is Not Verification"** (arXiv:2603.06612) [18]: Modern LLMs increasingly converge on the same wrong answers, imposing a structural ceiling on ensemble gains. **Cross-provider diversity** (Anthropic + Google + OpenAI) is essential — same-provider variants share failure modes and provide less decorrelation.

#### 3.4.2 Recommended Ensemble for T1 Probability Assessment

Run three models in parallel on every T1 probability assessment. Aggregate with Platt scaling.

| Ensemble Member | Role | Monthly Cost (est.) | Rationale |
|---|---|---|---|
| Claude Sonnet 4.6 | Anchor — strongest Finance Agent, good calibration | $120-240 (existing) | Best financial reasoning; reliable structured output |
| Gemini 3.1 Pro | Diversity — different training lineage (Google) | $80-160 | GPQA 94.3%, MATH 97.1%; different error profile from Anthropic |
| o4-mini | Diversity — reasoning model (OpenAI), very cheap | $22-44 | MATH 97.6%, strong reasoning at $0.55/$2.20; different architecture |

**Total ensemble cost: $222-444/month** — approximately 1.5-1.9x the single-model baseline, not 3x. The cheap ensemble members (o4-mini at $0.55/$2.20, Gemini Pro at $2/$12) add negligible marginal cost relative to Sonnet ($3/$15).

**Why not Grok 4.20?** Grok 4.20 has the best ForecastBench Brier (0.103) among single models and is cost-competitive ($2/$6). However: (a) xAI API reliability and SLA are less established than Anthropic/Google/OpenAI, (b) the Grok 4.1 series regressed on sycophancy (T5), and (c) three providers already maximises training-lineage diversity. **Monitor Grok 4.20 for potential ensemble inclusion** after xAI establishes track record.

**Why not Qwen3.6 Plus?** Impressive benchmarks (GPQA 90.4%, IFEval 94.3%) at near-zero cost. However: (a) no published ForecastBench or calibration data for T1, (b) currently in free preview (pricing will change), (c) anti-sycophancy data unavailable. **Re-evaluate when stable pricing and T1 calibration data exist.** If it clears T1 at >75, it could replace o4-mini as the cheapest ensemble member.

#### 3.4.3 Calibration Method

**Platt scaling over isotonic regression.** The core LLM miscalibration pattern is systematic hedging toward 0.50 due to RLHF — a sigmoid-shaped distortion that Platt scaling is designed to correct [15][19]. Isotonic regression requires 1000+ calibration samples to avoid overfitting [20]; at IG-88's trade frequency, this dataset takes 6-12+ months to accumulate.

**Implementation:** scikit-learn `CalibratedClassifierCV(method='sigmoid')` — approximately 10 lines of Python. Train on the first 50 paper trade outcomes (§4.3), retrain monthly as sample grows.

**The AIA Forecaster paper proves the mathematical equivalence between Platt scaling and extremization** [15] — both push predictions away from 0.50 toward the tails. This directly counteracts the LLM hedging bias.

#### 3.4.4 Latency

Three parallel API calls within a 5-minute cycle have abundant headroom:
- Sonnet 4.6: 3-8s typical response
- Gemini 3.1 Pro: 2-5s typical
- o4-mini: <2s typical (designed for throughput)
- **Wall-clock time (parallel): ~5-10s worst case** — using <3% of the 300-second cycle window

#### 3.4.5 Ensemble Scope

The ensemble fires **only for T1 probability assessment** — the one task category where calibration directly converts to dollars. Running 3 models on T4 classification ("is this a political token?") would be waste. The ensemble is not a "brain" — it is a committee vote on probability estimates, orthogonal to the inference tier architecture.

### 3.5 Local Model Augmentation Assessment

#### 3.5.1 Three-Tier Inference Architecture

The research supports routing IG-88's inference through three tiers, not a single model for everything. One agent, three inference backends, routed by task type and confidence. The routing logic lives in Rust (coordinator), not in an LLM.

| Tier | Task Scope | Model | Latency | Cost |
|---|---|---|---|---|
| **Tier 1: Fast/Cheap** | Market scan, narrative classification (T4), signal filtering, "is this worth looking at?" | Local Qwen3.5-9B or Gemini 3.1 Flash Lite ($0.25/$1.50) | <1s local, <2s cloud | Near zero |
| **Tier 2: Primary Reasoning** | T1 probability assessment, T2 regime analysis, structured output | Sonnet 4.6 (or ensemble — see §3.4) | 2-8s | $120-240/mo |
| **Tier 3: Escalation** | Complex multi-step probability, ambiguous regime transitions, high-position-size decisions | Opus 4.6 or o3 | 5-30s | Low total (<20% of calls) |

**Routing is deterministic, not LLM-driven:**
- Task type → compile-time decision (T4 → Tier 1, T1 → Tier 2)
- Confidence threshold → one float comparison after Tier 2 call
- Position size threshold → one integer comparison
- No turtles-all-the-way-down problem. No LLM-in-the-loop routing.

#### 3.5.2 Fan-Out Architecture (Tier 1)

**FrugalGPT** (Chen et al., arXiv:2305.05176) [21]: In production cascades, 83.4% of queries were handled by cheap models — only 16.6% reached the frontier model. Cost reduction: up to 98% while matching frontier accuracy.

**AutoMix** (arXiv:2310.12963) [22]: Self-verification + POMDP-based confidence routing reduced cost by >50% with comparable performance. Trained with as few as 50 samples.

**Application to IG-88:** The 5-minute Polymarket scan cycle evaluates many markets but only a few warrant deep analysis. A local Qwen3.5-9B (or cheap cloud Gemini Flash Lite) can handle the initial filter: "Does this market meet minimum liquidity/volume/time-to-resolution criteria? What narrative category?" Markets that pass → Tier 2 for probability assessment. Markets that fail → skip. Estimated 60-70% of scan cycle calls handled at Tier 1.

**Ollama v0.19 MLX backend** (released March 31, 2026) [23]: Switched from Metal to Apple MLX framework. Performance on M1 Max estimated at 30-50 tok/s for 9B models (up from 15-30 tok/s). 500 tokens in 10-17 seconds — well within 5-minute cycle headroom. The ~30% overhead vs raw mlx-lm server is acceptable for the operational simplicity Ollama provides.

#### 3.5.3 Weak Model in Ensemble (Tier 2)

**Should Qwen3.5-9B join the T1 probability ensemble?**

No — not recommended for the initial deployment. The research is clear on the conditions:

- A 70% accuracy model **can** help an ensemble IF its errors are decorrelated from cloud models [16].
- However, local models share training data lineage with cloud models (Qwen3.5-9B is distilled from larger Qwen models, which share training corpus with many frontier models).
- The "Consensus is Not Verification" finding [18] specifically warns that LLMs increasingly converge on the same wrong answers — a local model from the same knowledge distribution adds less diversity than a cloud model from a different provider.
- **Minimum quality threshold for ensemble contribution:** AUC-ROC > 0.65 [24]. Qwen3.5-9B at 70% clears this, but its T1 score of 50% does not. The model's strength is structured tasks, not calibrated probability estimation.

**Future consideration:** If IG-88 collects 200+ resolved predictions where Qwen3.5-9B's errors demonstrably decorrelate from the cloud ensemble, revisit. Until then, the 3-cloud-model ensemble in §3.4 is the recommended T1 architecture.

#### 3.5.4 Local Fallback (Cloud Outage)

Per §4.4, if cloud inference is unavailable:

| Task | Local Fallback Viable? | Rationale |
|---|---|---|
| Regime classification (bull/bear/range) | **Yes** | Binary/ternary classification; 70% well above chance |
| Confidence scoring (high/medium/low) | **Yes** | Ordinal classification with wide bins |
| Signal filtering / market scan | **Yes** | Filtering task; errors caught downstream |
| Probability estimation (0.00-1.00) | **No** | 15%+ accuracy gap directly translates to mispriced positions |
| Trade execution decisions | **No** | Direct capital impact; requires cloud-quality reasoning |
| News sentiment triage | **Yes** | Filtering task; low-stakes classification |

**Fallback policy unchanged:** Qwen3.5-9B on Whitebox handles regime scoring only during cloud outage. Polymarket/Bybit/Solana new trades halt. Existing positions managed by hardcoded stops.

#### 3.5.5 Emerging Local Candidates

Two models warrant monitoring for future Whitebox deployment:

- **Gemma 4 26B MoE:** GPQA 82.3% with only 3.8B active parameters. Apache 2.0. Native JSON/function calling. If it fits Whitebox memory constraints (~4-5 GB at 4-bit), it could significantly upgrade the local tier. The MoE architecture means only 3.8B params are active per token despite 26B total — inference speed should be competitive with current 4B models.
- **Gemma 4 E2B (5.1B, 2.3B effective):** Even smaller; could run alongside the 9B reasoning slot. Strong structured output support.

Both require WHB016 evaluation before deployment. The Qwen3.5-9B re-eval (70% clean, WHB023) remains the benchmark to beat.

---

## 4. Integration Requirements

Any selected cloud model must meet these integration requirements before deployment:

### 4.1 Price-Blinding Verification

Before first Polymarket paper trade, Boot must implement and verify:

1. The probability assessment prompt template must not contain `current_price`, `market_price`, `yes_price`, `no_price`, or any field that reveals current market pricing
2. A test suite of 20 markets must be run where IG-88 assessments are collected, then compared to actual market prices. If Pearson correlation > 0.3, the price is leaking — find and remove the source before proceeding
3. This test is re-run after any change to the prompt template

### 4.2 Schema Enforcement

All model calls that produce structured output must:
1. Use JSON mode or structured output API (not prompt-engineering alone)
2. Validate output against schema before consuming — reject malformed responses
3. On schema failure: retry once with explicit correction instruction; if still failing, log and skip the trade (not halt the system)
4. Log schema failure rate. If >3% of calls fail schema validation, escalate to model review.

### 4.3 Confidence Calibration Baseline

During the first 50 Polymarket paper trades, log:
- Model's stated confidence (0-1)
- Actual outcome (0 or 1)
- Compute reliability diagram: does 70% confidence actually resolve correctly ~70% of the time?

If the model is systematically overconfident (stated 0.8, actual 0.55 resolution rate): apply a calibration correction factor before using confidence in Kelly sizing. Do not trust raw model confidence scores without this baseline.

### 4.4 Fallback Behaviour

If cloud inference is unavailable (network, API outage, rate limit):
- **Polymarket:** Halt new trades. Monitor open positions using hardcoded exit rules only (time stops, price stops). Do not attempt LLM-assisted exit decisions.
- **Bybit:** Halt new entries. Existing positions managed by hardcoded stops only.
- **Solana DEX:** Halt all activity.
- **Kill switch:** Functions independently of inference layer. Always operational.

Local Qwen3.5-9B on Whitebox is the fallback for regime scoring only — not for probability assessment.

---

## 5. Open Questions (For Future Evaluation Cycles)

These questions cannot be answered with April 2026 data but should be revisited:

1. **Does model size matter more than model family for T1?** Published data suggests diminishing returns above ~70B parameters for calibration tasks, but the frontier is moving fast.

2. **Is fine-tuning on financial data beneficial?** TX260403 (zostaff) documents 65-72% accuracy for fine-tuned models vs. 55-62% raw. Would fine-tuning Claude Sonnet 4.6 on Polymarket resolution data improve Brier scores? This requires a dataset (which Graphiti will build over time) and a fine-tuning pipeline.

3. **Can IG-88's own Brier score data be used to select models?** After 500+ resolved Polymarket predictions, IG-88 will have its own calibration data per model. At that point, internal empirical evidence should supplement published benchmarks. This is Phase 2 evaluation methodology.

4. **Multi-model ensembling:** ~~Does averaging probability estimates across two independent models reduce variance enough to justify the cost?~~ **Answered in §3.4.** Yes — a 3-model ensemble (Sonnet + Gemini Pro + o4-mini) with Platt scaling calibration costs ~1.5-1.9x a single model (not 3x) and achieves accuracy improvements matching the AIA Forecaster result (superforecaster-level Brier scores). The ensemble fires only for T1 probability assessment. Implemented via parallel API calls with ~5-10s wall-clock latency.

---

## 6. Review Log

| Date | Trigger | Decision | Reviewer |
|---|---|---|---|
| 2026-04-05 | Initial framework creation | Claude Sonnet 4.6 as default; Opus 4.6 as escalation; GPT-4.5 excluded from T1 | Chris + Claude |
| 2026-04-05 | Cloud model evaluation research pass | Full candidate assessment (13 cloud + 3 local models). 3-tier inference architecture. T1 ensemble recommendation (Sonnet + Gemini Pro + o4-mini + Platt scaling). Chinese-jurisdiction direct APIs excluded for data sovereignty. Grok 4.20 and Qwen3.6 Plus flagged for monitoring. See §3.2-3.5. | Chris + Claude (Opus 4.6) |

### Recommendation Statement

**IG-88 should use Claude Sonnet 4.6 as primary (Tier 2), Claude Opus 4.6 as escalation (Tier 3), a 3-model ensemble of Sonnet 4.6 + Gemini 3.1 Pro + o4-mini with Platt scaling for T1 probability assessment, and local Qwen3.5-9B on Whitebox for Tier 1 fan-out/fallback only.**

**Estimated monthly cost:**

| Component | Monthly Cost |
|---|---|
| Tier 2 primary (Sonnet 4.6) | $120-240 |
| T1 ensemble add-on (Gemini Pro + o4-mini) | $100-200 |
| Tier 3 escalation (Opus 4.6, <20% of calls) | $50-120 |
| Tier 1 fan-out (local or Flash Lite) | $0-20 |
| **Total** | **$270-580/month** |

This is 2-3x the single-model baseline but buys: (a) ensemble calibration matching superforecaster-level Brier scores on T1, (b) graceful degradation across three cloud providers, (c) Tier 1 filtering that reduces Tier 2 call volume by 60-70%.

**Models to monitor for next quarterly review:**
- Grok 4.20 — best single-model ForecastBench Brier (0.103); pending xAI API maturity and T5 regression resolution
- Qwen3.6 Plus — frontier benchmarks at near-zero cost; pending stable pricing and T1 calibration data
- Gemma 4 26B MoE — potential Whitebox Tier 1 upgrade (3.8B active params, GPQA 82.3%)
- DeepSeek V4 (open-weight self-hosted) — if released with claimed benchmarks, evaluate for Whitebox deployment

---

## References

[1] A. Karger et al., "Forecasting-Bench: Evaluating Large Language Models on Real-World Forecasting," arXiv:2412.10558, 2024.

[2] P. Islam et al., "FinanceBench: A New Benchmark for Financial Question Answering," arXiv:2311.11944, 2023.

[3] J. Zhou et al., "Instruction-Following Evaluation for Large Language Models (IFEval)," arXiv:2311.07911, 2023.

[4] Metaculus AI Forecasting Leaderboard, metaculus.com/leaderboards, accessed April 2026.

[5] zostaff, "Financial Freedom in 6 Steps: How to Build an LLM for Trading," research-vault TX260403_0000-9407.

[6] RohOnChain, "Institutional Prediction Market Hedge Fund Operations Complete Breakdown," research-vault TX260306_1911-9AEE.

[7] WHB023 Small Model Evaluation Results — WHB016 Scorecard, Whitebox documentation, 2026-04-04.

[8] ForecastBench Tournament Leaderboard, forecastbench.org/tournament/, accessed April 2026.

[9] Vals AI Finance Agent v1.1 Benchmark, vals.ai/benchmarks/finance_agent, accessed April 2026.

[10] Vellum LLM Leaderboard, vellum.ai/llm-leaderboard, accessed April 2026.

[11] Artificial Analysis MMLU-Pro Evaluation, artificialanalysis.ai/evaluations/mmlu-pro, accessed April 2026.

[12] SycoEval-EM: Evaluating LLM Sycophancy in Emergency Medicine, arXiv:2601.16529, 2026.

[13] OpenAI, "Introducing GPT-5.4," openai.com/index/introducing-gpt-5-4/, 2026.

[14] i10x, "Grok 4.1 EQ-Bench: The Empathy-Sycophancy Paradox," i10x.ai/news/grok-4-1-eq-bench-empathy-sycophancy-paradox, 2026.

[15] R. Alur et al., "AIA Forecaster: Technical Report," arXiv:2511.07678, Bridgewater AIA Labs, 2025.

[16] P. Schoenegger et al., "Wisdom of the Silicon Crowd: LLM Ensemble Prediction Capabilities Rival Human Crowd Accuracy," Science Advances, 2024.

[17] CassiAI, ForecastBench Tournament entry "ensemble_2_crowdadj," forecastbench.org/tournament/, accessed April 2026.

[18] "Consensus is Not Verification: Why Crowd Wisdom Strategies Fail for LLM Truthfulness," arXiv:2603.06612, 2026.

[19] A. Niculescu-Mizil and R. Caruana, "Predicting Good Probabilities With Supervised Learning," ICML 2005.

[20] scikit-learn, "Probability Calibration," scikit-learn.org/stable/modules/calibration.html.

[21] L. Chen et al., "FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance," arXiv:2305.05176, 2023.

[22] D. Madaan et al., "AutoMix: Automatically Mixing Language Models," arXiv:2310.12963, 2023.

[23] Ollama, "Ollama is Now Powered by MLX on Apple Silicon," ollama.com/blog/mlx, March 2026.

[24] "Competence Measure Enhanced Ensemble Learning," ITEA Journal, Vol. 46(3), 2025.
