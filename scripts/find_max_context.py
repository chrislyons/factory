#!/usr/bin/env python3
"""Binary search for max context. Use prefill_step_size to chunk."""
import sys, gc, time, mlx.core as mx
from mlx_lm import load
from mlx_lm.models import cache
from mlx_lm.generate import generate_step

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"
model, tokenizer = load(MODEL_PATH)
print(f"Model loaded. Active: {mx.get_active_memory()/1e9:.1f} GB")

# Test WITH and WITHOUT prefill_step_size
for ctx in [8192, 12288, 16384, 24576, 32768]:
    for chunk in [None, 2048]:
        gc.collect()
        mx.metal.clear_cache()
        
        text = "Hello " * (ctx + 100)
        tokens = mx.array(tokenizer.encode(text, add_special_tokens=False)[:ctx])
        fresh = cache.make_prompt_cache(model)
        
        label = f"chunk={chunk}" if chunk else "no-chunk"
        try:
            gen = generate_step(tokens, model, max_tokens=1, prompt_cache=fresh,
                               prefill_step_size=chunk)
            tok, _ = next(gen)
            peak = mx.get_peak_memory() / 1e9
            active = mx.get_active_memory() / 1e9
            kv = sum(c.nbytes for c in fresh if hasattr(c, 'nbytes')) / 1e6
            print(f"  {ctx:>6} tok [{label:>12}]: OK  peak={peak:.1f}GB  active={active:.1f}GB  kv={kv:.0f}MB")
        except RuntimeError as e:
            print(f"  {ctx:>6} tok [{label:>12}]: OOM")
        except Exception as e:
            print(f"  {ctx:>6} tok [{label:>12}]: ERR: {e}")
        sys.stdout.flush()

print("\nDone.")
