#!/usr/bin/env python3
"""Compare two eval result files side-by-side.

Usage:
    python3 evals/compare.py results/Qwen3.5-9B-MLX-6bit_*.json results/Carnice-9b-Q6_K_*.json

Or run both evals fresh:
    python3 evals/compare.py --baseline ~/models/Qwen3.5-9B-MLX-6bit --challenger ~/models/kai-os/Carnice-9b-GGUF/Carnice-9b-Q6_K.gguf
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks from response text."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


EVAL_DIR = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"


def load_results(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def latest_result_for(model_name: str) -> Path | None:
    """Find the most recent result file for a model name."""
    candidates = sorted(RESULTS_DIR.glob(f"{model_name}_*.json"), reverse=True)
    return candidates[0] if candidates else None


def compare(baseline: dict, challenger: dict):
    """Print side-by-side comparison."""
    b_name = baseline["model"]
    c_name = challenger["model"]

    b_by_id = {r["id"]: r for r in baseline["results"]}
    c_by_id = {r["id"]: r for r in challenger["results"]}

    all_ids = sorted(set(list(b_by_id.keys()) + list(c_by_id.keys())))

    print(f"\n{'='*80}")
    print(f"  COMPARISON: {b_name} (baseline) vs {c_name} (challenger)")
    print(f"{'='*80}")
    print(f"\n  {'ID':<6} {'Category':<12} {'Base tok/s':>10} {'Chal tok/s':>10} {'Speedup':>8}")
    print(f"  {'─'*56}")

    cat_stats = {}
    for pid in all_ids:
        b = b_by_id.get(pid)
        c = c_by_id.get(pid)
        if not b or not c:
            continue

        cat = b["category"]
        if cat not in cat_stats:
            cat_stats[cat] = {"b_speeds": [], "c_speeds": []}

        b_speed = b.get("tok_per_s", 0)
        c_speed = c.get("tok_per_s", 0)

        if b_speed > 0:
            cat_stats[cat]["b_speeds"].append(b_speed)
        if c_speed > 0:
            cat_stats[cat]["c_speeds"].append(c_speed)

        speedup = ""
        if b_speed > 0 and c_speed > 0:
            ratio = c_speed / b_speed
            arrow = "+" if ratio >= 1 else ""
            speedup = f"{arrow}{(ratio - 1) * 100:.0f}%"

        print(f"  {pid:<6} {cat:<12} {b_speed:>10.1f} {c_speed:>10.1f} {speedup:>8}")

    print(f"\n  {'─'*56}")
    print(f"\n  CATEGORY AVERAGES:")
    print(f"  {'Category':<12} {'Base avg':>10} {'Chal avg':>10} {'Speedup':>8}")
    print(f"  {'─'*40}")

    total_b, total_c = [], []
    for cat, stats in sorted(cat_stats.items()):
        b_avg = sum(stats["b_speeds"]) / len(stats["b_speeds"]) if stats["b_speeds"] else 0
        c_avg = sum(stats["c_speeds"]) / len(stats["c_speeds"]) if stats["c_speeds"] else 0
        total_b.extend(stats["b_speeds"])
        total_c.extend(stats["c_speeds"])

        speedup = ""
        if b_avg > 0 and c_avg > 0:
            ratio = c_avg / b_avg
            arrow = "+" if ratio >= 1 else ""
            speedup = f"{arrow}{(ratio - 1) * 100:.0f}%"

        print(f"  {cat:<12} {b_avg:>10.1f} {c_avg:>10.1f} {speedup:>8}")

    overall_b = sum(total_b) / len(total_b) if total_b else 0
    overall_c = sum(total_c) / len(total_c) if total_c else 0
    overall_speedup = ""
    if overall_b > 0 and overall_c > 0:
        ratio = overall_c / overall_b
        arrow = "+" if ratio >= 1 else ""
        overall_speedup = f"{arrow}{(ratio - 1) * 100:.0f}%"

    print(f"  {'─'*40}")
    print(f"  {'OVERALL':<12} {overall_b:>10.1f} {overall_c:>10.1f} {overall_speedup:>8}")
    print()

    # Response comparison for manual review
    print(f"\n{'='*80}")
    print(f"  RESPONSE COMPARISON (first 200 chars)")
    print(f"{'='*80}")
    for pid in all_ids:
        b = b_by_id.get(pid)
        c = c_by_id.get(pid)
        if not b or not c:
            continue
        print(f"\n  --- {pid} ({b['category']}) ---")
        print(f"  Check: {b['check']}")
        b_resp = strip_thinking(b.get("response") or "")[:300] or "NO RESPONSE"
        c_resp = strip_thinking(c.get("response") or "")[:300] or "NO RESPONSE"
        print(f"  BASE: {b_resp}")
        print(f"  CHAL: {c_resp}")


def main():
    parser = argparse.ArgumentParser(description="Compare eval results")
    parser.add_argument("files", nargs="*", help="Two result JSON files to compare")
    parser.add_argument("--baseline", type=str, help="Baseline model path (will run eval)")
    parser.add_argument("--challenger", type=str, help="Challenger model path (will run eval)")
    args = parser.parse_args()

    if args.files and len(args.files) == 2:
        baseline = load_results(args.files[0])
        challenger = load_results(args.files[1])
    elif args.baseline and args.challenger:
        # Run evals sequentially
        print("Running baseline eval...")
        subprocess.run([
            sys.executable, str(EVAL_DIR / "run_eval.py"),
            "--model", args.baseline,
        ], check=True)

        print("\nRunning challenger eval...")
        subprocess.run([
            sys.executable, str(EVAL_DIR / "run_eval.py"),
            "--model", args.challenger,
        ], check=True)

        # Find latest results
        from run_eval import model_name_from_path
        b_name = model_name_from_path(args.baseline)
        c_name = model_name_from_path(args.challenger)
        b_file = latest_result_for(b_name)
        c_file = latest_result_for(c_name)
        if not b_file or not c_file:
            print("Could not find result files after eval run")
            sys.exit(1)
        baseline = load_results(str(b_file))
        challenger = load_results(str(c_file))
    else:
        parser.error("Provide two result files or --baseline and --challenger model paths")

    compare(baseline, challenger)


if __name__ == "__main__":
    main()
