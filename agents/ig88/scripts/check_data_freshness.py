#!/usr/bin/env python3
"""
Data Freshness Checker
Scans all binance_*_*.parquet files in data/ directory,
reports age of most recent bar for each file,
outputs JSON to state/data_freshness.json,
exits with error code if any critical file >4h stale.
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd

# Paths
BASE_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88')
DATA_DIR = BASE_DIR / 'data'
STATE_DIR = BASE_DIR / 'state'
STATE_DIR.mkdir(parents=True, exist_ok=True)
FRESHNESS_FILE = STATE_DIR / 'data_freshness.json'

# Threshold for staleness (hours)
STALE_THRESHOLD_HOURS = 4

def get_file_age_hours(parquet_path):
    """Read parquet file, return age of most recent bar in hours."""
    try:
        df = pd.read_parquet(parquet_path)
        if df.empty:
            return None, None, "empty file"
        # Expect index named 'open_time' or column 'open_time'
        if df.index.name == 'open_time':
            last_ts = df.index[-1]
        elif 'open_time' in df.columns:
            last_ts = df['open_time'].iloc[-1]
        else:
            # Fallback: assume index is datetime
            last_ts = df.index[-1]
        # Ensure timezone aware (UTC)
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = now - last_ts
        age_hours = age.total_seconds() / 3600
        return last_ts.isoformat(), age_hours, None
    except Exception as e:
        return None, None, str(e)

def main():
    results = []
    stale_files = []
    
    # Find all parquet files matching binance pattern
    parquet_files = list(DATA_DIR.glob('binance_*_*.parquet'))
    parquet_files += list(DATA_DIR.glob('binance_*USDT_*.parquet'))
    # deduplicate
    parquet_files = list(set(parquet_files))
    parquet_files.sort()
    
    for path in parquet_files:
        last_timestamp, age_hours, error = get_file_age_hours(path)
        file_result = {
            'file': path.name,
            'last_timestamp': last_timestamp,
            'age_hours': round(age_hours, 2) if age_hours is not None else None,
            'error': error,
            'stale': age_hours is not None and age_hours > STALE_THRESHOLD_HOURS
        }
        results.append(file_result)
        if file_result['stale']:
            stale_files.append(path.name)
        if error:
            print(f"ERROR reading {path.name}: {error}", file=sys.stderr)
    
    # Write JSON output
    output = {
        'scan_time': datetime.now(timezone.utc).isoformat(),
        'threshold_hours': STALE_THRESHOLD_HOURS,
        'total_files': len(results),
        'stale_count': len(stale_files),
        'stale_files': stale_files,
        'files': results
    }
    
    with open(FRESHNESS_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Print summary
    print(f"Scanned {len(results)} parquet files.")
    if stale_files:
        print(f"WARNING: {len(stale_files)} files older than {STALE_THRESHOLD_HOURS}h:")
        for name in stale_files:
            print(f"  - {name}")
        sys.exit(1)
    else:
        print("All files are fresh.")
        sys.exit(0)

if __name__ == '__main__':
    main()