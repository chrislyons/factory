#!/usr/bin/env python3
"""
Check if prefill_step_size is actually being used in generate(),
and profile memory at each chunk boundary.
"""
import sys
import gc
import time
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models import cache
from mlx_lm.generate import generate_step

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"

print("Loading model...")
model, tokenizer = load(MODEL_PATH)

# Check if generate_step supports prefill_step_size
import inspect
sig = inspect.signature(generate_step)
params = list(sig.parameters.keys())
print(f"generate_step params: {params}")
has_prefill_step = 'prefill_step_size' in params
print(f"  has prefill_step_size: {has_prefill_step}")

# Check generate() for the same
from mlx_lm.generate import generate as gen_func
sig2 = inspect.signature(gen_func)
params2 = list(sig2.parameters.keys())
print(f"generate() params: {params2}")

# Now let's understand the actual memory bottleneck.
# Run incrementally larger prompts and track peak per forward pass.
print("\n--- Incremental memory profiling ---")
for ctx_size in [512, 1024, 2048, 4096, 8192, 12288, 16384]:
    gc.collect()
    mx.metal.clear_cache()
    
    text = ("Hello " * (ctx_size + 100))
    tokens = mx.array(tokenizer.encode(text, add_special_tokens=False)[:ctx_size])
    
    fresh_cache = cache.make_prompt_cache(model)
    
    mem_before = mx.get_active_memory()
    mx.metal.set_memory_limit(30 * 1024 * 1024 * 1024)  # 30 GB soft limit
    
    try:
        gen = generate_step(tokens, model, max_tokens=1, prompt_cache=fresh_cache)
        tok, _ = next(gen)
        mem_after = mx.get_active_memory()
        peak = mx.get_peak_memory()
        
        # KV cache size
        kv_total = sum(c.nbytes for c in fresh_cache if hasattr(c, 'nbytes'))
        
        print(f"  ctx={ctx_size:>6}: active={mem_after/1e9:.2f} GB | "
              f"delta={((mem_after-mem_before)/1e6):.0f} MB | "
              f"peak={peak/1e9:.2f} GB | "
              f"kv_cache={kv_total/1e6:.0f} MB")
    except Exception as e:
        print(f"  ctx={ctx_size:>6}: FAILED - {e}")
    sys.stdout.flush()

# Try with set_memory_limit to see if we can force MLX to be more conservative
print("\n--- With explicit memory limit (28 GB soft) ---")
mx.metal.set_memory_limit(28 * 1024 * 1024 * 1024)

for ctx_size in [12288, 16384, 24576]:
    gc.collect()
    mx.metal.clear_cache()
    
    text = ("Hello " * (ctx_size + 100))
    tokens = mx.array(tokenizer.encode(text, add_special_tokens=False)[:ctx_size])
    fresh_cache = cache.make_prompt_cache(model)
    
    try:
        gen = generate_step(tokens, model, max_tokens=1, prompt_cache=fresh_cache)
        tok, _ = next(gen)
        mem_after = mx.get_active_memory()
        peak = mx.get_peak_memory()
        print(f"  ctx={ctx_size:>6}: OK active={mem_after/1e9:.2f} GB peak={peak/1e9:.2f} GB")
    except Exception as e:
        print(f"  ctx={ctx_size:>6}: FAILED - {e}")
    sys.stdout.flush()

print("\nDone.")
