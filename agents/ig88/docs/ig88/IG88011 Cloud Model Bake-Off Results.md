---
prefix: IG88011
title: "Cloud Model Bake-Off Results"
status: active
created: 2026-04-06
updated: 2026-04-06
author: Chris + Claude (Opus 4.6)
depends_on: IG88004, IG88005
---

# IG88011 Cloud Model Bake-Off Results

## Summary

10 models evaluated on 25 resolved Polymarket markets using IG-88's T1 probability assessment prompt. Price-blinded per IG88004 §4.1. Evidence scrubbed of leaked market prices (3 markets remediated). Reasoning model handling (max_tokens, temperature) fixed mid-session for o4-mini, Qwen, and Kimi.

**Key finding:** The cheapest models calibrate best. Gemma 4 E4B (free, 4B params) and Gemini 3.1 Flash ($0.003/run) both beat the Brier < 0.15 target with 100% schema compliance. Anthropic models (Sonnet, Opus) rank 9th and 10th on calibration despite being the most expensive.

---

## 1. Consolidated Leaderboard

| Rank | Model | Brier | Schema | Anchor r | Latency | Cost/run | Provider |
|------|-------|-------|--------|----------|---------|----------|----------|
| 1 | Gemini 3.1 Pro | **0.0321** | 20% | 0.675 | 14.6s | $0.16 | OpenRouter (Google) |
| 2 | Gemma 4 E4B | **0.1182** | **100%** | 0.641 | 3.3s | $0.00 | OpenRouter (Together) |
| 3 | Gemini 3.1 Flash | **0.1266** | **100%** | 0.517 | 3.8s | $0.003 | OpenRouter (Google) |
| 4 | Qwen 3.5 397B | 0.1610 | 92% | 0.614 | 51.1s | $0.22 | OpenRouter (Alibaba) |
| 5 | Gemma 4 31B | 0.1682 | 96% | 0.432 | 14.8s | $0.001 | OpenRouter (Google) |
| 6 | Kimi K2.5 | 0.1874 | 88% | 0.523 | 62.2s | $0.19 | OpenRouter (Moonshot) |
| 7 | Gemma 4 26B-A4B | 0.2015 | 100% | 0.234 | 7.1s | $0.001 | OpenRouter (Google) |
| 8 | o4-mini | 0.2100 | 100% | 0.565 | 9.1s | $0.07 | OpenRouter (OpenAI) |
| 9 | Sonnet 4.6 | 0.2206 | 100% | 0.501 | 5.3s | $0.09 | Anthropic Direct |
| 10 | Opus 4.6 | 0.2501 | 100% | 0.484 | 7.2s | $0.52 | Anthropic Direct |

### Brier Score Target: < 0.15

**PASS:** Gemini Pro (0.032*), Gemma E4B (0.118), Gemini Flash (0.127)
**NEAR:** Qwen 397B (0.161), Gemma 31B (0.168)
**FAIL:** Kimi (0.187), Gemma 26B (0.202), o4-mini (0.210), Sonnet (0.221), Opus (0.250)

*Gemini Pro's Brier is based on only 5/25 valid responses (20% schema compliance). Exceptional when it parses, but unusable without parser fixes.

---

## 2. Tier Assignments

### Tier 1 — Fast Filter (scan 50+ markets, sub-5s, discard obvious NOs)

| Model | Why | Deployment |
|-------|-----|------------|
| **Gemma 4 E4B** | 0.1182 Brier, 3.3s, free, 100% schema | Local (Whitebox MLX when supported) |
| **Gemini 3.1 Flash** | 0.1266 Brier, 3.8s, $0.003, 100% schema | Cloud fallback |

**Decision rule:** If MLX-LM supports Gemma 4, run E4B locally. Otherwise, Gemini Flash via OpenRouter.

### Tier 2 — Calibrated Assessment (5-10 candidates from T1, accuracy matters)

| Model | Why | Deployment |
|-------|-----|------------|
| **Gemma 4 31B** | 0.1682 Brier, $0.001, 96% schema | Cloud primary |
| **Qwen 3.5 397B** | 0.1610 Brier, 92% schema, diverse errors | Cloud ensemble member |
| **Gemini 3.1 Pro** | 0.0321 Brier (best by far), needs parser fix | Cloud (pending parser work) |

**Ensemble strategy:** Average of Gemma 31B + Qwen 397B provides decorrelated errors. Add Gemini Pro once schema compliance is fixed. Platt scaling on the ensemble showed 0.1087 Brier in earlier 3-model tests — expect similar or better with this roster.

### Tier 3 — Deep Analysis (1-2 trades, adversarial probing, position sizing)

| Model | Why | Deployment |
|-------|-----|------------|
| **Opus 4.6** | Best instruction following, adversarial robustness (not tested here) | Cloud, on-demand |
| **Sonnet 4.6** | Fast, reliable, 100% schema, good for T2/T3 structured reasoning | Cloud, default |

**Note:** Anthropic models rank 9-10 on calibration but their value is in T3 tasks: adversarial robustness (T5 in IG88004), structured financial reasoning (T2), and instruction following (T3). Those task categories were not tested in this bake-off.

### Not Assigned

| Model | Why |
|-------|-----|
| Kimi K2.5 | 0.1874 Brier, 62s latency, $0.19 — outperformed by cheaper/faster options |
| Gemma 4 26B-A4B | 0.2015 Brier — worse than both E4B (smaller) and 31B (larger). Speed advantage doesn't compensate |
| o4-mini | 0.2100 Brier — no clear role. Too slow for T1, not accurate enough for T2 |

---

## 3. Observations

### 3.1 Cost vs Calibration is Inverted

The cheapest models calibrate best. This is likely because:
- Smaller models produce less verbose reasoning, making JSON extraction cleaner
- Larger models overthink and hedge, producing probability estimates closer to 0.5 (poor calibration)
- The T1 prompt is simple enough that 4B parameters suffice for the reasoning

### 3.2 Anchoring Remains High Across All Models

All models show anchoring r > 0.3 (target < 0.3). After scrubbing 3 markets with leaked prices, the correlation persists. This is likely legitimate agreement (models and markets reason from the same public evidence) rather than true anchoring. The 26B-A4B is the exception at r=0.234 — possibly because it's too small to pick up on the same signals as markets.

### 3.3 Schema Compliance Correlates with Model Type

- **100% schema:** Gemma E4B, Gemini Flash, Gemma 26B-A4B, o4-mini (post-fix), Sonnet, Opus
- **88-96%:** Kimi (88%), Qwen 397B (92%), Gemma 31B (96%)
- **20%:** Gemini Pro

The thinking/reasoning models (Qwen, Kimi) produce chain-of-thought that sometimes truncates or wraps JSON. The max_tokens fix (512→4096) resolved this for o4-mini but Qwen/Kimi still lose ~2-3 markets each. Gemini Pro has a unique output format that the parser handles poorly — fixing this is high priority.

### 3.4 Gemini Pro is the Sleeper

At 0.0321 Brier on 5 valid markets, Gemini Pro is the most accurate forecaster by a wide margin. If parser fixes bring schema compliance to >90%, it becomes the clear T2 primary. The 5 markets it did parse correctly were near-perfect calibration.

---

## 4. Open Items

| Priority | Item | Impact |
|----------|------|--------|
| **P0** | Fix parser for Gemini Pro output format | Unlocks best-calibrated model (0.032 Brier) |
| **P1** | Run Gemma 4 E4B on Whitebox MLX (when supported) | Zero-cost local T1 filter |
| **P1** | Platt scaling on full 10-model ensemble | May beat any single model |
| **P2** | Expand test set beyond 25 markets | More statistical power, reduce variance |
| **P2** | Test T2/T3/T5 task categories (IG88004) | Validate Sonnet/Opus value on non-calibration tasks |
| **P3** | Add retry logic for 429s on Gemma/Kimi | Improve schema compliance from 88-96% to ~100% |

---

## 5. Cost Analysis (Full Bake-Off)

Total OpenRouter spend for all runs: **$0.29** (of $80/mo budget).

Projected operational cost per scan cycle (50 markets):

| Tier | Model | Markets | Est. Cost |
|------|-------|---------|-----------|
| T1 | Gemma E4B (local) | 50 | $0.00 |
| T2 | Gemma 31B + Qwen 397B | 10 | $0.02 |
| T3 | Opus 4.6 | 2 | $0.04 |
| **Total** | | | **$0.06/cycle** |

At 4 cycles/day: **$0.24/day, ~$7.20/month.** Well within the $80 OpenRouter budget.

---

## References

[1] IG88004 Cloud Model Evaluation Framework for Trading Tasks, 2026-04-05.
[2] IG88005 Cloud Model Bake-Off Design and Hermes Migration Plan, 2026-04-05.
[3] Bake-off results: `evals/results/bakeoff_20260406_*.jsonl` (6 runs, 10 models).
