
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88/.venv/lib/python3.11/site-packages')

import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from datetime import datetime, timezone, timedelta
import os
import re
from collections import defaultdict

OHLCV_DIR_1H = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h/"
OHLCV_DIR_4H = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/4h/"

# Cutoff: 2 years ago
two_years_ago = datetime.now(timezone.utc) - timedelta(days=730)

def extract_symbol(filename):
    """Extract base symbol from Binance parquet filename."""
    # Patterns: binance_BTCUSDT_1h.parquet, binance_BTC_USDT_60m.parquet
    m = re.match(r'binance_([A-Z0-9_]+)_(?:1h|60m|4h|240m|1440m)\.parquet', filename)
    if m:
        raw = m.group(1)
        return raw.replace("_", "")
    return None

def load_parquet_volume(path, symbol):
    """Load OHLCV parquet and return DataFrame with datetime index and volume_usd."""
    try:
        # Try to read just needed columns
        table = pq.read_table(path, columns=['time', 'volume', 'close'])
        df = table.to_pandas()
    except Exception as e1:
        try:
            # Some files use 'timestamp' instead of 'time'
            table = pq.read_table(path, columns=['timestamp', 'volume', 'close'])
            df = table.to_pandas()
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        except Exception as e2:
            return None, f"read error: {e1}; alt: {e2}"
    
    # Determine datetime column
    if 'datetime' not in df.columns:
        if 'time' in df.columns:
            df['datetime'] = pd.to_datetime(df['time'], unit='s', utc=True)
        elif 'timestamp' in df.columns:
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        else:
            return None, "no time column found"
    
    df = df.set_index('datetime').sort_index()
    
    # Compute USD volume = volume * close
    df['volume_usd'] = df['volume'] * df['close']
    
    return df, None

def analyze_pair(symbol, filepath):
    """Analyze a single pair's volume over the last 2 years."""
    df, err = load_parquet_volume(filepath, symbol)
    if err:
        return None, f"load error: {err}"
    
    # Filter to 2-year window
    df_2y = df[df.index >= two_years_ago]
    n_bars = len(df_2y)
    
    if n_bars < 24:  # At least 1 day of data
        return None, f"insufficient data: {n_bars} bars"
    
    # Calculate daily volumes
    daily = df_2y.resample('1D').agg({'volume_usd': 'sum'}).dropna()
    n_days = len(daily)
    
    if n_days < 30:
        return None, f"insufficient days: {n_days}"
    
    total_vol = daily['volume_usd'].sum()
    avg_daily = daily['volume_usd'].mean()
    median_daily = daily['volume_usd'].median()
    std_daily = daily['volume_usd'].std()
    cv = std_daily / avg_daily if avg_daily > 0 else np.inf
    
    return {
        'symbol': symbol,
        'file': os.path.basename(filepath),
        'total_volume_usd': float(total_vol),
        'avg_daily_volume_usd': float(avg_daily),
        'median_daily_volume_usd': float(median_daily),
        'volume_cv': float(cv),
        'bars_2yr': n_bars,
        'days_covered': n_days,
        'start': df_2y.index[0].date().isoformat(),
        'end': df_2y.index[-1].date().isoformat(),
    }, None

# Collect all candidate files
candidate_files = []

# 1h directory
for f in os.listdir(OHLCV_DIR_1H):
    if f.startswith("binance_") and ("USDT" in f or "USD" in f) and f.endswith(".parquet"):
        sym = extract_symbol(f)
        if sym:
            candidate_files.append((sym, os.path.join(OHLCV_DIR_1H, f)))

# 4h directory (as fallback for pairs not in 1h)
for f in os.listdir(OHLCV_DIR_4H):
    if f.startswith("binance_") and ("USDT" in f or "USD" in f) and f.endswith(".parquet"):
        sym = extract_symbol(f)
        if sym:
            candidate_files.append((sym, os.path.join(OHLCV_DIR_4H, f)))

print(f"Total candidate files: {len(candidate_files)}")

# Process all, keeping best (most bars) per symbol
results_by_symbol = defaultdict(list)
for sym, path in candidate_files:
    result, err = analyze_pair(sym, path)
    if result:
        results_by_symbol[sym].append(result)
    else:
        print(f"  SKIP {sym}: {err}")

# Deduplicate: pick the result with most bars_2yr for each symbol
results = []
for sym, res_list in results_by_symbol.items():
    best = max(res_list, key=lambda x: x['bars_2yr'])
    results.append(best)

print(f"\nSuccessfully analyzed {len(results)} unique symbols.")

if results:
    # Sort by average daily volume
    results.sort(key=lambda x: x['avg_daily_volume_usd'], reverse=True)
    
    print("\n" + "="*115)
    print("KRAKEN LIQUIDITY ANALYSIS — TOP 25 PAIRS (2-Year Avg Daily Volume)")
    print(f"Data source: Binance OHLCV (proxy for market-wide liquidity)")
    print(f"Period: {two_years_ago.date()} to present (~730 days)")
    print("="*115)
    print(f"{'Rank':<5} {'Symbol':<12} {'Avg Daily Vol':>18} {'Med Daily Vol':>18} {'CV':>7} {'Days':>6}")
    print("-"*115)
    for i, r in enumerate(results[:25], 1):
        print(f"{i:<5} {r['symbol']:<12} ${r['avg_daily_volume_usd']:>16,.0f}  ${r['median_daily_volume_usd']:>16,.0f}  {r['volume_cv']:>6.2f}  {r['days_covered']:>6d}")
    
    # Categorize by liquidity tiers
    print("\n\nLIQUIDITY TIERS (by Average Daily Volume):")
    print("-"*60)
    tiers = [
        ("Ultra (> $500M)", lambda r: r['avg_daily_volume_usd'] >= 5e8),
        ("High ($100M-500M)", lambda r: 1e8 <= r['avg_daily_volume_usd'] < 5e8),
        ("Medium ($10M-100M)", lambda r: 1e7 <= r['avg_daily_volume_usd'] < 1e8),
        ("Low (< $10M)", lambda r: r['avg_daily_volume_usd'] < 1e7),
    ]
    
    for tier_name, predicate in tiers:
        tier_pairs = [r for r in results if predicate(r)]
        print(f"\n{tier_name}: {len(tier_pairs)} pairs")
        for r in tier_pairs:
            print(f"  {r['symbol']:<12} ${r['avg_daily_volume_usd']:>12,.0f}")

    # Save full results
    import json
    output = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'analysis_period_days': 730,
        'cutoff_date': two_years_ago.date().isoformat(),
        'total_symbols_analyzed': len(results),
        'data_source': 'Binance 1h/4h OHLCV (via cached parquet)',
        'notes': 'Liquidity proxy: average daily USD trading volume. Binance used as proxy for cross-exchange liquidity.',
        'top_25': results[:25],
        'all_pairs': results,
    }
    out_path = "/Users/nesbitt/dev/factory/agents/ig88/memory/ig88/liquidity_analysis_2yr.json"
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nFull results saved to: {out_path}")
