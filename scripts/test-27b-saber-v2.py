#!/usr/bin/env python3
"""Benchmark v2 for Ornstein-Hermes-3.6-27b-SABER.

Thinking model (Qwen3.5 hybrid): reasoning_content must be combined with content.
Uses the 27b wrapper (4-bit KV, Metal limit, no wired limit).

Variants:
  6-bit: ~21 GB disk, ~7-10 tok/s, prefill-step-size 256 required
  4-bit: ~14 GB disk, ~13-15 tok/s, prefill-step-size 2048 safe
"""

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from benchmark_utils import find_mlx_python, get_mem, wait_server, write_wrapper

VARIANT = os.environ.get("VARIANT", "6bit")  # "6bit" or "4bit"
WRAPPER = os.environ.get("WRAPPER", "1")      # "1" to use wrapper, "0" for raw mlx_lm

if VARIANT == "4bit":
    MODEL = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-SABER-MLX-4bit"
    PORT = 41966
    PREFILL_STEP = 2048
    METAL_LIMIT = 20  # GB
    DISK_GB = 14
    EXPECTED_TOK_S = "13-15"
else:
    MODEL = "/Users/nesbitt/models/Ornstein-Hermes-3.6-27b-MLX-6bit"
    PORT = 41966
    PREFILL_STEP = 256
    METAL_LIMIT = 28  # GB
    DISK_GB = 21
    EXPECTED_TOK_S = "7-10"

BENCHMARKS = [
    {"name": "Short factual",    "prompt": "What is the capital of France? Answer in one word.", "max_tokens": 512},
    {"name": "Sheep riddle",     "prompt": "A farmer has 17 sheep. All but 9 die. How many are left?", "max_tokens": 1024},
    {"name": "Code: palindrome", "prompt": "Write a Python function that checks if a string is a palindrome. Include docstring and type hints.", "max_tokens": 2048},
    {"name": "Multi-step math",  "prompt": "If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets?", "max_tokens": 1024},
    {"name": "Instruction follow","prompt": "List exactly 5 benefits of exercise. Numbered list. One sentence each. No intro or conclusion.", "max_tokens": 1024},
    {"name": "Tool call",        "prompt": "You have a tool called read_file(path). User asks: 'Read config.yaml and tell me the database port.' Respond with the tool call JSON only.", "max_tokens": 1024},
]


def query_local(port, prompt, max_tokens):
    import requests
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
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    usage = data.get("usage", {})
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)

    return {
        "content_preview": content[:200] if content else "(thinking only)",
        "reasoning_len": len(reasoning),
        "content_len": len(content),
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_time": round(elapsed, 1),
        "tok_per_sec": round(ct / elapsed, 1) if elapsed > 0 else 0,
    }


def main():
    mlx_python = find_mlx_python()

    print("=" * 70)
    print(f"Ornstein-Hermes-3.6-27b-SABER Benchmark v2 ({VARIANT})")
    print(f"Model: {MODEL}")
    print(f"Disk: {DISK_GB} GB | Architecture: Qwen3.5 hybrid (64 layers: 48 GatedDeltaNet + 16 full attention)")
    print(f"Dense 27B — all parameters active per token")
    print(f"Expected speed: {EXPECTED_TOK_S} tok/s")
    print(f"Wrapper: {'YES' if WRAPPER == '1' else 'NO'} (Metal limit {METAL_LIMIT} GB, prefill-step-size {PREFILL_STEP})")
    print(f"Python: {mlx_python}")
    print("=" * 70)

    # Start server
    print("\n[1/5] Starting server...")
    if WRAPPER == "1":
        wrapper_path = "/tmp/test-27b-wrapper.py"
        write_wrapper(wrapper_path, METAL_LIMIT)
        proc = subprocess.Popen(
            [mlx_python, wrapper_path,
             "--model", MODEL, "--port", str(PORT),
             "--max-tokens", "16384",
             "--prefill-step-size", str(PREFILL_STEP),
             "--prompt-concurrency", "1",
             "--prompt-cache-bytes", "2147483648"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())
    else:
        proc = subprocess.Popen(
            [mlx_python, "-m", "mlx_lm", "server",
             "--model", MODEL, "--port", str(PORT),
             "--max-tokens", "16384",
             "--prefill-step-size", str(PREFILL_STEP),
             "--prompt-concurrency", "1",
             "--prompt-cache-bytes", "2147483648"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())

    if not wait_server(PORT, timeout=180, proc=proc):
        print("FAILED: Server did not start within 180s")
        proc.terminate()
        sys.exit(1)
    print("   Server ready!")

    # Pre-benchmark memory
    print("\n[2/5] Pre-benchmark memory:")
    m = get_mem()
    print(f"   Free: {m['free_gb']} GB | Active: {m['active_gb']} GB | Wired: {m['wired_gb']} GB")

    # Run benchmarks
    print("\n[3/5] Running benchmarks...")
    results = []

    for i, b in enumerate(BENCHMARKS):
        print(f"\n   [{i+1}/{len(BENCHMARKS)}] {b['name']}...")
        r = query_local(PORT, b["prompt"], b["max_tokens"])
        results.append({"name": b["name"], **r})

        if "error" in r:
            print(f"   ERROR: {r['error']}")
        else:
            print(f"   Tokens: {r['prompt_tokens']} -> {r['completion_tokens']} ({r['tok_per_sec']} tok/s, {r['total_time']}s)")
            print(f"   Thinking: {r['reasoning_len']} chars | Content: {r['content_len']} chars")
            print(f"   Answer: {r['content_preview'][:100]}")

    # Post-benchmark memory
    print("\n[4/5] Post-benchmark memory:")
    m = get_mem()
    print(f"   Free: {m['free_gb']} GB | Active: {m['active_gb']} GB | Wired: {m['wired_gb']} GB")

    # Summary table
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"{'Test':<22} {'P_tok':>6} {'C_tok':>6} {'tok/s':>7} {'Time':>6} {'Think':>6} {'Content':>8}")
    print("-" * 65)
    for r in results:
        if "error" in r:
            print(f"{r['name']:<22} ERROR: {r['error'][:40]}")
        else:
            print(f"{r['name']:<22} {r['prompt_tokens']:>6} {r['completion_tokens']:>6} {r['tok_per_sec']:>7} {r['total_time']:>5}s {r['reasoning_len']:>5}c {r['content_len']:>7}c")

    # Save
    out = f"/Users/nesbitt/dev/factory/docs/fct/FCT087-27b-saber-{VARIANT}-benchmark.json"
    with open(out, "w") as f:
        json.dump({"variant": VARIANT, "model": MODEL, "disk_gb": DISK_GB, "results": results}, f, indent=2)
    print(f"\n   Saved: {out}")

    # Cleanup
    print("\n[5/5] Stopping server...")
    proc.terminate()
    proc.wait(timeout=10)
    print("   Done.\n")


if __name__ == "__main__":
    main()
