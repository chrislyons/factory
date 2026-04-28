#!/usr/bin/env python3
"""Quick test: verify KV cache quantization actually applies and measures correctly."""
import sys
import gc
import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import generate_step

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"

print("Loading model...")
model, tokenizer = load(MODEL_PATH)
print(f"Loaded. Device: {mx.default_device()}")

# Make a ~4000 token prompt
text = "The quick brown fox jumps over the lazy dog. " * 600
tokens = mx.array(tokenizer.encode(text, add_special_tokens=False)[:4000])
print(f"Prompt: {len(tokens)} tokens")

# Test with fp16 KV cache
print("\n--- FP16 KV Cache ---")
gc.collect()
mx.metal.clear_cache()
mem_before = mx.metal.get_active_memory() / 1e9
print(f"Active memory before: {mem_before:.2f} GB")

# Run generate_step with fp16 cache
token_gen = generate_step(tokens, model, max_tokens=5, kv_bits=None)
for i, (tok, logprobs) in enumerate(token_gen):
    mem_during = mx.metal.get_active_memory() / 1e9
    print(f"  token {i}: mem_active={mem_during:.2f} GB (delta={mem_during - mem_before:.2f} GB)")
    if i >= 4:
        break

# Now test with q4 KV cache
print("\n--- Q4 KV Cache ---")
gc.collect()
mx.metal.clear_cache()
mem_before = mx.metal.get_active_memory() / 1e9
print(f"Active memory before: {mem_before:.2f} GB")

token_gen = generate_step(tokens, model, max_tokens=5, kv_bits=4, kv_group_size=64, quantized_kv_start=0)
for i, (tok, logprobs) in enumerate(token_gen):
    mem_during = mx.metal.get_active_memory() / 1e9
    print(f"  token {i}: mem_active={mem_during:.2f} GB (delta={mem_during - mem_before:.2f} GB)")
    if i >= 4:
        break

# Check the actual cache state
print("\n--- Cache Internals ---")
gc.collect()
mx.metal.clear_cache()

# Create fresh cache
from mlx_lm import cache
prompt_cache = cache.make_prompt_cache(model)
print(f"Cache layers: {len(prompt_cache)}")
for i, c in enumerate(prompt_cache[:3]):
    print(f"  Layer {i}: type={type(c).__name__}, offset={getattr(c, 'offset', 'N/A')}")
    if hasattr(c, 'to_quantized'):
        print(f"    Has to_quantized method!")
        qc = c.to_quantized(group_size=64, bits=4)
        print(f"    Quantized type: {type(qc).__name__}")

print("\nDone.")
