#!/usr/bin/env python3
"""Factory wrapper for Ornstein-26B-A4B-it 4-bit on dedicated port.

Gemma 4 MoE model. No custom KV cache needed — mlx_lm's native
Gemma4 TextModel.make_cache handles full attention (KVCache) and
sliding attention (RotatingKVCache) correctly.

Memory strategy:
  - Model loads via mmap (~13.8 GB wired)
  - NO wired limit — let model pages stay resident
  - Metal limit at 20 GB — leaves headroom for macOS
  - prefill-step-size 256 — small GPU buffer per step
"""

import sys
import mlx.core as mx

# ── Metal memory limit ─────────────────────────────────────────────
METAL_LIMIT_BYTES = 20 * 1024 * 1024 * 1024  # 20 GB
mx.set_memory_limit(METAL_LIMIT_BYTES)

print(f"[26b-a4b-wrapper] Metal limit: {METAL_LIMIT_BYTES // (1024**3)} GB")
print(f"[26b-a4b-wrapper] Prefill step size: set via CLI (256 recommended)")

# ── Launch the server ─────────────────────────────────────────────
sys.argv = ["mlx-lm-server"] + sys.argv[1:]
import mlx_lm.server
mlx_lm.server.main()
