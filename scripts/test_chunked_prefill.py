#!/usr/bin/env python3
"""
Test chunked prefill via mlx_lm's generate() with prefill_step_size.
This is what the server does internally — should avoid the OOM at 32K.
"""
import sys
import gc
import time
import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import generate

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"

print("Loading model...")
model, tokenizer = load(MODEL_PATH)
print(f"Loaded. Active: {mx.get_active_memory() / 1e9:.1f} GB")

for ctx_size in [2048, 8192, 32768]:
    gc.collect()
    mx.metal.clear_cache()
    
    text = ("The quick brown fox jumps over the lazy dog. " * ((ctx_size // 9) + 1))
    tokens = tokenizer.encode(text, add_special_tokens=False)[:ctx_size]
    prompt = mx.array(tokens)
    
    print(f"\n=== Context: {len(tokens)} tokens (prefill_step_size=2048) ===")
    sys.stdout.flush()
    
    t0 = time.perf_counter()
    try:
        response = generate(
            model, tokenizer, prompt,
            max_tokens=10,
            verbose=False,
            prefill_step_size=2048,
        )
        elapsed = time.perf_counter() - t0
        peak = mx.get_peak_memory() / 1e9
        print(f"  OK! Time: {elapsed:.1f}s | Peak: {peak:.1f} GB")
        print(f"  Response: {response[:200]}")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"  FAILED after {elapsed:.1f}s: {e}")
    sys.stdout.flush()
    gc.collect()

print("\nDone.")
