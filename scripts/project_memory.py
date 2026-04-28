#!/usr/bin/env python3
"""
Memory projection: 2B and 4B models at various context sizes.
Extrapolates from actual benchmark data using:
  peak = model_mem + kv_per_token * ctx + overhead(ctx)
where overhead grows slowly with context (MLX internals + activation buffers).
"""
import json

# Actual benchmark data
b2_data = {
    512:   {"peak": 2.3, "kv": 0.006},
    2048:  {"peak": 2.9, "kv": 0.025},
    8192:  {"peak": 3.4, "kv": 0.10},
    16384: {"peak": 3.6, "kv": 0.20},
    32768: {"peak": 4.3, "kv": 0.40},
}
b2_model = 1.53
b2_kv_per_token = 12288  # bytes

b4_data = {
    512:   {"peak": 4.3, "kv": 0.017},
    2048:  {"peak": 5.1, "kv": 0.067},
    8192:  {"peak": 5.8, "kv": 0.27},
    16384: {"peak": 6.6, "kv": 0.54},
    32768: {"peak": 8.2, "kv": 1.07},
}
b4_model = 3.42
b4_kv_per_token = 32768  # bytes

# Calculate overhead at each measured point
print("=== Measured overhead (peak - model - kv) ===")
for label, data, model in [("2B", b2_data, b2_model), ("4B", b4_data, b4_model)]:
    print(f"\n{label}:")
    for ctx, d in data.items():
        overhead = d["peak"] - model - d["kv"]
        print(f"  {ctx:>6} tok: peak={d['peak']:.1f}  kv={d['kv']:.2f}  overhead={overhead:.2f} GB")

# Overhead grows slowly — fit a rough model: overhead = base + growth * log2(ctx/32768)
# At 32K: overhead is our anchor
b2_overhead_32k = b2_data[32768]["peak"] - b2_model - b2_data[32768]["kv"]  # 2.37
b4_overhead_32k = b4_data[32768]["peak"] - b4_model - b4_data[32768]["kv"]  # 3.71

import math

def project_peak(model_mem, kv_per_token, overhead_32k, ctx):
    """Project peak memory at a given context size."""
    kv = kv_per_token * ctx / 1e9
    # Overhead grows logarithmically from 32K anchor
    if ctx <= 32768:
        overhead = overhead_32k * (ctx / 32768)  # linear up to 32K
    else:
        overhead = overhead_32k + 0.4 * math.log2(ctx / 32768)
    return model_mem + kv + overhead

# Project at various context sizes
contexts = [32768, 49152, 65536, 81920, 98304, 131072, 163840, 196608, 229376, 262144]

print("\n" + "=" * 80)
print("PROJECTED PEAK MEMORY (GB)")
print("=" * 80)
print(f"{'Context':>10} {'2B peak':>10} {'4B peak':>10} {'2x 2B':>10} {'2x 4B':>10} {'1x 4B':>10}")
print("-" * 80)

macos = 5.0
flash_moe = 6.0
budget = 32.0 - macos - flash_moe  # 21 GB available

for ctx in contexts:
    p2 = project_peak(b2_model, b2_kv_per_token, b2_overhead_32k, ctx)
    p4 = project_peak(b4_model, b4_kv_per_token, b4_overhead_32k, ctx)
    two_2b = p2 * 2
    two_4b = p4 * 2
    one_4b = p4

    ctx_label = f"{ctx//1024}K"
    
    def fit(val, budget):
        return "✓" if val <= budget else "✗"
    
    print(f"{ctx_label:>10} {p2:>8.1f}GB {p4:>8.1f}GB "
          f"{two_2b:>7.1f}GB{fit(two_2b, budget)} "
          f"{two_4b:>7.1f}GB{fit(two_4b, budget)} "
          f"{one_4b:>7.1f}GB{fit(one_4b, budget)}")

print("-" * 80)
print(f"Budget: {budget:.0f} GB available ({32:.0f} GB - {macos:.0f} macOS - {flash_moe:.0f} flash-moe)")
print()
print("✓ = fits within budget, ✗ = exceeds budget")

# Find max context per config
print("\n" + "=" * 60)
print("MAXIMUM CONTEXT PER CONFIGURATION")
print("=" * 60)

for label, model_mem, kv_pt, oh_32k in [
    ("1x 2B", b2_model, b2_kv_per_token, b2_overhead_32k),
    ("2x 2B", b2_model, b2_kv_per_token, b2_overhead_32k),
    ("1x 4B", b4_model, b4_kv_per_token, b4_overhead_32k),
    ("2x 4B", b4_model, b4_kv_per_token, b4_overhead_32k),
]:
    n_instances = 2 if label.startswith("2x") else 1
    # Binary search for max context
    lo, hi = 1024, 524288
    while lo < hi:
        mid = (lo + hi + 1) // 2
        total = project_peak(model_mem, kv_pt, oh_32k, mid) * n_instances
        if total <= budget:
            lo = mid
        else:
            hi = mid - 1
    max_ctx = lo
    peak = project_peak(model_mem, kv_pt, oh_32k, max_ctx) * n_instances
    # Find nearest nice round number
    for nice in [262144, 196608, 163840, 131072, 98304, 81920, 65536, 49152, 32768]:
        nice_peak = project_peak(model_mem, kv_pt, oh_32k, nice) * n_instances
        if nice_peak <= budget:
            print(f"  {label:8s}: max ~{max_ctx//1024}K (hard), "
                  f"recommended {nice//1024}K ({nice_peak:.1f} GB of {budget:.0f} GB)")
            break

print()
print("Note: 35B-A3B budgeted at 6 GB (includes spike headroom).")
print("      Actual resident is ~3 GB but inference can spike.")
