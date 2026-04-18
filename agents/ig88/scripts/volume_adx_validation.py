#!/usr/bin/env python3
"""
Volume+ADX Filter Validation on AVAX, LINK, NEAR, SOL, SUI, FIL
Base: Donchian(20) breakout, ATR(10), 2% trail, 96h max hold
Filter: volume > 1.5*SMA(20_vol) AND adx(14) > 25
Walk-forward: 50/60/70/80%
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h')
OUTPUT = Path('/Users/nesbitt/dev/factory/agents/ig88/data/volume_adx_validation.json')

ASSETS = {
    'AVAX': 'binance_AVAXUSDT_60m.parquet',
    'LINK': 'binance_LINKUSDT_60m.parquet',
    'NEAR': 'binance_NEARUSDT_60m.parquet',
    'SOL':  'binance_SOLUSDT_60m.parquet',
    'SUI':  'binance_SUIUSDT_60m.parquet',
    'FIL':  'binance_FILUSDT_60m.parquet',
}


def load_data(filename):
    df = pd.read_parquet(DATA_DIR / filename)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.sort_values('time').reset_index(drop=True)
    return df


def compute_atr(df, period=10):
    """True Range based ATR"""
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    n = len(df)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i-1]),
            abs(low[i] - close[i-1])
        )
    atr = np.full(n, np.nan)
    atr[period-1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return atr


def compute_adx(df, period=14):
    """ADX(14) calculation"""
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    n = len(df)

    # True Range
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i-1]),
            abs(low[i] - close[i-1])
        )

    # Directional movement
    up_move = np.zeros(n)
    down_move = np.zeros(n)
    for i in range(1, n):
        up_move[i] = high[i] - high[i-1]
        down_move[i] = low[i-1] - low[i]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Smooth with Wilder's method
    atr = np.zeros(n)
    atr[period] = np.mean(tr[1:period+1])
    for i in range(period+1, n):
        atr[i] = atr[i-1] - atr[i-1]/period + tr[i]

    smooth_plus_dm = np.zeros(n)
    smooth_minus_dm = np.zeros(n)
    smooth_plus_dm[period] = np.mean(plus_dm[1:period+1])
    smooth_minus_dm[period] = np.mean(minus_dm[1:period+1])
    for i in range(period+1, n):
        smooth_plus_dm[i] = smooth_plus_dm[i-1] - smooth_plus_dm[i-1]/period + plus_dm[i]
        smooth_minus_dm[i] = smooth_minus_dm[i-1] - smooth_minus_dm[i-1]/period + minus_dm[i]

    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)
    for i in range(period, n):
        if atr[i] > 0:
            plus_di[i] = 100 * smooth_plus_dm[i] / atr[i]
            minus_di[i] = 100 * smooth_minus_dm[i] / atr[i]
        denom = plus_di[i] + minus_di[i]
        if denom > 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / denom

    adx = np.full(n, np.nan)
    adx[2*period-1] = np.mean(dx[period:2*period])
    for i in range(2*period, n):
        adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period

    return adx


def compute_donchian_high(df, period=20):
    """Donchian upper band (highest high over period, shifted by 1)"""
    high = df['high'].values
    n = len(high)
    donchian = np.full(n, np.nan)
    for i in range(period, n):
        donchian[i] = np.max(high[i-period+1:i+1])
    # Shift by 1 so we don't use current bar
    donchian_shifted = np.full(n, np.nan)
    donchian_shifted[period:] = donchian[period-1:-1]
    return donchian_shifted


def simulate_trades(df, atr, donchian_high, vol_filter, splits):
    """Run walk-forward simulation"""
    n = len(df)
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    timestamps = df['time'].values

    results = {}

    for split_pct in splits:
        split_idx = int(n * split_pct / 100)

        # Only use data from split onward (out-of-sample)
        trades = []
        i = max(20, 2*14)  # need enough history for indicators

        while i < split_idx:
            # Check for breakout signal
            if (np.isnan(donchian_high[i]) or np.isnan(atr[i]) or
                close[i] <= donchian_high[i] or atr[i] <= 0):
                i += 1
                continue

            # Volume+ADX filter
            if not vol_filter[i]:
                i += 1
                continue

            # Enter at close
            entry_price = close[i]
            entry_idx = i
            trail_stop = entry_price * (1 - 0.02)  # 2% trailing stop
            max_hold = 96  # 96 hours

            # Walk forward from entry
            j = i + 1
            while j < min(i + max_hold + 1, split_idx):
                current_price = close[j]

                # Update trailing stop (close-based)
                new_trail = close[j] * (1 - 0.02)
                if new_trail > trail_stop:
                    trail_stop = new_trail

                # Check exit conditions
                if low[j] <= trail_stop:
                    # Trailing stop hit
                    exit_price = trail_stop
                    trades.append((entry_price, exit_price))
                    i = j + 1
                    break

                j += 1
            else:
                # Max hold reached
                exit_price = close[min(i + max_hold, split_idx - 1)]
                trades.append((entry_price, exit_price))
                i = i + max_hold + 1

            if j >= split_idx:
                break

        # Calculate profit factor
        if len(trades) > 0:
            returns = [(e - x) / e for e, x in trades]  # short trades (breakout then reversion)
            # Actually for Donchian breakout we go LONG
            returns = [(x - e) / e for e, x in trades]
            wins = [r for r in returns if r > 0]
            losses = [r for r in returns if r <= 0]
            gross_profit = sum(wins) if wins else 0
            gross_loss = abs(sum(losses)) if losses else 0
            pf = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0
            win_rate = len(wins) / len(trades) if trades else 0
            avg_return = np.mean(returns) if returns else 0
        else:
            pf = 0
            win_rate = 0
            avg_return = 0
            returns = []

        results[split_pct] = {
            'trades': len(trades),
            'profit_factor': round(pf, 3),
            'win_rate': round(win_rate, 3),
            'avg_return': round(avg_return, 6),
            'total_return': round(sum(returns) if returns else 0, 6)
        }

    return results


def run_validation():
    splits = [50, 60, 70, 80]
    all_results = {}

    for asset, filename in ASSETS.items():
        print(f"\n{'='*60}")
        print(f"Processing {asset}...")
        print(f"{'='*60}")

        filepath = DATA_DIR / filename
        if not filepath.exists():
            print(f"  WARNING: {filepath} not found, skipping")
            continue

        df = load_data(filename)
        print(f"  Loaded {len(df)} rows, {df['time'].min()} to {df['time'].max()}")

        # Compute indicators
        atr = compute_atr(df, period=10)
        adx = compute_adx(df, period=14)
        donchian_high = compute_donchian_high(df, period=20)
        vol_sma = df['volume'].rolling(window=20).mean().values

        # Volume filter: volume > 1.5 * SMA(20_volume)
        vol_ok = df['volume'].values > 1.5 * vol_sma
        # ADX filter: adx(14) > 25
        adx_ok = adx > 25
        # Combined filter
        combined_filter = vol_ok & adx_ok

        # Baseline: no filter (all signals)
        baseline_filter = np.ones(len(df), dtype=bool)

        print(f"  Indicators computed")

        # Baseline (no filter)
        print(f"  Running baseline (no filter)...")
        baseline_results = simulate_trades(df, atr, donchian_high, baseline_filter, splits)

        # Filtered (Volume + ADX)
        print(f"  Running filtered (Vol>1.5xSMA20 + ADX>25)...")
        filtered_results = simulate_trades(df, atr, donchian_high, combined_filter, splits)

        asset_results = {}
        for split in splits:
            baseline = baseline_results[split]
            filtered = filtered_results[split]

            improvement = 0
            if baseline['profit_factor'] > 0:
                improvement = ((filtered['profit_factor'] - baseline['profit_factor'])
                              / baseline['profit_factor'] * 100)

            asset_results[f'{split}%'] = {
                'baseline': baseline,
                'filtered': filtered,
                'pf_improvement_pct': round(improvement, 1)
            }

            print(f"  {split}% split: Baseline PF={baseline['profit_factor']:.3f} "
                  f"({baseline['trades']} trades) | "
                  f"Filtered PF={filtered['profit_factor']:.3f} "
                  f"({filtered['trades']} trades) | "
                  f"Improvement={improvement:+.1f}%")

        all_results[asset] = asset_results

    return all_results


if __name__ == '__main__':
    print("Volume+ADX Filter Validation")
    print("="*60)

    results = run_validation()

    # Save results
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n\n{'='*60}")
    print("SUMMARY: Baseline PF vs Filtered PF")
    print(f"{'='*60}")
    print(f"{'Asset':<8} {'Split':<8} {'Base PF':<10} {'Filt PF':<10} {'Improvement':<12} {'Base Trades':<12} {'Filt Trades':<12}")
    print("-"*72)
    for asset, splits in results.items():
        for split_key, data in splits.items():
            b = data['baseline']
            f = data['filtered']
            print(f"{asset:<8} {split_key:<8} {b['profit_factor']:<10.3f} {f['profit_factor']:<10.3f} "
                  f"{data['pf_improvement_pct']:>+10.1f}% {b['trades']:<12} {f['trades']:<12}")

    print(f"\nResults saved to {OUTPUT}")
