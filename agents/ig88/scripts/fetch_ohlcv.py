#!/usr/bin/env python3
"""
OHLCV Fetcher for Binance Public API
Fetch latest candles for all pairs in portfolio (from paper_scan.py PORTFOLIO dict).
Append to existing parquet files (or create new).
Support configurable interval (1m, 60m, 240m).
"""
import sys
import json
import pandas as pd
import requests
from pathlib import Path
from datetime import datetime, timezone
import time

# Paths
BASE_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88')
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Interval mapping: argument -> Binance interval, filename interval
INTERVAL_MAP = {
    '1m': {'binance': '1m', 'file': '1m'},
    '60m': {'binance': '1h', 'file': '60m'},
    '240m': {'binance': '4h', 'file': '240m'},
    '1h': {'binance': '1h', 'file': '60m'},
    '4h': {'binance': '4h', 'file': '240m'},
}

# Load portfolio from paper_scan.py
def load_portfolio():
    """Import PORTFOLIO dict from paper_scan.py"""
    sys.path.insert(0, str(BASE_DIR / 'scripts'))
    import paper_scan
    return paper_scan.PORTFOLIO

def fetch_binance_klines(symbol, interval='4h', limit=1000):
    """Fetch klines from Binance public API."""
    url = 'https://api.binance.com/api/v3/klines'
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # Convert to DataFrame
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        # Convert types
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
        df.set_index('open_time', inplace=True)
        df = df[['open', 'high', 'low', 'close', 'volume']]
        return df
    except Exception as e:
        print(f"Error fetching {symbol}: {e}", file=sys.stderr)
        return None

def get_parquet_path(pair, interval_arg):
    """Return Path for parquet file (existing or new)."""
    # Get filename interval suffix (e.g., '240m')
    file_interval = INTERVAL_MAP.get(interval_arg, {}).get('file', interval_arg)
    # Check existing patterns with both file_interval and binance interval
    binance_interval = INTERVAL_MAP.get(interval_arg, {}).get('binance', interval_arg)
    possible_intervals = list(set([file_interval, binance_interval]))
    patterns = []
    for iv in possible_intervals:
        patterns.append(f'binance_{pair}_USDT_{iv}.parquet')
        patterns.append(f'binance_{pair}USDT_{iv}.parquet')
    for pat in patterns:
        path = DATA_DIR / pat
        if path.exists():
            return path
    # Default to underscore pattern with file_interval
    return DATA_DIR / f'binance_{pair}_USDT_{file_interval}.parquet'

def ensure_tz_aware(df):
    """Ensure datetime index is UTC timezone aware."""
    if isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        elif df.index.tz != timezone.utc:
            df.index = df.index.tz_convert(timezone.utc)
    return df

def update_parquet(path, new_df):
    """Append new rows to existing parquet, deduplicate by index."""
    new_df = ensure_tz_aware(new_df)
    if path.exists():
        existing = pd.read_parquet(path)
        existing = ensure_tz_aware(existing)
        combined = pd.concat([existing, new_df])
        # Remove duplicates, keep latest
        combined = combined[~combined.index.duplicated(keep='last')]
        combined.sort_index(inplace=True)
    else:
        combined = new_df
    combined.to_parquet(path)
    return len(combined) - (len(existing) if path.exists() else 0)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fetch OHLCV data for portfolio pairs')
    parser.add_argument('--interval', default='4h', choices=list(INTERVAL_MAP.keys()),
                        help='Candle interval')
    parser.add_argument('--limit', type=int, default=1000,
                        help='Number of candles to fetch per pair')
    parser.add_argument('--pairs', nargs='+', help='Specific pairs to fetch (default: portfolio)')
    args = parser.parse_args()
    
    interval_info = INTERVAL_MAP[args.interval]
    binance_interval = interval_info['binance']
    
    portfolio = load_portfolio()
    pairs = args.pairs if args.pairs else list(portfolio.keys())
    
    total_added = 0
    errors = []
    
    for pair in pairs:
        symbol = pair + 'USDT'
        print(f"Fetching {symbol} {binance_interval}...")
        df = fetch_binance_klines(symbol, interval=binance_interval, limit=args.limit)
        if df is None:
            errors.append(pair)
            continue
        path = get_parquet_path(pair, args.interval)
        added = update_parquet(path, df)
        total_added += added
        print(f"  -> {path.name}: +{added} rows")
        # Be nice to API
        time.sleep(0.2)
    
    print(f"\nTotal new rows added: {total_added}")
    if errors:
        print(f"Failed pairs: {errors}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()