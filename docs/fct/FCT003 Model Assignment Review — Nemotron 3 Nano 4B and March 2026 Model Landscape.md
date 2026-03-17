# FCT003 Model Assignment Review — Nemotron 3 Nano 4B and March 2026 Model Landscape

**Prefix:** FCT | **Repo:** ~/dev/factory/ | **Status:** Living document | **Related:** FCT002

---

## 1. Trigger

Three model releases in Q1 2026 prompted a review of the FCT002 permanent agent roster:

- **Nemotron-3-Nano-4B**: 4B hybrid Mamba2-Transformer MoE, 1M token context (262K default safe cap), ~5GB RAM at 8-bit, ~3GB at 4-bit, reasoning toggle (on/off), native tool use. MLX port confirmed via LM Studio. Source: [1]
- **Qwen3.5-4B** (released Mar 2, 2026): hybrid GatedDeltaNet+MoE, 262K context, multimodal (text/image/video), Apache 2.0. MLX confirmed (Q6 ~3.4GB). Source: [2]
- **LFM2-2.6B-Exp** (released Dec 2025): pure RL checkpoint on LFM2-2.6B backbone, dynamic hybrid reasoning with think tokens. **32K context window confirmed.** Hybrid architecture: double-gated short-range LIV convolution + GQA, 30 layers. Strong IFBench (beats DeepSeek R1-0528), IFEval strict >88%, GPQA ~42%. Source: [3]

---

## 2. Corrections to FCT002

- **Nemotron-3-Nano-4B is a real distinct 4B model** — NOT the same as Nemotron-3-Nano-30B-A3B. Earlier analysis incorrectly conflated them. The 4B is a genuine 4B parameter model running in ~5GB RAM at 8-bit. The 30B-A3B is a separate MoE model with 31.6B total params and ~3.6B active per forward pass, requiring 18–20GB to load.
- **LFM2.5-3B/4B still does not exist** — FCT002 was correct. LFM2.5 series is 1.2B-scale only (Base, Instruct, JP, VL-1.6B, Audio-1.5B). No 3B or 4B variant confirmed as of March 2026.
- **LFM2.5-1.2B context window is 32K** — confirmed live constraint for Nan's observer role.
- **Nanbeige4.1-3B context window is 256K** — confirmed correct in FCT002.
- **LFM3** announced by Liquid AI CEO for 2026 release — optimized for AI PC (AMD), voice + vision agent. Not yet available.

---

## 3. Per-Agent Model Assessment

### Boot (currently Nanbeige4.1-3B — flagged lower confidence in FCT002)

Two new viable candidates have emerged:

- **Nemotron-3-Nano-4B**: Reasoning toggle suits Boot's dual-mode work (judgment vs. fast tool dispatch). 1M ctx window. Fits 16GB memory budget at 8-bit. MLX confirmed. However, agentic claims are NVIDIA-sourced only — no independent 600-turn validation.
- **Qwen3.5-4B** (Mar 2 release): Structured output, 262K ctx, multimodal, RAG-friendly. Already in production on Whitebox for Kelk and Expert pool — toolchain compatibility confirmed.

Nanbeige's primary advantage (600-turn deep-search agentic stability) is IG-88's use case more than Boot's. Boot's workload is project delegation, judgment calls, and multi-week coordination — context depth and structured output matter more than raw agentic loop stability.

**Decision: deferred.** Open question updated to three-way empirical test: Nanbeige4.1-3B vs. Qwen3.5-4B vs. Nemotron-3-Nano-4B. Run on Whitebox arrival. Also audit Nemotron tool-call format compatibility with coordinator-rs JSON schema before benchmarking.

---

### IG-88 (Nanbeige4.1-3B — high confidence)

No change. 600-turn documented agentic stability + deep-search training validated for 50+ source scanner sessions. Nemotron's agentic claims are NVIDIA-sourced only — no independent validation at this use case scale. Nanbeige holds.

---

### Kelk (Qwen3.5-4B)

Mar 2 release is a straightforward upgrade to the assigned model. No slot change. Kelk uses Qwen3.5-4B Q6 MLX (~3.4GB) and is already live on Whitebox.

LFM2.5-3B migration target still doesn't exist. LFM2-2.6B-Exp is interesting (think tokens, strong IFBench) but is LFM2 generation (previous gen architecture vs LFM2.5). Monitor.

SmolLM3-3B (Jul 2025, Apache 2.0, 128K ctx, dual-mode reasoning, 11.2T token training) is a new candidate worth noting — outperforms Llama-3.2-3B and Qwen2.5-3B, competitive with Qwen3-4B and Gemma3-4B. Not yet evaluated for Kelk's conversational continuity workload.

---

### Nan (LFM2.5-1.2B Thinking)

32K context confirmed as live constraint. Observer watching Chris-Boot-Kelk stream in active sessions can fill this window in hours during intensive work.

**LFM2-2.6B-Exp flagged as upgrade candidate**: think tokens, strong IFBench (beats DeepSeek R1-0528 at 263x smaller), GPQA ~42%. **Context window confirmed: 32K** — same constraint as current LFM2.5-1.2B. This means the upgrade improves reasoning quality but does not resolve the context depth problem. Evaluate whether 32K is acceptable long-term for Nan's observer role or whether a different architecture is needed.

**Action:** Add 32K callout to FCT002 sections 3 and 7. Evaluate LFM2-2.6B-Exp as a quality-over-size upgrade for Nan when Whitebox arrives.

---

### Expert Pool (Qwen3.5-4B)

Mar 2 release upgrade. No slot change.

---

## 4. Extended Model Landscape — New Candidates Surveyed

Models surveyed beyond the primary roster for potential future roles:

### Gemma 3-4B (Google)
- Sizes: 270M, 1B, 4B, 12B, 27B. Sub-5B options are 270M (text-only, 32K), 1B (text-only, 32K), 4B (multimodal, image+text).
- MLX confirmed: `mlx-community/gemma-3-4b-it-4bit` and `-bf16` available.
- QAT quantization: 54% perplexity reduction vs standard post-training quantization.
- 20–50% faster inference than llama.cpp on Apple Silicon.
- **Assessment:** Viable 4B multimodal option. Competes with Qwen3.5-4B. No strong differentiator for Factory's current agent workloads. Monitor.

### Phi-4-mini (Microsoft, 3.8B, MIT)
- 128K context window. Strong function calling and instruction following.
- Architecture: new vocabulary, better post-training for tool use. SFT + DPO.
- Phi-4-mini-reasoning variant: think tokens, distillation + RL, strong math.
- **Assessment:** 128K context is a meaningful advantage over Qwen3.5-4B (262K) — wait, Qwen3.5-4B has more context. Phi-4-mini's primary differentiator is native function calling discipline and Microsoft's tooling ecosystem. Lower priority for Factory given Qwen3.5-4B is already in production.

### SmolLM3-3B (Hugging Face, Jul 2025, Apache 2.0)
- 128K context (64K training, 128K via YaRN extrapolation).
- 11.2T token training. Dual-mode reasoning (think/no-think). 6 languages.
- NoPE architecture (no positional embeddings on every 4th layer) for long-context coherence.
- Outperforms Llama-3.2-3B and Qwen2.5-3B. Competitive with Qwen3-4B and Gemma3-4B.
- **Assessment:** Interesting for Kelk long-term. Fully open (weights + training recipe + data). Monitor for MLX community port availability.

---

## 5. Context Window Table

| Model | Context | Notes |
|-------|---------|-------|
| Nanbeige4.1-3B | 256K | Boot/IG-88 primary |
| Qwen3.5-4B | 262K | Kelk/Expert pool |
| Nemotron-3-Nano-4B | 1M (262K safe) | Boot candidate |
| LFM2.5-1.2B Thinking | 32K | Nan current — live constraint |
| LFM2-2.6B-Exp | 32K | Nan upgrade candidate — same constraint |
| SmolLM3-3B | 128K | Kelk future candidate |
| Phi-4-mini | 128K | Low priority |
| Gemma 3-4B | 128K | Low priority |

---

## 6. Open Questions (delta from FCT002)

1. **Boot three-way test**: Nanbeige4.1-3B vs. Qwen3.5-4B vs. Nemotron-3-Nano-4B — empirical comparison on Whitebox arrival. Criteria: tool-call reliability, judgment quality on multi-week project delegation, memory efficiency. Audit Nemotron tool-call JSON format vs coordinator-rs schema first.
2. **Nan long-term context problem**: LFM2-2.6B-Exp upgrade improves quality but 32K window is unchanged. Is 32K sufficient for Nan's observer role or does the role require a different model tier?
3. **SmolLM3 MLX availability**: Check for `mlx-community/SmolLM3-3B` port. If available, evaluate for Kelk long-term migration (NoPE architecture + 128K ctx could suit conversational continuity).
4. **Update FCT002 sections 3 and 7** — add explicit 32K Nan context constraint callout.
5. **Monitor LFM2.5 3B+** — still no release. Still the intended long-term architecture for Boot/Kelk when available.
6. **LFM3** — Liquid AI announced for 2026. Watch for release.

---

## References

[1] Unsloth, "Nemotron-3 How To Run Guide." [Online]. Available: https://unsloth.ai/docs/models/nemotron-3

[2] Qwen/Qwen3.5-4B, Hugging Face. [Online]. Available: https://huggingface.co/Qwen/Qwen3.5-4B

[3] LiquidAI/LFM2-2.6B-Exp, Hugging Face. [Online]. Available: https://huggingface.co/LiquidAI/LFM2-2.6B-Exp

[4] Liquid AI, "Introducing LFM2.5: The Next Generation of On-Device AI," Jan. 2026. [Online]. Available: https://www.liquid.ai/blog/introducing-lfm2-5-the-next-generation-of-on-device-ai

[5] HuggingFaceTB/SmolLM3-3B, Hugging Face. [Online]. Available: https://huggingface.co/HuggingFaceTB/SmolLM3-3B

[6] "Gemma 3 — mlx-community Collection," Hugging Face. [Online]. Available: https://huggingface.co/collections/mlx-community/gemma-3

[7] microsoft/Phi-4-mini-instruct, Hugging Face. [Online]. Available: https://huggingface.co/microsoft/Phi-4-mini-instruct
