#!/usr/bin/env python3
"""
Test scanner on historical period where signals were expected.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88')
DATA_DIR = BASE_DIR / 'data'

def load_data(pair):
    for suffix in ['binance_{pair}_USDT_240m.parquet', 'binance_{pair}USDT_240m.parquet']:
        path = DATA_DIR / suffix.format(pair=pair)
        if path.exists():
            return pd.read_parquet(path)
    return None

def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_upper = sma20 + std20 * 2
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio

# Test parameters from scanner.py for SUI
PAIR_PARAMS = {
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3},
}
# Also test with paper_scan thresholds
PAPER_PARAMS = {
    'SUI': {'rsi': 18, 'bb': 0.05, 'vol': 1.2},
    'OP': {'rsi': 25, 'bb': 0.15, 'vol': 1.2},  # Not in paper portfolio
}

def find_bar_by_timestamp(df, target_timestamp):
    """Find index of bar with timestamp closest to target."""
    # Assuming df has datetime index or column 'timestamp'
    if 'timestamp' in df.columns:
        ts = pd.to_datetime(df['timestamp'], unit='s')
        idx = (ts - target_timestamp).abs().argmin()
        return idx
    else:
        # index is datetime
        idx = (df.index - target_timestamp).abs().argmin()
        return idx

def test_pair(pair, target_timestamp, params, label):
    df = load_data(pair)
    if df is None:
        print(f"No data for {pair}")
        return
    print(f"\n--- Testing {pair} ({label}) ---")
    print(f"Target timestamp: {target_timestamp}")
    
    # Find bar index
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        idx = (df['timestamp'] - target_timestamp).abs().idxmin()
    else:
        idx = (df.index - target_timestamp).abs().idxmin()
    
    print(f"Closest bar index: {idx}")
    
    # Compute indicators
    c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
    
    # Get bar values
    close = c[idx]
    rsi_val = rsi[idx]
    bb_val = bb_pct[idx]
    vol_val = vol_ratio[idx]
    atr_val = atr[idx]
    atr_pct = atr_val / close * 100 if close > 0 else 0
    
    # Compute BB lower band using params['bb'] std
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20[idx] - std20[idx] * params['bb']
    bb_upper = sma20[idx] + std20[idx] * params['bb']
    bb_position = (close - bb_lower) / std20[idx] if std20[idx] > 0 else 0
    bb_pct_custom = (close - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0
    
    print(f"Close: {close:.4f}")
    print(f"RSI: {rsi_val:.1f} (threshold {params['rsi']})")
    print(f"BB% (2σ): {bb_val:.3f}")
    print(f"BB% ({params['bb']}σ): {bb_pct_custom:.3f}")
    print(f"BB position (z-score): {bb_position:.2f}")
    print(f"BB lower ({params['bb']}σ): {bb_lower:.4f}")
    print(f"Volume ratio: {vol_val:.2f} (threshold {params['vol']})")
    print(f"ATR%: {atr_pct:.2f}%")
    
    # Check scanner.py conditions: price < bb_lower
    cond_rsi = rsi_val < params['rsi']
    cond_bb = close < bb_lower  # price below lower band
    cond_vol = vol_val > params['vol']
    signal = cond_rsi and cond_bb and cond_vol
    print(f"\nScanner.py conditions:")
    print(f"  RSI < {params['rsi']}: {cond_rsi}")
    print(f"  Price < BB lower ({params['bb']}σ): {cond_bb}")
    print(f"  Volume > {params['vol']}: {cond_vol}")
    print(f"  SIGNAL: {signal}")
    
    # Check paper_scan conditions: BB% < threshold
    cond_bb_pct = bb_pct_custom < params['bb']
    signal2 = cond_rsi and cond_bb_pct and cond_vol
    print(f"\nPaper_scan conditions (BB% threshold):")
    print(f"  RSI < {params['rsi']}: {cond_rsi}")
    print(f"  BB% < {params['bb']}: {cond_bb_pct}")
    print(f"  Volume > {params['vol']}: {cond_vol}")
    print(f"  SIGNAL: {signal2}")

if __name__ == "__main__":
    # Test with known signal timestamps from mr_signals.jsonl
    # SOL signal 2026-03-16T12:00:00+00:00 (short)
    # Let's test SUI and OP with their timestamps (need to find)
    # For now, test with a recent date
    target = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
    
    # Test SUI with scanner.py params
    test_pair('SUI', target, PAIR_PARAMS['SUI'], 'scanner.py params')
    # Test SUI with paper_scan params
    test_pair('SUI', target, PAPER_PARAMS['SUI'], 'paper_scan params')
    
    # Test OP (if data exists)
    try:
        test_pair('OP', target, PAIR_PARAMS['OP'], 'scanner.py params')
    except:
        print("\nOP data not found.")