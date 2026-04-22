#!/usr/bin/env python3
"""
Multi-split walk-forward validation for 4H ATR.
5 non-overlapping train/test windows.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

def load_pair(pair):
    f = DATA_DIR / f"binance_{pair}_60m.parquet"
    df = pd.read_parquet(f)
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time').sort_index()
    return df

def resample_4h(df):
    return df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()

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

# 5-split walk-forward on portfolio
pairs = ["SOLUSDT", "AVAXUSDT", "ARBUSDT", "OPUSDT", "RENDERUSDT",
         "NEARUSDT", "AAVEUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT",
         "ETHUSDT", "BTCUSDT"]

# Load and resample all
all_data = {}
for p in pairs:
    df = load_pair(p)
    if df is not None:
        all_data[p] = resample_4h(df)

# Find common time range
all_index = sorted(set().union(*[set(d.index) for d in all_data.values()]))
min_date = all_index[0]
max_date = all_index[-1]
total_days = (max_date - min_date).days
print(f"Date range: {min_date.date()} to {max_date.date()} ({total_days} days)")

# Create 5 test windows (each ~20% of data)
n_splits = 5
split_pct = 0.20

all_oos = []
all_is = []

for split_i in range(n_splits):
    test_start_pct = split_i * split_pct
    test_end_pct = (split_i + 1) * split_pct

    test_start = min_date + pd.Timedelta(days=total_days * test_start_pct)
    test_end = min_date + pd.Timedelta(days=total_days * test_end_pct)

    # Training: everything before test_start (minimum 1 year)
    train_cutoff = test_start

    split_oos = []
    split_is = []

    for p, df in all_data.items():
        train_df = df[df.index < train_cutoff]
        test_df = df[(df.index >= test_start) & (df.index < test_end)]

        if len(train_df) < 500 or len(test_df) < 100:
            continue

        is_trades = backtest_4h(train_df)
        oos_trades = backtest_4h(test_df)

        split_is.extend(is_trades)
        split_oos.extend(oos_trades)

    if len(split_oos) > 10:
        pnls = np.array(split_oos)
        wr = (pnls > 0).mean() * 100
        avg = np.mean(pnls) * 100
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
        t, p_val = stats.ttest_1samp(pnls, 0)

        print(f"\nSplit {split_i+1}: {test_start.date()} → {test_end.date()}")
        print(f"  OOS: n={len(pnls):>4d}  PF={pf:.2f}  WR={wr:.1f}%  Avg={avg:+.2f}%  t={t:.2f}  p={p_val:.6f}")
        all_oos.extend(split_oos)
        all_is.extend(split_is)

# Aggregate
print(f"\n{'=' * 70}")
print("MULTI-SPLIT AGGREGATE RESULTS")
print(f"{'=' * 70}")

for label, trades in [("In-Sample", all_is), ("Out-of-Sample (all splits)", all_oos)]:
    pnls = np.array(trades)
    wr = (pnls > 0).mean() * 100
    avg = np.mean(pnls) * 100
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
    t, p_val = stats.ttest_1samp(pnls, 0)
    print(f"\n{label}:")
    print(f"  n={len(pnls)}  PF={pf:.2f}  WR={wr:.1f}%  Avg={avg:+.2f}%  t={t:.2f}  p={p_val:.10f}")

is_pnls = np.array(all_is)
oos_pnls = np.array(all_oos)
is_pf = sum(is_pnls[is_pnls>0]) / abs(sum(is_pnls[is_pnls<=0]))
oos_pf = sum(oos_pnls[oos_pnls>0]) / abs(sum(oos_pnls[oos_pnls<=0]))
deg = (1 - oos_pf / is_pf) * 100
print(f"\nDegradation: {deg:+.1f}%")
print(f"OOS PF > 1.0: {'PASS ✓' if oos_pf > 1.0 else 'FAIL ✗'}")
oos_t, oos_p = stats.ttest_1samp(oos_pnls, 0)
print(f"OOS significant: {'PASS ✓' if oos_p < 0.05 else 'FAIL ✗'}")
print(f"\nVERDICT: {'STRATEGY VALIDATED' if oos_pf > 1.5 and oos_p < 0.01 else 'NEEDS MORE WORK'}")
