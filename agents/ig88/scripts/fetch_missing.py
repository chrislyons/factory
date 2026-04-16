#!/usr/bin/env python3
"""Fetch missing 1h OHLCV data for Hyperliquid top 30 symbols from Binance."""

import os
import time
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
BASE_URL = "https://api.binance.com/api/v3"

# Hyperliquid top 30 symbols by volume (>$1M daily)
# Map to Binance symbol where different
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
    "kPEPE": "1000PEPEUSDT",  # PEPE on Binance
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

def fetch_binance_klines(symbol, interval="1h", limit=1000, start_time=None, end_time=None):
    """Fetch klines from Binance API."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    if start_time:
        params["startTime"] = int(start_time)
    if end_time:
        params["endTime"] = int(end_time)
    
    try:
        response = requests.get(f"{BASE_URL}/klines", params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"  Error fetching {symbol}: {e}")
        return []

def fetch_all_klines(symbol, years_back=2):
    """Fetch all available klines by paginating backwards."""
    all_klines = []
    
    # Start from now and go backwards using endTime
    end_time = int(time.time() * 1000)
    
    print(f"Fetching {symbol} 1h data...")
    
    while True:
        klines = fetch_binance_klines(symbol, "1h", 1000, end_time=end_time)
        
        if not klines:
            break
        
        all_klines = klines + all_klines
        earliest = klines[0][0]
        
        print(f"  Got {len(klines)} candles, earliest: {pd.Timestamp(earliest, unit='ms').strftime('%Y-%m-%d')}")
        
        if len(klines) < 1000:
            break
        
        # Move end_time to before the earliest candle
        end_time = earliest - 1
        time.sleep(0.1)
    
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
        
        klines = fetch_all_klines(binance_symbol)
        
        if klines and len(klines) > 100:
            df = klines_to_df(klines)
            df.to_parquet(output_file)
            print(f"  Saved {len(df)} rows to {output_file.name}")
            fetched += 1
        else:
            print(f"  Failed to get data for {binance_symbol}")
            failed += 1
        
        time.sleep(0.3)
    
    print(f"\nDone: fetched={fetched}, skipped={skipped}, failed={failed}")

if __name__ == "__main__":
    main()