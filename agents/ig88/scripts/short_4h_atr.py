#!/usr/bin/env python3
"""
4H ATR SHORT Breakout — backtest and walk-forward validation.
SHORT logic: asset below SMA100, price breaks below Donchian20 - ATR*mult.
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

def backtest_4h_short(df, atr_mult=1.5, trail_pct=0.025, max_hold=20):
    """4H SHORT: below SMA100, break below Donchian20 - ATR*mult"""
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

def compute_stats(pnls):
    if len(pnls) < 5: return None
    pnls = np.array(pnls)
    wr = (pnls > 0).mean() * 100
    avg = np.mean(pnls) * 100
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
    t, p = stats.ttest_1samp(pnls, 0)
    return {"n": len(pnls), "wr": wr, "avg": avg, "pf": pf, "t": t, "p": p}

pairs = ["SOLUSDT","BTCUSDT","ETHUSDT","AVAXUSDT","ARBUSDT","OPUSDT",
         "LINKUSDT","RENDERUSDT","NEARUSDT","AAVEUSDT","DOGEUSDT","LTCUSDT"]

print("=" * 80)
print("4H ATR SHORT BREAKOUT — FULL VALIDATION")
print("=" * 80)

all_full = []
all_is = []
all_oos = []

for pair in pairs:
    df = load_pair(pair)
    if df is None: continue
    df4h = resample_4h(df)
    n = len(df4h)
    split = int(n * 0.7)

    full_trades = backtest_4h_short(df4h)
    is_trades = backtest_4h_short(df4h.iloc[:split])
    oos_trades = backtest_4h_short(df4h.iloc[split:])

    fs = compute_stats(full_trades)
    iss = compute_stats(is_trades)
    ooss = compute_stats(oos_trades)

    all_full.extend(full_trades)
    all_is.extend(is_trades)
    all_oos.extend(oos_trades)

    if fs and ooss:
        deg = (1 - ooss['pf']/iss['pf'])*100 if iss and iss['pf'] > 0 else 0
        marker = "✓" if ooss['pf'] > 1.0 else "✗"
        print(f"\n{pair:>12s}: Full n={fs['n']:>4d} PF={fs['pf']:.2f} WR={fs['wr']:.1f}% Avg={fs['avg']:+.2f}% | OOS n={ooss['n']:>3d} PF={ooss['pf']:.2f} {marker}")
    elif fs:
        print(f"\n{pair:>12s}: Full n={fs['n']:>4d} PF={fs['pf']:.2f} WR={fs['wr']:.1f}% Avg={fs['avg']:+.2f}% | OOS: insufficient data")

print(f"\n{'=' * 80}")
for label, trades in [("Full", all_full), ("IS (70%)", all_is), ("OOS (30%)", all_oos)]:
    s = compute_stats(trades)
    if s:
        print(f"\n{label}: n={s['n']} PF={s['pf']:.2f} WR={s['wr']:.1f}% Avg={s['avg']:+.2f}% t={s['t']:.2f} p={s['p']:.8f}")

oos_s = compute_stats(all_oos)
is_s = compute_stats(all_is)
if oos_s and is_s:
    deg = (1 - oos_s['pf']/is_s['pf'])*100
    print(f"\nDegradation: {deg:+.1f}%")
    print(f"OOS > 1.0: {'PASS ✓' if oos_s['pf'] > 1.0 else 'FAIL ✗'}")
    print(f"Significant: {'YES ✓' if oos_s['p'] < 0.05 else 'NO ✗'}")
