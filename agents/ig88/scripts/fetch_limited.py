#!/usr/bin/env python3
"""Fetch 1h OHLCV data for Hyperliquid top 30 symbols from Binance (limited to 2 years)."""

import os
import time
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
BASE_URL = "https://api.binance.com/api/v3"

# Hyperliquid top 30 symbols by volume (>$1M daily)
SYMBOL_MAP = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "HYPE": None,  # Not on Binance
    "SOL": "SOLUSDT",
    "ZEC": "ZECUSDT",
    "XRP": "XRPUSDT",
    "FARTCOIN": None,  # Not on Binance
    "AAVE": "AAVEUSDT",
    "TAO": "TAOUSDT",
    "LIT": "LITUSDT",
    "kPEPE": "PEPEUSDT",
    "MON": None,  # Not on Binance
    "SUI": "SUIUSDT",
    "DOGE": "DOGEUSDT",
    "ENA": "ENAUSDT",
    "BIO": "BIOUSDT",
    "PUMP": None,  # Not on Binance
    "NEAR": "NEARUSDT",
    "XPL": None,  # Not on Binance
    "WLFI": None,  # Not on Binance
    "WLD": "WLDUSDT",
    "VVV": None,  # Not on Binance
    "PAXG": "PAXGUSDT",
    "LINK": "LINKUSDT",
    "BNB": "BNBUSDT",
    "ARB": "ARBUSDT",
    "PENGU": "PENGUUSDT",
    "ADA": "ADAUSDT",
    "TRUMP": "TRUMPUSDT",
    "XMR": "XMRUSDT",
}

def fetch_binance_klines(symbol, interval="1h", limit=1000, end_time=None):
    """Fetch klines from Binance API."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    if end_time:
        params["endTime"] = int(end_time)
    
    try:
        response = requests.get(f"{BASE_URL}/klines", params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"  Error: {e}")
        return []

def fetch_klines_limited(symbol, max_batches=18):
    """Fetch klines with limited pagination (18 batches = ~18000 candles = ~2 years)."""
    all_klines = []
    end_time = int(time.time() * 1000)
    
    print(f"Fetching {symbol} 1h data (max {max_batches} batches)...")
    
    for batch in range(max_batches):
        klines = fetch_binance_klines(symbol, "1h", 1000, end_time)
        
        if not klines:
            print(f"  Batch {batch+1}: no data")
            break
        
        all_klines = klines + all_klines
        earliest = klines[0][0]
        latest = klines[-1][0]
        
        print(f"  Batch {batch+1}: {len(klines)} candles, {pd.Timestamp(earliest, unit='ms').strftime('%Y-%m-%d')} to {pd.Timestamp(latest, unit='ms').strftime('%Y-%m-%d')}")
        
        if len(klines) < 1000:
            break
        
        # Move end_time to before the earliest candle
        end_time = earliest - 1
        time.sleep(0.15)
    
    return all_klines

def klines_to_df(klines):
    """Convert Binance klines to DataFrame."""
    if not klines:
        return pd.DataFrame()
    
    df = pd.DataFrame(klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.set_index("timestamp")
    
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df["trades"] = pd.to_numeric(df["trades"], errors="coerce").astype(int)
    
    return df[["open", "high", "low", "close", "volume", "quote_volume", "trades"]]

def main():
    fetched = 0
    skipped = 0
    failed = 0
    
    for hl_symbol, binance_symbol in SYMBOL_MAP.items():
        if binance_symbol is None:
            print(f"Skipping {hl_symbol} (not on Binance)")
            skipped += 1
            continue
        
        # Check if we already have this file
        output_file = DATA_DIR / f"binance_{binance_symbol}_1h.parquet"
        if output_file.exists():
            print(f"Skipping {hl_symbol} ({binance_symbol}) - already exists")
            skipped += 1
            continue
        
        klines = fetch_klines_limited(binance_symbol, max_batches=18)
        
        if klines and len(klines) > 100:
            df = klines_to_df(klines)
            df.to_parquet(output_file)
            print(f"  Saved {len(df)} rows to {output_file.name}")
            fetched += 1
        else:
            print(f"  Failed: got {len(klines) if klines else 0} candles")
            failed += 1
        
        time.sleep(0.3)
    
    print(f"\nDone: fetched={fetched}, skipped={skipped}, failed={failed}")

if __name__ == "__main__":
    main()