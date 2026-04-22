#!/usr/bin/env python3
"""
Download 60m Binance data for pairs that need re-downloading.
Truncated files have only 500-1000 bars instead of 40K+.
"""
import requests
import pandas as pd
import os
import time
from datetime import datetime

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"
os.makedirs(DATA_DIR, exist_ok=True)

BASE = "https://api.binance.com"
INTERVAL = "1h"
LIMIT = 1000  # max per request

# Pairs to download/refresh
PAIRS = [
    "DOTUSDT", "DOGEUSDT", "MATICUSDT", "ALGOUSDT", "UNIUSDT",
    "APTUSDT", "RNDRUSDT", "RENDERUSDT",
    "INJUSDT", "SUIUSDT", "FILUSDT", "AAVEUSDT",
    "ARBUSDT", "OPUSDT", "WLDUSDT", "TAOUSDT",
    "TRUMPUSDT", "PEPEUSDT", "PENGUUSDT", "XRPUSDT",
    "LTCUSDT", "ATOMUSDT", "BNBUSDT", "BIOUSDT",
    "ENAUSDT", "XMRUSDT", "ZECUSDT",
]

def fetch_all_klines(symbol, interval="1h"):
    """Fetch all historical klines using pagination."""
    all_candles = []
    start_time = 0  # start from earliest

    while True:
        url = f"{BASE}/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_time,
            "limit": LIMIT,
        }
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ERROR at {len(all_candles)} candles: {e}")
            break

        if not data:
            break

        for k in data:
            all_candles.append({
                "time": k[0] // 1000,  # ms to seconds
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })

        # Next batch starts after last candle
        start_time = data[-1][0] + 1

        if len(data) < LIMIT:
            break

        # Rate limit
        time.sleep(0.1)

    return all_candles

def main():
    for pair in PAIRS:
        fname = f"binance_{pair}_60m.parquet"
        fpath = os.path.join(DATA_DIR, fname)

        # Check existing
        if os.path.exists(fpath):
            existing = pd.read_parquet(fpath)
            if len(existing) > 30000:
                print(f"  {pair}: already {len(existing)} bars — SKIP")
                continue
            else:
                print(f"  {pair}: truncated ({len(existing)} bars) — re-downloading...")
        else:
            print(f"  {pair}: downloading...")

        candles = fetch_all_klines(pair)
        if not candles:
            print(f"  {pair}: NO DATA from Binance")
            continue

        df = pd.DataFrame(candles)
        df.index = pd.to_datetime(df['time'], unit='s')
        df.to_parquet(fpath)
        print(f"  {pair}: saved {len(df)} bars ({df.index[0].date()} to {df.index[-1].date()})")
        time.sleep(0.2)

    print("\nDone. Verifying:")
    for pair in PAIRS:
        fname = f"binance_{pair}_60m.parquet"
        fpath = os.path.join(DATA_DIR, fname)
        if os.path.exists(fpath):
            df = pd.read_parquet(fpath)
            status = "OK" if len(df) > 30000 else "SHORT"
            print(f"  {pair}: {len(df)} bars [{status}]")

if __name__ == "__main__":
    main()
