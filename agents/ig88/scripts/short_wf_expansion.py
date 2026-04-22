#!/usr/bin/env python3
"""
Walk-forward validation for SHORT sleeve expansion candidates.
Tests PF > 1.2 and n > 30 threshold on previously unconfirmed pairs.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

DONCHIAN = 20
ATR_PERIOD = 10
ATR_MULT_SHORT = 1.5
TRAIL_SHORT = 0.025
MAX_HOLD_SHORT = 48
FRICTION = 0.0014
SMA_REGIME = 100

TRAIN_PCT = 0.5  # 50% train, 50% test


def load_pair(pair):
    for pat in [f"binance_{pair}_60m.parquet", f"binance_{pair}_1h.parquet"]:
        f = DATA_DIR / pat
        if f.exists():
            df = pd.read_parquet(f)
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df = df.set_index('time').sort_index()
                return df
    return None


def compute_atr(df):
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr, index=df.index).rolling(ATR_PERIOD).mean().values


def run_short(df, start_bar=0, end_bar=None):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    lower = pd.Series(l).rolling(DONCHIAN).min().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values
    if end_bar is None:
        end_bar = len(c)
    trades, in_trade = [], False
    entry_price = entry_bar = lowest = 0
    for i in range(max(DONCHIAN, SMA_REGIME) + 1, len(c)):
        if i < start_bar or i >= end_bar:
            if in_trade:
                # Force close at boundary
                if i == end_bar - 1:
                    pnl = (entry_price - c[i]) / entry_price - FRICTION
                    trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i})
                    in_trade = False
            continue
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * (1 + TRAIL_SHORT)
            hours = i - entry_bar
            if h[i] >= trail or hours >= MAX_HOLD_SHORT or i == end_bar - 1:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i})
                in_trade = False
        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower[i-2] - atr[i-1] * ATR_MULT_SHORT
            if c[i-1] < trigger:
                in_trade = True
                entry_price = c[i-1]
                entry_bar = i
                lowest = l[i-1]
    return trades


def analyze(trades):
    if not trades:
        return {"n": 0, "pf": 0, "wr": 0, "avg": 0}
    pnls = [t['pnl'] for t in trades]
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else float('inf')
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    return {"n": len(trades), "pf": pf, "wr": wr, "avg": np.mean(pnls) * 100}


# === Walk-Forward with 3 splits (50/50 each) ===
SPLITS = 3

print("=" * 100)
print(f"WALK-FORWARD VALIDATION — SHORT SLEEVE EXPANSION ({SPLITS} splits, {int(TRAIN_PCT*100)}/{int((1-TRAIN_PCT)*100)} train/test)")
print("=" * 100)

EXPANSION_CANDIDATES = [
    "LINKUSDT", "DOGEUSDT", "NEARUSDT", "WLDUSDT",
    "AAVEUSDT", "LTCUSDT", "RENDERUSDT"
]

for pair in EXPANSION_CANDIDATES:
    df = load_pair(pair)
    if df is None:
        continue

    n_bars = len(df)
    split_size = n_bars // (SPLITS + 1)

    print(f"\n{pair} ({n_bars} bars):")
    test_results = []

    for s in range(SPLITS):
        train_start = split_size * s
        train_end = split_size * (s + 1)
        test_start = train_end
        test_end = split_size * (s + 2)

        train_trades = run_short(df, train_start, train_end)
        test_trades = run_short(df, test_start, test_end)

        t_stats = analyze(train_trades)
        v_stats = analyze(test_trades)

        train_start_date = df.index[train_start].strftime('%Y-%m-%d')
        test_end_date = df.index[min(test_end, len(df)-1)].strftime('%Y-%m-%d')

        print(f"  Split {s+1} [{train_start_date}→{test_end_date}]:")
        print(f"    Train: n={t_stats['n']:3d}  PF={t_stats['pf']:5.2f}  WR={t_stats['wr']:5.1f}%")
        print(f"    Test:  n={v_stats['n']:3d}  PF={v_stats['pf']:5.2f}  WR={v_stats['wr']:5.1f}%")

        test_results.append(v_stats)

    # Summary
    test_pfs = [r['pf'] for r in test_results if r['n'] > 0]
    if test_pfs:
        avg_pf = np.mean(test_pfs)
        min_pf = min(test_pfs)
        all_profitable = all(p > 1.0 for p in test_pfs)
        print(f"  WF Summary: Avg PF={avg_pf:.2f}, Min PF={min_pf:.2f}, All splits profitable: {all_profitable}")
        verdict = "PASS" if all_profitable and avg_pf >= 1.2 else "MARGINAL" if avg_pf >= 1.0 else "FAIL"
        print(f"  Verdict: {verdict}")
    else:
        print(f"  WF Summary: Insufficient trades in test splits")

# Also verify the 4 confirmed SHORT pairs pass
print("\n\n" + "=" * 100)
print("RE-VERIFICATION OF CONFIRMED SHORT PAIRS")
print("=" * 100)

CONFIRMED = ["ARBUSDT", "OPUSDT", "ETHUSDT", "AVAXUSDT"]
for pair in CONFIRMED:
    df = load_pair(pair)
    if df is None:
        continue
    n_bars = len(df)
    split_size = n_bars // (SPLITS + 1)
    print(f"\n{pair} ({n_bars} bars):")
    test_results = []
    for s in range(SPLITS):
        test_start = split_size * (s + 1)
        test_end = split_size * (s + 2)
        test_trades = run_short(df, test_start, test_end)
        v_stats = analyze(test_trades)
        print(f"  Split {s+1} test: n={v_stats['n']:3d}  PF={v_stats['pf']:5.2f}  WR={v_stats['wr']:5.1f}%")
        test_results.append(v_stats)
    test_pfs = [r['pf'] for r in test_results if r['n'] > 0]
    if test_pfs:
        avg_pf = np.mean(test_pfs)
        all_profitable = all(p > 1.0 for p in test_pfs)
        print(f"  WF Summary: Avg PF={avg_pf:.2f}, All profitable: {all_profitable}")
