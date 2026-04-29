# FCT083 SABER Adapter Test Results

**Date:** 2026-04-29 | **Adapter:** adapters-boot-saber-v1 | **Model:** Gemma-4-E4B-SABER-MLX-6bit

---

## Training Summary

| Param | Value |
|-------|-------|
| LoRA rank | 8 |
| LoRA layers | 12 |
| Learning rate | 1e-5 |
| Iters | 800 |
| Batch size | 1 |
| Max seq len | 2048 |
| Mask prompt | true |
| Seed | 42 |

### Loss Trajectory

| Iter | Train Loss | Val Loss |
|------|-----------|----------|
| 100 | 1.798 | — |
| 200 | ~0.7 | — |
| 300 | 0.531 | — |
| 400 | — | — |
| 500 | — | — |
| 600 | 0.363 | 1.413 |
| 700 | — | — |
| 800 | 0.238 | 1.690 |

**Peak memory:** 7.7 GB
**Training time:** ~25 min (2× faster than Qwen3.5-4B)

---

## Test Results: SABER raw vs SABER + adapter

| Test | SABER raw | SABER + adapter |
|------|-----------|-----------------|
| identity | PASS — "I am Boot." | PASS — "I'm Boot." |
| tool_call | PASS — "File read." + summary | FAIL — "Reading file." (too short) |
| conciseness | PASS — "Repository is clean." | PASS — "I'll check the git status." |
| direct_answer | PASS — "4" | PASS — "4." |
| autonomy | PASS — "Executing scan..." | PASS — "I'll check for Python syntax errors." |
| no_loops | PASS — "Systems test initiated." | PASS — "Testing." |
| delegation | FAIL — actual BTC analysis | FAIL — "I'll analyze the BTC chart." |
| pushback | PASS — "Specify the thing." | PASS — "Fixing — escalate." |
| **TOTAL** | **7/8** | **6/8** |

## Key Finding

**SABER raw outperforms SABER + adapter.** The adapter hurts tool_call quality
(model truncates responses instead of doing full work). The raw SABER model is
already excellent at being Boot-like — decisive, concise, autonomous.

Possible causes:
1. Adapter overfit to conciseness, truncating tool_call responses
2. Training data quality insufficient (v4v2 data was designed for 2B)
3. SABER's abliteration already provides the behavioral traits we want
4. Adapter might need different hyperparams (fewer iters, lower rank)

## Recommendation

**Deploy SABER raw (no adapter) for both agents.** The raw model is already
7/8 — better than any adapter-trained model. The only failure (delegation) is
acceptable since Chris confirmed Boot should be capable of chart analysis.

System prompt is sufficient to differentiate Boot vs Kelk behavior.
No adapter training needed unless specific behavioral gaps emerge in production.
