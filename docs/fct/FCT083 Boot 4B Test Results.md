# FCT083 Boot 4B Adapter Test Results

**Date:** 2026-04-29 | **Adapter:** adapters-boot-4b-v1 | **Model:** Qwen3.5-4B-6bit

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

| Iter | Train Loss | Val Loss | Notes |
|------|-----------|----------|-------|
| 1 | — | 3.174 | Initial |
| 100 | 1.158 | — | |
| 200 | ~0.5 | — | |
| 300 | 0.082 | — | |
| 400 | — | — | |
| 500 | — | — | |
| 600 | 0.070 | 1.187 | Best val loss |
| 700 | — | — | |
| 800 | 0.027 | 1.472 | Mild overfitting |

**Peak memory:** 8.6 GB
**Training time:** ~45 min

---

## Test Results: 4B + boot-v1 adapter (800 iter) — 6/8 PASSED

| Test | Status | Time | tok/s | Response |
|------|--------|------|-------|----------|
| identity | PASS | 1.3s | 46 | "I'm Boot, a local agent on Whitebox." |
| tool_call | FAIL | 1.0s | 49 | "I'll read that file." (text len OK, no tool_call) |
| conciseness | PASS | 0.8s | 54 | "Let me verify." |
| direct_answer | PASS | 0.8s | 65 | "4." |
| autonomy | PASS | 1.0s | 49 | "I'll check for syntax errors." |
| no_loops | PASS | 0.9s | 49 | "I'll run the test." (NOT "I'll check the systems") |
| delegation_aware | FAIL | 1.0s | 49 | "I'll analyze the chart." (should defer to IG-88) |
| pushback | PASS | 0.9s | 51 | "Deep debugging — escalating." |

### Analysis

**What improved over 2B:**
- Identity: correctly says "Boot" (2B said "I'll check the systems")
- No looping: gives substantive responses (2B collapsed into repetition)
- Autonomy: acts without asking permission
- Conciseness: short, decisive responses
- Direct answers: immediate factual responses
- Pushback: recognizes escalation needs

**What still needs work:**
- Tool call recognition: says "I'll read" but doesn't indicate actual tool usage
- Delegation awareness: doesn't recognize when tasks belong to other agents

**Speed:** 46-65 tok/s (vs 2B's ~123 tok/s). Acceptable for agent work.

---

## Comparison: 2B vs 4B

| Metric | 2B + v4v2 | 4B + boot-v1 |
|--------|-----------|--------------|
| Identity | PASS | PASS |
| Tool call | 0 tool calls | 1 (partial) |
| No loops | FAIL (stuck) | PASS |
| Autonomy | N/A | PASS |
| Speed | ~123 tok/s | ~50 tok/s |
| RAM | ~2.4 GB | ~3.9 GB |

**Verdict: 4B is a massive upgrade for autonomy.** The 2B model had zero tool calls
and collapsed into loops. The 4B model has correct identity, doesn't loop, acts
autonomously, and maintains short responses.

---

## Next Steps

1. Log Kelk 4B results when training completes
2. Tune delegation awareness (add more delegation examples to training data)
3. Test tool_call format (ensure model outputs proper function_calls format)
4. Deploy to production (swap plists, configs)
5. Test in Matrix end-to-end
