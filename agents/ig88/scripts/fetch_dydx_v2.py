#!/usr/bin/env python3
"""Fetch dYdX v4 historical data via curl."""
import subprocess
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import time

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
TARGETS = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'AVAX-USD', 'ARB-USD',
           'LINK-USD', 'UNI-USD', 'MATIC-USD', 'ATOM-USD', 'AAVE-USD',
           'SUI-USD', 'INJ-USD', 'ADA-USD', 'ALGO-USD', 'LTC-USD',
           'NEAR-USD', 'DOT-USD', 'FIL-USD']

print("FETCHING dYdX v4 DATA")
print("=" * 60)
success = 0

for market in TARGETS:
    url = f'https://indexer.dydx.trade/v4/candles/perpetualMarkets/{market}?resolution=4HOURS&limit=2000'
    
    try:
        result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        
        if 'candles' in data and len(data['candles']) >= 100:
            df = pd.DataFrame(data['candles'])
            
            for col in ['open', 'high', 'low', 'close', 'usdVolume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df['timestamp'] = pd.to_datetime(df['startedAt'])
            df = df.set_index('timestamp').sort_index()
            
            symbol = market.replace('-USD', '')
            outfile = DATA_DIR / f'dydx_{symbol}_USDT_240m.parquet'
            df[['open', 'high', 'low', 'close', 'usdVolume']].to_parquet(outfile)
            
            print(f"{symbol}: {len(df)} candles OK")
            success += 1
        else:
            print(f"{market}: FAILED")
    except Exception as e:
        print(f"{market}: ERROR - {e}")
    
    time.sleep(0.3)

print(f"\nSUCCESS: {success}/{len(TARGETS)}")
