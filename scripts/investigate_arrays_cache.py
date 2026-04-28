#!/usr/bin/env python3
"""
Investigate what ArraysCache (GatedDeltaNet) actually stores in memory.
The analytical model was wrong — only counting KVCache layers but the 48
ArraysCache layers also grow with context.
"""
import sys
import gc
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models import cache

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"

print("Loading model...")
model, tokenizer = load(MODEL_PATH)
print(f"Loaded. Active mem: {mx.get_active_memory() / 1e9:.2f} GB")

prompt_cache = cache.make_prompt_cache(model)
print(f"\nCache entries: {len(prompt_cache)}")

# Inspect ArraysCache internals
kv_entries = [c for c in prompt_cache if hasattr(c, 'to_quantized')]
arr_entries = [c for c in prompt_cache if not hasattr(c, 'to_quantized')]
print(f"KVCache entries: {len(kv_entries)}")
print(f"ArraysCache entries: {len(arr_entries)}")

# Deep inspect one ArraysCache
ac = arr_entries[0]
print(f"\nArraysCache type: {type(ac).__name__}")
print(f"  Module: {type(ac).__module__}")

# Check the 'cache' attribute
if hasattr(ac, 'cache'):
    c = ac.cache
    print(f"  .cache type: {type(c).__name__}")
    if isinstance(c, (list, tuple)):
        print(f"  .cache length: {len(c)}")
        for i, item in enumerate(c[:5]):
            if hasattr(item, 'shape'):
                print(f"    [{i}] shape={item.shape}, dtype={item.dtype}, nbytes={item.nbytes}")
            elif isinstance(item, dict):
                for k, v in item.items():
                    if hasattr(v, 'shape'):
                        print(f"    [{i}].{k} shape={v.shape}, dtype={v.dtype}, nbytes={v.nbytes}")
                    else:
                        print(f"    [{i}].{k} = {type(v).__name__}: {v}")
            else:
                print(f"    [{i}] type={type(item).__name__}: {item}")
    elif isinstance(c, dict):
        for k, v in c.items():
            if hasattr(v, 'shape'):
                print(f"    .{k} shape={v.shape}, dtype={v.dtype}, nbytes={v.nbytes}")
            else:
                print(f"    .{k} = {type(v).__name__}: {v}")
    elif hasattr(c, 'shape'):
        print(f"  .cache shape={c.shape}, dtype={c.dtype}, nbytes={c.nbytes}")

# Check state
if hasattr(ac, 'state'):
    s = ac.state
    print(f"\n  .state type: {type(s).__name__}")
    if isinstance(s, dict):
        for k, v in s.items():
            if hasattr(v, 'shape'):
                print(f"    .{k} shape={v.shape}, dtype={v.dtype}, nbytes={v.nbytes}")
            elif isinstance(v, dict):
                for kk, vv in v.items():
                    if hasattr(vv, 'shape'):
                        print(f"    .{k}.{kk} shape={vv.shape}, dtype={vv.dtype}, nbytes={vv.nbytes}")
                    else:
                        print(f"    .{k}.{kk} = {type(vv).__name__}")

# Check nbytes
if hasattr(ac, 'nbytes'):
    print(f"\n  .nbytes = {ac.nbytes}")

# Now run a forward pass with a small prompt and check memory growth
print("\n--- Memory growth test ---")
from mlx_lm.generate import generate_step

for ctx_size in [64, 256, 1024, 4096]:
    gc.collect()
    mx.metal.clear_cache()
    
    text = ("Hello world " * (ctx_size // 2))
    tokens = mx.array(tokenizer.encode(text, add_special_tokens=False)[:ctx_size])
    
    # Fresh cache
    fresh_cache = cache.make_prompt_cache(model)
    
    mem_before = mx.get_active_memory()
    
    # Run through the model
    gen = generate_step(tokens, model, max_tokens=1, prompt_cache=fresh_cache)
    for tok, _ in gen:
        pass
    
    mem_after = mx.get_active_memory()
    
    # Check ArraysCache state after forward pass
    ac_after = fresh_cache[0]  # Layer 0 is ArraysCache
    nbytes_after = ac_after.nbytes if hasattr(ac_after, 'nbytes') else 0
    
    print(f"  ctx={ctx_size:>5}: delta={((mem_after - mem_before) / 1e6):>8.1f} MB | "
          f"ArraysCache nbytes={nbytes_after / 1e6:.2f} MB | "
          f"total_active={mem_after / 1e9:.2f} GB")
    sys.stdout.flush()

print("\nDone.")
