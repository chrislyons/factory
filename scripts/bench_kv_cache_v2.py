#!/usr/bin/env python3
"""
KV Cache Quantization Benchmark v2 for Ornstein-Hermes-3.6-27b-MLX-6bit
Key finding: Only 16 of 64 layers use KVCache (rest are GatedDeltaNet linear attn).
So KV cache is ~1/4 what you'd expect for a 64-layer model.
"""
import sys
import gc
import time
import json
import mlx.core as mx
from mlx_lm import load
from mlx_lm.models import cache
from mlx_lm.generate import stream_generate

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"

KV_MODES = {"fp16": None, "q8": 8, "q6": 6, "q5": 5, "q4": 4}

def make_prompt_tokens(tokenizer, n_tokens):
    text = ("The quick brown fox jumps over the lazy dog. " * ((n_tokens // 9) + 1))
    tokens = tokenizer.encode(text, add_special_tokens=False)
    return tokens[:n_tokens]


def measure_cache_memory(model, tokenizer, prompt_tokens, kv_bits):
    """Measure actual cache memory by loading model + running prefill."""
    gc.collect()
    mx.metal.clear_cache()

    # Measure baseline (model loaded, no cache)
    baseline = mx.metal.get_active_memory()

    # Run generate_step for a few tokens to fill cache
    from mlx_lm.generate import generate_step
    gen = generate_step(
        mx.array(prompt_tokens), model, max_tokens=3,
        kv_bits=kv_bits, kv_group_size=64, quantized_kv_start=0
    )
    tokens_out = []
    for tok, _ in gen:
        tokens_out.append(tok)

    after = mx.metal.get_active_memory()
    cache_mem = after - baseline

    return {
        "baseline_gb": baseline / 1e9,
        "after_gb": after / 1e9,
        "cache_gb": cache_mem / 1e9,
        "tokens_out": len(tokens_out),
    }


def bench_decode(model, tokenizer, prompt_tokens, max_new, kv_bits):
    """Benchmark decode speed."""
    gc.collect()
    mx.metal.clear_cache()

    t0 = time.perf_counter()
    last = None
    for resp in stream_generate(
        model, tokenizer, prompt_tokens,
        max_tokens=max_new,
        kv_bits=kv_bits, kv_group_size=64, quantized_kv_start=0,
    ):
        last = resp
    elapsed = time.perf_counter() - t0

    if last is None:
        return {"error": "no output"}

    return {
        "prompt_tps": round(last.prompt_tps, 1),
        "gen_tps": round(last.generation_tps, 1),
        "elapsed_s": round(elapsed, 1),
        "gen_tokens": last.generation_tokens,
    }


def main():
    print(f"Loading model from {MODEL_PATH} ...")
    sys.stdout.flush()
    t0 = time.perf_counter()
    model, tokenizer = load(MODEL_PATH)
    print(f"Loaded in {time.perf_counter() - t0:.1f}s")

    # Count KV cache vs linear attention layers
    n_kv = sum(1 for c in cache.make_prompt_cache(model) if hasattr(c, 'to_quantized'))
    n_total = len(cache.make_prompt_cache(model))
    print(f"Layers: {n_total} total, {n_kv} KV cache, {n_total - n_kv} linear attention")

    # Model memory
    model_mem = mx.metal.get_active_memory() / 1e9
    print(f"Model memory (loaded): {model_mem:.1f} GB")
    print(f"Available for KV cache: {32 - model_mem:.1f} GB (assuming 32GB system)")
    print()

    # Phase 1: Memory measurement at 32K context
    print("=" * 65)
    print("PHASE 1: KV Cache Memory at 32K context")
    print("=" * 65)
    prompt_32k = make_prompt_tokens(tokenizer, 32000)
    actual_ctx = len(prompt_32k)
    print(f"Actual prompt tokens: {actual_ctx}")
    print()

    for mode_name, bits in KV_MODES.items():
        try:
            m = measure_cache_memory(model, tokenizer, prompt_32k, bits)
            print(f"  {mode_name:5s} | cache: {m['cache_gb']:>6.2f} GB | "
                  f"baseline: {m['baseline_gb']:.1f} GB | after: {m['after_gb']:.1f} GB")
            sys.stdout.flush()
        except Exception as e:
            print(f"  {mode_name:5s} | FAILED: {e}")
            sys.stdout.flush()
        gc.collect()
        mx.metal.clear_cache()

    # Phase 2: Decode speed at various contexts
    print()
    print("=" * 65)
    print("PHASE 2: Decode Speed (50 new tokens)")
    print("=" * 65)

    context_sizes = [512, 4096, 16384, 32768]
    modes_to_test = ["fp16", "q8", "q5", "q4"]
    results = []

    for ctx in context_sizes:
        prompt_tokens = make_prompt_tokens(tokenizer, ctx)
        actual = len(prompt_tokens)
        print(f"\n--- Context: {actual} tokens ---")
        sys.stdout.flush()

        for mode in modes_to_test:
            bits = KV_MODES[mode]
            try:
                r = bench_decode(model, tokenizer, prompt_tokens, 50, bits)
                r["kv_mode"] = mode
                r["context"] = actual
                results.append(r)
                print(f"  {mode:5s} | prefill: {r.get('prompt_tps',0):>7.1f} tok/s | "
                      f"decode: {r.get('gen_tps',0):>6.1f} tok/s | "
                      f"total: {r.get('elapsed_s',0):.1f}s")
                sys.stdout.flush()
            except Exception as e:
                r = {"kv_mode": mode, "context": actual, "error": str(e)}
                results.append(r)
                print(f"  {mode:5s} | FAILED: {e}")
                sys.stdout.flush()
            gc.collect()
            mx.metal.clear_cache()

    # Summary
    print()
    print("=" * 65)
    print("SUMMARY")
    print("=" * 65)
    print(f"{'ctx':>8} {'kv':>5} {'prefill':>10} {'decode':>10}")
    print(f"{'':>8} {'':>5} {'tok/s':>10} {'tok/s':>10}")
    print("-" * 65)
    for r in results:
        if "error" in r:
            print(f"{r['context']:>8} {r['kv_mode']:>5} {'FAILED':>10} {'':>10}")
        else:
            print(f"{r['context']:>8} {r['kv_mode']:>5} "
                  f"{r.get('prompt_tps',0):>10.1f} {r.get('gen_tps',0):>10.1f}")
    print("=" * 65)

    out_path = "/tmp/kv_cache_benchmark_v2.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
