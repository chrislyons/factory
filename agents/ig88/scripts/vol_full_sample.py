#!/usr/bin/env python3
"""
Quick full-sample comparison of vol filter thresholds.
Focuses on trade count + PF, not walk-forward.
"""
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"
THRESHOLDS = [0.0, 0.40, 0.50, 0.60]
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
            if len(df) > 5000: return df
    return None

def compute_atr(df, p=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
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
        vol_ok = True if threshold == 0 else (rank_arr[i] >= threshold if i < len(rank_arr) and not np.isnan(rank_arr[i]) else False)
        if not in_pos and vol_ok and c > sma100.iloc[i] and c > upper.iloc[i]:
            in_pos, entry, trail = True, c, c*(1-TRAIL_PCT)
        elif in_pos:
            if c < trail:
                trades.append((c-entry)/entry)
                in_pos = False
            else:
                trail = max(trail, c*(1-TRAIL_PCT))
    return trades

def run_short(df, rank_arr, threshold):
    atr = compute_atr(df, ATR_PERIOD)
    sma100 = df['close'].rolling(100).mean()
    lower = df['low'].shift(1) - ATR_MULTIPLIER * atr.shift(1)
    in_pos, entry, trail, trades = False, 0, 0, []
    for i in range(200, len(df)):
        c = df.iloc[i]['close']
        vol_ok = True if threshold == 0 else (rank_arr[i] >= threshold if i < len(rank_arr) and not np.isnan(rank_arr[i]) else False)
        if not in_pos and vol_ok and c < sma100.iloc[i] and c < lower.iloc[i]:
            in_pos, entry, trail = True, c, c*(1+TRAIL_PCT)
        elif in_pos:
            if c > trail:
                trades.append((entry-c)/entry)
                in_pos = False
            else:
                trail = min(trail, c*(1+TRAIL_PCT))
    return trades

def main():
    pairs = [
        ("ETHUSDT", "long"),
        ("AVAXUSDT", "long"),
        ("LINKUSDT", "long"),
        ("SOLUSDT", "short"),
    ]

    for sym, side in pairs:
        df = load_60m(sym)
        if df is None: continue

        atr = compute_atr(df, ATR_PERIOD)
        atr_pct_arr = (atr/df['close']).values
        rank_arr = atr_pct_rank(atr_pct_arr, ATR_PCT_LOOKBACK)
        fn = run_long if side == 'long' else run_short

        print(f"\n{sym} {side.upper()} ({df.index[0].date()} to {df.index[-1].date()}):")
        print(f"  {'Thresh':>8} {'Trades':>7} {'PF':>7} {'WR':>7} {'Return':>8} {'Avg/trade':>10}")
        print(f"  {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*8} {'-'*10}")

        for thresh in THRESHOLDS:
            trades = fn(df, rank_arr, thresh)
            if not trades:
                print(f"  {thresh:>8.0%} {'0':>7}")
                continue
            w = [t for t in trades if t > 0]
            l = [t for t in trades if t <= 0]
            gp = sum(w) if w else 0
            gl = abs(sum(l)) if l else 1e-10
            pf = gp/gl if gl > 0 else 999
            wr = len(w)/len(trades)*100
            cum = 1
            for t in trades: cum *= (1+t)
            ret = (cum-1)*100
            avg = np.mean(trades)*100
            print(f"  {thresh:>8.0%} {len(trades):>7} {pf:>7.2f} {wr:>6.1f}% {ret:>7.1f}% {avg:>9.2f}%")

if __name__ == "__main__":
    main()
