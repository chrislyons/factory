#!/usr/bin/env python3
"""Kraken auth test — run via:
bash -c '/Users/nesbitt/dev/factory/scripts/infisical-env.sh ig88 -- /Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3 /Users/nesbitt/dev/factory/agents/ig88/scripts/test_kraken_auth.py'
"""
import os, hashlib, hmac, base64, urllib.request, urllib.parse, time, json

key = os.environ.get("KRAKEN_API_KEY", "MISSING")
secret = os.environ.get("KRAKEN_API_SECRET", "MISSING")

print(f"key present: {key != 'MISSING'}, len={len(key)}")
print(f"secret present: {secret != 'MISSING'}, len={len(secret)}")
print(f"key hex prefix: {key.encode().hex()[:20]}")

nonce = str(int(time.time() * 1000))
data = urllib.parse.urlencode({"nonce": nonce})
msg = b"/0/private/Balance" + hashlib.sha256((nonce + data).encode()).digest()
decoded_secret = base64.b64decode(secret)
sig = base64.b64encode(hmac.new(decoded_secret, msg, hashlib.sha512).digest()).decode()

req = urllib.request.Request(
    "https://api.kraken.com/0/private/Balance",
    data=data.encode(),
    headers={"API-Key": key, "API-Sign": sig, "Content-Type": "application/x-www-form-urlencoded"},
)
resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
print(f"result: {resp}")
