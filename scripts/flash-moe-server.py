"""Thin OpenAI-compatible HTTP wrapper for flash-moe CLI.

Serves /v1/chat/completions and /v1/models on the configured port.
Calls flash-moe generate as a subprocess per request.
"""
import json
import subprocess
import time
import uuid
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

FLASH_MOE_BIN = "/Users/nesbitt/dev/vendor/flash-moe-gemma4/target/release/flash-moe"
MODEL_PATH = "/Users/nesbitt/models/gemma-4-26b-a4b-it-6bit-split"
TOKENIZER_PATH = MODEL_PATH
MODEL_ID = "gemma-4-26b-a4b-it-6bit"

# Default generation params
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.9


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def format_prompt(messages):
    """Convert OpenAI messages to a single prompt string using Gemma 4 chat format."""
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"<start_of_turn>system\n{content}<end_of_turn>")
        elif role == "user":
            parts.append(f"<start_of_turn>user\n{content}<end_of_turn>")
        elif role == "assistant":
            parts.append(f"<start_of_turn>model\n{content}<end_of_turn>")
    # Add the model turn start for generation
    parts.append("<start_of_turn>model\n")
    return "\n".join(parts)


def run_generate(prompt, max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE, top_p=DEFAULT_TOP_P):
    """Call flash-moe generate and return the generated text."""
    cmd = [
        FLASH_MOE_BIN, "generate",
        "--model-path", MODEL_PATH,
        "--tokenizer-path", TOKENIZER_PATH,
        "--prompt", prompt,
        "--max-tokens", str(max_tokens),
        "--temperature", str(temperature),
        "--top-p", str(top_p),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return None, f"flash-moe error: {result.stderr[:500]}"

        # Parse output — flash-moe prints loading info to stderr,
        # generated text mixed with progress to stdout.
        # The actual generated text is between "Engine ready." and the perf breakdown.
        stdout = result.stdout
        stderr = result.stderr

        # The generated text appears after the prefill line in stdout
        # Remove progress markers like " 10 tokens, 5.1 tok/s (last 10: 5.1 tok/s)"
        import re
        # Strip inline progress reports
        clean = re.sub(r'\s+\d+ tokens, [\d.]+ tok/s \(last \d+: [\d.]+ tok/s\)', '', stdout)
        # Strip the "Generation: N tokens in..." line and everything after
        gen_marker = clean.find("\nGeneration:")
        if gen_marker >= 0:
            clean = clean[:gen_marker]
        # Strip prefill line
        prefill_marker = clean.find("Prefill:")
        if prefill_marker >= 0:
            newline = clean.find("\n", prefill_marker)
            if newline >= 0:
                clean = clean[newline + 1:]

        return clean.strip(), None
    except subprocess.TimeoutExpired:
        return None, "flash-moe timed out after 300s"
    except Exception as e:
        return None, str(e)


class ChatHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v1/models":
            response = {
                "object": "list",
                "data": [{
                    "id": MODEL_ID,
                    "object": "model",
                    "created": int(time.time()),
                }]
            }
            self._send_json(200, response)
        elif self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        messages = request.get("messages", [])
        max_tokens = request.get("max_tokens", DEFAULT_MAX_TOKENS)
        temperature = request.get("temperature", DEFAULT_TEMPERATURE)
        top_p = request.get("top_p", DEFAULT_TOP_P)

        prompt = format_prompt(messages)
        text, error = run_generate(prompt, max_tokens, temperature, top_p)

        if error:
            self._send_json(500, {"error": error})
            return

        response = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        self._send_json(200, response)

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
    parser = argparse.ArgumentParser(description="flash-moe OpenAI-compatible server")
    parser.add_argument("--port", type=int, default=41966)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadedHTTPServer((args.host, args.port), ChatHandler)
    print(f"flash-moe server on http://{args.host}:{args.port}")
    print(f"  Model: {MODEL_ID}")
    print(f"  /v1/chat/completions — OpenAI-compatible")
    print(f"  /v1/models — model listing")
    print(f"  /health — health check")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
