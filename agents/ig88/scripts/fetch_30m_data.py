#!/usr/bin/env python3
"""
Fetch native 30m OHLCV data from Binance for walk-forward validation.
Binance API limit: 1000 candles per request, ~500 days of 30m data per batch.
Need to paginate for full history.
"""

import json
import time
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/30m")
DATA_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["ETHUSDT", "AVAXUSDT", "SOLUSDT", "LINKUSDT", "NEARUSDT"]
BINANCE_BASE = "https://api.binance.com"
LIMIT = 1000  # Max per request


def fetch_klines_paginated(symbol: str, interval: str = "30m", max_batches: int = 50) -> pd.DataFrame:
    """Fetch all available 30m klines with pagination."""
    all_candles = []
    end_time = None  # Start from most recent

    for batch in range(max_batches):
        url = f"{BINANCE_BASE}/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": LIMIT,
        }
        if end_time is not None:
            params["endTime"] = end_time

        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            break

        all_candles = data + all_candles  # Prepend (going backwards in time)
        oldest_time = data[0][0]
        end_time = oldest_time - 1  # Next batch ends just before this one

        print(f"  Batch {batch+1}: {len(data)} candles, oldest = {datetime.fromtimestamp(oldest_time/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}")

        if len(data) < LIMIT:
            break

        time.sleep(0.2)  # Rate limit

    # Convert to DataFrame
    rows = []
    for k in all_candles:
        rows.append({
            "time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df = df.sort_values("time").reset_index(drop=True)
    return df


# === MAIN ===
print("=== Fetching Native 30m OHLCV from Binance ===\n")

for symbol in SYMBOLS:
    asset = symbol.replace("USDT", "")
    outfile = DATA_DIR / f"binance_{symbol}_30m.parquet"

    if outfile.exists():
        existing = pd.read_parquet(outfile)
        print(f"{asset}: already have {len(existing)} bars ({outfile.name})")
        continue

    print(f"\n{asset}: fetching...")
    try:
        df = fetch_klines_paginated(symbol, "30m")
        print(f"  Total: {len(df)} bars ({len(df)/48:.0f} days)")
        print(f"  Range: {df['time'].iloc[0]} to {df['time'].iloc[-1]}")
        df.to_parquet(outfile, index=False)
        print(f"  Saved: {outfile}")
    except Exception as e:
        print(f"  ERROR: {e}")

print("\nDone.")
