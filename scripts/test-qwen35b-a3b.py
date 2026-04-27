#!/usr/bin/env python3
"""Test Qwen3.6-35B-A3B loading and basic inference via mlx-vlm.

Usage:
    python3 scripts/test-qwen35b-a3b.py [--port 41988] [--benchmark]
"""
import argparse
import subprocess
import sys
import time
import json
import os

MLX_VLM_PYTHON = "/Users/nesbitt/dev/vendor/mlx-vlm/.venv/bin/python3"
MODEL_ID = "mlx-community/Qwen3.6-35B-A3B-6bit"
TEST_PORT = 41988

def test_load():
    """Test that the model can be loaded without OOM."""
    print("=== Test: Model Loading ===")
    start = time.time()
    result = subprocess.run(
        [MLX_VLM_PYTHON, "-c", f"""
import time
start = time.time()
from mlx_vlm.utils import load_model
print("Loading model...")
model, processor = load_model("{MODEL_ID}")
elapsed = time.time() - start
print(f"Model loaded in {{elapsed:.1f}}s")
import mlx.core as mx
# Check memory
mem = mx.metal.get_active_memory() / 1024**3
print(f"Metal active memory: {{mem:.2f}} GB")
"""],
        capture_output=True, text=True, timeout=300
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-500:])
    elapsed = time.time() - start
    print(f"Total time: {elapsed:.1f}s")
    return result.returncode == 0


def test_server(port=TEST_PORT):
    """Start the server and test a simple inference."""
    print(f"\n=== Test: Server on :{port} ===")
    
    # Start server in background
    server_cmd = [
        MLX_VLM_PYTHON, "-m", "mlx_vlm.server",
        "--model", MODEL_ID,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--prefill-step-size", "2048",
    ]
    print(f"Starting: {' '.join(server_cmd)}")
    server = subprocess.Popen(
        server_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    
    # Wait for server to start
    print("Waiting for server to be ready...")
    for i in range(120):  # 2 minute timeout
        time.sleep(1)
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models")
            if resp.status == 200:
                print(f"Server ready after {i+1}s")
                break
        except:
            pass
    else:
        print("Server failed to start in 120s")
        server.terminate()
        return False
    
    # Test inference
    print("\n=== Test: Inference ===")
    start = time.time()
    import urllib.request
    payload = json.dumps({
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": "Say hello in exactly 5 words."}],
        "max_tokens": 50,
        "temperature": 0.0,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read())
    elapsed = time.time() - start
    
    content = result["choices"][0]["message"]["content"]
    usage = result.get("usage", {})
    print(f"Response: {content[:200]}")
    print(f"Time: {elapsed:.1f}s")
    print(f"Usage: {usage}")
    
    # Stop server
    server.terminate()
    server.wait(timeout=10)
    print("\nServer stopped.")
    return True


def benchmark(port=TEST_PORT):
    """Run a simple benchmark at different context lengths."""
    print(f"\n=== Benchmark ===")
    # This would need the server running and test at various context lengths
    # For now, just a placeholder
    print("Benchmark not yet implemented — run after initial test passes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=TEST_PORT)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--load-only", action="store_true", help="Only test loading, skip server")
    args = parser.parse_args()
    
    if args.load_only:
        ok = test_load()
        sys.exit(0 if ok else 1)
    
    ok = test_load()
    if not ok:
        print("FAIL: Model loading failed")
        sys.exit(1)
    
    ok = test_server(args.port)
    if not ok:
        print("FAIL: Server test failed")
        sys.exit(1)
    
    if args.benchmark:
        benchmark(args.port)
    
    print("\nAll tests passed.")
