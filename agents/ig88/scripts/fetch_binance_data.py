#!/usr/bin/env python3
import os
import glob
import pandas as pd
import requests
import time
from datetime import datetime, timedelta

# Configuration
DATA_DIR = '/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h/'
TARGET_BARS = 17520  # 2 years of hourly data
INTERVAL = '1h'
BINANCE_API = 'https://api.binance.com/api/v3/klines'

# Target symbols
SYMBOLS = ['RENDERUSDT', 'OPUSDT', 'WLDUSDT', 'SUIUSDT', 'ARBUSDT', 'INJUSDT', 'AAVEUSDT', 'FILUSDT']

def fetch_binance_klines(symbol, interval='1h', start_time=None, end_time=None, limit=1000):
    """Fetch klines from Binance API"""
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    if start_time:
        params['startTime'] = int(start_time * 1000)  # Convert to milliseconds
    if end_time:
        params['endTime'] = int(end_time * 1000)
    
    try:
        resp = requests.get(BINANCE_API, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and 'code' in data:
            print(f"  API Error for {symbol}: {data}")
            return []
        return data
    except Exception as e:
        print(f"  Request error for {symbol}: {e}")
        return []

def fetch_full_history(symbol, interval='1h', target_bars=TARGET_BARS):
    """Fetch full history with pagination, going backwards from now"""
    all_klines = []
    end_time = int(time.time())  # Current timestamp in seconds
    
    print(f"  Fetching {symbol} (target: {target_bars} bars)...")
    
    while len(all_klines) < target_bars:
        klines = fetch_binance_klines(symbol, interval, end_time=end_time, limit=1000)
        
        if not klines:
            print(f"    No more data available for {symbol}")
            break
            
        all_klines = klines + all_klines  # Prepend because we're going backwards
        print(f"    Fetched {len(klines)} bars, total: {len(all_klines)}")
        
        if len(klines) < 1000:
            # No more data available
            print(f"    Reached end of available data for {symbol}")
            break
            
        # Update end_time to the timestamp of the first candle in this batch minus 1 second
        # klines[0][0] is open time in milliseconds
        end_time = klines[0][0] / 1000 - 1  # Convert to seconds and subtract 1 second
        
        # Be nice to the API
        time.sleep(0.1)
    
    return all_klines[:target_bars]  # Return only the requested number of bars

def klines_to_dataframe(klines):
    """Convert Binance klines to DataFrame with required columns"""
    if not klines:
        return pd.DataFrame()
    
    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    
    # Convert types
    df['time'] = df['open_time'] // 1000  # Convert to seconds
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    
    # Set datetime index
    df['datetime'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('datetime', inplace=True)
    
    # Keep only needed columns
    df = df[['time', 'open', 'high', 'low', 'close', 'volume']]
    
    return df

def load_existing_data(symbol):
    """Try to load existing data for symbol from any parquet file"""
    # Search for files containing the symbol
    pattern = os.path.join(DATA_DIR, f'*{symbol}*.parquet')
    files = glob.glob(pattern)
    
    if not files:
        # Try with underscore variants (e.g., SUI_USDT)
        underscore_symbol = symbol.replace('USDT', '_USDT')
        pattern = os.path.join(DATA_DIR, f'*{underscore_symbol}*.parquet')
        files = glob.glob(pattern)
    
    if not files:
        return None
    
    # Use the first matching file
    filepath = files[0]
    print(f"  Found existing file: {os.path.basename(filepath)}")
    
    try:
        df = pd.read_parquet(filepath)
        return df
    except Exception as e:
        print(f"  Error reading {filepath}: {e}")
        return None

def convert_to_standard_format(df):
    """Convert various dataframe formats to standard format with time, open, high, low, close, volume"""
    if df is None or len(df) == 0:
        return pd.DataFrame()
    
    # Check if already has required columns
    required_cols = ['time', 'open', 'high', 'low', 'close', 'volume']
    if all(col in df.columns for col in required_cols):
        # Already in correct format
        return df[required_cols]
    
    # If has timestamp index, convert to time column
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        # Convert datetime index to Unix timestamp in seconds
        # The index is datetime64[ms], so convert to int64 (milliseconds) then divide by 1000
        df['time'] = df.index.astype('int64') // 1000  # Convert milliseconds to seconds
        # Keep only required columns if they exist
        cols_to_keep = []
        for col in required_cols:
            if col in df.columns:
                cols_to_keep.append(col)
        if 'time' not in cols_to_keep:
            cols_to_keep.append('time')
        return df[cols_to_keep]
    
    # If has timestamp column (not index)
    if 'timestamp' in df.columns:
        df = df.copy()
        df['time'] = pd.to_datetime(df['timestamp']).astype('int64') // 1000  # Convert to seconds
        return df[['time', 'open', 'high', 'low', 'close', 'volume']]
    
    print("  Warning: Could not determine format, returning as-is")
    return df

def get_symbol_with_enough_history(symbol):
    """For RENDERUSDT, check if we need to use RNDRUSDT instead"""
    if symbol != 'RENDERUSDT':
        return symbol
    
    print("  Checking RENDERUSDT vs RNDRUSDT...")
    
    # Get earliest data for both
    def get_earliest_timestamp(sym):
        start_time = 1483228800000  # 2017-01-01
        params = {
            'symbol': sym,
            'interval': '1h',
            'startTime': start_time,
            'limit': 1
        }
        try:
            resp = requests.get(BINANCE_API, params=params, timeout=10)
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0][0]
        except:
            pass
        return None
    
    render_start = get_earliest_timestamp('RENDERUSDT')
    rndr_start = get_earliest_timestamp('RNDRUSDT')
    
    now_ms = int(time.time() * 1000)
    
    if render_start:
        render_hours = (now_ms - render_start) / (1000 * 3600)
        print(f"    RENDERUSDT: {render_hours:.0f} hours available")
    else:
        render_hours = 0
        print(f"    RENDERUSDT: not available")
    
    if rndr_start:
        rndr_hours = (now_ms - rndr_start) / (1000 * 3600)
        print(f"    RNDRUSDT: {rndr_hours:.0f} hours available")
    else:
        rndr_hours = 0
        print(f"    RNDRUSDT: not available")
    
    # Choose the one with more history
    if rndr_hours > render_hours and rndr_hours >= TARGET_BARS:
        print(f"  Using RNDRUSDT (more history)")
        return 'RNDRUSDT'
    elif render_hours >= TARGET_BARS:
        print(f"  Using RENDERUSDT")
        return 'RENDERUSDT'
    elif rndr_hours > 0:
        print(f"  Using RNDRUSDT (RENDERUSDT insufficient)")
        return 'RNDRUSDT'
    else:
        print(f"  Warning: Neither has enough data, trying RENDERUSDT anyway")
        return 'RENDERUSDT'

def main():
    print("Fetching Binance historical 1h OHLCV data")
    print("=" * 50)
    
    for symbol in SYMBOLS:
        print(f"\nProcessing {symbol}:")
        
        # Special handling for RENDERUSDT
        actual_symbol = get_symbol_with_enough_history(symbol)
        
        # Try to load existing data first
        existing_df = load_existing_data(actual_symbol)
        
        if existing_df is not None and len(existing_df) >= TARGET_BARS:
            print(f"  Existing data has {len(existing_df)} rows (>= {TARGET_BARS})")
            # Convert to standard format
            df = convert_to_standard_format(existing_df)
        else:
            # Fetch from API
            if existing_df is not None:
                print(f"  Existing data has only {len(existing_df)} rows (< {TARGET_BARS}), fetching more...")
            else:
                print(f"  No existing data found, fetching from API...")
            
            klines = fetch_full_history(actual_symbol, INTERVAL, TARGET_BARS)
            if not klines:
                print(f"  ERROR: Failed to fetch data for {actual_symbol}")
                continue
            
            df = klines_to_dataframe(klines)
        
        # Save to parquet with required naming pattern
        output_filename = f"binance_{actual_symbol}_60m.parquet"
        output_path = os.path.join(DATA_DIR, output_filename)
        
        # Ensure we have enough data
        if len(df) < TARGET_BARS:
            print(f"  WARNING: Only {len(df)} rows available (target: {TARGET_BARS})")
        
        df.to_parquet(output_path)
        print(f"  Saved {len(df)} rows to {output_filename}")
        
        # Show date range
        if len(df) > 0:
            start_dt = datetime.fromtimestamp(df['time'].min())
            end_dt = datetime.fromtimestamp(df['time'].max())
            print(f"  Date range: {start_dt} to {end_dt}")

if __name__ == '__main__':
    main()