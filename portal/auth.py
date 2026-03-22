#!/usr/bin/env python3
"""Cookie-based auth sidecar for Factory Portal.

Runs on :41912. Caddy forward_auth sends every request here.
- Valid cookie → 200 (allow)
- Missing/invalid cookie → 401 with redirect to /login
- POST /auth/login → validate u/pw, set signed cookie, redirect

Cookie: HMAC-SHA256 signed, 30-day expiry, HttpOnly + SameSite=Strict.
"""

import hashlib
import hmac
import http.server
import json
import os
import secrets
import time
import urllib.parse

import bcrypt

# ── Config ────────────────────────────────────────────────────────────
PORT = 41914
COOKIE_NAME = "factory_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days
BCRYPT_HASH = os.environ.get(
    "AUTH_BCRYPT_HASH",
    "$2a$14$EpVwjmAQzSbVuQwxr3MFhunjzx2HnUqRJBgjC8qKVC5GOb9.ypEKm",
)
AUTH_USER = os.environ.get("AUTH_USER", "nesbitt")
SECRET_KEY = os.environ.get("AUTH_SECRET", "")
if not SECRET_KEY:
    import sys
    print("FATAL: AUTH_SECRET environment variable is required. Generate with: python3 -c \"import secrets; print(secrets.token_hex(32))\"", file=sys.stderr)
    sys.exit(1)


def sign_cookie(payload: str) -> str:
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_cookie(cookie_val: str) -> bool:
    if "." not in cookie_val:
        return False
    payload, sig = cookie_val.rsplit(".", 1)
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
            return part[len(name) + 1 :]
    # Also check X-Forwarded-* headers from Caddy forward_auth
    cookie_fwd = headers.get("X-Forwarded-Cookie", "")
    for part in cookie_fwd.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part[len(name) + 1 :]
    return None


class AuthHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silent

    def do_GET(self):
        # Caddy forward_auth sends subrequests here
        cookie = get_cookie(self.headers, COOKIE_NAME)
        if cookie and verify_cookie(cookie):
            fwd_method = self.headers.get("X-Forwarded-Method", "GET")
            if fwd_method in ("POST", "PUT", "DELETE"):
                csrf_cookie = get_cookie(self.headers, "factory_csrf")
                csrf_header = self.headers.get("X-CSRF-Token", "")
                if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
                    self.send_response(403)
                    self.end_headers()
                    return
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(401)
            self.end_headers()

    def do_POST(self):
        if self.path != "/auth/login":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        params = urllib.parse.parse_qs(body)
        user = params.get("username", [""])[0]
        pw = params.get("password", [""])[0]

        redirect = params.get("redirect", ["/"])[0]
        # Sanitize redirect — only allow relative paths
        if not redirect.startswith("/") or redirect.startswith("//"):
            redirect = "/"

        if user == AUTH_USER and bcrypt.checkpw(pw.encode(), BCRYPT_HASH.encode()):
            csrf_token = generate_csrf_token()
            self.send_response(303)
            self.send_header("Set-Cookie", make_session_cookie())
            self.send_header("Set-Cookie", make_csrf_cookie(csrf_token))
            self.send_header("Location", redirect)
            self.end_headers()
        else:
            self.send_response(303)
            self.send_header("Location", f"/login?error=1&redirect={urllib.parse.quote(redirect)}")
            self.end_headers()


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", PORT), AuthHandler)
    print(f"Auth sidecar listening on 127.0.0.1:{PORT}")
    server.serve_forever()
