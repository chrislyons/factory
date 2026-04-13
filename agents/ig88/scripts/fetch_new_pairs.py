"""
Fetch Additional Pairs from Binance
=====================================
Download 4h OHLCV for new altcoins to expand the portfolio.
"""
import pandas as pd
import json
import subprocess
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# New pairs to fetch
NEW_PAIRS = ['ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']


def fetch_binance_klines(symbol, interval='4h', limit=1000):
    """Fetch klines from Binance public API using curl."""
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}'
    
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', '30', url],
            capture_output=True, text=True, timeout=35
        )
        
        if result.returncode != 0:
            print(f"  Curl error: {result.stderr}")
            return None
        
        data = json.loads(result.stdout)
        
        if not data or isinstance(data, dict):
            # Error response
            print(f"  API error: {data}")
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
        print(f"  Error fetching {symbol}: {e}")
        return None


print("=" * 60)
print("FETCHING ADDITIONAL PAIRS FROM BINANCE")
print("=" * 60)

for pair in NEW_PAIRS:
    print(f"\nFetching {pair}...")
    
    # Check if already exists
    existing = list(DATA_DIR.glob(f'binance_{pair}*_240m.parquet'))
    if existing:
        print(f"  Already exists: {existing[0].name}")
        continue
    
    df = fetch_binance_klines(pair, interval='4h', limit=1000)
    
    if df is not None and len(df) >= 500:
        output_path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
        df.to_parquet(output_path)
        print(f"  Saved: {len(df)} bars to {output_path.name}")
    else:
        if df is None:
            print(f"  FAILED: No data returned")
        else:
            print(f"  SKIPPED: Only {len(df)} bars (need 500+)")

print("\n" + "=" * 60)
print("DATA FETCH COMPLETE")
print("=" * 60)

# List all available 4h data
print("\nAvailable 4h data:")
for f in sorted(DATA_DIR.glob('*_240m.parquet')):
    df = pd.read_parquet(f)
    print(f"  {f.name}: {len(df)} bars")
