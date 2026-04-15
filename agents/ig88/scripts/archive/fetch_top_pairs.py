"""
Fetch Top 30 Binance USDT Pairs
=================================
Download 4h OHLCV for top pairs by volume.
"""
import urllib.request
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import time

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# Top pairs by volume (excluding stablecoins, leveraged tokens)
TARGET_PAIRS = [
    'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'DOGE', 'AVAX',
    'DOT', 'LINK', 'MATIC', 'TRX', 'UNI', 'LTC', 'AAVE',
    'ARB', 'OP', 'ATOM', 'NEAR', 'APT', 'FIL', 'INJ', 'SUI',
    'STX', 'IMX', 'RUNE', 'LDO', 'MKR', 'SNX', 'GRT', 'ALGO', 'VET'
]


def fetch_binance_klines(symbol, interval='4h', limit=5000):
    """Fetch klines from Binance public API."""
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval={interval}&limit={limit}'
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
                df[col] = df[col].astype(float)
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.set_index('timestamp')
            
            return df[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades']]
    except Exception as e:
        print(f"  Error: {e}")
        return None


print("=" * 80)
print("FETCHING TOP BINANCE PAIRS")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

successful = []
failed = []

for pair in TARGET_PAIRS:
    if pair in successful:
        continue
    
    print(f"{pair}USDT...", end=' ', flush=True)
    
    existing_file = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if existing_file.exists():
        existing = pd.read_parquet(existing_file)
        if len(existing) > 4000:
            print(f"EXISTS ({len(existing)} bars)")
            successful.append(pair)
            continue
    
    df = fetch_binance_klines(pair)
    
    if df is not None and len(df) > 500:
        df.to_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')
        print(f"OK ({len(df)} bars)")
        successful.append(pair)
    else:
        print(f"FAILED ({len(df) if df is not None else 0} bars)")
        failed.append(pair)
    
    time.sleep(0.3)

print(f"\n{'=' * 80}")
print(f"SUCCESSFUL: {len(successful)} pairs")
print(f"FAILED: {', '.join(failed) if failed else 'none'}")

print(f"\nAVAILABLE 240m DATA:")
for f in sorted(DATA_DIR.glob('binance_*_USDT_240m.parquet')):
    df = pd.read_parquet(f)
    pair = f.name.replace('binance_', '').replace('_USDT_240m.parquet', '')
    print(f"  {pair}: {len(df)} bars")
