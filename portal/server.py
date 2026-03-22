#!/usr/bin/env python3
"""Factory Portal task/status sidecar.

Serves live reads for /tasks.json and /status/*.json and accepts PUT writes for
the same paths. The data root is configurable so Caddy can serve the React
build from dist/ while this sidecar exposes mutable JSON from the project root.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

HOST = os.environ.get("GSD_HOST", "127.0.0.1")
PORT = int(os.environ.get("GSD_PORT", 41935))
DATA_ROOT = Path(os.environ.get("GSD_DATA_ROOT", Path(__file__).resolve().parent)).resolve()
GSD_AUTH_SECRET = os.environ.get("GSD_AUTH_SECRET")
ALLOWED_WRITE_PATHS = {"tasks.json", "jobs.json"}
ALLOWED_WRITE_DIRS = {"status"}


class PortalDataHandler(SimpleHTTPRequestHandler):
    """Serve JSON files from DATA_ROOT and allow controlled PUT writes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DATA_ROOT), **kwargs)

    def _check_auth(self) -> bool:
        if not GSD_AUTH_SECRET:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {GSD_AUTH_SECRET}":
            return True
        self.send_error(401, "Unauthorized")
        return False

    def do_GET(self) -> None:  # noqa: N802
        if not self._check_auth():
            return
        super().do_GET()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib hook name
        if not self._check_auth():
            return
        try:
            self._handle_put()
        except Exception as error:  # pragma: no cover - defensive logging
            print(f"PUT error: {error}", file=sys.stderr)
            try:
                self.send_error(500, str(error))
            except Exception:
                pass

    def _handle_put(self) -> None:
        request_path = self.path.lstrip("/")
        if not self._is_allowed_write_path(request_path):
            self.send_error(403, f"Write not allowed: {request_path}")
            return

        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self.send_error(400, "Empty body")
            return
        if length > 1_000_000:
            self.send_error(413, "Payload too large")
            return

        body = self.rfile.read(length)
        try:
            json.loads(body)
        except (json.JSONDecodeError, ValueError) as error:
            self.send_error(400, f"Invalid JSON: {error}")
            return

        file_path = (DATA_ROOT / request_path).resolve()
        if not file_path.is_relative_to(DATA_ROOT):
            self.send_error(403, "Path traversal denied")
            return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(body)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def end_headers(self) -> None:
        path = getattr(self, "path", "") or ""
        if path.endswith(".json"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        try:
            if len(args) >= 2:
                request = str(args[0])
                status = str(args[1])
                if "PUT" in request or not status.startswith("2"):
                    super().log_message(format, *args)
            else:
                super().log_message(format, *args)
        except (AttributeError, TypeError, ValueError):
            super().log_message(format, *args)

    @staticmethod
    def _is_allowed_write_path(request_path: str) -> bool:
        if request_path in ALLOWED_WRITE_PATHS:
            return True

        parts = request_path.split("/")
        return (
            len(parts) == 2
            and parts[0] in ALLOWED_WRITE_DIRS
            and parts[1].endswith(".json")
            and ".." not in request_path
        )


def main() -> None:
    os.chdir(DATA_ROOT)
    server = HTTPServer((HOST, PORT), PortalDataHandler)
    print(f"Factory Portal sidecar -> http://{HOST}:{PORT}/")
    print(f"  Serving: {DATA_ROOT}")
    print("  Writable: tasks.json, jobs.json, status/*.json")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutdown.")
        server.server_close()


if __name__ == "__main__":
    main()
