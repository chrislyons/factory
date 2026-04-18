#!/usr/bin/env python3
"""
Deep dive into 30m insights:
1. 1.5x ATR stop on 60m — does the tighter stop work at 1h too?
2. Hybrid: LINK on 30m, others on 60m — portfolio-level PF
3. Walk-forward validation of best 30m params (not just full-sample)
4. Entry timing: does 30m give better entry prices than 60m for same signals?
"""

import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR_30M = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/30m")
DATA_DIR_60M = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

ASSETS = ["ETH", "AVAX", "SOL", "LINK", "NEAR"]
FRICTION = 0.0007


def ensure_datetime(df):
    if 'time' not in df.columns:
        df = df.reset_index()
        for col in ['timestamp', 'datetime', 'index', 'level_0']:
            if col in df.columns:
                df = df.rename(columns={col: 'time'})
                break
    if 'time' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['time']):
        if df['time'].dtype == 'int64':
            unit = 'ms' if df['time'].iloc[0] > 1e12 else 's'
            df['time'] = pd.to_datetime(df['time'], unit=unit)
    return df


def load_data():
    data = {}
    for asset in ASSETS:
        # 30m
        f30 = DATA_DIR_30M / f"binance_{asset}USDT_30m.parquet"
        df30 = ensure_datetime(pd.read_parquet(f30)).sort_values('time').reset_index(drop=True) if f30.exists() else None
        # 60m (longest file)
        f60 = None
        best = 0
        for f in DATA_DIR_60M.glob(f"*{asset}*_60m.parquet"):
            tmp = pd.read_parquet(f)
            if len(tmp) > best:
                best = len(tmp)
                f60 = f
        df60 = ensure_datetime(pd.read_parquet(f60)).sort_values('time').reset_index(drop=True) if f60 else None
        data[asset] = {'30m': df30, '60m': df60}
    return data


def run_bt(df, donchian, atr_period, atr_mult, trail_pct, max_hold_bars):
    n = len(df)
    if n < max(donchian, atr_period) + 50:
        return None
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    c = df['close'].values.astype(float)
    upper = np.full(n, np.nan)
    for i in range(donchian - 1, n):
        upper[i] = np.max(h[i - donchian + 1: i + 1])
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    atr = np.full(n, np.nan)
    for i in range(atr_period, n):
        atr[i] = np.mean(tr[i - atr_period + 1: i + 1])

    trades = []
    in_pos = False
    entry_px = stop_px = highest = 0.0
    entry_bar = 0
    start = max(donchian + 2, atr_period + 2, 50)
    for i in range(start, n):
        if np.isnan(upper[i]) or np.isnan(atr[i]):
            continue
        if in_pos:
            if c[i] > highest: highest = c[i]
            stop_px = max(stop_px, highest * (1 - trail_pct))
            if c[i] <= stop_px or (i - entry_bar) >= max_hold_bars:
                trades.append((stop_px - entry_px) / entry_px - FRICTION)
                in_pos = False
        else:
            if i > 0 and c[i] > upper[i-1]:
                in_pos = True
                entry_px = c[i]
                stop_px = entry_px - atr_mult * atr[i]
                highest = c[i]
                entry_bar = i
    if not trades:
        return {"trades": 0, "pf": 0, "wr": 0, "avg_ret": 0, "max_dd": 0}
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gp = sum(wins) if wins else 0
    gl = abs(sum(losses)) if losses else 0.001
    equity = np.cumsum(trades)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    return {
        "trades": len(trades),
        "pf": round(gp / gl, 2),
        "wr": round(len(wins) / len(trades) * 100, 1),
        "avg_ret": round(np.mean(trades) * 100, 3),
        "max_dd": round(np.max(dd) * 100, 2) if len(dd) > 0 else 0,
        "total_ret": round(sum(trades) * 100, 1),
    }


def walk_forward(df, donchian, atr_period, atr_mult, trail_pct, max_hold_bars, n_splits=5):
    """Walk-forward: 5 splits, test on second half of each."""
    n = len(df)
    if n < 2000:
        return None
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    c = df['close'].values.astype(float)
    upper = np.full(n, np.nan)
    for i in range(donchian - 1, n):
        upper[i] = np.max(h[i - donchian + 1: i + 1])
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    atr = np.full(n, np.nan)
    for i in range(atr_period, n):
        atr[i] = np.mean(tr[i - atr_period + 1: i + 1])

    split_size = n // n_splits
    splits = []
    for s in range(n_splits):
        test_start = s * split_size + split_size // 2
        test_end = min((s + 1) * split_size, n)
        if test_end - test_start < 100:
            continue
        trades = []
        in_pos = False
        ep = sp = hi = 0.0
        eb = 0
        for i in range(test_start, test_end):
            if np.isnan(upper[i]) or np.isnan(atr[i]):
                continue
            if in_pos:
                if c[i] > hi: hi = c[i]
                sp = max(sp, hi * (1 - trail_pct))
                if c[i] <= sp or (i - eb) >= max_hold_bars:
                    trades.append((sp - ep) / ep - FRICTION)
                    in_pos = False
            else:
                if i > 0 and c[i] > upper[i-1]:
                    in_pos = True
                    ep = c[i]
                    sp = ep - atr_mult * atr[i]
                    hi = c[i]
                    eb = i
        if trades:
            w = [t for t in trades if t > 0]
            lo = [t for t in trades if t <= 0]
            gp = sum(w) if w else 0
            gl = abs(sum(lo)) if lo else 0.001
            splits.append({"pf": gp/gl, "trades": len(trades), "wr": len(w)/len(trades)*100})
    if not splits:
        return None
    return {
        "avg_pf": round(np.mean([s['pf'] for s in splits]), 2),
        "min_pf": round(min(s['pf'] for s in splits), 2),
        "splits": len(splits),
    }


# === MAIN ===
data = load_data()

# === TEST 1: 1.5x ATR stop on 60m ===
print("=== TEST 1: 1.5x ATR stop on 60m (grid finding ported to 1h) ===\n")
print(f"{'Asset':6s} {'2.0x PF':8s} {'1.5x PF':8s} {'Delta':8s}")
print("-" * 35)
for asset in ASSETS:
    df = data[asset]['60m']
    r2 = run_bt(df, 20, 10, 2.0, 0.02, 96)
    r15 = run_bt(df, 20, 10, 1.5, 0.02, 96)
    delta = r15['pf'] - r2['pf'] if r2 and r15 else 0
    print(f"{asset:6s} {r2['pf']:8.2f} {r15['pf']:8.2f} {delta:+8.2f}")

# === TEST 2: Walk-forward validation of best 30m params ===
print("\n=== TEST 2: Walk-forward — 30m D40/A20/S1.5/T2% vs 60m D20/A10/S2.0/T2% ===\n")
print(f"{'Asset':6s} {'60m WF PF':10s} {'60m Min':8s} {'30m WF PF':10s} {'30m Min':8s} {'Winner':8s}")
print("-" * 55)
for asset in ASSETS:
    df60 = data[asset]['60m']
    df30 = data[asset]['30m']
    wf60 = walk_forward(df60, 20, 10, 2.0, 0.02, 96)
    wf30 = walk_forward(df30, 40, 20, 1.5, 0.02, 192)
    if wf60 and wf30:
        winner = "30m" if wf30['avg_pf'] > wf60['avg_pf'] else "60m"
        print(f"{asset:6s} {wf60['avg_pf']:10.2f} {wf60['min_pf']:8.2f} {wf30['avg_pf']:10.2f} {wf30['min_pf']:8.2f} {winner:8s}")

# === TEST 3: Hybrid portfolio — best timeframe per asset ===
print("\n=== TEST 3: Hybrid Portfolio — best timeframe per asset ===\n")
# From grid search, LINK benefits most from 30m. Test hybrid.
hybrid_params = {
    "ETH":  {"tf": "60m", "d": 20, "a": 10, "s": 2.0, "t": 0.02, "h": 96},
    "AVAX": {"tf": "60m", "d": 20, "a": 10, "s": 2.0, "t": 0.02, "h": 96},
    "SOL":  {"tf": "60m", "d": 20, "a": 10, "s": 2.0, "t": 0.02, "h": 96},
    "LINK": {"tf": "30m", "d": 40, "a": 20, "s": 1.5, "t": 0.02, "h": 192},
    "NEAR": {"tf": "60m", "d": 20, "a": 10, "s": 2.0, "t": 0.02, "h": 96},
}

print("Hybrid config:")
for asset, p in hybrid_params.items():
    print(f"  {asset}: {p['tf']} D{p['d']} A{p['a']} S{p['s']} T{p['t']*100:.0f}%")

print(f"\n{'Asset':6s} {'60m PF':8s} {'Hybrid PF':10s} {'Winner':8s}")
print("-" * 35)
total_60 = 0
total_hyb = 0
for asset in ASSETS:
    df = data[asset][hybrid_params[asset]['tf']]
    p = hybrid_params[asset]
    r60 = run_bt(data[asset]['60m'], 20, 10, 2.0, 0.02, 96)
    rhy = run_bt(df, p['d'], p['a'], p['s'], p['t'], p['h'])
    winner = "HYB" if rhy['pf'] > r60['pf'] else "60m"
    print(f"{asset:6s} {r60['pf']:8.2f} {rhy['pf']:10.2f} {winner:8s}")
    total_60 += r60['pf']
    total_hyb += rhy['pf']

print(f"\nSum PF: 60m={total_60:.2f} | Hybrid={total_hyb:.2f}")
improvement = (total_hyb / total_60 - 1) * 100
print(f"Hybrid improvement: {improvement:+.1f}%")

# === TEST 4: What if we run 1.5x stop on ALL assets at 60m? ===
print("\n=== TEST 4: 60m with 1.5x ATR stop across ALL assets ===\n")
print(f"{'Asset':6s} {'2.0x PF':8s} {'1.5x PF':8s} {'2.0x DD':8s} {'1.5x DD':8s}")
print("-" * 40)
for asset in ASSETS:
    df = data[asset]['60m']
    r2 = run_bt(df, 20, 10, 2.0, 0.02, 96)
    r15 = run_bt(df, 20, 10, 1.5, 0.02, 96)
    print(f"{asset:6s} {r2['pf']:8.2f} {r15['pf']:8.2f} {r2['max_dd']:7.1f}% {r15['max_dd']:7.1f}%")
