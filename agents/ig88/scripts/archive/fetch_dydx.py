"""
Fetch dYdX v4 Historical Candles
=================================
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
    'NEAR-USD', 'DOT-USD', 'FIL-USD', 'SNX-USD', 'OP-USD',
    'GRT-USD', 'IMX-USD', 'XRP-USD'
]


def fetch_candles(market, resolution='4HOURS', limit=1000):
    """Fetch candles from dYdX indexer."""
    url = f'https://indexer.dydx.trade/v4/candles/perpetualMarkets/{market}?resolution={resolution}&limit={limit}'
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            
            if 'candles' in data:
                candles = data['candles']
                
                df = pd.DataFrame(candles)
                
                # Convert types
                for col in ['open', 'high', 'low', 'close', 'baseTokenVolume', 'usdVolume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                if 'startedAt' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['startedAt'])
                    df = df.set_index('timestamp')
                    df = df.sort_index()
                
                return df
            return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


print("FETCHING dYdX v4 HISTORICAL DATA")
print("=" * 70)
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Resolution: 4H (240 minutes)")
print(f"Target pairs: {len(TARGET_PAIRS)}")

success = 0

for pair in TARGET_PAIRS:
    print(f"\n{pair}...", end=' ', flush=True)
    
    df = fetch_candles(pair, '4HOURS', 2000)
    
    if df is not None and len(df) >= 100:
        # Save to parquet
        symbol = pair.replace('-USD', '')
        outfile = DATA_DIR / f'dydx_{symbol}_USDT_240m.parquet'
        df.to_parquet(outfile)
        
        print(f"OK - {len(df)} candles")
        print(f"  Date range: {df.index[0]} to {df.index[-1]}")
        print(f"  Columns: {list(df.columns)[:5]}")
        success += 1
    else:
        print(f"FAILED (got {len(df) if df is not None else 0} candles)")
    
    time.sleep(0.5)

print(f"\n{'=' * 70}")
print(f"SUCCESS: {success}/{len(TARGET_PAIRS)} pairs fetched")
