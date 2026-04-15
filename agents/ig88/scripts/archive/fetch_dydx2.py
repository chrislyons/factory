"""
Fetch dYdX v4 Historical Candles - Fixed Version
"""
import urllib.request
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import time

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

TARGET_PAIRS = [
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'AVAX-USD', 'ARB-USD',
    'LINK-USD', 'UNI-USD', 'MATIC-USD', 'ATOM-USD', 'AAVE-USD',
    'SUI-USD', 'INJ-USD', 'ADA-USD', 'ALGO-USD', 'LTC-USD',
    'NEAR-USD', 'DOT-USD', 'FIL-USD'
]


def fetch_candles(market, resolution='4HOURS', limit=1000):
    """Fetch candles from dYdX indexer."""
    url = f'https://indexer.dydx.trade/v4/candles/perpetualMarkets/{market}?resolution={resolution}&limit={limit}'
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Accept': 'application/json',
            'Accept-Encoding': 'identity'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode('utf-8')
            data = json.loads(raw)
            
            if 'candles' in data and data['candles']:
                candles = data['candles']
                
                df = pd.DataFrame(candles)
                
                # Convert types
                for col in ['open', 'high', 'low', 'close', 'usdVolume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                if 'startedAt' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['startedAt'])
                    df = df.set_index('timestamp')
                    df = df.sort_index()
                
                # Keep only OHLCV columns
                cols = ['open', 'high', 'low', 'close', 'usdVolume']
                cols = [c for c in cols if c in df.columns]
                return df[cols]
            return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


print("FETCHING dYdX v4 HISTORICAL DATA")
print("=" * 70)
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

success = 0

for pair in TARGET_PAIRS:
    print(f"{pair}...", end=' ', flush=True)
    
    df = fetch_candles(pair, '4HOURS', 2000)
    
    if df is not None and len(df) >= 100:
        symbol = pair.replace('-USD', '')
        outfile = DATA_DIR / f'dydx_{symbol}_USDT_240m.parquet'
        df.to_parquet(outfile)
        
        print(f"OK - {len(df)} candles")
        success += 1
    else:
        print(f"FAILED")
    
    time.sleep(0.3)

print(f"\nSUCCESS: {success}/{len(TARGET_PAIRS)} pairs fetched")
