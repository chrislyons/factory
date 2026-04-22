#!/usr/bin/env python3
"""Test SHORT entry sensitivity to ATR multiplier on WF-validated assets."""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

SHORT_ASSETS = [
    ("ARBUSDT", "binance_ARBUSDT_60m.parquet", 26956),
    ("OPUSDT", "binance_OPUSDT_60m.parquet", 34043),
    ("ETHUSDT", "binance_ETHUSDT_60m.parquet", 43788),
    ("APTUSDT", "binance_APTUSDT_60m.parquet", 30690),
]

DONCHIAN = 20
ATR_PERIOD = 10
TRAIL = 0.025
MAX_HOLD = 48
FRICTION = 0.0014
SMA_PERIOD = 100


def run_short_backtest(df, atr_mult):
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values

    # ATR
    tr = np.zeros(len(close))
    for i in range(1, len(close)):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr = pd.Series(tr).rolling(ATR_PERIOD).mean().values

    # Donchian lower
    dlow = pd.Series(low).rolling(DONCHIAN).min().values
    # SMA
    sma = pd.Series(close).rolling(SMA_PERIOD).mean().values

    trades = []
    in_trade = False
    entry_price = 0
    entry_bar = 0
    lowest = 0

    for i in range(max(DONCHIAN, SMA_PERIOD) + 1, len(close)):
        if in_trade:
            # Update trailing stop
            lowest = min(lowest, low[i])
            trail_stop = lowest * (1 + TRAIL)
            hours_held = i - entry_bar

            hit_stop = high[i] >= trail_stop
            hit_hold = hours_held >= MAX_HOLD

            if hit_stop or hit_hold:
                exit_price = trail_stop if hit_stop else close[i]
                pnl = (entry_price - exit_price) / entry_price - FRICTION
                trades.append(pnl)
                in_trade = False

        if not in_trade:
            # Entry: below SMA100 AND close < prev_dlow - ATR*mult
            if close[i-1] < sma[i-1]:
                prev_dlow = dlow[i-2]
                trigger = prev_dlow - atr[i-1] * atr_mult
                if close[i-1] < trigger:
                    in_trade = True
                    entry_price = close[i-1]
                    entry_bar = i
                    lowest = low[i-1]

    if not trades:
        return {"n": 0, "pf": 0, "wr": 0, "avg": 0}

    gp = sum(p for p in trades if p > 0)
    gl = abs(sum(p for p in trades if p < 0))
    return {
        "n": len(trades),
        "pf": gp / gl if gl > 0 else float('inf'),
        "wr": sum(1 for p in trades if p > 0) / len(trades) * 100,
        "avg": np.mean(trades) * 100,
    }


print("SHORT Entry Sensitivity to ATR Multiplier")
print("=" * 70)

for mult in [1.0, 1.5, 2.0, 2.5, 3.0]:
    print(f"\nATR Multiplier: {mult}x")
    print(f"  {'Asset':10s} {'n':>5s} {'PF':>6s} {'WR':>6s} {'Avg%':>7s}")
    print(f"  {'-'*36}")
    total_n = 0
    pfs = []
    for pair, fname, bars in SHORT_ASSETS:
        f = DATA_DIR / fname
        if not f.exists():
            continue
        df = pd.read_parquet(f)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time').sort_index()
        r = run_short_backtest(df, mult)
        total_n += r['n']
        if r['pf'] > 0 and r['pf'] < 100:
            pfs.append(r['pf'])
        print(f"  {pair:10s} {r['n']:5d} {r['pf']:6.2f} {r['wr']:5.1f}% {r['avg']:+6.2f}%")
    avg_pf = np.mean(pfs) if pfs else 0
    print(f"  {'TOTAL':10s} {total_n:5d} {avg_pf:6.2f}")
