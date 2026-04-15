#!/usr/bin/env python3
"""Debug dYdX fetch."""
import subprocess
import json

market = 'BTC-USD'
url = f'https://indexer.dydx.trade/v4/candles/perpetualMarkets/{market}?resolution=4HOURS&limit=3'

print(f"URL: {url}")
print(f"Type of market: {type(market)}")
print(f"URL bytes: {url.encode()}")

result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)

print(f"\nReturn code: {result.returncode}")
print(f"Stdout length: {len(result.stdout)}")
print(f"Stdout: {result.stdout[:200]}")
print(f"Stderr: {result.stderr}")

try:
    data = json.loads(result.stdout)
    print(f"\nParsed OK, keys: {list(data.keys())}")
    print(f"Candles: {len(data.get('candles', []))}")
except Exception as e:
    print(f"\nJSON parse error: {e}")
