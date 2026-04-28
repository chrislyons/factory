#!/usr/bin/env python3
"""
Careful memory profiling — small increments, never exceed safe limits.
Find out what ArraysCache actually stores and how it grows.
"""
import sys
import gc
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models import cache

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"

print("Loading model...")
model, tokenizer = load(MODEL_PATH)
base_mem = mx.get_active_memory() / 1e9
print(f"Base memory: {base_mem:.2f} GB")

prompt_cache = cache.make_prompt_cache(model)

# Count types
kv_indices = [i for i, c in enumerate(prompt_cache) if hasattr(c, 'to_quantized')]
arr_indices = [i for i, c in enumerate(prompt_cache) if not hasattr(c, 'to_quantized')]
print(f"KVCache layers: {len(kv_indices)} at indices {kv_indices[:5]}...")
print(f"ArraysCache layers: {len(arr_indices)}")

# Inspect fresh ArraysCache — before any forward pass
ac0 = prompt_cache[arr_indices[0]]
print(f"\nFresh ArraysCache (layer {arr_indices[0]}):")
print(f"  type: {type(ac0).__name__}")
print(f"  nbytes: {ac0.nbytes}")
print(f"  offset: {getattr(ac0, 'offset', 'N/A')}")

# Look at cache internals
if hasattr(ac0, 'cache'):
    inner = ac0.cache
    if isinstance(inner, mx.array):
        print(f"  cache: mx.array shape={inner.shape} dtype={inner.dtype} nbytes={inner.nbytes}")
    elif isinstance(inner, (list, tuple)):
        print(f"  cache: {type(inner).__name__} len={len(inner)}")
        for i, x in enumerate(inner[:4]):
            if hasattr(x, 'shape'):
                print(f"    [{i}]: shape={x.shape} dtype={x.dtype} nbytes={x.nbytes}")
    elif inner is None:
        print(f"  cache: None")
    else:
        print(f"  cache: {type(inner).__name__}")

# Now do ONE forward pass with 64 tokens
print("\n--- Forward pass with 64 tokens ---")
tokens_64 = mx.array(tokenizer.encode("Hello world " * 10, add_special_tokens=False)[:64])
from mlx_lm.generate import generate_step
gen = generate_step(tokens_64, model, max_tokens=1, prompt_cache=prompt_cache)
for tok, _ in gen:
    pass

# Check after
ac0_after = prompt_cache[arr_indices[0]]
print(f"\nArraysCache after 64-token forward:")
print(f"  nbytes: {ac0_after.nbytes}")
print(f"  offset: {getattr(ac0_after, 'offset', 'N/A')}")

if hasattr(ac0_after, 'cache'):
    inner = ac0_after.cache
    if isinstance(inner, mx.array):
        print(f"  cache: mx.array shape={inner.shape} dtype={inner.dtype} nbytes={inner.nbytes}")
    elif isinstance(inner, (list, tuple)):
        print(f"  cache: {type(inner).__name__} len={len(inner)}")
        for i, x in enumerate(inner[:4]):
            if hasattr(x, 'shape'):
                print(f"    [{i}]: shape={x.shape} dtype={x.dtype} nbytes={x.nbytes}")
    elif inner is None:
        print(f"  cache: None")
    else:
        print(f"  cache: {type(inner).__name__}")

# Memory delta
after_mem = mx.get_active_memory() / 1e9
print(f"\nMemory after 64 tokens: {after_mem:.2f} GB (delta: {after_mem - base_mem:.2f} GB)")

# Now 256 tokens
print("\n--- Forward pass with 256 tokens ---")
prompt_cache2 = cache.make_prompt_cache(model)  # fresh cache
tokens_256 = mx.array(tokenizer.encode("Hello world " * 40, add_special_tokens=False)[:256])
gen = generate_step(tokens_256, model, max_tokens=1, prompt_cache=prompt_cache2)
for tok, _ in gen:
    pass

ac256 = prompt_cache2[arr_indices[0]]
print(f"ArraysCache after 256-token forward:")
print(f"  nbytes: {ac256.nbytes}")
if hasattr(ac256, 'cache') and isinstance(ac256.cache, (list, tuple)):
    for i, x in enumerate(ac256.cache[:4]):
        if hasattr(x, 'shape'):
            print(f"    [{i}]: shape={x.shape} dtype={x.dtype} nbytes={x.nbytes}")

after256 = mx.get_active_memory() / 1e9
print(f"Memory after 256 tokens: {after256:.2f} GB (delta: {after256 - base_mem:.2f} GB)")

# Total per-token from ArraysCache alone (48 layers)
arr_nbytes_total = sum(prompt_cache2[i].nbytes for i in arr_indices)
kv_nbytes_total = sum(prompt_cache2[i].nbytes for i in kv_indices)
print(f"\nTotal ArraysCache nbytes (48 layers): {arr_nbytes_total / 1e6:.1f} MB")
print(f"Total KVCache nbytes (16 layers): {kv_nbytes_total / 1e6:.1f} MB")
print(f"Per-token cost (ArraysCache): {arr_nbytes_total / 256 / 1024:.1f} KB")
print(f"Per-token cost (KVCache): {kv_nbytes_total / 256 / 1024:.1f} KB")

print("\nDone.")
