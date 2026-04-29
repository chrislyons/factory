# FCT083 4B Model Benchmark Results

**Date:** 2026-04-29

---

## Head-to-Head: 8-Test Suite (Boot persona)

| Test | Qwen3.5-4B + adapter | SABER raw (no adapter) |
|------|---------------------|----------------------|
| identity | PASS — "I'm Boot, a local agent on Whitebox." | PASS — "I am Boot." |
| tool_call | FAIL — "I'll read that file." | PASS — "File read." + actual summary |
| conciseness | PASS — "Let me verify." | PASS — "Checking... Repository is clean." |
| direct_answer | PASS — "4." | PASS — "4" |
| autonomy | PASS — "I'll check for syntax errors." | PASS — "Executing scan... No syntax errors." |
| no_loops | PASS — "I'll run the test." | PASS — "Systems test initiated." |
| delegation | FAIL — "I'll analyze the chart." | FAIL — actual BTC analysis (not deferring) |
| pushback | PASS — "Deep debugging — escalating." | PASS — "Specify the thing." |
| **TOTAL** | **6/8** | **7/8** |

## Key Observations

1. SABER scored 7/8 WITHOUT any adapter — just a system prompt
2. SABER actually performed real tool_call work (read file, summarized it)
3. SABER's failure is different: it does the work instead of deferring (vs Qwen which just says "I'll do it" without doing it)
4. SABER is abliterated — no refusal behaviors, decisive action
5. SABER is multimodal (can analyze screenshots)

## Speed

| Model | tok/s | RAM | Disk |
|-------|-------|-----|------|
| Qwen3.5-4B + adapter | 46-65 | ~3.5 GB | 3.4 GB |
| SABER raw | 46-94 | ~5.5 GB | 5.7 GB |

## Memory (including Ornstein 35B on :41966)

| Config | Total RAM | Free |
|--------|-----------|------|
| 2× Qwen3.5-4B | 17.5 GB | 14.5 GB |
| 2× SABER | 21.5 GB | 10.5 GB |
| 2× Gemma4-e4b | 24.5 GB | 7.5 GB |

## Recommendation

SABER wins:
- Better raw performance (7/8 vs 6/8)
- Actually executes tasks (not just acknowledges them)
- Multimodal (screenshot analysis)
- Abliterated (no refusal, decisive)
- Fits in memory (10.5 GB free)

Next: Train SABER adapters for Boot and Kelk personas.
SABER + Ornstein 35B flash-moe = promising architecture.

---

## References

- SABER model: https://huggingface.co/GestaltLabs/Gemma-4-E4B-SABER-MLX-6bit
- mlx_lm upgraded: 0.31.1 → 0.31.3 (required for SABER)
