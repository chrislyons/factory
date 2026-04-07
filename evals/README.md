# Factory Model Evals

Local model evaluation framework for MLX and GGUF models on Whitebox.

## Quick Start

```bash
# Run full eval suite against a model
python3 evals/run_eval.py --model ~/models/kai-os/Carnice-9b-GGUF/Carnice-9b-Q6_K.gguf

# Run specific category
python3 evals/run_eval.py --model ~/models/Qwen3.5-9B-MLX-6bit --category reasoning

# Compare two models
python3 evals/compare.py --baseline ~/models/Qwen3.5-9B-MLX-6bit --challenger ~/models/kai-os/Carnice-9b-GGUF/Carnice-9b-Q6_K.gguf
```

## Categories

| Category | Prompts | Tests |
|----------|---------|-------|
| reasoning | 10 | Logic, math, deduction |
| instruction | 10 | Format compliance, constraints |
| code | 10 | Python, Rust, debugging |
| agentic | 10 | Tool use, multi-step planning |
| creative | 10 | Writing quality, coherence |

## Serving

- **MLX models:** `mlx_lm.server` on localhost (OpenAI-compatible)
- **GGUF models:** `llama-server` on localhost (OpenAI-compatible)

Both expose `/v1/chat/completions`, so the eval harness is format-agnostic.
