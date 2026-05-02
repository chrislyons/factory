#!/usr/bin/env python3
"""Factory wrapper for mlx-lm.server — memory-safe dual-SABER configuration.

Applies three memory controls before starting the server:
  1. mx.set_memory_limit() — hard cap on Metal GPU allocations
  2. mx.set_wired_limit() — cap on wired (non-swappable) memory
  3. QuantizedKVCache — 8-bit KV cache quantization (~50% KV memory savings)

Usage: python mlx-lm-factory-wrapper.py [all normal mlx_lm.server args]

FCT078: Created 2026-04-30 to prevent Metal OOM on dual-SABER Whitebox setup.
"""

import sys
import mlx.core as mx

METAL_LIMIT_BYTES = 12 * 1024 * 1024 * 1024  # 12 GB (FCT093: bumped from 10 after Coord aux removal)
WIRED_LIMIT_BYTES = 12 * 1024 * 1024 * 1024  # 12 GB (FCT093: bumped from 10 after Coord aux removal)
_KV_BITS = 8
_KV_GROUP_SIZE = 64

# ── 1. Metal memory limit ────────────────────────────────────────────
mx.set_memory_limit(METAL_LIMIT_BYTES)

# ── 2. Wired memory limit ────────────────────────────────────────────
# Patch so the server's main() can't override our limit.
_real_set_wired_limit = mx.set_wired_limit
_real_set_wired_limit(WIRED_LIMIT_BYTES)
mx.set_wired_limit = lambda *args, **kwargs: None

# ── 3. Quantized KV cache (8-bit) ────────────────────────────────────
from mlx_lm.models.cache import QuantizedKVCache, RotatingKVCache
import mlx.nn as nn
from typing import List, Optional, Any


def make_prompt_cache_quantized(
    model: nn.Module,
    max_kv_size: Optional[int] = None,
) -> List[Any]:
    """Quantized replacement for make_prompt_cache."""
    if hasattr(model, "make_cache"):
        return model.make_cache()

    num_layers = len(model.layers)
    if max_kv_size is not None:
        return [
            RotatingKVCache(max_size=max_kv_size, keep=4) for _ in range(num_layers)
        ]
    return [
        QuantizedKVCache(group_size=_KV_GROUP_SIZE, bits=_KV_BITS)
        for _ in range(num_layers)
    ]


import mlx_lm.models.cache
mlx_lm.models.cache.make_prompt_cache = make_prompt_cache_quantized

import mlx_lm.server
mlx_lm.server.make_prompt_cache = make_prompt_cache_quantized

print(f"[factory-wrapper] Metal limit: {METAL_LIMIT_BYTES // (1024**3)} GB")
print(f"[factory-wrapper] Wired limit: {WIRED_LIMIT_BYTES // (1024**3)} GB")
print(f"[factory-wrapper] KV cache: {_KV_BITS}-bit quantized (group_size={_KV_GROUP_SIZE})")

# ── Launch the server ─────────────────────────────────────────────────
# Set argv to just the server args (drop this script's path)
sys.argv = ["mlx-lm-server"] + sys.argv[1:]
mlx_lm.server.main()
