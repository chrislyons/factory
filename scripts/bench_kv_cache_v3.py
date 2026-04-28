#!/usr/bin/env python3
"""
KV Cache Analysis + Benchmark v3 for Ornstein-Hermes-3.6-27b-MLX-6bit
Analytical memory calculation + actual tok/s benchmarks at achievable contexts.
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


def make_prompt_tokens(tokenizer, n_tokens):
    text = ("The quick brown fox jumps over the lazy dog. " * ((n_tokens // 9) + 1))
    tokens = tokenizer.encode(text, add_special_tokens=False)
    return tokens[:n_tokens]


def bench_decode(model, tokenizer, prompt_tokens, max_new, kv_bits, label):
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
        "label": label,
        "prompt_tps": round(last.prompt_tps, 1),
        "gen_tps": round(last.generation_tps, 1),
        "elapsed_s": round(elapsed, 1),
        "gen_tokens": last.generation_tokens,
        "peak_mem_gb": round(last.peak_memory, 2),
    }


def main():
    print(f"Loading model from {MODEL_PATH} ...")
    sys.stdout.flush()
    t0 = time.perf_counter()
    model, tokenizer = load(MODEL_PATH)
    print(f"Loaded in {time.perf_counter() - t0:.1f}s")

    # Count layers
    prompt_cache = cache.make_prompt_cache(model)
    n_kv = sum(1 for c in prompt_cache if hasattr(c, 'to_quantized'))
    n_total = len(prompt_cache)
    print(f"Layers: {n_total} total, {n_kv} KV cache, {n_total - n_kv} linear attention")

    # Analytical KV cache calculation
    # Qwen3.5 architecture: kv_heads=4, head_dim=256
    kv_heads = 4
    head_dim = 256

    print(f"\n{'='*70}")
    print("ANALYTICAL KV CACHE MEMORY (only the 16 full-attn layers)")
    print(f"{'='*70}")
    print(f"Per token per layer: 2(K+V) × {kv_heads} heads × {head_dim} dim = "
          f"{2 * kv_heads * head_dim:,} bytes (fp16)")
    print(f"Per token all {n_kv} KV layers: {2 * kv_heads * head_dim * n_kv:,} bytes = "
          f"{2 * kv_heads * head_dim * n_kv / 1024:.0f} KB (fp16)")
    print()
    print(f"{'Context':>10} {'fp16':>10} {'q8':>10} {'q6':>10} {'q5':>10} {'q4':>10}")
    print(f"{'':>10} {'(2 B)':>10} {'(1 B)':>10} {'(0.75 B)':>10} {'(0.625 B)':>10} {'(0.5 B)':>10}")
    print("-" * 70)

    bytes_per_token_layer_fp16 = 2 * kv_heads * head_dim  # 2048 bytes
    for ctx in [1024, 4096, 8192, 16384, 32768, 65536, 131072, 262144]:
        total_fp16 = bytes_per_token_layer_fp16 * n_kv * ctx
        total_q8 = total_fp16 / 2
        total_q6 = total_fp16 * 0.75 / 2  # 6-bit = 0.75 bytes
        total_q5 = total_fp16 * 5 / 8 / 2  # 5 bits per weight
        total_q4 = total_fp16 / 4
        fmt = lambda b: f"{b/1e9:.2f} GB" if b > 1e9 else f"{b/1e6:.0f} MB"
        print(f"{ctx:>10,} {fmt(total_fp16):>10} {fmt(total_q8):>10} {fmt(total_q6):>10} "
              f"{fmt(total_q5):>10} {fmt(total_q4):>10}")

    print()
    print("Note: mlx quantizes KV to the nearest supported quant (not arbitrary bits).")
    print("      Supported: q4 (4-bit), q8 (8-bit). q5/q6 are interpolated estimates.")
    print()

    # System memory budget
    model_mem_gb = mx.metal.get_active_memory() / 1e9
    available = 32 - model_mem_gb  # ~32GB system
    print(f"Model memory: {model_mem_gb:.1f} GB")
    print(f"Available for KV: ~{available:.1f} GB")
    print()

    # Max context per KV mode
    bytes_per_token_all_layers = bytes_per_token_layer_fp16 * n_kv  # fp16
    print("Maximum context (fitting in available memory):")
    for mode, bpp_mult in [("fp16", 1.0), ("q8", 0.5), ("q4", 0.25)]:
        bpp = bytes_per_token_all_layers * bpp_mult
        max_ctx = int(available * 1e9 / bpp)
        # Round down to nearest power of 2
        max_ctx_pow2 = 1
        while max_ctx_pow2 * 2 <= max_ctx:
            max_ctx_pow2 *= 2
        print(f"  {mode:5s}: {max_ctx:>10,} tokens (≈{max_ctx_pow2:,} pow2, ≈{max_ctx/1024:.0f}K)")

    # Actual decode benchmarks
    print(f"\n{'='*70}")
    print("DECODE SPEED BENCHMARKS (50 new tokens)")
    print(f"{'='*70}")

    context_sizes = [512, 2048, 8192]
    modes = [("fp16", None), ("q8", 8), ("q4", 4)]
    max_new = 50
    results = []

    for ctx in context_sizes:
        prompt_tokens = make_prompt_tokens(tokenizer, ctx)
        actual = len(prompt_tokens)
        print(f"\n--- Context: {actual} tokens ---")
        sys.stdout.flush()

        for mode_name, bits in modes:
            try:
                r = bench_decode(model, tokenizer, prompt_tokens, max_new, bits, mode_name)
                r["context"] = actual
                results.append(r)
                print(f"  {mode_name:5s} | prefill: {r['prompt_tps']:>7.1f} tok/s | "
                      f"decode: {r['gen_tps']:>6.1f} tok/s | "
                      f"peak: {r['peak_mem_gb']:.1f}GB | "
                      f"time: {r['elapsed_s']:.1f}s")
                sys.stdout.flush()
            except Exception as e:
                r = {"label": mode_name, "context": actual, "error": str(e)}
                results.append(r)
                print(f"  {mode_name:5s} | FAILED: {e}")
                sys.stdout.flush()
            gc.collect()
            mx.metal.clear_cache()

    # Now try a bigger context — 32K with q4
    print(f"\n--- Context: 32K tokens (q4 KV cache) ---")
    sys.stdout.flush()
    try:
        prompt_32k = make_prompt_tokens(tokenizer, 32000)
        r = bench_decode(model, tokenizer, prompt_32k, max_new, 4, "q4-32k")
        r["context"] = len(prompt_32k)
        results.append(r)
        print(f"  q4    | prefill: {r['prompt_tps']:>7.1f} tok/s | "
              f"decode: {r['gen_tps']:>6.1f} tok/s | "
              f"peak: {r['peak_mem_gb']:.1f}GB | "
              f"time: {r['elapsed_s']:.1f}s")
        sys.stdout.flush()
    except Exception as e:
        print(f"  q4    | FAILED at 32K: {e}")
        sys.stdout.flush()

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"{'ctx':>8} {'kv':>5} {'prefill':>10} {'decode':>10} {'peak_gb':>10}")
    print(f"{'':>8} {'':>5} {'tok/s':>10} {'tok/s':>10} {'':>10}")
    print("-" * 70)
    for r in results:
        if "error" in r:
            print(f"{r.get('context',0):>8} {r.get('label','?'):>5} {'FAILED':>10} {'':>10} {'':>10}")
        else:
            print(f"{r['context']:>8} {r['label']:>5} "
                  f"{r['prompt_tps']:>10.1f} {r['gen_tps']:>10.1f} {r['peak_mem_gb']:>10.1f}")
    print(f"{'='*70}")

    out_path = "/tmp/kv_cache_benchmark_v3.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
