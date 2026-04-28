#!/usr/bin/env python3
"""
KV Cache Quantization Benchmark for Ornstein-Hermes-3.6-27b-MLX-6bit
Tests: fp16 (baseline), q8, q5_1, q4 at various context lengths.
Measures: prefill tok/s, decode tok/s, peak memory.
"""
import sys
import time
import json
import gc
import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import stream_generate

MODEL_PATH = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"

# Map friendly names to bits
KV_MODES = {
    "fp16": None,
    "q8": 8,
    "q6": 6,
    "q5": 5,
    "q4": 4,
}

def make_prompt_tokens(tokenizer, n_tokens_approx):
    """Generate token list of approximately n tokens."""
    n_words = max(9, int(n_tokens_approx / 1.3))
    base = "The quick brown fox jumps over the lazy dog. "
    text = (base * (n_words // 9 + 1))[:n_words * 6]
    tokens = tokenizer.encode(text, add_special_tokens=False)
    return tokens[:n_tokens_approx]


def bench(model, tokenizer, prompt_tokens, max_new_tokens, kv_bits, kv_group_size=64):
    """Run generation and collect timing from GenerationResponse."""
    mx.metal.clear_cache()
    gc.collect()

    n_prompt = len(prompt_tokens)
    last_resp = None
    n_gen = 0

    t_start = time.perf_counter()
    for resp in stream_generate(
        model, tokenizer, prompt_tokens,
        max_tokens=max_new_tokens,
        kv_bits=kv_bits,
        kv_group_size=kv_group_size,
        quantized_kv_start=0,
    ):
        last_resp = resp
        n_gen = resp.generation_tokens
    t_total = time.perf_counter() - t_start

    if last_resp is None:
        return {"error": "no output"}

    return {
        "prompt_tokens": n_prompt,
        "gen_tokens": n_gen,
        "prompt_tps": round(last_resp.prompt_tps, 2),
        "gen_tps": round(last_resp.generation_tps, 2),
        "peak_mem_gb": round(last_resp.peak_memory, 2),
        "total_s": round(t_total, 2),
    }


def main():
    print(f"Loading model from {MODEL_PATH} ...")
    sys.stdout.flush()
    t0 = time.perf_counter()
    model, tokenizer = load(MODEL_PATH)
    print(f"Loaded in {time.perf_counter() - t0:.1f}s")
    sys.stdout.flush()

    # Test matrix
    context_sizes = [512, 2048, 8192, 32768, 65536]
    kv_modes_to_test = ["fp16", "q8", "q5", "q4"]
    max_new = 50

    results = []

    for ctx in context_sizes:
        prompt_tokens = make_prompt_tokens(tokenizer, ctx)
        actual_ctx = len(prompt_tokens)
        print(f"\n{'='*60}")
        print(f"Context: ~{actual_ctx} tokens")
        print(f"{'='*60}")
        sys.stdout.flush()

        for mode_name in kv_modes_to_test:
            bits = KV_MODES[mode_name]
            try:
                r = bench(model, tokenizer, prompt_tokens, max_new, bits)
                r["kv_mode"] = mode_name
                r["context"] = actual_ctx
                results.append(r)
                print(f"  {mode_name:5s} | pref_tps: {r['prompt_tps']:>8.1f} | "
                      f"gen_tps: {r['gen_tps']:>6.1f} | "
                      f"peak_mem: {r['peak_mem_gb']:>5.1f}GB | "
                      f"time: {r['total_s']:.1f}s")
                sys.stdout.flush()
            except Exception as e:
                err = {"kv_mode": mode_name, "context": actual_ctx, "error": str(e)}
                results.append(err)
                print(f"  {mode_name:5s} | FAILED: {e}")
                sys.stdout.flush()
                # If OOM at this context, skip bigger modes too? No — smaller quant may fit
                gc.collect()
                mx.metal.clear_cache()

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'ctx':>8} {'kv':>5} {'pref_tps':>10} {'gen_tps':>10} {'peak_gb':>10}")
    print(f"{'-'*8} {'-'*5} {'-'*10} {'-'*10} {'-'*10}")
    for r in results:
        if "error" in r:
            print(f"{r['context']:>8} {r['kv_mode']:>5} {'OOM/ERR':>10} {'':>10} {'':>10}")
        else:
            print(f"{r['context']:>8} {r['kv_mode']:>5} {r['prompt_tps']:>10.1f} "
                  f"{r['gen_tps']:>10.1f} {r['peak_mem_gb']:>10.1f}")
    print(f"{'='*60}")

    # Save
    out_path = "/tmp/kv_cache_benchmark.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
