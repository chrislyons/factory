#!/usr/bin/env python3
"""
ATR Breakout v2b — Threshold Sweep
====================================
Test ATR% percentile thresholds from 0% (no filter) to 80% (very restrictive)
to find optimal filter strength per pair.
"""
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"
THRESHOLDS = [0.0, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
ATR_PCT_LOOKBACK = 500
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0
TRAIL_PCT = 0.01

def load_60m(symbol):
    sym_clean = symbol.replace("_", "")
    for fname in [f"binance_{symbol}_60m.parquet", f"binance_{sym_clean}_60m.parquet",
                  f"binance_{symbol}_1h.parquet", f"binance_{sym_clean}_1h.parquet"]:
        path = os.path.join(DATA_DIR, fname)
        if os.path.exists(path):
            df = pd.read_parquet(path)
            if 'time' in df.columns:
                df.index = pd.to_datetime(df['time'], unit='s')
            df = df.sort_index()
            if len(df) > 5000:
                return df
    return None

def compute_atr(df, p=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def atr_pct_rank(arr, lookback):
    n = len(arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = arr[i-lookback:i]
        sorted_w = np.sort(window)
        result[i] = np.searchsorted(sorted_w, arr[i], side='right') / lookback
    return result

def run_long(df, rank_arr, threshold):
    atr = compute_atr(df, ATR_PERIOD)
    sma100 = df['close'].rolling(100).mean()
    upper = df['high'].shift(1) + ATR_MULTIPLIER * atr.shift(1)
    in_pos, entry, trail, trades = False, 0, 0, []
    for i in range(200, len(df)):
        c = df.iloc[i]['close']
        vol_ok = True if threshold == 0 else (rank_arr[i] >= threshold if not np.isnan(rank_arr[i]) else False)
        if not in_pos and vol_ok and c > sma100.iloc[i] and c > upper.iloc[i]:
            in_pos, entry, trail = True, c, c * (1 - TRAIL_PCT)
        elif in_pos:
            if c < trail:
                trades.append((c - entry) / entry)
                in_pos = False
            else:
                trail = max(trail, c * (1 - TRAIL_PCT))
    return trades

def run_short(df, rank_arr, threshold):
    atr = compute_atr(df, ATR_PERIOD)
    sma100 = df['close'].rolling(100).mean()
    lower = df['low'].shift(1) - ATR_MULTIPLIER * atr.shift(1)
    in_pos, entry, trail, trades = False, 0, 0, []
    for i in range(200, len(df)):
        c = df.iloc[i]['close']
        vol_ok = True if threshold == 0 else (rank_arr[i] >= threshold if not np.isnan(rank_arr[i]) else False)
        if not in_pos and vol_ok and c < sma100.iloc[i] and c < lower.iloc[i]:
            in_pos, entry, trail = True, c, c * (1 + TRAIL_PCT)
        elif in_pos:
            if c > trail:
                trades.append((entry - c) / entry)
                in_pos = False
            else:
                trail = min(trail, c * (1 + TRAIL_PCT))
    return trades

def metrics(trades):
    if len(trades) < 3: return None
    w = [t for t in trades if t > 0]
    l = [t for t in trades if t <= 0]
    gp = sum(w) if w else 0
    gl = abs(sum(l)) if l else 1e-10
    pf = gp / gl if gl > 0 else float('inf')
    wr = len(w) / len(trades)
    cum = 1
    for t in trades: cum *= (1 + t)
    return {'trades': len(trades), 'pf': round(pf, 2), 'wr': round(wr*100, 1), 'ret': round((cum-1)*100, 1)}

def wf_splits(df, fn, rank_arr, threshold, n_splits=5):
    total = len(df)
    test_size = int(total * 0.3 / n_splits)
    results = []
    for i in range(n_splits):
        ts = int(total * (1 - 0.3 + i * 0.3 / n_splits))
        te = min(ts + test_size, total)
        if te - ts < 200: continue
        test_df = df.iloc[ts:te]
        test_rank = rank_arr[ts:te]
        trades = fn(test_df, test_rank, threshold)
        m = metrics(trades)
        if m:
            results.append({'split': i+1, 'pf': m['pf'], 'ret': m['ret']})
    return results

def main():
    print("=" * 80)
    print("ATR BREAKOUT — VOL FILTER THRESHOLD SWEEP")
    print("=" * 80)

    pairs = [
        ("ETHUSDT", "long"),
        ("AVAXUSDT", "long"),
        ("LINKUSDT", "long"),
        ("NEARUSDT", "long"),
        ("SOLUSDT", "short"),
    ]

    for sym, side in pairs:
        df = load_60m(sym)
        if df is None:
            print(f"\n{sym}: no data")
            continue

        atr = compute_atr(df, ATR_PERIOD)
        atr_pct_arr = (atr / df['close']).values
        rank_arr = atr_pct_rank(atr_pct_arr, ATR_PCT_LOOKBACK)

        fn = run_long if side == 'long' else run_short

        print(f"\n{'='*60}")
        print(f"  {sym} {side.upper()} ({len(df)} bars)")
        print(f"{'='*60}")
        print(f"  {'Threshold':>10} {'Bad/Total':>10} {'Avg PF':>8} {'Avg Ret':>8} {'Min PF':>8}")
        print(f"  {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'-'*8}")

        for thresh in THRESHOLDS:
            wf = wf_splits(df, fn, rank_arr, thresh)
            if not wf:
                print(f"  {thresh:>10.0%} {'no data':>10}")
                continue
            bad = sum(1 for w in wf if w['pf'] < 1.0)
            total_splits = len(wf)
            avg_pf = np.mean([w['pf'] for w in wf])
            avg_ret = np.mean([w['ret'] for w in wf])
            min_pf = min(w['pf'] for w in wf)
            print(f"  {thresh:>10.0%} {bad:>4}/{total_splits:<5} {avg_pf:>8.2f} {avg_ret:>7.1f}% {min_pf:>8.2f}")

if __name__ == "__main__":
    np.random.seed(42)
    main()
