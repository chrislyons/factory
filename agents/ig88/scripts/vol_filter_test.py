#!/usr/bin/env python3
"""
ATR Breakout v2 — Volatility Regime Filter
============================================
Tests whether adding an ATR% percentile filter improves walk-forward robustness.

Hypothesis: ATR Breakout profits come from high-volatility regimes.
Adding a filter to only trade when ATR% is in the top 40% of its rolling
distribution should improve out-of-sample consistency.

Test: Walk-forward comparison of v1 (no filter) vs v2 (ATR% filter) on
all pairs with adequate data.
"""
import pandas as pd
import numpy as np
import os
import json
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"

PAIRS = {
    "long": ["ETHUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT"],
    "short": ["SOLUSDT", "WLDUSDT"],
}

ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0
TRAIL_PCT = 0.01
ATR_PCT_LOOKBACK = 500  # rolling window for ATR% percentile
ATR_PCT_THRESHOLD = 0.60  # only trade when ATR% in top 40% (>= 60th percentile)

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
            if len(df) > 1000:
                return df
    return None

def compute_atr(df, period=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def run_long_v1(df):
    """v1: No vol filter."""
    atr = compute_atr(df, ATR_PERIOD)
    sma100 = df['close'].rolling(100).mean()
    upper = df['high'].shift(1) + ATR_MULTIPLIER * atr.shift(1)
    in_pos, entry, trail, trades = False, 0, 0, []
    for i in range(200, len(df)):
        c = df.iloc[i]['close']
        if not in_pos and c > sma100.iloc[i] and c > upper.iloc[i]:
            in_pos, entry, trail = True, c, c * (1 - TRAIL_PCT)
        elif in_pos:
            if c < trail:
                trades.append((c - entry) / entry)
                in_pos = False
            else:
                trail = max(trail, c * (1 - TRAIL_PCT))
    return trades

def atr_pct_rank(arr, lookback):
    """Vectorized rolling percentile rank using searchsorted."""
    n = len(arr)
    result = np.full(n, np.nan)
    for i in range(lookback, n):
        window = arr[i-lookback:i]
        sorted_w = np.sort(window)
        rank = np.searchsorted(sorted_w, arr[i], side='right') / lookback
        result[i] = rank
    return result

def run_long_v2(df):
    """v2: ATR% percentile filter."""
    atr = compute_atr(df, ATR_PERIOD)
    atr_pct_arr = (atr / df['close']).values
    rank_arr = atr_pct_rank(atr_pct_arr, ATR_PCT_LOOKBACK)
    sma100 = df['close'].rolling(100).mean()
    upper = df['high'].shift(1) + ATR_MULTIPLIER * atr.shift(1)
    in_pos, entry, trail, trades = False, 0, 0, []
    for i in range(200, len(df)):
        c = df.iloc[i]['close']
        vol_ok = rank_arr[i] >= ATR_PCT_THRESHOLD if not np.isnan(rank_arr[i]) else False
        if not in_pos and vol_ok and c > sma100.iloc[i] and c > upper.iloc[i]:
            in_pos, entry, trail = True, c, c * (1 - TRAIL_PCT)
        elif in_pos:
            if c < trail:
                trades.append((c - entry) / entry)
                in_pos = False
            else:
                trail = max(trail, c * (1 - TRAIL_PCT))
    return trades

def run_short_v1(df):
    """v1: No vol filter."""
    atr = compute_atr(df, ATR_PERIOD)
    sma100 = df['close'].rolling(100).mean()
    lower = df['low'].shift(1) - ATR_MULTIPLIER * atr.shift(1)
    in_pos, entry, trail, trades = False, 0, 0, []
    for i in range(200, len(df)):
        c = df.iloc[i]['close']
        if not in_pos and c < sma100.iloc[i] and c < lower.iloc[i]:
            in_pos, entry, trail = True, c, c * (1 + TRAIL_PCT)
        elif in_pos:
            if c > trail:
                trades.append((entry - c) / entry)
                in_pos = False
            else:
                trail = min(trail, c * (1 + TRAIL_PCT))
    return trades

def run_short_v2(df):
    """v2: ATR% percentile filter."""
    atr = compute_atr(df, ATR_PERIOD)
    atr_pct_arr = (atr / df['close']).values
    rank_arr = atr_pct_rank(atr_pct_arr, ATR_PCT_LOOKBACK)
    sma100 = df['close'].rolling(100).mean()
    lower = df['low'].shift(1) - ATR_MULTIPLIER * atr.shift(1)
    in_pos, entry, trail, trades = False, 0, 0, []
    for i in range(200, len(df)):
        c = df.iloc[i]['close']
        vol_ok = rank_arr[i] >= ATR_PCT_THRESHOLD if not np.isnan(rank_arr[i]) else False
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
    if len(trades) < 3:
        return None
    w = [t for t in trades if t > 0]
    l = [t for t in trades if t <= 0]
    gp = sum(w) if w else 0
    gl = abs(sum(l)) if l else 1e-10
    pf = gp / gl if gl > 0 else float('inf')
    wr = len(w) / len(trades)
    cum = 1
    for t in trades: cum *= (1 + t)
    ret = (cum - 1) * 100
    return {'trades': len(trades), 'pf': round(pf, 2), 'wr': round(wr*100, 1), 'ret': round(ret, 1)}

def walk_forward(df, fn, n_splits=5):
    total = len(df)
    test_size = int(total * 0.3 / n_splits)
    results = []
    for i in range(n_splits):
        ts = int(total * (1 - 0.3 + i * 0.3 / n_splits))
        te = min(ts + test_size, total)
        if te - ts < 200:
            continue
        trades = fn(df.iloc[ts:te])
        m = metrics(trades)
        if m:
            results.append({'split': i+1, 'start': str(df.index[ts].date()),
                           'end': str(df.index[min(te-1, total-1)].date()), **m})
    return results

def main():
    print("=" * 75)
    print("ATR BREAKOUT v2: VOLATILITY REGIME FILTER COMPARISON")
    print(f"Filter: ATR% >= {int(ATR_PCT_THRESHOLD*100)}th percentile (rolling {ATR_PCT_LOOKBACK})")
    print("=" * 75)

    all_results = {}

    for side in ['long', 'short']:
        fn_v1 = run_long_v1 if side == 'long' else run_short_v1
        fn_v2 = run_long_v2 if side == 'long' else run_short_v2

        for sym in PAIRS[side]:
            df = load_60m(sym)
            if df is None or len(df) < 5000:
                print(f"\n{sym} {side}: insufficient data")
                continue

            print(f"\n{'='*60}")
            print(f"  {sym} {side.upper()} ({len(df)} bars)")
            print(f"{'='*60}")

            wf_v1 = walk_forward(df, fn_v1)
            wf_v2 = walk_forward(df, fn_v2)

            if not wf_v1 and not wf_v2:
                print("  No walk-forward data")
                continue

            print(f"\n  {'Window':22} {'v1 PF':>7} {'v1 WR':>7} {'v1 Ret':>7}  {'v2 PF':>7} {'v2 WR':>7} {'v2 Ret':>7}  {'Δ PF':>7}")
            print(f"  {'-'*22} {'-'*7} {'-'*7} {'-'*7}  {'-'*7} {'-'*7} {'-'*7}  {'-'*7}")

            v1_pfs, v2_pfs = [], []

            for s in range(max(len(wf_v1), len(wf_v2))):
                v1 = wf_v1[s] if s < len(wf_v1) else None
                v2 = wf_v2[s] if s < len(wf_v2) else None

                label = v1['start'] if v1 else (v2['start'] if v2 else '?')
                v1_pf = v1['pf'] if v1 else '-'
                v1_wr = f"{v1['wr']}%" if v1 else '-'
                v1_ret = f"{v1['ret']}%" if v1 else '-'
                v2_pf = v2['pf'] if v2 else '-'
                v2_wr = f"{v2['wr']}%" if v2 else '-'
                v2_ret = f"{v2['ret']}%" if v2 else '-'

                if v1 and v2:
                    delta = round(v2['pf'] - v1['pf'], 2)
                    delta_str = f"{delta:+.2f}"
                    v1_pfs.append(v1['pf'])
                    v2_pfs.append(v2['pf'])
                else:
                    delta_str = '-'

                print(f"  {label:22} {str(v1_pf):>7} {str(v1_wr):>7} {str(v1_ret):>7}  "
                      f"{str(v2_pf):>7} {str(v2_wr):>7} {str(v2_ret):>7}  {delta_str:>7}")

            if v1_pfs and v2_pfs:
                v1_bad = sum(1 for p in v1_pfs if p < 1.0)
                v2_bad = sum(1 for p in v2_pfs if p < 1.0)
                print(f"\n  v1: {v1_bad}/{len(v1_pfs)} splits < 1.0 PF, avg PF={np.mean(v1_pfs):.2f}")
                print(f"  v2: {v2_bad}/{len(v2_pfs)} splits < 1.0 PF, avg PF={np.mean(v2_pfs):.2f}")
                if v2_bad < v1_bad:
                    print(f"  >>> v2 IMPROVES: {v1_bad} bad splits -> {v2_bad} bad splits")
                elif v2_bad == v1_bad and np.mean(v2_pfs) > np.mean(v1_pfs):
                    print(f"  >>> v2 IMPROVES: same bad splits but higher avg PF")
                else:
                    print(f"  >>> v2 does NOT improve on v1")

            all_results[f"{sym}_{side}"] = {'v1': wf_v1, 'v2': wf_v2}

    # Save
    out = "/Users/nesbitt/dev/factory/agents/ig88/data/vol_filter_comparison.json"
    with open(out, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n\nResults saved to {out}")

if __name__ == "__main__":
    np.random.seed(42)
    main()
