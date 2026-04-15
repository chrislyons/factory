#!/usr/bin/env python3
"""
Backtest scanner over historical data to see if signals would have been generated.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import json

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

# Thresholds
SCANNER_THRESHOLDS = {
    'SUI': {'rsi': 30, 'bb': 1.0, 'vol': 1.8},
    'OP': {'rsi': 25, 'bb': 1.0, 'vol': 1.3},
}
PAPER_THRESHOLDS = {
    'ARB': {'rsi': 18, 'bb': 0.10, 'vol': 1.2},
    'SUI': {'rsi': 18, 'bb': 0.05, 'vol': 1.2},
    'AVAX': {'rsi': 20, 'bb': 0.15, 'vol': 1.2},
    'MATIC': {'rsi': 25, 'bb': 0.15, 'vol': 1.8},
    'UNI': {'rsi': 22, 'bb': 0.10, 'vol': 1.8},
    'ALGO': {'rsi': 25, 'bb': 0.20, 'vol': 1.2},
    'ATOM': {'rsi': 20, 'bb': 0.05, 'vol': 1.2},
    'ADA': {'rsi': 25, 'bb': 0.05, 'vol': 1.2},
    'INJ': {'rsi': 20, 'bb': 0.05, 'vol': 1.5},
    'LINK': {'rsi': 18, 'bb': 0.05, 'vol': 1.8},
    'LTC': {'rsi': 25, 'bb': 0.05, 'vol': 1.2},
    'AAVE': {'rsi': 22, 'bb': 0.15, 'vol': 1.5},
}

def analyze_pair(pair, thresholds, label):
    df = load_data(pair)
    if df is None:
        return
    c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
    n = len(c)
    
    # Count signals in last 500 bars (or all)
    start = max(0, n - 500)
    signal_count = 0
    for i in range(start, n - 2):  # i = -2 is signal bar
        close = c[i]
        rsi_val = rsi[i]
        bb_val = bb_pct[i]
        vol_val = vol_ratio[i]
        if np.isnan(rsi_val) or np.isnan(bb_val) or np.isnan(vol_val):
            continue
        
        # Compute BB lower using thresholds['bb'] std
        sma20 = df['close'].rolling(20).mean().values
        std20 = df['close'].rolling(20).std().values
        bb_lower = sma20[i] - std20[i] * thresholds['bb']
        bb_upper = sma20[i] + std20[i] * thresholds['bb']
        bb_pct_custom = (close - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0
        
        cond_rsi = rsi_val < thresholds['rsi']
        cond_bb = close < bb_lower  # scanner.py condition
        cond_bb_pct = bb_pct_custom < thresholds['bb']  # paper_scan condition
        cond_vol = vol_val > thresholds['vol']
        
        # scanner.py signal
        if cond_rsi and cond_bb and cond_vol:
            signal_count += 1
    
    print(f"{pair} ({label}): {signal_count} signals in last {n - start} bars")
    if signal_count > 0:
        # Show last few signals
        last_signals = []
        for i in range(start, n - 2):
            close = c[i]
            rsi_val = rsi[i]
            bb_val = bb_pct[i]
            vol_val = vol_ratio[i]
            if np.isnan(rsi_val) or np.isnan(bb_val) or np.isnan(vol_val):
                continue
            sma20 = df['close'].rolling(20).mean().values
            std20 = df['close'].rolling(20).std().values
            bb_lower = sma20[i] - std20[i] * thresholds['bb']
            bb_upper = sma20[i] + std20[i] * thresholds['bb']
            bb_pct_custom = (close - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0
            cond_rsi = rsi_val < thresholds['rsi']
            cond_bb = close < bb_lower
            cond_vol = vol_val > thresholds['vol']
            if cond_rsi and cond_bb and cond_vol:
                last_signals.append((i, close, rsi_val, bb_pct_custom, vol_val))
        # Print last 3
        for idx, close, rsi_val, bb_pct_custom, vol_val in last_signals[-3:]:
            print(f"  Bar {idx}: Close={close:.4f} RSI={rsi_val:.1f} BB%={bb_pct_custom:.3f} Vol={vol_val:.2f}")

def main():
    print("=" * 80)
    print("Historical Signal Scan")
    print("=" * 80)
    
    # Test scanner.py pairs
    for pair, params in SCANNER_THRESHOLDS.items():
        analyze_pair(pair, params, 'scanner.py')
    
    print("\n" + "-" * 80)
    print("Paper scan thresholds:")
    for pair, params in PAPER_THRESHOLDS.items():
        analyze_pair(pair, params, 'paper_scan')

if __name__ == "__main__":
    main()