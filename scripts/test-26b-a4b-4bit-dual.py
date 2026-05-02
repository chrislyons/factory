#!/usr/bin/env python3
"""Dual-instance test for Ornstein-26B-A4B-it-MLX-4bit.

Tests: single instance speed → start second instance → measure both → stress test.

Key hypothesis: mmap shares model pages between processes. 4-bit model (~13 GB)
should allow dual instances within 32 GB RAM (vs 6-bit which thrashed).
"""

import subprocess
import time
import json
import requests
import os
import sys

# Will be set to the actual model path once downloaded
MODEL = None
PORT_A = 41967
PORT_B = 41968

WRAPPER = '''
import sys, mlx.core as mx

# Memory limit only — NO wired limit
# Let mmap manage page residency. The 4-bit model should be small enough
# that both instances share pages without exhausting RAM.
mx.set_memory_limit(20 * 1024 * 1024 * 1024)  # 20 GB per instance

import mlx_lm.server
sys.argv = ["mlx-lm-server"] + sys.argv[1:]
mlx_lm.server.main()
'''

BENCHMARKS = [
    {"name": "Short factual", "prompt": "What is the capital of France? One word.", "max_tokens": 256},
    {"name": "Reasoning", "prompt": "A farmer has 17 sheep. All but 9 die. How many left?", "max_tokens": 512},
    {"name": "Code gen", "prompt": "Write a Python palindrome checker with docstring and type hints.", "max_tokens": 1024},
    {"name": "Multi-step", "prompt": "5 machines make 5 widgets in 5 minutes. How long for 100 machines to make 100 widgets?", "max_tokens": 512},
    {"name": "Instruction", "prompt": "List exactly 5 benefits of exercise. Numbered. One sentence each. No intro/conclusion.", "max_tokens": 512},
    {"name": "Tool call", "prompt": "You have read_file(path). User: 'Read config.yaml, tell me the db port.' Respond with tool call JSON only.", "max_tokens": 512},
]


def mem():
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    page_size = 16384
    free = wired = active = 0
    for line in out.strip().split("\n"):
        if "Pages free" in line:
            free = int(line.split()[-1].rstrip(".")) * page_size / (1024**3)
        elif "Pages wired" in line:
            wired = int(line.split()[-1].rstrip(".")) * page_size / (1024**3)
        elif "Pages active" in line and "inactive" not in line:
            active = int(line.split()[-1].rstrip(".")) * page_size / (1024**3)
    return free, wired, active


def wait_health(port, timeout=180):
    for _ in range(timeout):
        try:
            if requests.get(f"http://localhost:{port}/health", timeout=2).status_code == 200:
                return True
        except:
            pass
        time.sleep(1)
    return False


def query(port, prompt, max_tokens=256, timeout=300):
    payload = {
        "model": MODEL,
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


def start_server(port):
    with open("/tmp/wrapper-26b-4bit.py", "w") as f:
        f.write(WRAPPER)
    proc = subprocess.Popen([
        "/opt/homebrew/Cellar/mlx-lm/0.31.3/libexec/bin/python",
        "/tmp/wrapper-26b-4bit.py",
        "--model", MODEL, "--port", str(port),
        "--max-tokens", "16384", "--prefill-step-size", "256",
        "--prompt-concurrency", "1", "--prompt-cache-bytes", "2147483648",
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=os.environ.copy())
    return proc


def bench(port, label):
    results = []
    for b in BENCHMARKS:
        r = query(port, b["prompt"], b["max_tokens"])
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


def main():
    global MODEL

    # Find the model
    import glob
    candidates = glob.glob("/Users/nesbitt/models/*26B*A4B*4bit*")
    if not candidates:
        candidates = glob.glob("/Users/nesbitt/models/*26b*a4b*4bit*")
    if not candidates:
        candidates = glob.glob("/Users/nesbitt/models/*Ornstein*26*4bit*")

    if not candidates:
        print("ERROR: 4-bit 26B-A4B model not found in ~/models/")
        print("Checked: *26B*A4B*4bit*, *26b*a4b*4bit*, *Ornstein*26*4bit*")
        sys.exit(1)

    MODEL = candidates[0]
    print(f"Model: {MODEL}")

    # Get model size
    total_size = sum(
        os.path.getsize(os.path.join(MODEL, f))
        for f in os.listdir(MODEL)
        if f.endswith(".safetensors")
    )
    print(f"Disk size: {total_size / (1024**3):.1f} GB")

    print(f"\n{'='*65}")
    print("  ORNSTEIN 26B-A4B 4-BIT: DUAL INSTANCE TEST")
    print(f"{'='*65}")

    # ── Phase 1: Baseline ────────────────────────────────────────────
    free, wired, active = mem()
    print(f"\n[Phase 0] Baseline: Free={free:.1f}GB  Wired={wired:.1f}GB  Active={active:.1f}GB")

    # ── Phase 1: Single instance ─────────────────────────────────────
    print("\n[Phase 1] Starting single instance on :{}...".format(PORT_A))
    proc_a = start_server(PORT_A)
    if not wait_health(PORT_A):
        print("FAILED: Instance A did not start")
        proc_a.terminate()
        sys.exit(1)

    # Warmup
    query(PORT_A, "Hello!", 32)
    free, wired, active = mem()
    print(f"  Loaded: Free={free:.1f}GB  Wired={wired:.1f}GB  Active={active:.1f}GB")
    print(f"  Model footprint: ~{wired - 3.1:.1f} GB wired")

    # Benchmark single
    print("\n  Running benchmarks (single instance)...")
    results_single = bench(PORT_A, "Single")
    print_results(results_single, "PHASE 1: SINGLE INSTANCE")

    free, wired, active = mem()
    print(f"\n  Post-bench: Free={free:.1f}GB  Wired={wired:.1f}GB")

    # ── Phase 2: Dual instances ──────────────────────────────────────
    print(f"\n[Phase 2] Starting second instance on :{PORT_B}...")
    proc_b = start_server(PORT_B)
    if not wait_health(PORT_B):
        print("  FAILED: Instance B did not start")
        print("  (Expected if model is too large for dual)")
        proc_a.terminate()
        proc_b.terminate()
        sys.exit(0)

    free, wired, active = mem()
    print(f"  Both loaded: Free={free:.1f}GB  Wired={wired:.1f}GB  Active={active:.1f}GB")
    print(f"  Headroom: {free:.1f} GB")

    if free < 1.0:
        print("  WARNING: <1 GB free — likely to thrash")
    elif free < 3.0:
        print("  CAUTION: <3 GB free — may degrade under load")
    else:
        print("  OK: sufficient headroom")

    # Benchmark both
    print("\n  Running benchmarks (both instances)...")
    results_a = bench(PORT_A, "Instance A")
    results_b = bench(PORT_B, "Instance B")

    print_results(results_a, "PHASE 2: INSTANCE A (with B running)")
    print_results(results_b, "PHASE 2: INSTANCE B (with A running)")

    free, wired, active = mem()
    print(f"\n  Final: Free={free:.1f}GB  Wired={wired:.1f}GB")

    # ── Phase 3: Concurrent stress test ──────────────────────────────
    print(f"\n[Phase 3] Concurrent decode test...")
    import threading

    results_concurrent = {}

    def run_query(port, name):
        r = query(port, "Explain quantum entanglement in 3 sentences.", 256)
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

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print("  SUMMARY")
    print(f"{'='*65}")

    avg_single = sum(r.get("tok_per_sec", 0) for r in results_single if "error" not in r) / max(len([r for r in results_single if "error" not in r]), 1)
    avg_a = sum(r.get("tok_per_sec", 0) for r in results_a if "error" not in r) / max(len([r for r in results_a if "error" not in r]), 1)
    avg_b = sum(r.get("tok_per_sec", 0) for r in results_b if "error" not in r) / max(len([r for r in results_b if "error" not in r]), 1)

    print(f"  Single instance avg:  {avg_single:.1f} tok/s")
    print(f"  Dual instance A avg:  {avg_a:.1f} tok/s")
    print(f"  Dual instance B avg:  {avg_b:.1f} tok/s")
    print(f"  Speed degradation:    {((avg_single - avg_a) / avg_single * 100):.0f}%" if avg_single > 0 else "")
    print(f"  Model disk:           {total_size / (1024**3):.1f} GB")

    verdict = "PASS" if avg_a > 15 and avg_b > 15 and free > 1.0 else "FAIL"
    print(f"\n  VERDICT: {verdict}")
    if verdict == "PASS":
        print("  Dual instances viable for production!")
    else:
        print("  Dual instances NOT viable. Stick with single instance.")

    # Save results
    output = {
        "model": MODEL,
        "disk_size_gb": round(total_size / (1024**3), 1),
        "single": results_single,
        "dual_a": results_a,
        "dual_b": results_b,
        "concurrent": results_concurrent,
        "avg_single_tok_s": round(avg_single, 1),
        "avg_dual_a_tok_s": round(avg_a, 1),
        "avg_dual_b_tok_s": round(avg_b, 1),
    }
    out_path = "/Users/nesbitt/dev/factory/docs/fct/FCT088-26b-a4b-4bit-dual-test.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results: {out_path}")

    # Cleanup
    proc_a.terminate()
    proc_b.terminate()
    try:
        proc_a.wait(timeout=10)
        proc_b.wait(timeout=10)
    except:
        pass
    print("\n  Cleanup done.")


if __name__ == "__main__":
    main()
