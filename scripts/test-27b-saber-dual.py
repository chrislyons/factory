#!/usr/bin/env python3
"""Dual-instance test for 27B-SABER 4-bit.

Only the 4-bit variant (~14 GB) has enough headroom for dual instances.
The 6-bit variant (~21 GB) will thrash — do NOT run this with VARIANT=6bit.

Tests: single instance speed -> start second instance -> measure both -> concurrent stress.

Key facts (from FCT087/FCT088):
  - 4-bit 27B: 14 GB model, ~14 GB wired, ~11 GB headroom as single
  - Dual instances share model pages via mmap (same file)
  - Prefill serialized (prompt-concurrency 1), decode can be parallel
"""

import glob
import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(__file__))
from benchmark_utils import find_mlx_python, get_mem, wait_server, write_wrapper

PORT_A = 41966
PORT_B = 41967

BENCHMARKS = [
    {"name": "Short factual", "prompt": "What is the capital of France? One word.", "max_tokens": 256},
    {"name": "Reasoning",     "prompt": "A farmer has 17 sheep. All but 9 die. How many left?", "max_tokens": 512},
    {"name": "Code gen",      "prompt": "Write a Python palindrome checker with docstring and type hints.", "max_tokens": 1024},
    {"name": "Multi-step",    "prompt": "5 machines make 5 widgets in 5 minutes. How long for 100 machines to make 100 widgets?", "max_tokens": 512},
    {"name": "Instruction",   "prompt": "List exactly 5 benefits of exercise. Numbered. One sentence each. No intro/conclusion.", "max_tokens": 512},
    {"name": "Tool call",     "prompt": "You have read_file(path). User: 'Read config.yaml, tell me the db port.' Respond with tool call JSON only.", "max_tokens": 512},
]


def query(port, model, prompt, max_tokens=256, timeout=300):
    import requests
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    start = time.time()
    try:
        r = requests.post(f"http://localhost:{port}/v1/chat/completions",
                          json=payload, timeout=timeout)
        elapsed = time.time() - start
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        data = r.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning_content") or ""
        usage = data.get("usage", {})
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        return {
            "content": content[:150],
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_time": round(elapsed, 1),
            "tok_per_sec": round(ct / elapsed, 1) if elapsed > 0 else 0,
        }
    except Exception as e:
        return {"error": str(e)[:100]}


def start_server(port, model, mlx_python):
    wrapper_path = "/tmp/test-27b-dual-wrapper.py"
    write_wrapper(wrapper_path, metal_limit_gb=20)
    proc = subprocess.Popen(
        [mlx_python, wrapper_path,
         "--model", model, "--port", str(port),
         "--max-tokens", "16384", "--prefill-step-size", "2048",
         "--prompt-concurrency", "1", "--prompt-cache-bytes", "2147483648"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())
    return proc


def bench(port, model):
    results = []
    for b in BENCHMARKS:
        r = query(port, model, b["prompt"], b["max_tokens"])
        results.append({"name": b["name"], **r})
    return results


def print_results(results, label):
    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")
    print(f"  {'Test':<18} {'P_tok':>6} {'C_tok':>6} {'tok/s':>7} {'Time':>6}")
    print(f"  {'-'*50}")
    for r in results:
        if "error" in r:
            print(f"  {r['name']:<18} ERROR: {r['error'][:35]}")
        else:
            print(f"  {r['name']:<18} {r['prompt_tokens']:>6} {r['completion_tokens']:>6} "
                  f"{r['tok_per_sec']:>7} {r['total_time']:>5}s")


def avg_tok_s(results):
    valid = [r for r in results if "error" not in r]
    return sum(r.get("tok_per_sec", 0) for r in valid) / max(len(valid), 1)


def main():
    mlx_python = find_mlx_python()

    # Find the 4-bit model
    candidates = glob.glob("/Users/nesbitt/models/*27b*SABER*4bit*")
    if not candidates:
        candidates = glob.glob("/Users/nesbitt/models/*Ornstein*27b*4bit*")
    if not candidates:
        candidates = glob.glob("/Users/nesbitt/models/*27b*4bit*")

    if not candidates:
        print("ERROR: 4-bit 27B-SABER model not found in ~/models/")
        print("Checked: *27b*SABER*4bit*, *Ornstein*27b*4bit*, *27b*4bit*")
        sys.exit(1)

    model = candidates[0]
    print(f"Model: {model}")
    print(f"Python: {mlx_python}")

    total_size = sum(
        os.path.getsize(os.path.join(model, f))
        for f in os.listdir(model)
        if f.endswith(".safetensors")
    )
    print(f"Disk size: {total_size / (1024**3):.1f} GB")

    print(f"\n{'='*65}")
    print("  ORNSTEIN-HERMES-3.6-27B-SABER 4-BIT: DUAL INSTANCE TEST")
    print(f"{'='*65}")

    # Phase 0: Baseline
    m_baseline = get_mem()
    print(f"\n[Phase 0] Baseline: Free={m_baseline['free_gb']}GB  Wired={m_baseline['wired_gb']}GB  Active={m_baseline['active_gb']}GB")

    # Phase 1: Single instance
    print(f"\n[Phase 1] Starting single instance on :{PORT_A}...")
    proc_a = start_server(PORT_A, model, mlx_python)
    if not wait_server(PORT_A, timeout=180, proc=proc_a):
        print("FAILED: Instance A did not start")
        proc_a.terminate()
        sys.exit(1)

    query(PORT_A, model, "Hello!", 32)  # warmup
    m = get_mem()
    print(f"  Loaded: Free={m['free_gb']}GB  Wired={m['wired_gb']}GB  Active={m['active_gb']}GB")
    footprint = m["wired_gb"] - m_baseline["wired_gb"]
    print(f"  Model footprint: ~{footprint:.1f} GB wired")

    print("\n  Running benchmarks (single instance)...")
    results_single = bench(PORT_A, model)
    print_results(results_single, "PHASE 1: SINGLE INSTANCE")

    m = get_mem()
    print(f"\n  Post-bench: Free={m['free_gb']}GB  Wired={m['wired_gb']}GB")

    # Phase 2: Dual instances
    print(f"\n[Phase 2] Starting second instance on :{PORT_B}...")
    proc_b = start_server(PORT_B, model, mlx_python)
    if not wait_server(PORT_B, timeout=180, proc=proc_b):
        print("  FAILED: Instance B did not start")
        print("  (Expected if model is too large for dual)")
        proc_a.terminate()
        proc_b.terminate()
        sys.exit(0)

    m = get_mem()
    print(f"  Both loaded: Free={m['free_gb']}GB  Wired={m['wired_gb']}GB  Active={m['active_gb']}GB")
    print(f"  Headroom: {m['free_gb']} GB")

    if m["free_gb"] < 1.0:
        print("  WARNING: <1 GB free — likely to thrash")
    elif m["free_gb"] < 3.0:
        print("  CAUTION: <3 GB free — may degrade under load")
    else:
        print("  OK: sufficient headroom")

    print("\n  Running benchmarks (both instances)...")
    results_a = bench(PORT_A, model)
    results_b = bench(PORT_B, model)

    print_results(results_a, "PHASE 2: INSTANCE A (with B running)")
    print_results(results_b, "PHASE 2: INSTANCE B (with A running)")

    m = get_mem()
    print(f"\n  Final: Free={m['free_gb']}GB  Wired={m['wired_gb']}GB")

    # Phase 3: Concurrent stress
    print(f"\n[Phase 3] Concurrent decode test...")
    results_concurrent = {}

    def run_query(port, name):
        r = query(port, model, "Explain quantum entanglement in 3 sentences.", 256)
        results_concurrent[name] = r

    t0 = time.time()
    t1 = threading.Thread(target=run_query, args=(PORT_A, "A"))
    t2 = threading.Thread(target=run_query, args=(PORT_B, "B"))
    t1.start()
    t2.start()
    t1.join(timeout=120)
    t2.join(timeout=120)
    concurrent_time = time.time() - t0

    print(f"  Concurrent time: {concurrent_time:.1f}s")
    for name, r in results_concurrent.items():
        if "error" in r:
            print(f"  {name}: ERROR - {r['error']}")
        else:
            print(f"  {name}: {r['completion_tokens']} tok, {r['tok_per_sec']} tok/s")

    # Summary
    print(f"\n{'='*65}")
    print("  SUMMARY")
    print(f"{'='*65}")

    avg_single = avg_tok_s(results_single)
    avg_a = avg_tok_s(results_a)
    avg_b = avg_tok_s(results_b)

    print(f"  Single instance avg:  {avg_single:.1f} tok/s")
    print(f"  Dual instance A avg:  {avg_a:.1f} tok/s")
    print(f"  Dual instance B avg:  {avg_b:.1f} tok/s")
    if avg_single > 0:
        print(f"  Speed degradation:    {((avg_single - avg_a) / avg_single * 100):.0f}%")
    print(f"  Model disk:           {total_size / (1024**3):.1f} GB")

    verdict = "PASS" if avg_a > 10 and avg_b > 10 and m["free_gb"] > 1.0 else "FAIL"
    print(f"\n  VERDICT: {verdict}")
    if verdict == "PASS":
        print("  Dual instances viable for production!")
    else:
        print("  Dual instances NOT viable. Stick with single instance.")

    # Save
    output = {
        "model": model,
        "disk_size_gb": round(total_size / (1024**3), 1),
        "single": results_single,
        "dual_a": results_a,
        "dual_b": results_b,
        "concurrent": results_concurrent,
        "avg_single_tok_s": round(avg_single, 1),
        "avg_dual_a_tok_s": round(avg_a, 1),
        "avg_dual_b_tok_s": round(avg_b, 1),
    }
    out_path = "/Users/nesbitt/dev/factory/docs/fct/FCT087-27b-saber-4bit-dual-test.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results: {out_path}")

    # Cleanup
    proc_a.terminate()
    proc_b.terminate()
    try:
        proc_a.wait(timeout=10)
        proc_b.wait(timeout=10)
    except Exception:
        pass
    print("\n  Cleanup done.")


if __name__ == "__main__":
    main()
