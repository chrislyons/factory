#!/usr/bin/env python3
"""Stress test: long context + memory profiling for 26B-A4B."""

import subprocess
import time
import json
import requests
import os

MODEL = "/Users/nesbitt/models/Ornstein-26B-A4B-it-MLX-6bit"
PORT = 41967

def get_vm():
    import subprocess as sp
    out = sp.run(["vm_stat"], capture_output=True, text=True).stdout
    lines = out.strip().split("\n")
    page_size = 16384
    stats = {}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":.").replace(" ", "_")
            try:
                val = int(parts[-1].rstrip("."))
                stats[key] = val * page_size / (1024**3)
            except:
                pass
    return stats

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
    print("=" * 60)
    print("26B-A4B Stress Test: Long Context + Memory Profile")
    print("=" * 60)
    
    # Baseline memory
    vm = get_vm()
    print(f"\nBaseline: Free={vm.get('Pages_free',0):.1f}GB Active={vm.get('Pages_active',0):.1f}GB Wired={vm.get('Pages_wired_down',0):.1f}GB")
    
    # Start server
    proc = subprocess.Popen([
        "/opt/homebrew/Cellar/mlx-lm/0.31.3/libexec/bin/python", "-m", "mlx_lm", "server",
        "--model", MODEL, "--port", str(PORT),
        "--max-tokens", "16384", "--prefill-step-size", "256",
        "--prompt-concurrency", "1", "--prompt-cache-bytes", "4294967296",
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())
    
    for _ in range(180):
        try:
            if requests.get(f"http://localhost:{PORT}/health", timeout=2).status_code == 200:
                break
        except: pass
        time.sleep(1)
    
    # After model load
    vm = get_vm()
    print(f"After load: Free={vm.get('Pages_free',0):.1f}GB Active={vm.get('Pages_active',0):.1f}GB Wired={vm.get('Pages_wired_down',0):.1f}GB")
    model_footprint = vm.get('Pages_active', 0) - 3.5  # subtract baseline ~3.5GB
    print(f"Model footprint estimate: ~{model_footprint:.1f} GB resident")
    
    # Warmup
    print("\nWarmup...")
    query(PORT, "Hello", 32)
    
    # Test 1: ~1K tokens
    print("\n--- Test: ~1K tokens ---")
    prompt_1k = "Explain the theory of relativity in detail. " * 30
    r = query(PORT, prompt_1k, 512)
    vm = get_vm()
    print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
    print(f"Memory: Free={vm.get('Pages_free',0):.1f}GB")
    if "error" in r: print(f"ERROR: {r['error']}")
    
    # Test 2: ~4K tokens
    print("\n--- Test: ~4K tokens ---")
    prompt_4k = "Explain the theory of relativity in detail, covering special and general relativity, their mathematical foundations, and experimental confirmations. " * 100
    r = query(PORT, prompt_4k, 512)
    vm = get_vm()
    print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
    print(f"Memory: Free={vm.get('Pages_free',0):.1f}GB")
    if "error" in r: print(f"ERROR: {r['error']}")
    
    # Test 3: ~16K tokens
    print("\n--- Test: ~16K tokens ---")
    prompt_16k = "Write a comprehensive guide to machine learning, covering supervised learning, unsupervised learning, reinforcement learning, neural networks, decision trees, support vector machines, and ensemble methods. Include examples and mathematical notation. " * 200
    r = query(PORT, prompt_16k, 1024)
    vm = get_vm()
    print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
    print(f"Memory: Free={vm.get('Pages_free',0):.1f}GB")
    if "error" in r: print(f"ERROR: {r['error']}")
    
    # Test 4: Try 32K tokens if previous passed
    if "error" not in r:
        print("\n--- Test: ~32K tokens ---")
        prompt_32k = "Write a comprehensive guide to machine learning. " * 600
        r = query(PORT, prompt_32k, 1024)
        vm = get_vm()
        print(f"Tokens: {r.get('prompt_tokens','?')} -> {r.get('completion_tokens','?')} | {r.get('tok_per_sec','?')} tok/s | {r.get('total_time','?')}s")
        print(f"Memory: Free={vm.get('Pages_free',0):.1f}GB")
        if "error" in r: print(f"ERROR: {r['error']}")
    
    proc.terminate()
    proc.wait(timeout=10)
    
    # Post
    vm = get_vm()
    print(f"\nAfter stop: Free={vm.get('Pages_free',0):.1f}GB")
    print("\nDone.")

if __name__ == "__main__":
    main()
