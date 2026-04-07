#!/usr/bin/env python3
"""Factory Model Eval Runner

Serves a local model (MLX or GGUF) and runs the prompt suite against it.
Results are written to evals/results/<model_name>_<timestamp>.json.

Usage:
    python3 evals/run_eval.py --model ~/models/Qwen3.5-9B-MLX-6bit
    python3 evals/run_eval.py --model ~/models/kai-os/Carnice-9b-GGUF/Carnice-9b-Q6_K.gguf --category agentic
    python3 evals/run_eval.py --port 8080  # use already-running server
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error
import yaml


EVAL_DIR = Path(__file__).parent
PROMPTS_FILE = EVAL_DIR / "prompts.yaml"
RESULTS_DIR = EVAL_DIR / "results"

DEFAULT_PORT = 8198  # avoid collisions with MLX-LM agent slots (41961-41963)
SERVE_TIMEOUT = 120  # seconds to wait for server startup
THINKING_TOKEN_CAP = 8192  # thinking models: generous cap for reasoning + answer


def detect_format(model_path: str) -> str:
    """Detect whether model is GGUF or MLX based on file contents."""
    p = Path(model_path)
    if p.suffix == ".gguf" or (p.is_file() and p.name.endswith(".gguf")):
        return "gguf"
    if p.is_dir():
        files = [f.name for f in p.iterdir()]
        if any(f.endswith(".safetensors") for f in files):
            return "mlx"
        if any(f.endswith(".gguf") for f in files):
            # directory containing a gguf
            gguf = next(f for f in p.iterdir() if f.name.endswith(".gguf"))
            return "gguf"
    raise ValueError(f"Cannot detect format for {model_path}")


def find_gguf_file(model_path: str) -> str:
    """If model_path is a directory, find the .gguf file inside it."""
    p = Path(model_path)
    if p.is_file():
        return str(p)
    if p.is_dir():
        ggufs = list(p.glob("*.gguf"))
        if len(ggufs) == 1:
            return str(ggufs[0])
        if len(ggufs) > 1:
            # prefer Q6_K
            for g in ggufs:
                if "Q6_K" in g.name:
                    return str(g)
            return str(ggufs[0])
    raise FileNotFoundError(f"No .gguf file found in {model_path}")


def model_name_from_path(model_path: str) -> str:
    """Extract a clean model name from the path."""
    p = Path(model_path)
    if p.is_file():
        return p.stem
    return p.name


def start_server(model_path: str, port: int, fmt: str) -> subprocess.Popen:
    """Start the appropriate model server."""
    if fmt == "gguf":
        gguf_path = find_gguf_file(model_path)
        cmd = [
            "llama-server",
            "-m", gguf_path,
            "--port", str(port),
            "-c", "8192",
            "-ngl", "99",  # offload all layers to GPU/ANE
        ]
    else:
        cmd = [
            "mlx_lm.server",
            "--model", model_path,
            "--port", str(port),
            "--prompt-cache-size", "1",  # prevent KV cache OOM (WHB023 lesson)
        ]

    print(f"Starting server: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def wait_for_server(port: int, timeout: int = SERVE_TIMEOUT) -> bool:
    """Wait for the server to become responsive."""
    url = f"http://localhost:{port}/v1/models"
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            pass
        time.sleep(1)
    return False


def query_model(port: int, prompt: str, max_tokens: int = 512, temperature: float = 0.0) -> dict:
    """Send a chat completion request and return response + timing."""
    url = f"http://localhost:{port}/v1/chat/completions"
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
    except Exception as e:
        return {
            "error": str(e),
            "elapsed_s": time.perf_counter() - t0,
            "response": None,
            "tokens": 0,
        }
    elapsed = time.perf_counter() - t0

    choice = body.get("choices", [{}])[0]
    message = choice.get("message", {})
    usage = body.get("usage", {})
    completion_tokens = usage.get("completion_tokens", 0)

    content = message.get("content", "") or ""
    reasoning = message.get("reasoning_content", "") or ""
    has_thinking = bool(reasoning)

    return {
        "response": content,
        "reasoning": reasoning,
        "has_thinking": has_thinking,
        "elapsed_s": round(elapsed, 3),
        "tokens": completion_tokens,
        "tok_per_s": round(completion_tokens / elapsed, 1) if elapsed > 0 and completion_tokens > 0 else 0,
        "finish_reason": choice.get("finish_reason"),
    }


def load_prompts(category: str | None = None) -> list[dict]:
    """Load prompts from YAML, optionally filtering by category."""
    with open(PROMPTS_FILE) as f:
        data = yaml.safe_load(f)

    prompts = []
    for cat, items in data.items():
        if category and cat != category:
            continue
        for item in items:
            item["category"] = cat
            prompts.append(item)
    return prompts


def is_thinking_model(port: int) -> bool:
    """Check if the model uses thinking tokens by sending a tiny probe."""
    probe = query_model(port, "Say hi.", max_tokens=512)
    # Check for reasoning_content field (llama-server) or <think> in content (mlx_lm)
    if probe.get("has_thinking"):
        return True
    resp = probe.get("response") or ""
    if "<think>" in resp:
        return True
    # If we got length-limited with empty content, likely thinking consumed all tokens
    if probe.get("finish_reason") == "length" and len(resp.strip()) == 0:
        return True
    return False


def run_eval(port: int, prompts: list[dict], think_boost: bool = True,
             server_proc=None, model_path: str = "", fmt: str = "") -> list[dict]:
    """Run all prompts and collect results."""
    is_thinker = False
    if think_boost:
        is_thinker = is_thinking_model(port)
        if is_thinker:
            print(f"  Detected thinking model — using {THINKING_TOKEN_CAP} token cap")

    results = []
    total = len(prompts)
    for i, p in enumerate(prompts, 1):
        base_tok = p.get("max_tokens", 512)
        max_tok = THINKING_TOKEN_CAP if is_thinker else base_tok
        print(f"  [{i}/{total}] {p['id']}: {p['prompt'][:60]}...")
        result = query_model(port, p["prompt"], max_tokens=max_tok)

        # If server died (connection refused), restart it and retry once
        if result.get("error") and "Connection refused" in str(result["error"]):
            if server_proc:
                print(f"    Server crashed — restarting...")
                server_proc.kill()
                server_proc.wait(timeout=10)
                time.sleep(2)
                server_proc = start_server(model_path, port, fmt)
                if wait_for_server(port):
                    print(f"    Server restarted — retrying {p['id']}...")
                    result = query_model(port, p["prompt"], max_tokens=max_tok)

        result["id"] = p["id"]
        result["category"] = p["category"]
        result["prompt"] = p["prompt"]
        result["check"] = p["check"]
        results.append(result)
        # brief pause to avoid hammering
        time.sleep(0.5)
    return results


def print_summary(results: list[dict], model_name: str):
    """Print a summary table to stdout."""
    print(f"\n{'='*70}")
    print(f"  EVAL RESULTS: {model_name}")
    print(f"{'='*70}")

    by_cat = {}
    for r in results:
        cat = r["category"]
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(r)

    total_tok_s = []
    for cat, items in by_cat.items():
        speeds = [r.get("tok_per_s", 0) for r in items if r.get("tok_per_s", 0) > 0]
        errors = sum(1 for r in items if r.get("error"))
        avg_speed = sum(speeds) / len(speeds) if speeds else 0
        total_tok_s.extend(speeds)
        print(f"\n  {cat.upper()} ({len(items)} prompts)")
        print(f"  {'─'*40}")
        for r in items:
            status = "ERR" if r.get("error") else "OK "
            tps = r.get("tok_per_s", 0)
            speed = f"{tps:6.1f} tok/s" if tps > 0 else "  --.-- tok/s"
            print(f"    {status} {r['id']}  {r['elapsed_s']:6.2f}s  {speed}")
        if errors:
            print(f"    !! {errors} error(s)")
        print(f"    avg: {avg_speed:.1f} tok/s")

    overall_avg = sum(total_tok_s) / len(total_tok_s) if total_tok_s else 0
    print(f"\n{'='*70}")
    print(f"  OVERALL: {len(results)} prompts | avg {overall_avg:.1f} tok/s")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="Factory Model Eval Runner")
    parser.add_argument("--model", type=str, help="Path to model (directory or .gguf file)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})")
    parser.add_argument("--category", type=str, help="Run only this category")
    parser.add_argument("--no-serve", action="store_true", help="Don't start a server, connect to existing one")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    parser.add_argument("--no-think-boost", action="store_true", help="Don't boost max_tokens for thinking models")
    parser.add_argument("--token-cap", type=int, default=10000, help="Max tokens for thinking models (default: 10000)")
    args = parser.parse_args()

    if not args.model and not args.no_serve:
        parser.error("--model is required unless --no-serve is used")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    prompts = load_prompts(args.category)
    if not prompts:
        print(f"No prompts found" + (f" for category '{args.category}'" if args.category else ""))
        sys.exit(1)

    print(f"Loaded {len(prompts)} prompts" + (f" (category: {args.category})" if args.category else ""))

    server_proc = None
    model_name = "external"

    if not args.no_serve:
        model_path = os.path.expanduser(args.model)
        fmt = detect_format(model_path)
        model_name = model_name_from_path(model_path)
        print(f"Model: {model_name} ({fmt})")

        server_proc = start_server(model_path, args.port, fmt)
        print(f"Waiting for server on port {args.port}...")
        if not wait_for_server(args.port):
            print("Server failed to start. Stderr:")
            if server_proc.stderr:
                print(server_proc.stderr.read().decode()[-2000:])
            server_proc.kill()
            sys.exit(1)
        print("Server ready.")

    try:
        model_path_resolved = os.path.expanduser(args.model) if args.model else ""
        fmt_resolved = detect_format(model_path_resolved) if model_path_resolved else ""
        results = run_eval(args.port, prompts, think_boost=not args.no_think_boost,
                          server_proc=server_proc, model_path=model_path_resolved, fmt=fmt_resolved)
        print_summary(results, model_name)

        # save results
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_file = RESULTS_DIR / f"{model_name}_{ts}.json"
        output = {
            "model": model_name,
            "timestamp": ts,
            "category": args.category,
            "temperature": args.temperature,
            "results": results,
        }
        with open(out_file, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Results saved to {out_file}")

    finally:
        if server_proc:
            print("Stopping server...")
            server_proc.send_signal(signal.SIGTERM)
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()


if __name__ == "__main__":
    main()
