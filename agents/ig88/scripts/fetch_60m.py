"""
Fetch 1h Data for All Target Pairs
===================================
"""
import urllib.request
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import time

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

TARGET_PAIRS = [
    'AAVE', 'ADA', 'ALGO', 'ARB', 'ATOM', 'AVAX', 'DOT', 'FIL',
    'GRT', 'IMX', 'INJ', 'LINK', 'LTC', 'MATIC', 'NEAR', 'OP',
    'POL', 'SOL', 'SNX', 'SUI', 'UNI', 'XRP'
]


def fetch_binance_klines(symbol, interval='1h', limit=5000):
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
        return None


print("FETCHING 1H DATA")
print("=" * 60)

for pair in TARGET_PAIRS:
    outfile = DATA_DIR / f'binance_{pair}_USDT_60m.parquet'
    
    if outfile.exists():
        df = pd.read_parquet(outfile)
        if len(df) > 3000:
            print(f"{pair}: EXISTS ({len(df)} bars)")
            continue
    
    print(f"{pair}...", end=' ', flush=True)
    df = fetch_binance_klines(pair, '1h', 5000)
    
    if df is not None:
        print(f"got {len(df)} bars", end=' ')
        if len(df) >= 500:
            df.to_parquet(outfile)
            print(f"OK")
        else:
            print(f"(too few)")
    else:
        print(f"FAILED (None)")
    
    time.sleep(1.0)

print("\n60m DATA AVAILABLE:")
for f in sorted(DATA_DIR.glob('binance_*_USDT_60m.parquet')):
    df = pd.read_parquet(f)
    pair = f.name.replace('binance_', '').replace('_USDT_60m.parquet', '')
    if pair in TARGET_PAIRS:
        print(f"  {pair}: {len(df)} bars")
