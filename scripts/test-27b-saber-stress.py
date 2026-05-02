#!/usr/bin/env python3
"""Stress test: long context + memory profiling for 27B-SABER.

Tests context scaling at 1K, 4K, 8K, 16K tokens.
Uses the 27b wrapper (4-bit KV, Metal limit, no wired limit).

The 6-bit model OOMs at 18K tokens with prefill-step-size 2048 (crash in FCT087).
The 4-bit model is safe at 2048 step size up to 16K+.

Environment:
  VARIANT=6bit  (default) — 21 GB, prefill-step-size 256
  VARIANT=4bit           — 14 GB, prefill-step-size 2048
"""

import json
import os
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from benchmark_utils import find_mlx_python, get_mem, get_vm_stats, wait_server, write_wrapper

VARIANT = os.environ.get("VARIANT", "6bit")

if VARIANT == "4bit":
    MODEL = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-SABER-MLX-4bit"
    PORT = 41966
    PREFILL_STEP = 2048
    METAL_LIMIT = 20
else:
    MODEL = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"
    PORT = 41966
    PREFILL_STEP = 256
    METAL_LIMIT = 28


def query(port, prompt, max_tokens):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    start = time.time()
    try:
        r = requests.post(f"http://localhost:{port}/v1/chat/completions", json=payload, timeout=600)
        elapsed = time.time() - start
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        data = r.json()
        msg = data["choices"][0]["message"]
        usage = data.get("usage", {})
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        return {
            "content": (msg.get("content") or "")[:200],
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_time": round(elapsed, 1),
            "tok_per_sec": round(ct / elapsed, 1) if elapsed > 0 else 0,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def main():
    mlx_python = find_mlx_python()

    print("=" * 60)
    print(f"27B-SABER Stress Test: Long Context + Memory Profile ({VARIANT})")
    print(f"Model: {MODEL}")
    print(f"Metal limit: {METAL_LIMIT} GB | Prefill step: {PREFILL_STEP}")
    print(f"Python: {mlx_python}")
    print("=" * 60)

    # Baseline memory (captured before server starts, used for footprint estimate)
    m_baseline = get_mem()
    print(f"\nBaseline: Free={m_baseline['free_gb']}GB Active={m_baseline['active_gb']}GB Wired={m_baseline['wired_gb']}GB")

    # Start server via wrapper
    wrapper_path = "/tmp/test-27b-stress-wrapper.py"
    write_wrapper(wrapper_path, METAL_LIMIT)

    proc = subprocess.Popen(
        [mlx_python, wrapper_path,
         "--model", MODEL, "--port", str(PORT),
         "--max-tokens", "16384", "--prefill-step-size", str(PREFILL_STEP),
         "--prompt-concurrency", "1", "--prompt-cache-bytes", "2147483648"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())

    if not wait_server(PORT, timeout=180, proc=proc):
        print("FAILED: Server did not start within 180s")
        proc.terminate()
        sys.exit(1)

    # After model load
    m = get_mem()
    print(f"After load: Free={m['free_gb']}GB Active={m['active_gb']}GB Wired={m['wired_gb']}GB")
    footprint = m["active_gb"] - m_baseline["active_gb"]
    print(f"Model footprint estimate: ~{footprint:.1f} GB resident")

    # Warmup
    print("\nWarmup...")
    query(PORT, "Hello", 32)

    # Context scaling tests
    tests = [
        ("~1K tokens",  "Explain the theory of relativity in detail. " * 30, 512),
        ("~4K tokens",  "Explain the theory of relativity in detail, covering special and general relativity, their mathematical foundations, and experimental confirmations. " * 100, 512),
        ("~8K tokens",  "Write a comprehensive guide to machine learning, covering supervised learning, unsupervised learning, reinforcement learning, neural networks, decision trees, support vector machines, and ensemble methods. " * 100, 1024),
        ("~16K tokens", "Write a comprehensive guide to machine learning, covering supervised learning, unsupervised learning, reinforcement learning, neural networks, decision trees, support vector machines, and ensemble methods. Include examples and mathematical notation. " * 200, 1024),
    ]

    results = []
    for name, prompt, max_tok in tests:
        print(f"\n--- Test: {name} ---")
        r = query(PORT, prompt, max_tok)
        m = get_mem()
        print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
        print(f"Memory: Free={m['free_gb']}GB Wired={m['wired_gb']}GB")
        if "error" in r:
            print(f"ERROR: {r['error']}")
            results.append({"test": name, "error": r["error"]})
            if "Insufficient Memory" in r.get("error", "") or "OOM" in r.get("error", ""):
                print("  OOM detected — stopping context scaling tests.")
                break
        else:
            results.append({"test": name, **{k: v for k, v in r.items() if k != "content"}})

    # Try 32K if 16K passed
    if results and "error" not in results[-1]:
        print("\n--- Test: ~32K tokens ---")
        r = query(PORT, "Write a comprehensive guide to machine learning. " * 600, 1024)
        m = get_mem()
        print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
        print(f"Memory: Free={m['free_gb']}GB Wired={m['wired_gb']}GB")
        if "error" in r:
            print(f"ERROR: {r['error']}")
        results.append({"test": "~32K tokens", **{k: v for k, v in r.items() if k != "content"}})

    proc.terminate()
    proc.wait(timeout=10)

    m = get_mem()
    print(f"\nAfter stop: Free={m['free_gb']}GB")

    # Save
    out = f"/Users/nesbitt/dev/factory/docs/fct/FCT087-27b-saber-{VARIANT}-stress.json"
    with open(out, "w") as f:
        json.dump({"variant": VARIANT, "model": MODEL, "results": results}, f, indent=2)
    print(f"Saved: {out}")
    print("\nDone.")


if __name__ == "__main__":
    main()
