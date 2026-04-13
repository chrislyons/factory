"""
Fetch Extended Historical Data for New Pairs
=============================================
Multiple requests to get full history (up to 5000 bars per pair).
Binance API limit is 1000 per request, so we need multiple calls
with startTime parameters.
"""
import pandas as pd
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# Pairs to fetch (excluding DOT, FTM per Chris vetoes)
PAIRS = ['ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']

# Target: ~5000 bars of 4h data = ~833 days
TARGET_BARS = 5000
BARS_PER_REQUEST = 1000
INTERVAL = '4h'
MS_PER_4H = 4 * 60 * 60 * 1000  # 14,400,000 ms


def fetch_klines(symbol, interval='4h', limit=1000, start_time=None, end_time=None):
    """Fetch klines from Binance."""
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}'
    if start_time:
        url += f'&startTime={start_time}'
    if end_time:
        url += f'&endTime={end_time}'
    
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', '30', url],
            capture_output=True, text=True, timeout=35
        )
        
        if result.returncode != 0:
            return None
        
        data = json.loads(result.stdout)
        
        if not data or isinstance(data, dict):
            return None
        
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        
        return df[['open', 'high', 'low', 'close', 'volume']]
    
    except Exception as e:
        print(f"  Error: {e}")
        return None


def fetch_full_history(symbol):
    """Fetch full history by making multiple requests."""
    print(f"\nFetching {symbol}...")
    
    all_data = []
    end_time = None
    
    for i in range(5):  # Max 5 requests = 5000 bars
        df = fetch_klines(symbol, interval=INTERVAL, limit=BARS_PER_REQUEST, end_time=end_time)
        
        if df is None or len(df) == 0:
            break
        
        all_data.append(df)
        
        # Set end_time to one ms before the earliest timestamp
        earliest = df.index.min()
        end_time = int(earliest.timestamp() * 1000) - 1
        
        print(f"  Request {i+1}: {len(df)} bars (earliest: {earliest.date()})")
        
        if len(df) < BARS_PER_REQUEST:
            break
    
    if not all_data:
        return None
    
    # Combine and deduplicate
    combined = pd.concat(all_data)
    combined = combined[~combined.index.duplicated(keep='first')]
    combined.sort_index(inplace=True)
    
    return combined


print("=" * 70)
print("FETCHING EXTENDED HISTORICAL DATA")
print("=" * 70)

for pair in PAIRS:
    # Check if we already have sufficient data
    existing_path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if existing_path.exists():
        existing = pd.read_parquet(existing_path)
        if len(existing) >= 4000:
            print(f"\n{pair}: Already have {len(existing)} bars — skipping")
            continue
    
    df = fetch_full_history(pair)
    
    if df is not None and len(df) >= 1000:
        output_path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
        df.to_parquet(output_path)
        print(f"  SAVED: {len(df)} bars to {output_path.name}")
        print(f"  Date range: {df.index.min().date()} to {df.index.max().date()}")
    else:
        if df is None:
            print(f"  FAILED: No data returned")
        else:
            print(f"  INSUFFICIENT: Only {len(df)} bars")


# Summary
print("\n" + "=" * 70)
print("DATA SUMMARY")
print("=" * 70)

print(f"\n{'Pair':<10} {'Bars':<10} {'Date Range'}")
print("-" * 50)

for pair in PAIRS:
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if path.exists():
        df = pd.read_parquet(path)
        print(f"{pair:<10} {len(df):<10} {df.index.min().date()} to {df.index.max().date()}")
    else:
        print(f"{pair:<10} {'NO DATA'}")
