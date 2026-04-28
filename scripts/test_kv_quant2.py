#!/usr/bin/env python3
"""Diagnostic: check if mlx_lm KV cache quantization actually works."""
import sys
import gc
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models import cache

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"

print("Loading model...")
model, tokenizer = load(MODEL_PATH)
print(f"Loaded. Layers: {len(getattr(model, 'layers', []))}")

# Make fresh cache and inspect
prompt_cache = cache.make_prompt_cache(model)
print(f"\nCache entries: {len(prompt_cache)}")
for i, c in enumerate(prompt_cache[:5]):
    cname = type(c).__name__
    has_q = hasattr(c, 'to_quantized')
    offset = getattr(c, 'offset', 'N/A')
    keys = [k for k in dir(c) if not k.startswith('_') and k not in ('offset',)]
    print(f"  Layer {i}: {cname} | offset={offset} | to_quantized={has_q} | attrs={keys[:8]}")

# Try manually quantizing
print("\n--- Manual quantize test ---")
c0 = prompt_cache[0]
if hasattr(c0, 'to_quantized'):
    qc0 = c0.to_quantized(group_size=64, bits=4)
    print(f"Original: {type(c0).__name__}, bytes={getattr(c0, 'state', {}).get('k', 'no k state')}")
    print(f"Quantized: {type(qc0).__name__}")
    # Check if state has data
    if hasattr(c0, 'state'):
        print(f"Original state keys: {list(c0.state.keys()) if isinstance(c0.state, dict) else type(c0.state)}")
    if hasattr(qc0, 'state'):
        print(f"Quant state keys: {list(qc0.state.keys()) if isinstance(qc0.state, dict) else type(qc0.state)}")
    # Check sizes
    def state_bytes(s):
        if isinstance(s, dict):
            total = 0
            for v in s.values():
                if hasattr(v, 'nbytes'):
                    total += v.nbytes
                elif isinstance(v, dict):
                    total += state_bytes(v)
            return total
        elif hasattr(s, 'nbytes'):
            return s.nbytes
        return 0
    orig_size = state_bytes(c0.state) if hasattr(c0, 'state') else 0
    q_size = state_bytes(qc0.state) if hasattr(qc0, 'state') else 0
    print(f"Original state bytes: {orig_size / 1e6:.2f} MB")
    print(f"Quantized state bytes: {q_size / 1e6:.2f} MB")
    if orig_size > 0 and q_size > 0:
        print(f"Compression ratio: {orig_size / q_size:.2f}x")
else:
    print("No to_quantized method!")

# Check what types exist in the cache
print("\n--- All cache entry types ---")
types = set()
for c in prompt_cache:
    types.add(type(c).__name__)
print(f"Types found: {types}")

# Check how the prompt cache works with the model
print(f"\nModel type: {type(model).__name__}")
if hasattr(model, 'layers'):
    layer0 = model.layers[0]
    print(f"Layer 0 type: {type(layer0).__name__}")
    attn = getattr(layer0, 'self_attn', getattr(layer0, 'attention', None))
    if attn:
        print(f"Attention type: {type(attn).__name__}")

print("\nDone.")
