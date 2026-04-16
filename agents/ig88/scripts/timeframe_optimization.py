#!/usr/bin/env python3
"""
ATR Breakout Timeframe Optimization.
Test ATR BO on 15m and 30m candles vs 1h.
Hypothesis: Higher frequency signals → more trades → higher returns (or more noise).
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
DATA_DIR = BASE_DIR / "data" / "ohlcv" / "1h"
OUT_DIR = BASE_DIR / "data" / "timeframe_tests"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ASSETS = ["ETH", "AVAX", "LINK", "NEAR", "SOL"]
TIMEFRAMES = {
    "15m": 4,   # 4x more candles than 1h
    "30m": 2,   # 2x more candles than 1h
    "60m": 1,   # baseline
}

DONCHIAN_PERIOD = 20
ATR_PERIOD = 10
ATR_MULT_STOP = 2.0
TRAIL_PCT = 0.02
MAX_HOLD_H = 96
FRICTION = 0.0007  # Hyperliquid round-trip


def resample_ohlcv(df: pd.DataFrame, factor: int) -> pd.DataFrame:
    """Resample 1h candles to coarser timeframe by grouping."""
    if factor == 1:
        return df.copy()
    
    # Group every `factor` candles
    n = len(df)
    groups = np.repeat(np.arange(n // factor + 1), factor)[:n]
    df = df.copy()
    df['group'] = groups
    
    resampled = df.groupby('group').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
    }).reset_index(drop=True)
    
    return resampled


def run_backtest(df: pd.DataFrame, label: str, factor: int = 1) -> dict:
    """Run ATR BO backtest on given dataframe. factor=1 for 1h, 2 for 30m, 4 for 15m."""
    n = len(df)
    if n < DONCHIAN_PERIOD + ATR_PERIOD + 10:
        return {"trades": 0, "pf": 0, "label": label}

    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values

    # Donchian
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(DONCHIAN_PERIOD - 1, n):
        upper[i] = np.max(highs[i - DONCHIAN_PERIOD + 1: i + 1])
        lower[i] = np.min(lows[i - DONCHIAN_PERIOD + 1: i + 1])

    # True Range
    tr = np.zeros(n)
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    atr = np.full(n, np.nan)
    for i in range(ATR_PERIOD, n):
        atr[i] = np.mean(tr[i - ATR_PERIOD + 1: i + 1])

    # Walk-forward (5 splits)
    min_bars = max(DONCHIAN_PERIOD + 2, 500)
    if n < min_bars * 2:
        return {"trades": 0, "pf": 0, "label": label}

    split_size = n // 5
    split_results = []

    for split in range(5):
        test_start = split * split_size + split_size // 2
        test_end = min((split + 1) * split_size, n)
        
        if test_end - test_start < 100:
            continue

        trades = []
        in_pos = False
        entry_px = 0
        stop_px = 0
        highest = 0
        entry_bar = 0

        for i in range(test_start, test_end):
            if np.isnan(upper[i]) or np.isnan(atr[i]):
                continue

            if in_pos:
                # Trailing stop
                if closes[i] > highest:
                    highest = closes[i]
                new_trail = highest * (1 - TRAIL_PCT)
                stop_px = max(stop_px, new_trail)

                # Exit: close <= stop OR max hold
                bars_held = i - entry_bar
                max_hold_bars = MAX_HOLD_H  # 1 bar = 1 hour equivalent
                if factor != 1:
                    max_hold_bars = MAX_HOLD_H * factor

                if closes[i] <= stop_px or bars_held >= max_hold_bars:
                    ret = (stop_px - entry_px) / entry_px - FRICTION
                    trades.append(ret)
                    in_pos = False

            else:
                # Entry: close > prev upper
                if i > 0 and closes[i] > upper[i - 1]:
                    in_pos = True
                    entry_px = closes[i]
                    stop_px = entry_px - ATR_MULT_STOP * atr[i]
                    highest = closes[i]
                    entry_bar = i

        if trades:
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            gross_profit = sum(wins) if wins else 0
            gross_loss = abs(sum(losses)) if losses else 0.001
            pf = gross_profit / gross_loss
            
            split_results.append({
                "trades": len(trades),
                "wr": len(wins) / len(trades) * 100,
                "pf": pf,
                "avg_ret": np.mean(trades) * 100,
            })

    if not split_results:
        return {"trades": 0, "pf": 0, "label": label}

    avg_pf = np.mean([s["pf"] for s in split_results])
    min_pf = min([s["pf"] for s in split_results])
    total_trades = sum([s["trades"] for s in split_results])

    return {
        "trades": total_trades,
        "avg_pf": round(avg_pf, 2),
        "min_pf": round(min_pf, 2),
        "avg_wr": round(np.mean([s["wr"] for s in split_results]), 1),
        "avg_ret": round(np.mean([s["avg_ret"] for s in split_results]), 3),
        "label": label,
    }


# === MAIN ===
print("=== ATR Breakout Timeframe Optimization ===\n")
print("Testing: 15m, 30m, 60m candles from 1h data")
print(f"Assets: {', '.join(ASSETS)}")
print(f"Params: Donchian={DONCHIAN_PERIOD}, ATR={ATR_PERIOD}, Stop={ATR_MULT_STOP}x, Trail={TRAIL_PCT*100}%")
print()

results = {}

for asset in ASSETS:
    # Try multiple naming conventions
    candidates = [
        DATA_DIR / f"binance_{asset}USDT_60m.parquet",
        DATA_DIR / f"binance_{asset}_USDT_60m.parquet",
        DATA_DIR / f"binance_{asset}USDT_1h.parquet",
        DATA_DIR / f"binance_{asset}_USDT_1h.parquet",
    ]
    data_file = None
    for c in candidates:
        if c.exists():
            data_file = c
            break
    if data_file is None:
        print(f"  {asset}: data not found (tried {[str(c.name) for c in candidates]})")
        continue

    df = pd.read_parquet(data_file)
    
    # Parse timestamps - column 'time' in seconds (int64)
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Sort by time column or index
    if 'time' in df.columns:
        df = df.sort_values('time').reset_index(drop=True)
    else:
        df = df.sort_index().reset_index(drop=True)
    print(f"\n{asset} ({len(df)} 1h bars):")

    for tf_name, factor in TIMEFRAMES.items():
        if factor == 1:
            test_df = df[['open', 'high', 'low', 'close']].copy()
        else:
            test_df = resample_ohlcv(df[['open', 'high', 'low', 'close']], factor)

        result = run_backtest(test_df, f"{asset}_{tf_name}", factor)
        print(f"  {tf_name:4s}: PF={result.get('avg_pf', 0):.2f} | MinPF={result.get('min_pf', 0):.2f} | WR={result.get('avg_wr', 0):.1f}% | Trades={result.get('trades', 0)}")

        if asset not in results:
            results[asset] = {}
        results[asset][tf_name] = result

# Summary
print("\n" + "=" * 60)
print("SUMMARY: Best timeframe per asset")
print(f"{'Asset':6s} {'Best TF':6s} {'PF':6s} {'Trades':7s} {'vs 60m':8s}")
print("-" * 40)
for asset in ASSETS:
    if asset not in results:
        continue
    best_tf = max(results[asset], key=lambda x: results[asset][x].get('avg_pf', 0))
    best = results[asset][best_tf]
    baseline = results[asset].get('60m', {}).get('avg_pf', 1)
    improvement = (best.get('avg_pf', 0) / baseline - 1) * 100 if baseline > 0 else 0
    print(f"{asset:6s} {best_tf:6s} {best.get('avg_pf', 0):.2f}  {best.get('trades', 0):5d}    {improvement:+.0f}%")
