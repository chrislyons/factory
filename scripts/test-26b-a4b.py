#!/usr/bin/env python3
"""Benchmark test for Ornstein-26B-A4B-it-MLX-6bit on Whitebox.

Tests speed, memory, and quality at various context lengths.
Uses mlx_lm.server on port 41967 for isolated testing.
"""

import json
import os
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from benchmark_utils import find_mlx_python, wait_server

MODEL_PATH = "/Users/nesbitt/models/Ornstein-26B-A4B-it-MLX-6bit"
PORT = 41967
METAL_LIMIT_GB = 28

# Benchmark prompts
BENCHMARKS = [
    {
        "name": "Short factual",
        "prompt": "What is the capital of France? Answer in one word.",
        "max_tokens": 64,
    },
    {
        "name": "Medium reasoning",
        "prompt": "A farmer has 17 sheep. All but 9 die. How many are left? Explain step by step.",
        "max_tokens": 256,
    },
    {
        "name": "Code generation",
        "prompt": "Write a Python function that checks if a string is a palindrome. Include docstring and type hints.",
        "max_tokens": 512,
    },
    {
        "name": "Multi-step reasoning",
        "prompt": "If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets? Think step by step.",
        "max_tokens": 512,
    },
    {
        "name": "Instruction following",
        "prompt": "List exactly 5 benefits of exercise. Format as a numbered list. Each item must be one sentence. Do not include an introduction or conclusion.",
        "max_tokens": 256,
    },
    {
        "name": "Tool call simulation",
        "prompt": "You are a helpful assistant. The user asks: 'Read the file config.yaml and tell me the database port.' You have access to a tool called read_file(path). Respond with the tool call in JSON format.",
        "max_tokens": 256,
    },
]

LONG_PROMPT = "Explain the history of computing in detail, covering the major milestones from Charles Babbage's Analytical Engine through modern AI. " * 200  # ~3500 tokens


def chat_completion(port, prompt, max_tokens=256, temperature=0.0):
    """Send a chat completion request and measure timing."""
    payload = {
        "model": MODEL_PATH,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    
    start = time.time()
    try:
        r = requests.post(
            f"http://localhost:{port}/v1/chat/completions",
            json=payload,
            timeout=300,
        )
        elapsed = time.time() - start
        
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        # Calculate decode speed (exclude prefill time)
        if completion_tokens > 0 and elapsed > 0:
            # Rough: total time includes prefill, so tok/s is approximate
            tok_per_sec = completion_tokens / elapsed
        else:
            tok_per_sec = 0
        
        return {
            "content": content[:300],
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_time": round(elapsed, 1),
            "tok_per_sec": round(tok_per_sec, 1),
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    mlx_python = find_mlx_python()

    print("=" * 70)
    print("Ornstein-26B-A4B-it-MLX-6bit Benchmark")
    print(f"Model: {MODEL_PATH}")
    print(f"Port: {PORT}")
    print(f"Python: {mlx_python}")
    print("=" * 70)

    # Start the server
    print("\n[1] Starting mlx_lm.server...")
    proc = subprocess.Popen(
        [mlx_python, "-m", "mlx_lm", "server",
         "--model", MODEL_PATH,
         "--port", str(PORT),
         "--max-tokens", "16384",
         "--prefill-step-size", "256",
         "--prompt-concurrency", "1",
         "--prompt-cache-bytes", "2147483648"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ.copy(),
    )

    print(f"   Server PID: {proc.pid}")
    print("   Waiting for server to be ready...")

    if not wait_server(PORT, timeout=180, proc=proc):
        print("   FAILED: Server did not start within 180s")
        proc.terminate()
        sys.exit(1)

    print("   Server ready!")
    
    # Check memory
    print("\n[2] Memory state (pre-benchmark):")
    try:
        mem = subprocess.run(["memory_pressure"], capture_output=True, text=True)
        for line in mem.stdout.strip().split("\n")[:3]:
            print(f"   {line}")
    except:
        pass
    
    # Run benchmarks
    print("\n[3] Running benchmarks...")
    results = []
    
    for i, bench in enumerate(BENCHMARKS):
        print(f"\n   [{i+1}/{len(BENCHMARKS)}] {bench['name']}...")
        result = chat_completion(PORT, bench["prompt"], bench["max_tokens"])
        results.append({"name": bench["name"], **result})
        
        if "error" in result:
            print(f"   ERROR: {result['error']}")
        else:
            print(f"   Tokens: {result['prompt_tokens']} -> {result['completion_tokens']}")
            print(f"   Speed: {result['tok_per_sec']} tok/s | Time: {result['total_time']}s")
            print(f"   Content: {result['content'][:120]}...")
    
    # Long context test
    print(f"\n   [6/6] Long context test (~3500 tokens)...")
    result = chat_completion(PORT, LONG_PROMPT, 512)
    results.append({"name": "Long context (~3500 tok)", **result})
    
    if "error" in result:
        print(f"   ERROR: {result['error']}")
    else:
        print(f"   Tokens: {result['prompt_tokens']} -> {result['completion_tokens']}")
        print(f"   Speed: {result['tok_per_sec']} tok/s | Time: {result['total_time']}s")
        print(f"   Content: {result['content'][:120]}...")
    
    # Summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Test':<30} {'P_tok':>6} {'C_tok':>6} {'tok/s':>7} {'Time':>6}")
    print("-" * 60)
    for r in results:
        if "error" in r:
            print(f"{r['name']:<30} {'ERROR':>6}")
        else:
            print(f"{r['name']:<30} {r['prompt_tokens']:>6} {r['completion_tokens']:>6} {r['tok_per_sec']:>7} {r['total_time']:>5}s")
    
    # Memory after
    print("\n[4] Memory state (post-benchmark):")
    try:
        mem = subprocess.run(["memory_pressure"], capture_output=True, text=True)
        for line in mem.stdout.strip().split("\n")[:3]:
            print(f"   {line}")
    except:
        pass
    
    # Save results
    output_path = "/Users/nesbitt/dev/factory/docs/fct/FCT088-26b-a4b-benchmark.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n   Results saved: {output_path}")
    
    # Cleanup
    print("\n[5] Stopping server...")
    proc.terminate()
    proc.wait(timeout=10)
    print("   Done.")
    
    return results


if __name__ == "__main__":
    main()
