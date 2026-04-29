#!/usr/bin/env python3
"""OpenAI-compatible HTTP wrapper for flash-moe serving Ornstein3.6-35B-A3B.

Role: Deep reasoning consultant for Boot + Kelk.
Backend: flash-moe (C/Metal, streams expert ECB files from SSD).
Flash-moe split at: /Users/nesbitt/models/Ornstein3.6-35B-A3B-flash-moe-8bit
"""

import json
import re
import subprocess
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

FLASH_MOE_BIN  = "/Users/nesbitt/dev/vendor/flash-moe-gemma4/target/release/flash-moe"
MODEL_PATH     = "/Users/nesbitt/models/Ornstein3.6-35B-A3B-flash-moe-8bit"
MODEL_ID       = "Ornstein3.6-35B-A3B-8bit"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.6
DEFAULT_TOP_P = 0.9


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def format_qwen_prompt(messages):
    """Convert OpenAI messages to Qwen3.6 chat template."""
    parts = []
    system_parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "") or ""
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            parts.append(f"<|im_start|>user\n{content}<|im_end|>")
        elif role == "assistant":
            parts.append(f"<|im_start|>assistant\n{content}<|im_end|>")
        elif role == "tool":
            tool_name = msg.get("name", "tool")
            parts.append(f"<|im_start|>user\n[TOOL: {tool_name}]\n{content}<|im_end|>")
    if system_parts:
        combined_sys = "\n\n".join(system_parts)
        parts.insert(0, f"<|im_start|>system\n{combined_sys}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def run_generate(prompt, max_tokens, temperature, top_p):
    """Call flash-moe generate and return (text, None) or (None, error)."""
    cmd = [
        FLASH_MOE_BIN, "generate",
        "--model-path", MODEL_PATH,
        "--tokenizer-path", MODEL_PATH,
        "--prompt", prompt,
        "--max-tokens", str(max_tokens),
        "--temperature", str(temperature),
        "--top-p", str(top_p),
        "--no-kv-quant",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            return None, f"flash-moe error: {result.stderr[:500]}"
        stdout = result.stdout
        # Strip inline tok/s progress markers
        clean = re.sub(r"\s+\d+ tokens, [\d.]+ tok/s \(last \d+: [\d.]+ tok/s\)", "", stdout)
        # Strip "Generation: N tokens in Xs" and after
        gen_marker = clean.find("\nGeneration:")
        if gen_marker >= 0:
            clean = clean[:gen_marker]
        # Strip prefill line
        prefill_marker = clean.find("Prefill:")
        if prefill_marker >= 0:
            nl = clean.find("\n", prefill_marker)
            if nl >= 0:
                clean = clean[nl + 1:]
        return clean.strip(), None
    except subprocess.TimeoutExpired:
        return None, "flash-moe timed out after 600s"
    except Exception as e:
        return None, str(e)


class ChatHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v1/models":
            self._send_json(200, {
                "object": "list",
                "data": [{"id": MODEL_ID, "object": "model", "created": int(time.time())}]
            })
        elif self.path == "/health":
            self._send_json(200, {"status": "ok", "model": MODEL_ID})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": "not found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            request = json.loads(self.rfile.read(content_length))
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "invalid JSON"})
            return

        messages    = request.get("messages", [])
        max_tokens  = request.get("max_tokens", DEFAULT_MAX_TOKENS)
        temperature = request.get("temperature", DEFAULT_TEMPERATURE)
        top_p       = request.get("top_p", DEFAULT_TOP_P)

        if request.get("stream"):
            self._send_json(400, {"error": "streaming not supported"})
            return

        prompt, error = run_generate(
            format_qwen_prompt(messages),
            max_tokens, temperature, top_p
        )
        if error:
            self._send_json(500, {"error": error})
            return

        self._send_json(200, {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": prompt},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    def _send_json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        msg = format % args
        if "POST" in msg or "error" in msg.lower():
            print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="flash-moe Ornstein35B server")
    ap.add_argument("--port", type=int, default=41966)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    server = ThreadedHTTPServer((args.host, args.port), ChatHandler)
    print(f"flash-moe Ornstein server on http://{args.host}:{args.port}")
    print(f"  Model: {MODEL_ID}  Split: {MODEL_PATH}")
    print(f"  /v1/chat/completions  /v1/models  /health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
