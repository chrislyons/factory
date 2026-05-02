#!/usr/bin/env python3
"""Stress test: long context + memory profiling for 26B-A4B."""

import json
import os
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from benchmark_utils import find_mlx_python, get_mem, wait_server

MODEL = "/Users/nesbitt/models/Ornstein-26B-A4B-it-MLX-6bit"
PORT = 41967


def query(port, prompt, max_tokens):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    start = time.time()
    r = requests.post(f"http://localhost:{port}/v1/chat/completions", json=payload, timeout=600)
    elapsed = time.time() - start
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    data = r.json()
    msg = data["choices"][0]["message"]
    usage = data.get("usage", {})
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    tok_s = ct / elapsed if elapsed > 0 else 0
    return {
        "content": (msg.get("content") or "")[:200],
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_time": round(elapsed, 1),
        "tok_per_sec": round(tok_s, 1),
    }


def main():
    mlx_python = find_mlx_python()

    print("=" * 60)
    print("26B-A4B Stress Test: Long Context + Memory Profile")
    print(f"Python: {mlx_python}")
    print("=" * 60)

    # Baseline memory (captured before server starts, used for footprint estimate)
    m_baseline = get_mem()
    print(f"\nBaseline: Free={m_baseline['free_gb']}GB Active={m_baseline['active_gb']}GB Wired={m_baseline['wired_gb']}GB")

    # Start server
    proc = subprocess.Popen([
        mlx_python, "-m", "mlx_lm", "server",
        "--model", MODEL, "--port", str(PORT),
        "--max-tokens", "16384", "--prefill-step-size", "256",
        "--prompt-concurrency", "1", "--prompt-cache-bytes", "4294967296",
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())

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

    # Test 1: ~1K tokens
    print("\n--- Test: ~1K tokens ---")
    r = query(PORT, "Explain the theory of relativity in detail. " * 30, 512)
    m = get_mem()
    print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
    print(f"Memory: Free={m['free_gb']}GB")
    if "error" in r:
        print(f"ERROR: {r['error']}")

    # Test 2: ~4K tokens
    print("\n--- Test: ~4K tokens ---")
    r = query(PORT, "Explain the theory of relativity in detail, covering special and general relativity, their mathematical foundations, and experimental confirmations. " * 100, 512)
    m = get_mem()
    print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
    print(f"Memory: Free={m['free_gb']}GB")
    if "error" in r:
        print(f"ERROR: {r['error']}")

    # Test 3: ~16K tokens
    print("\n--- Test: ~16K tokens ---")
    r = query(PORT, "Write a comprehensive guide to machine learning, covering supervised learning, unsupervised learning, reinforcement learning, neural networks, decision trees, support vector machines, and ensemble methods. Include examples and mathematical notation. " * 200, 1024)
    m = get_mem()
    print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
    print(f"Memory: Free={m['free_gb']}GB")
    if "error" in r:
        print(f"ERROR: {r['error']}")

    # Test 4: Try 32K if 16K passed
    if "error" not in r:
        print("\n--- Test: ~32K tokens ---")
        r = query(PORT, "Write a comprehensive guide to machine learning. " * 600, 1024)
        m = get_mem()
        print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
        print(f"Memory: Free={m['free_gb']}GB")
        if "error" in r:
            print(f"ERROR: {r['error']}")

    proc.terminate()
    proc.wait(timeout=10)

    m = get_mem()
    print(f"\nAfter stop: Free={m['free_gb']}GB")
    print("\nDone.")


if __name__ == "__main__":
    main()
