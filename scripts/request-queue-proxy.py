#!/usr/bin/env python3
"""Request queue proxy — serializes concurrent requests to mlx_lm.server.

Uses a threading lock to ensure only one request hits the backend at a time.
mlx_lm.server crashes on concurrent METAL compute. This proxy fixes that.

Usage: python3 request-queue-proxy.py [--listen 41961] [--backend http://127.0.0.1:41966]
"""
import http.server, json, threading, urllib.request, sys, argparse

_lock = threading.Lock()
_backend = "http://127.0.0.1:41966"

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()

    def _proxy(self):
        with _lock:
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else None
                req = urllib.request.Request(
                    f"{_backend}{self.path}",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method=self.command,
                )
                with urllib.request.urlopen(req, timeout=600) as resp:
                    data = resp.read()
                    self.send_response(resp.status)
                    for h in ["Content-Type", "X-Request-Id"]:
                        v = resp.getheader(h)
                        if v:
                            self.send_header(h, v)
                    self.end_headers()
                    self.wfile.write(data)
            except Exception as e:
                try:
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
                except:
                    pass

def main():
    global _backend
    p = argparse.ArgumentParser()
    p.add_argument("--listen", type=int, default=41961)
    p.add_argument("--backend", default="http://127.0.0.1:41966")
    args = p.parse_args()
    _backend = args.backend

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.listen), Handler)
    server.daemon_threads = True
    print(f"Queue proxy: :{args.listen} -> {_backend}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
