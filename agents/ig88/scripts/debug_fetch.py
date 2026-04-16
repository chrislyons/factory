#!/usr/bin/env python3
"""Debug Binance API fetching."""

import requests
import time
import pandas as pd

BASE_URL = "https://api.binance.com/api/v3"

def fetch_binance_klines(symbol, interval="1h", limit=1000, start_time=None):
    """Fetch klines from Binance API."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    if start_time:
        params["startTime"] = int(start_time)
    
    print(f"  Params: {params}")
    
    try:
        response = requests.get(f"{BASE_URL}/klines", params=params, timeout=30)
        print(f"  Status: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        print(f"  Got {len(data)} klines")
        return data
    except Exception as e:
        print(f"  Error: {e}")
        return []

# Test
print("Testing BTCUSDT fetch...")
klines = fetch_binance_klines("BTCUSDT", "1h", 5)
if klines:
    print(f"First timestamp: {klines[0][0]}")
    print(f"Last timestamp: {klines[-1][0]}")