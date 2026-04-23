
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88/.venv/lib/python3.11/site-packages')

import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from datetime import datetime, timezone, timedelta
import os
import re

OHLCV_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h/"

def extract_symbol(filename):
    m = re.match(r'binance_([A-Z0-9_]+)_(?:1h|60m)\.parquet', filename)
    if m:
        raw = m.group(1)
        return raw.replace("_", "")
    return None

# Get all Binance USDT/USD 1h files
files = [f for f in os.listdir(OHLCV_DIR) if f.startswith("binance_") and ("USDT" in f or "USD" in f) and f.endswith(".parquet")]
print(f"Files to process: {len(files)}")

# Analysis cutoff: 2 years ago from now
two_years_ago = datetime.now(timezone.utc) - timedelta(days=730)
print(f"2-year cutoff date: {two_years_ago.date()}")

results = []

for f in sorted(files):
    symbol = extract_symbol(f)
    if not symbol:
        continue
    
    path = os.path.join(OHLCV_DIR, f)
    try:
        # Read parquet - just the columns we need
        table = pq.read_table(path, columns=['time', 'volume', 'close'])
        df = table.to_pandas()
        
        # Convert timestamp (seconds) to datetime
        df['datetime'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df = df.set_index('datetime').sort_index()
        
        # Filter to last 2 years
        df_2y = df[df.index >= two_years_ago]
        
        if len(df_2y) < 100:  # Need at least 100 hours of data
            print(f"  SKIP {symbol}: only {len(df_2y)} bars in 2yr window")
            continue
        
        # Calculate metrics
        total_volume_usd = (df_2y['volume'] * df_2y['close']).sum()
        avg_daily_volume = total_volume_usd / (len(df_2y) / 24)  # divide by num days
        median_daily = df_2y.resample('1D').agg({'volume': 'sum', 'close': 'last'})
        median_daily_volume = (median_daily['volume'] * median_daily['close']).median()
        std_daily = (median_daily['volume'] * median_daily['close']).std()
        cv = std_daily / avg_daily_volume if avg_daily_volume > 0 else np.inf
        
        # Data span
        start_date = df_2y.index[0].date()
        end_date = df_2y.index[-1].date()
        days_covered = (df_2y.index[-1] - df_2y.index[0]).days
        
        results.append({
            'symbol': symbol,
            'file': f,
            'total_volume_usd': total_volume_usd,
            'avg_daily_volume_usd': avg_daily_volume,
            'median_daily_volume_usd': median_daily_volume,
            'volume_cv': cv,
            'bars_2yr': len(df_2y),
            'days_covered': days_covered,
            'start': start_date,
            'end': end_date,
        })
        
        print(f"  OK {symbol:15s}  AD Vol: ${avg_daily_volume:>12,.0f}  Med: ${median_daily_volume:>12,.0f}  Total: ${total_volume_usd:>15,.0f}  CV: {cv:.2f}")
        
    except Exception as e:
        print(f"  ERR {symbol}: {e}")

print(f"\nProcessed {len(results)} pairs successfully.")

if results:
    # Sort by average daily volume descending
    results.sort(key=lambda x: x['avg_daily_volume_usd'], reverse=True)
    
    print("\n" + "="*120)
    print("TOP 20 PAIRS BY AVERAGE DAILY VOLUME (2yr)")
    print("="*120)
    print(f"{'Rank':<5} {'Symbol':<12} {'Avg Daily Vol':>18} {'Med Daily Vol':>18} {'Volume CV':>10} {'Days':>6}")
    print("-"*120)
    for i, r in enumerate(results[:20], 1):
        print(f"{i:<5} {r['symbol']:<12} ${r['avg_daily_volume_usd']:>16,.0f}  ${r['median_daily_volume_usd']:>16,.0f}  {r['volume_cv']:>9.2f}  {r['days_covered']:>6d}")
    
    # Save results
    import json
    output = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'analysis_period_days': 730,
        'total_pairs_analyzed': len(results),
        'top_pairs': results[:50],
    }
    with open('/Users/nesbitt/dev/factory/agents/ig88/memory/ig88/scratchpad.md', 'a') as f:
        f.write("\n\n## Liquidity Analysis Results\n")
        f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"Total pairs analyzed: {len(results)}\n")
        f.write("Top 20 pairs:\n")
        for i, r in enumerate(results[:20], 1):
            f.write(f"  {i}. {r['symbol']}: ${r['avg_daily_volume_usd']:,.0f} avg daily\n")
