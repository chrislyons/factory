#!/usr/bin/env python3
"""Benchmark Qwen3.5-4B Claude Opus Reasoning Distill with KV cache quantization."""
import sys, gc, time, json
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models import cache
from mlx_lm.generate import stream_generate

MODEL_PATH = "/Users/nesbitt/models/MLX-Qwen3.5-4B-Claude-4.6-Opus-Reasoning-Distilled-v2-6bit"

print("Loading Qwen3.5-4B Distill...")
model, tokenizer = load(MODEL_PATH)
model_mem = mx.get_active_memory() / 1e9
print(f"Loaded. Active: {model_mem:.2f} GB")

pc = cache.make_prompt_cache(model)
n_kv = sum(1 for c in pc if hasattr(c, 'to_quantized'))
n_total = len(pc)
print(f"Layers: {n_total} total, {n_kv} KV cache")

types = set()
for c in pc:
    types.add(type(c).__name__)
print(f"Cache types: {types}")

import json as json_mod
with open(f"{MODEL_PATH}/config.json") as f:
    cfg = json_mod.load(f)
tc = cfg.get("text_config", {})
kv_heads = tc.get("num_key_value_heads", cfg.get("num_key_value_heads", 4))
head_dim = tc.get("head_dim", cfg.get("head_dim", 256))
print(f"KV heads: {kv_heads}, head_dim: {head_dim}")
kv_per_token_fp16 = n_kv * 2 * kv_heads * head_dim * 2
print(f"KV per token fp16: {kv_per_token_fp16} bytes = {kv_per_token_fp16/1024:.1f} KB")

def make_tokens(tokenizer, n):
    text = "The quick brown fox jumps over the lazy dog. " * ((n // 9) + 1)
    return tokenizer.encode(text, add_special_tokens=False)[:n]

def bench(model, tokenizer, prompt_tokens, max_new, kv_bits, label):
    gc.collect()
    mx.metal.clear_cache()
    t0 = time.perf_counter()
    last = None
    for resp in stream_generate(model, tokenizer, prompt_tokens,
                                 max_tokens=max_new, kv_bits=kv_bits,
                                 kv_group_size=64, quantized_kv_start=0):
        last = resp
    elapsed = time.perf_counter() - t0
    if last is None:
        return {"label": label, "error": "no output"}
    return {
        "label": label,
        "prompt_tps": round(last.prompt_tps, 1),
        "gen_tps": round(last.generation_tps, 1),
        "elapsed_s": round(elapsed, 1),
        "peak_mem_gb": round(last.peak_memory, 2),
    }

contexts = [512, 2048, 8192, 16384, 32768]
modes = [("fp16", None), ("q8", 8), ("q4", 4)]
max_new = 50
results = []

for ctx in contexts:
    tokens = make_tokens(tokenizer, ctx)
    actual = len(tokens)
    print(f"\n=== Context: {actual} tokens ===")
    sys.stdout.flush()
    
    for mode_name, bits in modes:
        try:
            r = bench(model, tokenizer, tokens, max_new, bits, mode_name)
            r["context"] = actual
            results.append(r)
            print(f"  {mode_name:5s} | prefill: {r['prompt_tps']:>7.1f} tok/s | "
                  f"decode: {r['gen_tps']:>6.1f} tok/s | "
                  f"peak: {r['peak_mem_gb']:.1f}GB | time: {r['elapsed_s']:.1f}s")
        except Exception as e:
            results.append({"label": mode_name, "context": actual, "error": str(e)})
            print(f"  {mode_name:5s} | FAILED: {e}")
        sys.stdout.flush()
        gc.collect()
        mx.metal.clear_cache()

# Also test with thinking mode disabled (for simple tasks)
print(f"\n=== Thinking mode test (512 tokens) ===")
tokens = make_tokens(tokenizer, 512)
# Test with enable_thinking=False via chat template
try:
    gc.collect()
    mx.metal.clear_cache()
    t0 = time.perf_counter()
    last = None
    for resp in stream_generate(model, tokenizer, tokens, max_tokens=50,
                                 kv_bits=None, kv_group_size=64, quantized_kv_start=0):
        last = resp
    elapsed = time.perf_counter() - t0
    print(f"  fp16 | prefill: {last.prompt_tps:.1f} tok/s | decode: {last.generation_tps:.1f} tok/s")
except Exception as e:
    print(f"  FAILED: {e}")

print(f"\n{'='*70}")
print("SUMMARY — Qwen3.5-4B Claude Opus Distill KV Cache")
print(f"{'='*70}")
print(f"{'ctx':>8} {'kv':>5} {'prefill':>10} {'decode':>10} {'peak_gb':>10}")
print("-" * 70)
for r in results:
    if "error" in r:
        print(f"{r.get('context',0):>8} {r.get('label','?'):>5} {'FAILED':>10} {'':>10} {'':>10}")
    else:
        print(f"{r['context']:>8} {r['label']:>5} {r['prompt_tps']:>10.1f} "
              f"{r['gen_tps']:>10.1f} {r['peak_mem_gb']:>10.1f}")
print(f"{'='*70}")

# Memory for two instances
print(f"\nFeasibility: 2x 4B + 35B-A3B")
print(f"  4B model memory: {model_mem:.1f} GB")
print(f"  2x 4B = {model_mem*2:.1f} GB")
print(f"  35B-A3B resident = 3.0 GB")
print(f"  Total model RAM = {model_mem*2 + 3.0:.1f} GB")
print(f"  macOS overhead ~ 5 GB")
print(f"  Total = {model_mem*2 + 3.0 + 5:.1f} GB of 32 GB")
print(f"  Headroom = {32 - model_mem*2 - 3.0 - 5:.1f} GB")

with open("/tmp/qwen35_4b_distill_kv_benchmark.json", "w") as f:
    json.dump(results, f, indent=2)
print("Results saved to /tmp/qwen35_4b_distill_kv_benchmark.json")
