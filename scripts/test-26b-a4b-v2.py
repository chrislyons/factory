#!/usr/bin/env python3
"""Benchmark v2 for Ornstein-26B-A4B-it-MLX-6bit.

This is a thinking model — reasoning_content must be combined with content.
Adequate max_tokens to allow thinking + answer.
"""

import subprocess
import time
import json
import requests
import os
import sys

MODEL = "/Users/nesbitt/models/Ornstein-26B-A4B-it-MLX-6bit"
PORT = 41967

BENCHMARKS = [
    {"name": "Short factual", "prompt": "What is the capital of France? Answer in one word.", "max_tokens": 512},
    {"name": "Sheep riddle", "prompt": "A farmer has 17 sheep. All but 9 die. How many are left?", "max_tokens": 1024},
    {"name": "Code: palindrome", "prompt": "Write a Python function that checks if a string is a palindrome. Include docstring and type hints.", "max_tokens": 2048},
    {"name": "Multi-step math", "prompt": "If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets?", "max_tokens": 1024},
    {"name": "Instruction follow", "prompt": "List exactly 5 benefits of exercise. Numbered list. One sentence each. No intro or conclusion.", "max_tokens": 1024},
    {"name": "Tool call", "prompt": "You have a tool called read_file(path). User asks: 'Read config.yaml and tell me the database port.' Respond with the tool call JSON only.", "max_tokens": 1024},
]


def wait_server(port, timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"http://localhost:{port}/health", timeout=2)
            if r.status_code == 200:
                return True
        except:
            pass
        time.sleep(1)
    return False


def get_mem():
    """Get memory pressure info."""
    try:
        r = requests.get("http://localhost:41967/v1/models", timeout=2)
    except:
        pass
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
        lines = out.strip().split("\n")
        free_pages = int(lines[1].split()[-1].rstrip("."))
        active_pages = int(lines[2].split()[-1].rstrip("."))
        wired_pages = int(lines[7].split()[-1].rstrip("."))
        page_size = 16384
        free_gb = free_pages * page_size / (1024**3)
        active_gb = active_pages * page_size / (1024**3)
        wired_gb = wired_pages * page_size / (1024**3)
        return {"free_gb": round(free_gb, 1), "active_gb": round(active_gb, 1), "wired_gb": round(wired_gb, 1)}
    except:
        return {}


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
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    usage = data.get("usage", {})
    
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    tok_s = ct / elapsed if elapsed > 0 else 0
    
    # Combined output for quality check
    combined = (reasoning + "\n---\n" + content).strip() if reasoning else content
    
    return {
        "content_preview": content[:200] if content else "(thinking only)",
        "reasoning_len": len(reasoning),
        "content_len": len(content),
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_time": round(elapsed, 1),
        "tok_per_sec": round(tok_s, 1),
    }


def main():
    print("=" * 70)
    print("Ornstein-26B-A4B-it-MLX-6bit Benchmark v2")
    print(f"Model: {MODEL}")
    print(f"Disk: 19 GB | Architecture: Gemma4 MoE (26B total, 4B active)")
    print(f"128 experts, top_k=8, 30 layers (5 full_attn + 25 sliding)")
    print("=" * 70)
    
    # Start server
    print("\n[1/5] Starting server...")
    proc = subprocess.Popen([
        "/opt/homebrew/Cellar/mlx-lm/0.31.3/libexec/bin/python", "-m", "mlx_lm", "server",
        "--model", MODEL,
        "--port", str(PORT),
        "--max-tokens", "16384",
        "--prefill-step-size", "256",
        "--prompt-concurrency", "1",
        "--prompt-cache-bytes", "4294967296",  # 4GB
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())
    
    if not wait_server(PORT, timeout=180):
        print("FAILED: Server timeout")
        proc.terminate()
        sys.exit(1)
    print("   Server ready!")
    
    # Pre-benchmark memory
    print("\n[2/5] Pre-benchmark memory:")
    m = get_mem()
    print(f"   Free: {m.get('free_gb', '?')} GB | Active: {m.get('active_gb', '?')} GB | Wired: {m.get('wired_gb', '?')} GB")
    
    # Run benchmarks
    print("\n[3/5] Running benchmarks...")
    results = []
    
    for i, b in enumerate(BENCHMARKS):
        print(f"\n   [{i+1}/{len(BENCHMARKS)}] {b['name']}...")
        r = query(PORT, b["prompt"], b["max_tokens"])
        results.append({"name": b["name"], **r})
        
        if "error" in r:
            print(f"   ERROR: {r['error']}")
        else:
            print(f"   Tokens: {r['prompt_tokens']} -> {r['completion_tokens']} ({r['tok_per_sec']} tok/s, {r['total_time']}s)")
            has_content = r['content_len'] > 0
            has_reasoning = r['reasoning_len'] > 0
            print(f"   Thinking: {r['reasoning_len']} chars | Content: {r['content_len']} chars")
            print(f"   Answer: {r['content_preview'][:100]}")
    
    # Post-benchmark memory
    print("\n[4/5] Post-benchmark memory:")
    m = get_mem()
    print(f"   Free: {m.get('free_gb', '?')} GB | Active: {m.get('active_gb', '?')} GB | Wired: {m.get('wired_gb', '?')} GB")
    
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
    out = "/Users/nesbitt/dev/factory/docs/fct/FCT088-26b-a4b-benchmark-v2.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n   Saved: {out}")
    
    # Cleanup
    print("\n[5/5] Stopping server...")
    proc.terminate()
    proc.wait(timeout=10)
    print("   Done.\n")


if __name__ == "__main__":
    main()
