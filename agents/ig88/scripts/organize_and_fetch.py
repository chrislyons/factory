#!/usr/bin/env python3
"""
Organize existing data and fetch new OHLCV data from Hyperliquid and Binance.
"""

import os
import json
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
BASE_URL = "https://api.binance.com/api/v3"

# Hyperliquid API for market data
HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"

def fetch_hyperliquid_symbols():
    """Fetch top 30 Hyperliquid symbols by 24h volume."""
    try:
        # Get all mids and meta
        payload = {"type": "metaAndAssetCtxs"}
        response = requests.post(HYPERLIQUID_API, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if not data or len(data) < 2:
            print("Warning: Unexpected Hyperliquid API response")
            return []
        
        meta = data[0]
        ctx = data[1]
        
        symbols_info = []
        for i, (asset, context) in enumerate(zip(meta["universe"], ctx)):
            name = asset["name"]
            try:
                daily_volume = float(context.get("dayNtlVlm") or 0)
            except (ValueError, TypeError):
                daily_volume = 0
            
            try:
                mark_px = float(context.get("markPx") or 0)
            except (ValueError, TypeError):
                mark_px = 0
            
            try:
                mid_px = float(context.get("midPx") or 0)
            except (ValueError, TypeError):
                mid_px = 0
            
            symbols_info.append({
                "symbol": name,
                "daily_volume": daily_volume,
                "mark_px": mark_px,
                "mid_px": mid_px,
            })
        
        # Sort by volume descending and take top 30
        symbols_info.sort(key=lambda x: x["daily_volume"], reverse=True)
        top_30 = symbols_info[:30]
        
        # Filter for >$1M daily volume
        high_volume = [s for s in top_30 if s["daily_volume"] > 1_000_000]
        
        print(f"Found {len(symbols_info)} Hyperliquid symbols")
        print(f"Top 30 by volume:")
        for i, s in enumerate(top_30[:30], 1):
            vol_m = s["daily_volume"] / 1_000_000
            print(f"  {i:2d}. {s['symbol']:10s} ${vol_m:>8.2f}M")
        
        return [s["symbol"] for s in high_volume]
    
    except Exception as e:
        print(f"Error fetching Hyperliquid symbols: {e}")
        return []


def fetch_binance_klines(symbol, interval="1h", limit=1000, start_time=None):
    """Fetch klines from Binance API."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    if start_time:
        params["startTime"] = int(start_time * 1000)
    
    try:
        response = requests.get(f"{BASE_URL}/klines", params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching {symbol} {interval}: {e}")
        return []


def fetch_all_binance_klines(symbol, interval="1h", years_back=3):
    """Fetch all available klines by paginating backwards."""
    all_klines = []
    
    # Start from now and go backwards
    end_time = int(time.time() * 1000)
    start_ts = int((datetime.now() - timedelta(days=years_back*365)).timestamp() * 1000)
    
    print(f"Fetching {symbol} {interval} data (up to {years_back} years)...")
    
    while True:
        klines = fetch_binance_klines(symbol, interval, limit=1000, start_time=end_time/1000)
        
        if not klines:
            break
        
        all_klines = klines + all_klines
        
        # Get the earliest timestamp
        earliest = klines[0][0]
        
        print(f"  Fetched {len(klines)} candles, earliest: {datetime.fromtimestamp(earliest/1000).strftime('%Y-%m-%d')}")
        
        # If we've gone back far enough or no more data
        if earliest <= start_ts or len(klines) < 1000:
            break
        
        # Move end_time back
        end_time = earliest - 1
        
        # Rate limiting
        time.sleep(0.1)
    
    return all_klines


def klines_to_dataframe(klines):
    """Convert Binance klines to pandas DataFrame."""
    if not klines:
        return pd.DataFrame()
    
    df = pd.DataFrame(klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    
    numeric_cols = ["open", "high", "low", "close", "volume", "quote_volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df = df[["timestamp", "open", "high", "low", "close", "volume", "quote_volume", "trades"]]
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    return df


def get_timeframe_from_filename(filename):
    """Extract timeframe from filename patterns."""
    # Patterns: _60m, _240m, _1440m, _15m, _120m, _resampled
    patterns = {
        r"_15m": "15m",
        r"_60m": "1h",
        r"_120m": "2h",
        r"_240m": "4h",
        r"_1440m": "1d",
        r"_resampled": "resampled",
    }
    
    for pattern, tf in patterns.items():
        if re.search(pattern, filename, re.IGNORECASE):
            return tf
    
    return None


def organize_existing_files():
    """Move existing parquet files into organized subdirectories."""
    moved_count = 0
    
    for file_path in DATA_DIR.glob("*.parquet"):
        if file_path.is_file():
            timeframe = get_timeframe_from_filename(file_path.name)
            
            if timeframe == "15m":
                dest = DATA_DIR / "ohlcv" / "15m" / file_path.name
            elif timeframe == "1h":
                dest = DATA_DIR / "ohlcv" / "1h" / file_path.name
            elif timeframe == "4h":
                dest = DATA_DIR / "ohlcv" / "4h" / file_path.name
            else:
                # Keep daily, resampled, and unknown in 1h for now
                dest = DATA_DIR / "ohlcv" / "1h" / file_path.name
            
            try:
                shutil.move(str(file_path), str(dest))
                moved_count += 1
            except Exception as e:
                print(f"Error moving {file_path.name}: {e}")
    
    print(f"Organized {moved_count} parquet files")


def fetch_binance_symbol(symbol, base_asset):
    """Fetch 1h data for a Binance symbol."""
    output_file = DATA_DIR / "ohlcv" / "1h" / f"binance_{symbol}_1h.parquet"
    
    if output_file.exists():
        print(f"  {symbol} already exists, skipping")
        return True
    
    # Try USDT pair first, then USD
    for quote in ["USDT", "USD"]:
        pair = f"{base_asset}{quote}"
        
        klines = fetch_all_binance_klines(pair, interval="1h", years_back=3)
        
        if klines and len(klines) > 100:
            df = klines_to_dataframe(klines)
            df.to_parquet(output_file, index=False)
            print(f"  Saved {len(df)} rows for {pair}")
            return True
        
        time.sleep(0.2)
    
    return False


def fetch_missing_symbols():
    """Fetch top 30 Hyperliquid symbols that we don't have."""
    print("\n=== Fetching Hyperliquid top 30 symbols ===")
    hl_symbols = fetch_hyperliquid_symbols()
    
    if not hl_symbols:
        print("No Hyperliquid symbols fetched")
        return
    
    # Map Hyperliquid symbols to Binance equivalents
    symbol_mapping = {
        "BTC": "BTC",
        "ETH": "ETH",
        "SOL": "SOL",
        "DOGE": "DOGE",
        "XRP": "XRP",
        "LINK": "LINK",
        "AVAX": "AVAX",
        "ARB": "ARB",
        "SUI": "SUI",
        "APT": "APT",
        "NEAR": "NEAR",
        "DOT": "DOT",
        "MATIC": "POL",  # MATIC rebranded to POL
        "UNI": "UNI",
        "AAVE": "AAVE",
        "LDO": "LDO",
        "OP": "OP",
        "INJ": "INJ",
        "SEI": "SEI",
        "TIA": "TIA",
        "WIF": "WIF",
        "BONK": "BONK",
        "PEPE": "PEPE",
        "W": "W",
        "ORDI": "ORDI",
        "PYTH": "PYTH",
        "JUP": "JUP",
        "RENDER": "RENDER",
        "FIL": "FIL",
        "RUNE": "RUNE",
        "FET": "FET",
        "GRT": "GRT",
        "ALGO": "ALGO",
        "IMX": "IMX",
        "ADA": "ADA",
        "TRX": "TRX",
        "LTC": "LTC",
        "MKR": "MKR",
        "SNX": "SNX",
        "BNB": "BNB",
        "STX": "STX",
        "VET": "VET",
        "ATOM": "ATOM",
    }
    
    print("\n=== Fetching Binance 1h data ===")
    fetched = 0
    failed = 0
    
    for hl_symbol in hl_symbols:
        binance_symbol = symbol_mapping.get(hl_symbol, hl_symbol)
        
        if fetch_binance_symbol(hl_symbol, binance_symbol):
            fetched += 1
        else:
            failed += 1
            print(f"  Failed to fetch {hl_symbol}")
        
        time.sleep(0.3)
    
    print(f"\nFetched {fetched} symbols, failed {failed}")


def get_time_range(df):
    """Get min and max timestamps from DataFrame (handles both index and column)."""
    if "timestamp" in df.columns:
        return df["timestamp"].min(), df["timestamp"].max()
    elif isinstance(df.index, pd.DatetimeIndex):
        return df.index.min(), df.index.max()
    else:
        # Try to find any datetime column
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                return df[col].min(), df[col].max()
        return None, None


def create_manifest():
    """Create manifest.json with all available data."""
    manifest = {
        "created_at": datetime.now().isoformat(),
        "data": {
            "1h": [],
            "4h": [],
            "15m": [],
            "1d": [],
            "other": [],
        }
    }
    
    timeframe_dirs = {
        "1h": DATA_DIR / "ohlcv" / "1h",
        "4h": DATA_DIR / "ohlcv" / "4h",
        "15m": DATA_DIR / "ohlcv" / "15m",
    }
    
    for tf, dir_path in timeframe_dirs.items():
        if not dir_path.exists():
            continue
        
        for file_path in sorted(dir_path.glob("*.parquet")):
            try:
                df = pd.read_parquet(file_path)
                
                if len(df) == 0:
                    continue
                
                # Extract symbol from filename
                name = file_path.stem
                # Remove prefix and timeframe suffix
                symbol = re.sub(r"^binance_", "", name)
                symbol = re.sub(r"_\d+m$|_resampled$", "", symbol)
                
                min_date, max_date = get_time_range(df)
                
                entry = {
                    "file": str(file_path.relative_to(DATA_DIR)),
                    "symbol": symbol,
                    "timeframe": tf,
                    "rows": len(df),
                    "start_date": min_date.isoformat() if pd.notna(min_date) else None,
                    "end_date": max_date.isoformat() if pd.notna(max_date) else None,
                    "file_size_kb": file_path.stat().st_size / 1024,
                }
                
                manifest["data"][tf].append(entry)
                
            except Exception as e:
                print(f"Error reading {file_path.name}: {e}")
    
    # Also check root for any remaining parquet files
    for file_path in sorted(DATA_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(file_path)
            if len(df) == 0:
                continue
            
            name = file_path.stem
            symbol = re.sub(r"^binance_", "", name)
            
            # Detect timeframe
            tf = get_timeframe_from_filename(name) or "unknown"
            
            min_date, max_date = get_time_range(df)
            
            entry = {
                "file": str(file_path.relative_to(DATA_DIR)),
                "symbol": symbol,
                "timeframe": tf,
                "rows": len(df),
                "start_date": min_date.isoformat() if pd.notna(min_date) else None,
                "end_date": max_date.isoformat() if pd.notna(max_date) else None,
                "file_size_kb": file_path.stat().st_size / 1024,
            }
            
            manifest["data"]["other"].append(entry)
            
        except Exception as e:
            print(f"Error reading {file_path.name}: {e}")
    
    # Summary
    total_files = sum(len(v) for v in manifest["data"].values())
    total_rows = sum(
        sum(e.get("rows", 0) for e in entries)
        for entries in manifest["data"].values()
    )
    
    manifest["summary"] = {
        "total_files": total_files,
        "total_rows": total_rows,
        "by_timeframe": {
            tf: len(entries) for tf, entries in manifest["data"].items()
        }
    }
    
    manifest_path = DATA_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    
    print(f"\n=== Manifest Summary ===")
    print(f"Total files: {total_files}")
    print(f"Total rows: {total_rows:,}")
    for tf, count in manifest["summary"]["by_timeframe"].items():
        if count > 0:
            print(f"  {tf}: {count} files")
    
    return manifest


def main():
    print("=== Organizing and Fetching Market Data ===\n")
    
    # Step 1: Organize existing files
    print("Step 1: Organizing existing parquet files...")
    organize_existing_files()
    
    # Step 2: Fetch missing symbols from Hyperliquid
    print("\nStep 2: Fetching data for Hyperliquid top 30...")
    fetch_missing_symbols()
    
    # Step 3: Create manifest
    print("\nStep 3: Creating manifest.json...")
    create_manifest()
    
    print("\n=== Done ===")


if __name__ == "__main__":
    main()