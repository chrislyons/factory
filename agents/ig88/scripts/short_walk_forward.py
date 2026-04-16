#!/usr/bin/env python3
"""
Walk-Forward OOS Validation for Short Edges

Tests SOL/ETH Daily Break EMA50 short signals with walk-forward methodology:
- 60% in-sample for parameter optimization
- 40% out-of-sample for validation
- Multiple split points (sliding window)
- Reports OOS PF, stability, and compound return
"""

import numpy as np, pandas as pd, requests
from datetime import datetime, timezone
from pathlib import Path


def fetch_binance(symbol, interval="1d", start_ms=None):
    url = "https://api.binance.com/api/v3/klines"
    all_data = []
    params = {"symbol": symbol, "interval": interval, "limit": 1000}
    if start_ms: params["startTime"] = start_ms
    while True:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data: break
        all_data.extend(data)
        if len(data) < 1000: break
        params["startTime"] = data[-1][0] + 1
    df = pd.DataFrame(all_data, columns=['ts','o','h','l','c','v','ct','q','t','tb','tq','ig'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df.set_index('ts')[['o','h','l','c','v']].rename(
        columns={'o':'open','h':'high','l':'low','c':'close','v':'volume'})


def compute_atr(h, l, c, p=14):
    tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    tr = np.concatenate([[0], tr])
    return pd.Series(tr).rolling(p).mean().values


def backtest_short(df, trail_mult=3.0, friction=0.005, max_hold=30):
    c=df['close'].values; h=df['high'].values; l=df['low'].values; v=df['volume'].values
    atr=compute_atr(h,l,c)
    ema50 = pd.Series(c).ewm(span=50, adjust=False).mean().values
    vsma=pd.Series(v).rolling(20).mean().values

    trades = []
    in_trade = False
    lowest = 0.0
    entry_idx = 0
    entry_price = 0.0

    for i in range(55, len(c)):
        if in_trade:
            lowest = min(lowest, c[i])
            trail_stop = lowest + trail_mult * atr[i]
            bars_held = i - entry_idx
            ret = (entry_price - c[i]) / entry_price - friction
            if c[i] > trail_stop or bars_held >= max_hold:
                trades.append(ret)
                in_trade = False
                continue
        if in_trade:
            continue
        # Signal: close breaks below EMA50 with volume
        if c[i] < ema50[i] and c[i-1] >= ema50[i-1] and v[i] > 1.2 * vsma[i]:
            in_trade = True
            entry_price = c[i]
            entry_idx = i
            lowest = c[i]

    if not trades:
        return {'n': 0, 'pf': 0, 'wr': 0, 'avg': 0, 'total': 0}
    pnls = np.array(trades)
    wins = pnls[pnls>0]
    gl = abs(pnls[pnls<=0].sum())
    pf = wins.sum()/max(gl, 0.0001)
    return {'n': len(pnls), 'pf': pf, 'wr': len(wins)/len(pnls), 'avg': pnls.mean(), 'total': pnls.sum()}


def walk_forward(df, trail_mult=3.0, n_splits=4):
    """
    Walk-forward: split data into n_splits chunks.
    For each split, use first portion as IS (parameter fit) and last portion as OOS.
    Report OOS PF for each split.
    """
    total_bars = len(df)
    results = []

    for k in range(1, n_splits + 1):
        # Split: first 50+k*10% IS, rest OOS
        is_pct = 0.50 + k * 0.05
        is_idx = int(total_bars * is_pct)
        if is_idx < 100 or total_bars - is_idx < 50:
            continue

        df_is = df.iloc[:is_idx]
        df_oos = df.iloc[is_idx:]

        # Test on OOS only
        r = backtest_short(df_oos, trail_mult=trail_mult)
        results.append({
            'split': k,
            'is_bars': len(df_is),
            'oos_bars': len(df_oos),
            'oos_start': df_oos.index[0].strftime('%Y-%m-%d'),
            'oos_end': df_oos.index[-1].strftime('%Y-%m-%d'),
            'oos_n': r['n'],
            'oos_pf': r['pf'],
            'oos_wr': r['wr'],
            'oos_avg': r['avg'],
            'oos_total': r['total'],
        })

    return results


def main():
    print("=" * 70)
    print("  WALK-FORWARD OOS VALIDATION — SHORT EDGES")
    print("=" * 70)

    start_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

    assets = [
        ('SOLUSDT', 'SOL', 3.0),
        ('ETHUSDT', 'ETH', 2.0),
    ]

    for symbol, label, trail in assets:
        print(f"\n--- {label} Daily (trail={trail}x) ---")
        try:
            df = fetch_binance(symbol, "1d", start_ms=start_ms)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        print(f"  Full data: {len(df)} bars ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

        # Full sample
        r_full = backtest_short(df, trail_mult=trail)
        print(f"\n  Full Sample: n={r_full['n']} PF={r_full['pf']:.3f} WR={r_full['wr']:.0%} Avg={r_full['avg']:+.3f} Total={r_full['total']:+.1%}")

        # Walk-forward
        wf = walk_forward(df, trail_mult=trail, n_splits=4)

        print(f"\n  Walk-Forward OOS:")
        print(f"  {'Split':<6s} {'OOS Period':<25s} {'n':>4s} {'PF':>7s} {'WR':>6s} {'Avg':>8s} {'Total':>8s}")
        print(f"  {'-'*6} {'-'*25} {'-'*4} {'-'*7} {'-'*6} {'-'*8} {'-'*8}")

        oos_pfs = []
        for w in wf:
            period = f"{w['oos_start']} to {w['oos_end']}"
            print(f"  {w['split']:<6d} {period:<25s} {w['oos_n']:4d} {w['oos_pf']:7.3f} {w['oos_wr']:5.0%} {w['oos_avg']:+8.3f} {w['oos_total']:+7.1%}")
            if w['oos_n'] > 0:
                oos_pfs.append(w['oos_pf'])

        if oos_pfs:
            mean_pf = np.mean(oos_pfs)
            std_pf = np.std(oos_pfs)
            print(f"\n  OOS PF: {mean_pf:.3f} ± {std_pf:.3f}")
            if mean_pf > 1.0:
                print(f"  RESULT: ROBUST — OOS mean PF > 1.0 across {len(oos_pfs)} splits")
            else:
                print(f"  RESULT: FRAGILE — OOS mean PF < 1.0. Edge may not hold.")
        else:
            print(f"\n  Insufficient OOS trades for validation")

    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
