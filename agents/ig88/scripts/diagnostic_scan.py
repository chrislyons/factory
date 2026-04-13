#!/usr/bin/env python3
"""
Diagnostic script for paper trading scanner.
Prints indicator values for each pair and checks regime.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88')
DATA_DIR = BASE_DIR / 'data'

# Import compute_indicators from paper_scan
from scripts.paper_scan import PORTFOLIO, load_data, compute_indicators

def main():
    print("=" * 80)
    print("DIAGNOSTIC: Paper Trading Scanner Indicator Values")
    print("=" * 80)
    
    # Load regime state
    regime_path = BASE_DIR / 'data' / 'regime_state.json'
    if regime_path.exists():
        import json
        with open(regime_path) as f:
            regime = json.load(f)
        print(f"\nCurrent Regime: {regime['regime']} (MR weight: {regime['weights']['mr']:.3f})")
        print(f"Primary Regime: {regime['metadata']['primary_regime']}")
        print(f"BTC Price: {regime['btc_price']:.2f} | 200 SMA: {regime['btc_sma200']:.2f}")
    else:
        print("\nRegime file not found.")
    
    print("\n" + "-" * 80)
    print("PAIR INDICATOR VALUES (last 3 bars, i = -2 is signal bar)")
    print("-" * 80)
    
    # For each pair
    for pair, cfg in PORTFOLIO.items():
        print(f"\n{pair} ({cfg['tier']}):")
        df = load_data(pair)
        if df is None:
            print(f"  No data file found.")
            continue
        
        c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
        n = len(c)
        print(f"  Data points: {n}")
        
        # Print last 3 bars
        for offset in [-2, -1, -0]:  # -2 is the completed bar used for signals
            idx = n + offset if offset < 0 else offset
            if idx < 0 or idx >= n:
                continue
            close = c[idx]
            rsi_val = rsi[idx]
            bb_val = bb_pct[idx]
            vol_val = vol_ratio[idx]
            atr_val = atr[idx]
            atr_pct = atr_val / close * 100 if close > 0 else 0
            
            # Check entry conditions
            cond_rsi = rsi_val < cfg['rsi']
            cond_bb = bb_val < cfg['bb']
            cond_vol = vol_val > cfg['vol']
            all_cond = cond_rsi and cond_bb and cond_vol
            
            bar_str = f"  Bar {idx} (offset {offset}): Close={close:.4f} RSI={rsi_val:.1f} BB%={bb_val:.3f} VolRatio={vol_val:.2f} ATR%={atr_pct:.2f}%"
            if offset == -2:
                bar_str += " [SIGNAL BAR]"
                if all_cond:
                    bar_str += " -> SIGNAL!"
                else:
                    reasons = []
                    if not cond_rsi:
                        reasons.append(f"RSI {rsi_val:.1f} >= {cfg['rsi']}")
                    if not cond_bb:
                        reasons.append(f"BB% {bb_val:.3f} >= {cfg['bb']}")
                    if not cond_vol:
                        reasons.append(f"VolRatio {vol_val:.2f} <= {cfg['vol']}")
                    bar_str += f" FAIL: {', '.join(reasons)}"
            print(bar_str)
        
        # Also compute ATR regime: high ATR relative to price
        # Let's compute average ATR% over last 20 bars
        atr_pct_series = atr[-20:] / c[-20:] * 100
        avg_atr_pct = np.mean(atr_pct_series)
        print(f"  Avg ATR% (20 bars): {avg_atr_pct:.2f}%")
    
    print("\n" + "-" * 80)
    print("ENTRY CONDITION THRESHOLDS:")
    print("-" * 80)
    for pair, cfg in PORTFOLIO.items():
        print(f"{pair}: RSI<{cfg['rsi']} BB<{cfg['bb']} Vol>{cfg['vol']}")

if __name__ == "__main__":
    main()