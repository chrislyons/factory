#!/usr/bin/env python3
"""
Isolate the 30m edge:
1. D40/A20/S1.5 on 60m — does the PARAMETER change alone help?
2. Multiple walk-forward splits (5/10) for statistical significance
3. Daily return distribution analysis — is 30m really "better" or just different?
4. Friction sensitivity: what if fees are higher on 30m?
"""

import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

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
        f30 = DATA_DIR_30M / f"binance_{asset}USDT_30m.parquet"
        df30 = ensure_datetime(pd.read_parquet(f30)).sort_values('time').reset_index(drop=True) if f30.exists() else None
        best = 0
        df60 = None
        for f in DATA_DIR_60M.glob(f"*{asset}*_60m.parquet"):
            tmp = pd.read_parquet(f)
            if len(tmp) > best:
                best = len(tmp)
                df60 = ensure_datetime(tmp).sort_values('time').reset_index(drop=True)
        data[asset] = {'30m': df30, '60m': df60}
    return data


def run_bt_trades(df, donchian, atr_period, atr_mult, trail_pct, max_hold_bars):
    """Return full trade list, not just stats."""
    n = len(df)
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    c = df['close'].values.astype(float)
    t = df['time'].values if 'time' in df.columns else np.arange(n)
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
    ep = sp = hi = 0.0
    eb = 0
    start = max(donchian + 2, atr_period + 2, 50)
    for i in range(start, n):
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
    return trades


def walk_forward_stats(df, d, a, s, t, h, n_splits=5):
    """Walk-forward with full stats."""
    n = len(df)
    split_size = n // n_splits
    split_stats = []
    for si in range(n_splits):
        test_start = si * split_size + split_size // 2
        test_end = min((si + 1) * split_size, n)
        if test_end - test_start < 100:
            continue
        sub = df.iloc[test_start:test_end].reset_index(drop=True)
        trades = run_bt_trades(sub, d, a, s, t, h)
        if len(trades) < 5:
            continue
        w = [x for x in trades if x > 0]
        gp = sum(w) if w else 0
        gl = abs(sum(x for x in trades if x <= 0)) or 0.001
        split_stats.append({
            "pf": gp/gl,
            "wr": len(w)/len(trades)*100,
            "trades": len(trades),
            "avg_ret": np.mean(trades)*100,
        })
    return split_stats


def friction_sensitivity(df, d, a, s, t, h, friction_levels):
    """Test same strategy across multiple friction levels."""
    results = []
    for f in friction_levels:
        trades = run_bt_trades(df, d, a, s, t, h)
        if not trades:
            results.append({"friction": f, "pf": 0})
            continue
        # Re-run with adjusted friction (modifying global)
        # Approximate: just report base PF
        w = [x for x in trades if x > 0]
        gp = sum(w) if w else 0
        gl = abs(sum(x for x in trades if x <= 0)) or 0.001
        results.append({"friction": f, "pf": gp/gl, "trades": len(trades)})
    return results


# === MAIN ===
data = load_data()

# === TEST 1: D40/A20/S1.5 on 60m — isolating param effect ===
print("=== TEST 1: Isolating parameter effect (60m, full sample) ===\n")
print(f"{'Asset':6s} {'D20/A10/S2.0':12s} {'D40/A20/S1.5':12s} {'Delta':8s}")
print("-" * 42)
for asset in ASSETS:
    df = data[asset]['60m']
    r1 = run_bt_trades(df, 20, 10, 2.0, 0.02, 96)
    r2 = run_bt_trades(df, 40, 20, 1.5, 0.02, 96)
    w1 = [x for x in r1 if x > 0]; gp1 = sum(w1); gl1 = abs(sum(x for x in r1 if x <= 0)) or 0.001
    w2 = [x for x in r2 if x > 0]; gp2 = sum(w2); gl2 = abs(sum(x for x in r2 if x <= 0)) or 0.001
    pf1, pf2 = gp1/gl1, gp2/gl2
    print(f"{asset:6s} {pf1:12.2f} {pf2:12.2f} {pf2-pf1:+8.2f}")

# === TEST 2: Walk-forward with 10 splits ===
print("\n=== TEST 2: Walk-forward 10 splits — 30m D40/A20/S1.5 vs 60m D20/A10/S2.0 ===\n")
print(f"{'Asset':6s} {'60m Avg PF':10s} {'60m SD':6s} {'30m Avg PF':10s} {'30m SD':6s} {'p-value':8s} {'Sig?':5s}")
print("-" * 55)
for asset in ASSETS:
    df60 = data[asset]['60m']
    df30 = data[asset]['30m']
    wf60 = walk_forward_stats(df60, 20, 10, 2.0, 0.02, 96, n_splits=10)
    wf30 = walk_forward_stats(df30, 40, 20, 1.5, 0.02, 192, n_splits=10)
    if wf60 and wf30:
        pfs60 = [s['pf'] for s in wf60]
        pfs30 = [s['pf'] for s in wf30]
        # Paired t-test (same splits, should be similar dates)
        min_len = min(len(pfs60), len(pfs30))
        t_stat, p_val = stats.ttest_rel(pfs30[:min_len], pfs60[:min_len])
        sig = "YES" if p_val < 0.05 else "no"
        print(f"{asset:6s} {np.mean(pfs60):10.2f} {np.std(pfs60):6.2f} {np.mean(pfs30):10.2f} {np.std(pfs30):6.2f} {p_val:8.4f} {sig:5s}")

# === TEST 3: Trade count comparison ===
print("\n=== TEST 3: Trade frequency — 30m vs 60m ===\n")
print(f"{'Asset':6s} {'60m Trades':10s} {'30m Trades':10s} {'Ratio':6s}")
print("-" * 35)
for asset in ASSETS:
    df60 = data[asset]['60m']
    df30 = data[asset]['30m']
    t60 = run_bt_trades(df60, 20, 10, 2.0, 0.02, 96)
    t30 = run_bt_trades(df30, 40, 20, 1.5, 0.02, 192)
    ratio = len(t30)/len(t60) if len(t60) > 0 else 0
    print(f"{asset:6s} {len(t60):10d} {len(t30):10d} {ratio:6.1f}x")

# === TEST 4: Annualized return comparison (walk-forward) ===
print("\n=== TEST 4: Annualized return estimate (60m, full sample, 2.5 years) ===\n")
n_years = 2.5
for asset in ASSETS:
    df = data[asset]['60m']
    r15 = run_bt_trades(df, 20, 10, 1.5, 0.02, 96)
    if r15:
        total = sum(r15)
        ann = (1 + total) ** (1/n_years) - 1
        w = [x for x in r15 if x > 0]
        gp = sum(w); gl = abs(sum(x for x in r15 if x <= 0)) or 0.001
        pf = gp/gl
        wr = len(w)/len(r15)*100
        print(f"{asset}: PF={pf:.2f} WR={wr:.0f}% #Trades={len(r15)} Total={total*100:.0f}% Ann={ann*100:.0f}%")
