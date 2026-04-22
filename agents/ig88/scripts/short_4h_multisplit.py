#!/usr/bin/env python3
"""
Multi-split walk-forward for 4H ATR SHORT.
5 non-overlapping test windows. Check for robustness.
"""
import pandas as pd, numpy as np
from pathlib import Path
from scipy import stats

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

def load_pair(pair):
    f = DATA_DIR / f"binance_{pair}_60m.parquet"
    if not f.exists(): f = DATA_DIR / f"binance_{pair}_1h.parquet"
    if not f.exists(): return None
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

def backtest_short(df, atr_mult=1.5, trail_pct=0.025, max_hold=20):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df, 14)
    lower_dc = pd.Series(l).rolling(20).min().values
    sma = pd.Series(c).rolling(100).mean().values
    friction = 0.0014
    trades = []
    in_trade = False
    entry_price = entry_bar = lowest = 0
    for i in range(120, len(c)):
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * (1 + trail_pct)
            bars_held = i - entry_bar
            if h[i] >= trail or bars_held >= max_hold:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - friction
                trades.append(pnl)
                in_trade = False
        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower_dc[i-2] - atr[i-1] * atr_mult
            if c[i-1] < trigger:
                in_trade = True
                entry_price = c[i-1]
                entry_bar = i
                lowest = l[i-1]
    return trades

pairs = ["SOLUSDT","BTCUSDT","ETHUSDT","AVAXUSDT","ARBUSDT","OPUSDT",
         "LINKUSDT","NEARUSDT","AAVEUSDT","DOGEUSDT","LTCUSDT"]

all_data = {}
for p in pairs:
    df = load_pair(p)
    if df is not None:
        all_data[p] = resample_4h(df)

all_index = sorted(set().union(*[set(d.index) for d in all_data.values()]))
total_days = (all_index[-1] - all_index[0]).days

print("=" * 70)
print("4H ATR SHORT — MULTI-SPLIT WALK-FORWARD (5 windows)")
print("=" * 70)

all_oos = []
n_splits = 5

for si in range(n_splits):
    test_start_pct = si / n_splits
    test_end_pct = (si + 1) / n_splits
    ts = all_index[0] + pd.Timedelta(days=total_days * test_start_pct)
    te = all_index[0] + pd.Timedelta(days=total_days * test_end_pct)
    tc = ts

    split_oos = []
    for p, df in all_data.items():
        test_df = df[(df.index >= ts) & (df.index < te)]
        if len(test_df) < 100: continue
        t = backtest_short(test_df)
        split_oos.extend(t)

    if len(split_oos) > 5:
        pnls = np.array(split_oos)
        wr = (pnls > 0).mean() * 100
        avg = np.mean(pnls) * 100
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
        t, p_val = stats.ttest_1samp(pnls, 0)
        all_oos.extend(split_oos)
        print(f"\nSplit {si+1}: {ts.date()} → {te.date()}")
        print(f"  OOS: n={len(pnls):>4d} PF={pf:.2f} WR={wr:.1f}% Avg={avg:+.2f}% t={t:.2f} p={p_val:.6f} {'✓' if pf > 1.0 else '✗'}")

print(f"\n{'=' * 70}")
if len(all_oos) > 5:
    pnls = np.array(all_oos)
    wr = (pnls > 0).mean() * 100
    avg = np.mean(pnls) * 100
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
    t, p_val = stats.ttest_1samp(pnls, 0)
    print(f"\nAGGREGATE OOS: n={len(pnls)} PF={pf:.2f} WR={wr:.1f}% Avg={avg:+.2f}% t={t:.2f} p={p_val:.10f}")
    print(f"PF > 1.0: {'PASS ✓' if pf > 1.0 else 'FAIL ✗'}")
    print(f"Significant: {'YES ✓' if p_val < 0.05 else 'NO ✗'}")
    print(f"\nTrades per year: {len(pnls) / (total_days/365.25):.1f}")
    print(f"Trades per pair per year: {len(pnls) / len(pairs) / (total_days/365.25):.1f}")

# Parameter sensitivity: test with 1.0x and 2.0x ATR mult
print(f"\n{'=' * 70}")
print("PARAMETER SENSITIVITY (ATR multiplier)")
for mult in [1.0, 1.5, 2.0, 2.5]:
    all_t = []
    for p, df in all_data.items():
        t = backtest_short(df, atr_mult=mult)
        all_t.extend(t)
    if len(all_t) > 5:
        pnls = np.array(all_t)
        wr = (pnls > 0).mean() * 100
        avg = np.mean(pnls) * 100
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
        print(f"  ATR {mult}x: n={len(pnls):>4d} PF={pf:.2f} WR={wr:.1f}% Avg={avg:+.2f}%")
