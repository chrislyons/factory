#!/usr/bin/env python3
"""Shared utilities for mlx_lm benchmark scripts."""

import glob
import os
import subprocess
import sys
import time

import requests


# ---------------------------------------------------------------------------
# mlx-lm Python interpreter discovery
# ---------------------------------------------------------------------------

def find_mlx_python() -> str:
    """Return the Python interpreter that has mlx_lm installed.

    Search order:
      1. Homebrew Cellar (newest version wins)
      2. PATH shim via `which mlx-lm-server`
      3. Current interpreter (sys.executable) as last resort
    """
    cellar_root = "/opt/homebrew/Cellar/mlx-lm"
    if os.path.isdir(cellar_root):
        versions = sorted(glob.glob(f"{cellar_root}/*/libexec/bin/python"), reverse=True)
        if versions:
            return versions[0]

    # Try the PATH shim — `mlx-lm-server` is a thin script whose shebang
    # points at the right interpreter.
    try:
        shim = subprocess.run(
            ["which", "mlx-lm-server"], capture_output=True, text=True
        ).stdout.strip()
        if shim and os.path.isfile(shim):
            with open(shim) as fh:
                first_line = fh.readline().strip()
            if first_line.startswith("#!"):
                candidate = first_line[2:].strip().split()[0]
                if os.path.isfile(candidate):
                    return candidate
    except Exception:
        pass

    return sys.executable


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------

def get_vm_stats() -> dict:
    """Return vm_stat values as a dict of {key: GB float}.

    Uses key-based parsing — safe across macOS versions.
    """
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
        page_size = 16384
        stats: dict = {}
        for line in out.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":.").replace(" ", "_")
                try:
                    val = int(parts[-1].rstrip("."))
                    stats[key] = val * page_size / (1024 ** 3)
                except ValueError:
                    pass
        return stats
    except Exception:
        return {}


def get_mem() -> dict:
    """Return free/active/wired memory in GB."""
    stats = get_vm_stats()
    return {
        "free_gb": round(stats.get("Pages_free", 0), 1),
        "active_gb": round(stats.get("Pages_active", 0), 1),
        "wired_gb": round(
            stats.get("Pages_wired_down", stats.get("Pages_wired", 0)), 1
        ),
    }


def mem_tuple() -> tuple:
    """Return (free_gb, wired_gb, active_gb) for compact dual-script usage."""
    m = get_mem()
    return m["free_gb"], m["wired_gb"], m["active_gb"]


# ---------------------------------------------------------------------------
# Server helpers
# ---------------------------------------------------------------------------

def wait_server(port: int, timeout: int = 180, proc=None) -> bool:
    """Poll /health until the server responds 200 or timeout expires.

    If `proc` is supplied and it dies before the timeout, fail immediately
    and print captured output to aid diagnosis.
    """
    start = time.time()
    while time.time() - start < timeout:
        if proc is not None and proc.poll() is not None:
            # Process exited — print whatever it wrote before dying
            try:
                out = proc.stdout.read()
                if out:
                    print(f"  [server exited early]\n{out[:2000]}")
            except Exception:
                pass
            return False
        try:
            r = requests.get(f"http://localhost:{port}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    # Timeout — try to print any output for diagnosis
    if proc is not None:
        try:
            out = proc.stdout.read()
            if out:
                print(f"  [server stdout/stderr]\n{out[:2000]}")
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Inference helper
# ---------------------------------------------------------------------------

def query(port: int, model: str, prompt: str, max_tokens: int,
          timeout: int = 600) -> dict:
    """Send a single chat completion and return timing + token counts."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    start = time.time()
    try:
        r = requests.post(
            f"http://localhost:{port}/v1/chat/completions",
            json=payload,
            timeout=timeout,
        )
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
            "content": content[:200] if content else "(thinking only)",
            "reasoning_len": len(reasoning),
            "content_len": len(content),
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_time": round(elapsed, 1),
            "tok_per_sec": round(ct / elapsed, 1) if elapsed > 0 else 0,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Wrapper script template (4-bit KV cache patch for Qwen3.5 hybrid models)
# ---------------------------------------------------------------------------

def make_wrapper_script(metal_limit_gb: int) -> str:
    """Return the wrapper source that patches mlx_lm with a quantized KV cache."""
    return f'''\
import sys, mlx.core as mx

mx.set_memory_limit({metal_limit_gb} * 1024 * 1024 * 1024)

_KV_BITS = 4
_KV_GROUP_SIZE = 64

from mlx_lm.models.cache import QuantizedKVCache, ArraysCache
import mlx.nn as nn
from typing import List, Any


def make_quantized_cache(model: nn.Module, max_kv_size=None) -> List[Any]:
    """4-bit KV for full-attention layers, ArraysCache for GatedDeltaNet."""
    if hasattr(model, "language_model"):
        layers = model.language_model.layers
    elif hasattr(model, "layers"):
        layers = model.layers
    else:
        return [QuantizedKVCache(group_size=_KV_GROUP_SIZE, bits=_KV_BITS)
                for _ in range(64)]
    cache = []
    for layer in layers:
        if getattr(layer, "is_linear", False):
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

print(f"[benchmark] Metal limit: {metal_limit_gb} GB | KV cache: 4-bit quantized")
sys.argv = ["mlx-lm-server"] + sys.argv[1:]
mlx_lm.server.main()
'''


def write_wrapper(path: str, metal_limit_gb: int) -> None:
    with open(path, "w") as fh:
        fh.write(make_wrapper_script(metal_limit_gb))
