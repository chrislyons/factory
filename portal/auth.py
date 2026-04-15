#!/usr/bin/env python3
"""Cookie-based auth sidecar for Factory Portal.

Runs on :41914. Validates session cookies and proxies data API calls to GSD (:41911).
- GET /auth/check       → 200 if valid cookie, 401 otherwise
- GET /auth/validate    → 200 if valid cookie, 401 otherwise (forward_auth compat)
- POST /auth/login      → JSON response with Set-Cookie (no redirect)
- GET/PUT /jobs.json    → validate cookie, proxy to GSD :41911
- GET /tasks.json       → validate cookie, proxy to GSD :41911
- GET /status/*         → validate cookie, proxy to GSD :41911

Cookie: HMAC-SHA256 signed, 30-day expiry, HttpOnly + SameSite=Strict.
"""

import hashlib
import hmac
import http.client
import http.server
import json
import os
import secrets
import time
import urllib.parse

import bcrypt

# ── Config ────────────────────────────────────────────────────────────
PORT = 41914
GSD_PORT = 41911
COOKIE_NAME = "factory_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days
BCRYPT_HASH = os.environ.get("AUTH_BCRYPT_HASH", "")
if not BCRYPT_HASH:
    import sys
    print("FATAL: AUTH_BCRYPT_HASH environment variable is required.", file=sys.stderr)
    sys.exit(1)
AUTH_USER = os.environ.get("AUTH_USER", "nesbitt")
SECRET_KEY = os.environ.get("AUTH_SECRET", "")
if not SECRET_KEY:
    import sys
    print("FATAL: AUTH_SECRET environment variable is required. Generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\"", file=sys.stderr)
    sys.exit(1)

DATA_PATHS = ("/jobs.json", "/tasks.json")
CONFIG_API_PATHS = ("/api/config",)


def sign_cookie(payload: str) -> str:
    import base64
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{encoded}.{sig}"


def verify_cookie(cookie_val: str) -> bool:
    import base64
    if "." not in cookie_val:
        return False
    encoded, sig = cookie_val.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(encoded.encode()).decode()
    except Exception:
        return False
    expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(payload)
        return data.get("exp", 0) > time.time()
    except (json.JSONDecodeError, TypeError):
        return False


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


def make_csrf_cookie(token: str) -> str:
    return (
        f"factory_csrf={token}; "
        f"Path=/; "
        f"Max-Age={COOKIE_MAX_AGE}; "
        f"SameSite=Strict"
    )


def make_session_cookie() -> str:
    payload = json.dumps({"user": AUTH_USER, "exp": int(time.time() + COOKIE_MAX_AGE)})
    signed = sign_cookie(payload)
    return (
        f"{COOKIE_NAME}={signed}; "
        f"Path=/; "
        f"Max-Age={COOKIE_MAX_AGE}; "
        f"HttpOnly; "
        f"SameSite=Strict"
    )


def get_cookie(headers, name):
    cookie_header = headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part[len(name) + 1:]
    return None


class AuthHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silent

    def proxy_to_gsd(self, path):
        """Forward a validated request to GSD sidecar and stream response back."""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else None
        forward_headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "connection", "transfer-encoding")
        }
        conn = http.client.HTTPConnection("127.0.0.1", GSD_PORT, timeout=10)
        conn.request(self.command, path, body=body, headers=forward_headers)
        r = conn.getresponse()
        resp_body = r.read()
        self.send_response(r.status)
        for h, v in r.getheaders():
            if h.lower() not in ("transfer-encoding", "connection"):
                self.send_header(h, v)
        self.end_headers()
        self.wfile.write(resp_body)

    def _cookie_valid(self):
        cookie = get_cookie(self.headers, COOKIE_NAME)
        return cookie and verify_cookie(cookie)

    def _check_csrf(self):
        csrf_cookie = get_cookie(self.headers, "factory_csrf")
        csrf_header = self.headers.get("X-CSRF-Token", "")
        return csrf_cookie and csrf_header and hmac.compare_digest(csrf_cookie, csrf_header)

    def do_GET(self):
        # Auth check endpoint (client-side session verification)
        if self.path in ("/auth/check", "/auth/validate"):
            if self._cookie_valid():
                self.send_response(200)
                self.end_headers()
            else:
                self.send_response(401)
                self.end_headers()
            return

        # Config API — validate cookie then forward to GSD
        if self.path.startswith(CONFIG_API_PATHS):
            if self._cookie_valid():
                self.proxy_to_gsd(self.path)
            else:
                self.send_response(401)
                self.end_headers()
            return

        # Data proxy paths — validate cookie then forward to GSD
        if self.path.startswith(DATA_PATHS) or self.path.startswith("/status/"):
            if self._cookie_valid():
                self.proxy_to_gsd(self.path)
            else:
                self.send_response(401)
                self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def do_PUT(self):
        if self.path.startswith(DATA_PATHS) or self.path.startswith("/status/"):
            if self._cookie_valid() and self._check_csrf():
                self.proxy_to_gsd(self.path)
            elif not self._cookie_valid():
                self.send_response(401)
                self.end_headers()
            else:
                self.send_response(403)
                self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/auth/login":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in content_type:
                d = json.loads(body.decode())
                user = d.get("username", "")
                pw = d.get("password", "")
                redirect = d.get("redirect", "/")
            else:
                params = urllib.parse.parse_qs(body.decode())
                user = params.get("username", [""])[0]
                pw = params.get("password", [""])[0]
                redirect = params.get("redirect", ["/"])[0]

            if not redirect.startswith("/") or redirect.startswith("//"):
                redirect = "/"

            if user == AUTH_USER and bcrypt.checkpw(pw.encode(), BCRYPT_HASH.encode()):
                csrf_token = generate_csrf_token()
                resp = json.dumps({"ok": True, "redirect": redirect}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.send_header("Set-Cookie", make_session_cookie())
                self.send_header("Set-Cookie", make_csrf_cookie(csrf_token))
                self.end_headers()
                self.wfile.write(resp)
            else:
                resp = json.dumps({"ok": False, "error": "invalid_credentials"}).encode()
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            return

        # Config API POST (restart gateways etc.)
        if self.path.startswith(CONFIG_API_PATHS):
            if self._cookie_valid() and self._check_csrf():
                self.proxy_to_gsd(self.path)
            elif not self._cookie_valid():
                self.send_response(401)
                self.end_headers()
            else:
                self.send_response(403)
                self.end_headers()
            return

        # Data proxy POST paths
        if self.path.startswith(DATA_PATHS) or self.path.startswith("/status/"):
            if self._cookie_valid() and self._check_csrf():
                self.proxy_to_gsd(self.path)
            elif not self._cookie_valid():
                self.send_response(401)
                self.end_headers()
            else:
                self.send_response(403)
                self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def do_PATCH(self):
        """Handle PATCH requests for config API."""
        if self.path.startswith(CONFIG_API_PATHS):
            if self._cookie_valid() and self._check_csrf():
                self.proxy_to_gsd(self.path)
            elif not self._cookie_valid():
                self.send_response(401)
                self.end_headers()
            else:
                self.send_response(403)
                self.end_headers()
            return
        self.send_response(404)
        self.end_headers()


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", PORT), AuthHandler)
    print(f"Auth sidecar listening on 127.0.0.1:{PORT}")
    server.serve_forever()
