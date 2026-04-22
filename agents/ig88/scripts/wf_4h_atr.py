#!/usr/bin/env python3
"""
Walk-Forward Validation for 4H ATR Breakout.
70/30 split, sliding window approach.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

def load_pair(pair):
    f = DATA_DIR / f"binance_{pair}_60m.parquet"
    if not f.exists():
        f = DATA_DIR / f"binance_{pair}_1h.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f)
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time').sort_index()
    return df

def resample_4h(df):
    return df.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum'
    }).dropna()

def compute_atr(df, period=14):
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr, index=df.index).rolling(period).mean().values

def backtest_4h(df):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df, 14)
    upper_dc = pd.Series(h).rolling(20).max().values
    sma = pd.Series(c).rolling(100).mean().values
    friction = 0.0014
    trades = []
    in_trade = False
    entry_price = entry_bar = highest = 0
    for i in range(120, len(c)):
        if in_trade:
            highest = max(highest, h[i])
            trail = highest * 0.985
            bars_held = i - entry_bar
            if l[i] <= trail or bars_held >= 30:
                exit_p = trail if l[i] <= trail else c[i]
                pnl = (exit_p - entry_price) / entry_price - friction
                trades.append(pnl)
                in_trade = False
        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]:
            in_trade = True
            entry_price = c[i-1]
            entry_bar = i
            highest = h[i-1]
    return trades

def compute_stats(pnls):
    if len(pnls) < 5:
        return None
    pnls = np.array(pnls)
    wr = (pnls > 0).mean() * 100
    avg = np.mean(pnls) * 100
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
    t_stat, p_val = stats.ttest_1samp(pnls, 0)
    return {"n": len(pnls), "wr": wr, "avg": avg, "pf": pf, "t": t_stat, "p": p_val}

# === WALK-FORWARD ===
pairs = ["SOLUSDT", "AVAXUSDT", "ARBUSDT", "OPUSDT", "RENDERUSDT",
         "NEARUSDT", "AAVEUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT",
         "ETHUSDT", "BTCUSDT"]

print("=" * 80)
print("4H ATR BREAKOUT — WALK-FORWARD VALIDATION (70/30 split)")
print("=" * 80)

all_is = []  # in-sample
all_oos = []  # out-of-sample
all_recomb = []

for pair in pairs:
    df = load_pair(pair)
    if df is None:
        continue
    df4h = resample_4h(df)
    n = len(df4h)
    split = int(n * 0.7)

    is_df = df4h.iloc[:split]
    oos_df = df4h.iloc[split:]

    is_trades = backtest_4h(is_df)
    oos_trades = backtest_4h(oos_df)
    full_trades = backtest_4h(df4h)

    is_stats = compute_stats(is_trades)
    oos_stats = compute_stats(oos_trades)

    for t in is_trades:
        all_is.append(t)
    for t in oos_trades:
        all_oos.append(t)
    for t in full_trades:
        all_recomb.append(t)

    if is_stats and oos_stats:
        degradation = (1 - oos_stats['pf'] / is_stats['pf']) * 100
        print(f"\n{pair:>12s}:")
        print(f"  IS:  n={is_stats['n']:>4d}  PF={is_stats['pf']:.2f}  WR={is_stats['wr']:.1f}%  Avg={is_stats['avg']:+.2f}%")
        print(f"  OOS: n={oos_stats['n']:>4d}  PF={oos_stats['pf']:.2f}  WR={oos_stats['wr']:.1f}%  Avg={oos_stats['avg']:+.2f}%")
        print(f"  Degradation: {degradation:+.1f}%  {'✓' if degradation < 50 else '⚠'}")

# Portfolio totals
print(f"\n{'=' * 80}")
print("PORTFOLIO WALK-FORWARD SUMMARY")

for label, trades in [("In-Sample (70%)", all_is), ("Out-of-Sample (30%)", all_oos)]:
    s = compute_stats(trades)
    if s:
        print(f"\n{label}:")
        print(f"  Trades: {s['n']}")
        print(f"  PF: {s['pf']:.2f}")
        print(f"  WR: {s['wr']:.1f}%")
        print(f"  Avg: {s['avg']:+.2f}%")
        print(f"  t-stat: {s['t']:.2f}, p-value: {s['p']:.8f}")
        print(f"  Significant: {'YES' if s['p'] < 0.05 else 'NO'}")

s = compute_stats(all_recomb)
print(f"\nFull dataset:")
print(f"  Trades: {s['n']}, PF: {s['pf']:.2f}, WR: {s['wr']:.1f}%, Avg: {s['avg']:+.2f}%")

is_s = compute_stats(all_is)
oos_s = compute_stats(all_oos)
if is_s and oos_s:
    deg = (1 - oos_s['pf'] / is_s['pf']) * 100
    print(f"\nOverall degradation: {deg:+.1f}%")
    print(f"OOS PF > 1.0: {'YES ✓' if oos_s['pf'] > 1.0 else 'NO ✗'}")
    print(f"OOS statistically significant: {'YES ✓' if oos_s['p'] < 0.05 else 'NO ✗'}")
