#!/usr/bin/env python3
"""
Parquet Data Validation Script
Checks OHLC sanity, detects gaps, duplicate timestamps.
"""
import sys
import pandas as pd
from pathlib import Path
from datetime import timedelta

# Paths
BASE_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88')
DATA_DIR = BASE_DIR / 'data'

def validate_file(path):
    """Validate a single parquet file. Return list of issues."""
    issues = []
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        return [f"Failed to read: {e}"]
    
    if df.empty:
        return ["Empty dataframe"]
    
    # Ensure index is datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'open_time' in df.columns:
            df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
            df.set_index('open_time', inplace=True)
        else:
            return ["Index is not datetime and no open_time column"]
    
    # Sort by time
    df.sort_index(inplace=True)
    
    # 1. Duplicate timestamps
    dup = df.index.duplicated()
    if dup.any():
        dup_count = dup.sum()
        issues.append(f"Duplicate timestamps: {dup_count}")
    
    # 2. OHLC sanity
    # high >= low, open/close within range
    invalid_high_low = df['high'] < df['low']
    if invalid_high_low.any():
        count = invalid_high_low.sum()
        issues.append(f"High < Low violations: {count}")
    
    invalid_open = (df['open'] > df['high']) | (df['open'] < df['low'])
    if invalid_open.any():
        count = invalid_open.sum()
        issues.append(f"Open outside High-Low range: {count}")
    
    invalid_close = (df['close'] > df['high']) | (df['close'] < df['low'])
    if invalid_close.any():
        count = invalid_close.sum()
        issues.append(f"Close outside High-Low range: {count}")
    
    # 3. Gaps in time series (assuming regular intervals)
    if len(df) > 1:
        freq = pd.infer_freq(df.index)
        if freq is None:
            # If we can't infer frequency, compute median diff
            diffs = df.index.to_series().diff().dt.total_seconds()
            median_diff = diffs.median()
            if median_diff > 0:
                expected_freq = timedelta(seconds=median_diff)
                # Find gaps where difference > expected * 1.5
                gap_mask = diffs > median_diff * 1.5
                gap_count = gap_mask.sum()
                if gap_count > 0:
                    issues.append(f"Potential gaps detected: {gap_count} (median interval {median_diff}s)")
        # else we have a regular frequency, we could check for missing periods but keep simple
    
    # 4. Negative volumes
    if 'volume' in df.columns:
        neg_vol = df['volume'] < 0
        if neg_vol.any():
            count = neg_vol.sum()
            issues.append(f"Negative volume: {count}")
    
    return issues

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Validate parquet files')
    parser.add_argument('files', nargs='*', help='Specific files to validate (default: all binance_*_*.parquet)')
    parser.add_argument('--output', help='Write report to file')
    args = parser.parse_args()
    
    if args.files:
        files = [Path(f) for f in args.files]
    else:
        files = list(DATA_DIR.glob('binance_*_*.parquet'))
        files += list(DATA_DIR.glob('binance_*USDT_*.parquet'))
        files = list(set(files))
        files.sort()
    
    report_lines = []
    total_issues = 0
    files_with_issues = 0
    
    for path in files:
        issues = validate_file(path)
        if issues:
            files_with_issues += 1
            total_issues += len(issues)
            report_lines.append(f"--- {path.name} ---")
            for issue in issues:
                report_lines.append(f"  {issue}")
    
    report_lines.append(f"\nSummary: {len(files)} files, {files_with_issues} with issues, {total_issues} total issues.")
    report = "\n".join(report_lines)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
    else:
        print(report)
    
    if total_issues > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == '__main__':
    main()