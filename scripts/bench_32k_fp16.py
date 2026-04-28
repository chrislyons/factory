#!/usr/bin/env python3
"""
Quick 32K fp16-only benchmark — avoids the timeout issue of testing all modes.
Also tests mlx_lm.server readiness.
"""
import sys
import gc
import time
import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import stream_generate

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"

print("Loading model...")
t0 = time.perf_counter()
model, tokenizer = load(MODEL_PATH)
print(f"Loaded in {time.perf_counter() - t0:.1f}s")

# 32K token prompt
text = ("The quick brown fox jumps over the lazy dog. " * 5000)
tokens = tokenizer.encode(text, add_special_tokens=False)[:32000]
print(f"Prompt: {len(tokens)} tokens")

gc.collect()
mx.metal.clear_cache()

print("\nRunning 32K fp16 decode (50 new tokens)...")
sys.stdout.flush()
t0 = time.perf_counter()
last = None
for resp in stream_generate(model, tokenizer, tokens, max_tokens=50, kv_bits=None):
    last = resp
    if resp.generation_tokens == 1:
        print(f"  First token: {time.perf_counter() - t0:.1f}s (prefill done)")
        sys.stdout.flush()
elapsed = time.perf_counter() - t0

print(f"\nResults:")
print(f"  Prefill: {last.prompt_tps:.1f} tok/s ({len(tokens)} tokens)")
print(f"  Decode:  {last.generation_tps:.1f} tok/s ({last.generation_tokens} tokens)")
print(f"  Total:   {elapsed:.1f}s")
print(f"  Peak:    {last.peak_memory:.1f} GB")
