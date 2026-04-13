"""
Friction Tracker (Binance-based)
=================================
Estimates friction from OHLCV data:
- Open-to-High spread (entry slippage on market buy)
- Low-to-Open spread (stop run probability)
- Close-to-Open gap (overnight/weekend risk)
- Intra-bar volatility (noise estimate)

This is a proxy for DEX friction when Jupiter API is unavailable.
For live trading, replace with actual Jupiter quotes.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION_LOG = DATA_DIR / 'friction_log.jsonl'

PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX', 'ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def estimate_pair_friction(pair):
    """
    Estimate friction from OHLCV data for a pair.
    
    Metrics:
    1. Entry slippage: (High - Open) / Open when buying at bar open
    2. Stop run risk: (Open - Low) / Open when stop is just below bar
    3. Gap risk: |Close_prev - Open| / Close_prev between bars
    4. Intra-bar volatility: (High - Low) / Open
    """
    df = load_data(pair)
    
    # Use last 500 bars for recent estimate
    df = df.tail(500)
    
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    
    # 1. Entry slippage (buying at market, worst case = High)
    entry_slippage = (h - o) / o * 100
    
    # 2. Stop run risk (stop below bar, could get stopped at Low)
    stop_slippage = (o - l) / o * 100  # How much below open the low goes
    
    # 3. Gap risk (close to next open)
    gap_risk = np.abs(c[:-1] - o[1:]) / c[:-1] * 100
    
    # 4. Intra-bar volatility
    intra_bar_vol = (h - l) / o * 100
    
    return {
        'pair': pair,
        'bars_analyzed': len(df),
        'entry_slippage_pct': float(np.mean(entry_slippage)),
        'entry_slippage_p95': float(np.percentile(entry_slippage, 95)),
        'stop_slippage_pct': float(np.mean(stop_slippage)),
        'stop_slippage_p95': float(np.percentile(stop_slippage, 95)),
        'gap_risk_pct': float(np.mean(gap_risk)),
        'gap_risk_p95': float(np.percentile(gap_risk, 95)),
        'intra_bar_vol_pct': float(np.mean(intra_bar_vol)),
        'intra_bar_vol_p95': float(np.percentile(intra_bar_vol, 95)),
        'estimated_total_friction': float(np.mean(entry_slippage) + 0.1),  # slippage + ~0.1% exchange fee
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


def log_friction(data):
    """Append friction measurement to log file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(FRICTION_LOG, 'a') as f:
        f.write(json.dumps(data) + '\n')


def scan_all_friction():
    """Scan friction for all pairs."""
    results = []
    
    for pair in PAIRS:
        try:
            data = estimate_pair_friction(pair)
            log_friction(data)
            results.append(data)
        except Exception as e:
            print(f"Error analyzing {pair}: {e}")
    
    return results


if __name__ == '__main__':
    print("Friction Tracker - Binance OHLCV Analysis")
    print("=" * 80)
    print("Estimating friction from entry slippage, stop risk, and gap risk")
    print()
    
    results = scan_all_friction()
    
    print(f"\n{'Pair':<10} {'Entry Slip':<12} {'Stop Risk':<12} {'Gap Risk':<12} {'IntraVol':<12} {'Est Total'}")
    print("-" * 72)
    
    for r in results:
        print(f"{r['pair']:<10} {r['entry_slippage_pct']:>8.3f}%    {r['stop_slippage_pct']:>8.3f}%    {r['gap_risk_pct']:>8.3f}%    {r['intra_bar_vol_pct']:>8.3f}%    {r['estimated_total_friction']:>6.3f}%")
    
    if results:
        totals = [r['estimated_total_friction'] for r in results]
        entries = [r['entry_slippage_pct'] for r in results]
        print(f"\n{'=' * 60}")
        print(f"Portfolio Average Estimated Friction: {np.mean(totals):.3f}%")
        print(f"Average Entry Slippage: {np.mean(entries):.3f}%")
        print(f"Pairs exceeding 0.5% friction: {sum(1 for t in totals if t > 0.5)}/12")
        print(f"Pairs exceeding 1.0% friction: {sum(1 for t in totals if t > 1.0)}/12")
        print(f"\nLog file: {FRICTION_LOG}")
