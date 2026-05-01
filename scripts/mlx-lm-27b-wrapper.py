#!/usr/bin/env python3
"""Factory wrapper for Ornstein-Hermes-3.6-27B on :41966.

Single-instance 27B model. Both E4B SABERs must be offline.

Memory strategy (v3 — no wired limit, control GPU buffers via prefill size):
  - Model loads via mmap, pages stay resident (~21 GB active)
  - NO wired limit — forcing eviction causes 2 tok/s thrashing
  - Metal limit at 28 GB — leaves 4 GB for macOS
  - prefill-step-size 256 — tiny GPU buffer allocation per step
    (crash was at step-size 2048 during 6144/18520 token prefill)
  - 4-bit QuantizedKVCache on 16 full attention layers
  - ArraysCache (GatedDeltaNet) untouched — already tiny
"""

import sys
import mlx.core as mx

# ── 1. Metal memory limit only ──────────────────────────────────────
# NO wired limit — let model pages stay resident. The crash was Metal GPU
# OOM during prefill, not system memory pressure.
METAL_LIMIT_BYTES = 28 * 1024 * 1024 * 1024   # 28 GB
mx.set_memory_limit(METAL_LIMIT_BYTES)

# ── 2. Quantized KV cache (4-bit) ───────────────────────────────────
_KV_BITS = 8
_KV_GROUP_SIZE = 64

from mlx_lm.models.cache import QuantizedKVCache, KVCache, ArraysCache
import mlx.nn as nn
from typing import List, Optional, Any


def make_quantized_cache(model: nn.Module, max_kv_size=None) -> List[Any]:
    """4-bit KV for full attention layers, ArraysCache for GatedDeltaNet."""
    if hasattr(model, 'language_model'):
        layers = model.language_model.layers
    elif hasattr(model, 'layers'):
        layers = model.layers
    else:
        return [QuantizedKVCache(group_size=_KV_GROUP_SIZE, bits=_KV_BITS)
                for _ in range(64)]

    cache = []
    for layer in layers:
        is_linear = getattr(layer, 'is_linear', False)
        if is_linear:
            cache.append(ArraysCache(size=2))
        else:
            cache.append(QuantizedKVCache(group_size=_KV_GROUP_SIZE, bits=_KV_BITS))
    return cache


import mlx_lm.models.cache
import mlx_lm.server
from mlx_lm.models.qwen3_5 import TextModel

mlx_lm.models.cache.make_prompt_cache = make_quantized_cache
mlx_lm.server.make_prompt_cache = make_quantized_cache
TextModel.make_cache = make_quantized_cache

print(f"[27b-wrapper] Metal limit: {METAL_LIMIT_BYTES // (1024**3)} GB (no wired limit)")
print(f"[27b-wrapper] KV cache: {_KV_BITS}-bit quantized")
print(f"[27b-wrapper] Prefill step size: set via CLI (256 recommended)")

# ── Launch the server ─────────────────────────────────────────────
sys.argv = ["mlx-lm-server"] + sys.argv[1:]
mlx_lm.server.main()
