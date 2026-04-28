#!/usr/bin/env python3
"""Benchmark Gemma4 E4B with KV cache quantization."""
import sys, gc, time, json
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models import cache
from mlx_lm.generate import stream_generate

MODEL_PATH = "/Users/nesbitt/models/gemma-4-e4b-6bit"

print("Loading E4B...")
model, tokenizer = load(MODEL_PATH)
model_mem = mx.get_active_memory() / 1e9
print(f"Loaded. Active: {model_mem:.2f} GB")

pc = cache.make_prompt_cache(model)
n_kv = sum(1 for c in pc if hasattr(c, 'to_quantized'))
n_total = len(pc)
print(f"Layers: {n_total} total, {n_kv} KV cache")

# Check cache types
types = set()
for c in pc:
    types.add(type(c).__name__)
print(f"Cache types: {types}")

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

print(f"\n{'='*70}")
print("SUMMARY — Gemma4 E4B KV Cache Quantization")
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

with open("/tmp/e4b_kv_benchmark.json", "w") as f:
    json.dump(results, f, indent=2)
print("Results saved to /tmp/e4b_kv_benchmark.json")
