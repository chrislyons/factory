#!/usr/bin/env python3
"""Test specific context sizes with chunked prefill — one at a time."""
import sys, gc, time, mlx.core as mx
from mlx_lm import load
from mlx_lm.models import cache
from mlx_lm.generate import generate_step

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"
model, tokenizer = load(MODEL_PATH)
print(f"Model loaded. Active: {mx.get_active_memory()/1e9:.1f} GB")

import argparse
p = argparse.ArgumentParser()
p.add_argument("--ctx", type=int, default=32768)
args = p.parse_args()

ctx = args.ctx
text = "Hello " * (ctx + 100)
tokens = mx.array(tokenizer.encode(text, add_special_tokens=False)[:ctx])
print(f"Testing {len(tokens)} tokens with prefill_step_size=2048")

gc.collect()
mx.metal.clear_cache()

fresh = cache.make_prompt_cache(model)
t0 = time.perf_counter()
try:
    gen = generate_step(tokens, model, max_tokens=10, prompt_cache=fresh,
                        prefill_step_size=2048)
    first_tok_time = None
    n = 0
    for tok, _ in gen:
        if first_tok_time is None:
            first_tok_time = time.perf_counter() - t0
        n += 1
    elapsed = time.perf_counter() - t0
    peak = mx.get_peak_memory() / 1e9
    active = mx.get_active_memory() / 1e9
    kv = sum(c.nbytes for c in fresh if hasattr(c, 'nbytes')) / 1e6
    print(f"OK: {n} tokens in {elapsed:.1f}s")
    print(f"  TTFT: {first_tok_time:.1f}s")
    print(f"  prefill: {len(tokens)/first_tok_time:.1f} tok/s")
    print(f"  decode: {(n-1)/(elapsed-first_tok_time):.1f} tok/s")
    print(f"  peak: {peak:.1f}GB  active: {active:.1f}GB  kv_cache: {kv:.0f}MB")
except RuntimeError as e:
    print(f"OOM after {time.perf_counter()-t0:.1f}s")
except Exception as e:
    print(f"Error: {e}")
