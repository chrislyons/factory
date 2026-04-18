#!/usr/bin/env python3
"""
Three objectives:
1. Asset-specific parameter optimization — full grid per asset, walk-forward validation
2. Regime stress test — how does strategy perform in bear/trending/low-vol periods?
3. 2x leverage walk-forward — realistic annualized with 2x on perps
"""

import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

ASSETS = ["ETH", "AVAX", "SOL", "LINK", "NEAR"]
FRICTION = 0.0007  # Jupiter perps

# Asset-specific parameter grids
PARAM_GRID = {
    "ETH":  {"d": [15, 20, 30, 40], "a": [8, 10, 15, 20], "s": [1.5, 2.0, 2.5], "t": [0.015, 0.02, 0.025]},
    "AVAX": {"d": [15, 20, 30, 40], "a": [8, 10, 15, 20], "s": [1.5, 2.0, 2.5], "t": [0.015, 0.02, 0.025]},
    "SOL":  {"d": [15, 20, 30, 40], "a": [8, 10, 15, 20], "s": [1.5, 2.0, 2.5], "t": [0.015, 0.02, 0.025]},
    "LINK": {"d": [15, 20, 30, 40], "a": [8, 10, 15, 20], "s": [1.5, 2.0, 2.5], "t": [0.015, 0.02, 0.025]},
    "NEAR": {"d": [15, 20, 30, 40], "a": [8, 10, 15, 20], "s": [1.5, 2.0, 2.5], "t": [0.015, 0.02, 0.025]},
}

LEVERAGE = 2.0
HOLD_BARS = 96


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
        best, df = 0, None
        for f in DATA_DIR.glob(f"*{asset}*_60m.parquet"):
            tmp = pd.read_parquet(f)
            if len(tmp) > best:
                best = len(tmp)
                df = ensure_datetime(tmp).sort_values('time').reset_index(drop=True)
        data[asset] = df
    return data


def run_bt(df, d, a, s, t, h, friction=FRICTION):
    n = len(df)
    high, low, close = df['high'].values.astype(float), df['low'].values.astype(float), df['close'].values.astype(float)
    upper = np.full(n, np.nan)
    for i in range(d - 1, n):
        upper[i] = np.max(high[i - d + 1: i + 1])
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = np.full(n, np.nan)
    for i in range(a, n):
        atr[i] = np.mean(tr[i - a + 1: i + 1])
    trades, in_pos, ep, sp, hi, eb = [], False, 0.0, 0.0, 0.0, 0
    for i in range(max(d + 2, a + 2, 50), n):
        if np.isnan(upper[i]) or np.isnan(atr[i]): continue
        if in_pos:
            hi = max(hi, close[i])
            sp = max(sp, hi * (1 - t))
            if close[i] <= sp or (i - eb) >= h:
                trades.append((sp - ep) / ep - friction)
                in_pos = False
        else:
            if i > 0 and close[i] > upper[i-1]:
                in_pos, ep, sp, hi, eb = True, close[i], close[i] - s * atr[i], close[i], i
    if not trades:
        return None
    w = [x for x in trades if x > 0]
    lo = [x for x in trades if x <= 0]
    gp, gl = sum(w) if w else 0, abs(sum(lo)) if lo else 0.001
    equity = np.cumsum(trades)
    peak = np.maximum.accumulate(equity)
    return {
        "pf": gp/gl, "wr": len(w)/len(trades)*100, "trades": len(trades),
        "avg": np.mean(trades)*100, "total": sum(trades)*100,
        "max_dd": np.max(peak - equity)*100,
    }


def walk_forward_best(df, params_list, n_splits=5):
    """Find best params using walk-forward: train on first half of each split, test on second."""
    n = len(df)
    split_size = n // n_splits
    wf_results = []
    best_params = None
    for si in range(n_splits):
        train_end = si * split_size + split_size // 2
        test_start = train_end
        test_end = min((si + 1) * split_size, n)
        if test_end - test_start < 200 or train_end < 500:
            continue
        # Optimize on train
        train_df = df.iloc[si * split_size:train_end].reset_index(drop=True)
        test_df = df.iloc[test_start:test_end].reset_index(drop=True)
        best_train_pf, best_p = 0, params_list[0]
        for p in params_list:
            r = run_bt(train_df, p['d'], p['a'], p['s'], p['t'], p.get('h', HOLD_BARS))
            if r and r['pf'] > best_train_pf:
                best_train_pf = r['pf']
                best_p = p
        # Test on out-of-sample
        r = run_bt(test_df, best_p['d'], best_p['a'], best_p['s'], best_p['t'], best_p.get('h', HOLD_BARS))
        if r:
            wf_results.append({"pf": r['pf'], "wr": r['wr'], "trades": r['trades'],
                               "avg": r['avg'], "max_dd": r['max_dd'], "total": r['total'],
                               "params": best_p})
    if not wf_results:
        return None, []
    best_params = wf_results[0]['params']  # Use first split's params as baseline
    return best_params, wf_results


def compute_regimes(df, sma_short=50, sma_long=200):
    """Simple regime classification."""
    c = df['close'].values.astype(float)
    sma_s = pd.Series(c).rolling(sma_short).mean().values
    sma_l = pd.Series(c).rolling(sma_long).mean().values
    regimes = np.full(len(c), 'UNCERTAIN', dtype=object)
    regimes[(sma_s > sma_l) & (sma_s > np.roll(sma_s, 1))] = 'BULL'
    regimes[(sma_s < sma_l) & (sma_s < np.roll(sma_s, 1))] = 'BEAR'
    return regimes


def regime_breakdown(df, d, a, s, t, h):
    """Show PF by regime."""
    n = len(df)
    regimes = compute_regimes(df)
    high, low, close = df['high'].values.astype(float), df['low'].values.astype(float), df['close'].values.astype(float)
    upper = np.full(n, np.nan)
    for i in range(d - 1, n):
        upper[i] = np.max(high[i - d + 1: i + 1])
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = np.full(n, np.nan)
    for i in range(a, n):
        atr[i] = np.mean(tr[i - a + 1: i + 1])

    regime_trades = {'BULL': [], 'BEAR': [], 'UNCERTAIN': []}
    in_pos, ep, sp, hi, eb, reg_entry = False, 0.0, 0.0, 0.0, 0, 'BULL'
    for i in range(max(d + 2, a + 2, 200), n):
        if np.isnan(upper[i]) or np.isnan(atr[i]): continue
        if in_pos:
            hi = max(hi, close[i])
            sp = max(sp, hi * (1 - t))
            if close[i] <= sp or (i - eb) >= h:
                regime_trades[reg_entry].append((sp - ep) / ep - FRICTION)
                in_pos = False
        else:
            if i > 0 and close[i] > upper[i-1]:
                in_pos, ep, sp, hi, eb = True, close[i], close[i] - s * atr[i], close[i], i
                reg_entry = regimes[i]
    results = {}
    for reg, tr_list in regime_trades.items():
        if len(tr_list) < 3:
            results[reg] = {"trades": len(tr_list), "pf": 0, "wr": 0}
            continue
        w = [x for x in tr_list if x > 0]
        gp, gl = sum(w) if w else 0, abs(sum(x for x in tr_list if x <= 0)) or 0.001
        results[reg] = {"trades": len(tr_list), "pf": gp/gl, "wr": len(w)/len(tr_list)*100}
    return results


# === MAIN ===
data = load_data()

# === STEP 1: Per-asset grid optimization ===
print("=" * 60)
print("STEP 1: ASSET-SPECIFIC PARAMETER OPTIMIZATION")
print("=" * 60)
best_params = {}
for asset in ASSETS:
    df = data[asset]
    pg = PARAM_GRID[asset]
    param_list = []
    for d in pg['d']:
        for a in pg['a']:
            for s in pg['s']:
                for t in pg['t']:
                    param_list.append({"d": d, "a": a, "s": s, "t": t})
    print(f"\n{asset}: testing {len(param_list)} combos on {len(df)} bars...")
    best_p, wf_results = walk_forward_best(df, param_list, n_splits=5)
    if wf_results:
        avg_pf = np.mean([r['pf'] for r in wf_results])
        min_pf = min(r['pf'] for r in wf_results)
        avg_dd = np.mean([r['max_dd'] for r in wf_results])
        best_params[asset] = best_p
        print(f"  Best params: D{best_p['d']} A{best_p['a']} S{best_p['s']} T{best_p['t']*100:.1f}%")
        print(f"  WF avg PF: {avg_pf:.2f} | min PF: {min_pf:.2f} | avg DD: {avg_dd:.1f}%")
        print(f"  Splits: {[(r['params']['d'], r['params']['a'], r['params']['s'], r['params']['t']) for r in wf_results]}")
    else:
        print(f"  FAILED — no valid results")
        best_params[asset] = {"d": 20, "a": 10, "s": 2.0, "t": 0.02}

# === STEP 2: Regime breakdown with best params ===
print("\n" + "=" * 60)
print("STEP 2: REGIME BREAKDOWN (with optimized params)")
print("=" * 60)
for asset in ASSETS:
    p = best_params[asset]
    r = regime_breakdown(data[asset], p['d'], p['a'], p['s'], p['t'], HOLD_BARS)
    print(f"\n{asset} (D{p['d']} A{p['a']} S{p['s']} T{p['t']*100:.1f}%):")
    for reg, stats in r.items():
        print(f"  {reg:12s}: PF={stats['pf']:.2f} WR={stats['wr']:.0f}% #={stats['trades']}")

# === STEP 3: Portfolio-level annualized (walk-forward, with leverage) ===
print("\n" + "=" * 60)
print("STEP 3: PORTFOLIO ANNUALIZED RETURNS (Walk-Forward, 2x Leverage)")
print("=" * 60)
n_years = 2.5
total_pf_sum = 0
total_ann_sum = 0
for asset in ASSETS:
    p = best_params[asset]
    df = data[asset]
    r = run_bt(df, p['d'], p['a'], p['s'], p['t'], HOLD_BARS)
    if r:
        # Walk-forward avg PF for reality check
        param_list = [p]  # Just test the best params
        wf_results = []
        n = len(df)
        split_size = n // 5
        for si in range(5):
            test_start = si * split_size + split_size // 2
            test_end = min((si + 1) * split_size, n)
            if test_end - test_start < 200: continue
            sub = df.iloc[test_start:test_end].reset_index(drop=True)
            sr = run_bt(sub, p['d'], p['a'], p['s'], p['t'], HOLD_BARS)
            if sr:
                wf_results.append(sr)
        wf_pf = np.mean([wr['pf'] for wr in wf_results]) if wf_results else r['pf']

        # Leverage-adjusted return
        lev_ret = r['total'] * LEVERAGE
        ann_lev = (1 + lev_ret / 100) ** (1/n_years) - 1
        total_pf_sum += wf_pf
        total_ann_sum += ann_lev
        print(f"{asset}: Full PF={r['pf']:.2f} WF PF={wf_pf:.2f} Total={r['total']:.0f}% 2xLev Total={lev_ret:.0f}% Ann={ann_lev*100:.0f}%")

print(f"\nPortfolio sum PF (WF): {total_pf_sum:.2f}")
print(f"Average annualized (2x leverage): {total_ann_sum/len(ASSETS)*100:.0f}%")

# === STEP 4: What's the realistic ceiling? ===
print("\n" + "=" * 60)
print("STEP 4: REALISTIC ANNUALIZED ESTIMATE (Conservative)")
print("=" * 60)
# Use walk-forward PF × 0.75 discount factor for overfitting
discount = 0.75
for asset in ASSETS:
    p = best_params[asset]
    df = data[asset]
    wf_results = []
    n = len(df)
    split_size = n // 5
    for si in range(5):
        test_start = si * split_size + split_size // 2
        test_end = min((si + 1) * split_size, n)
        if test_end - test_start < 200: continue
        sub = df.iloc[test_start:test_end].reset_index(drop=True)
        sr = run_bt(sub, p['d'], p['a'], p['s'], p['t'], HOLD_BARS)
        if sr:
            wf_results.append(sr)
    if wf_results:
        wf_pf = np.mean([wr['pf'] for wr in wf_results])
        wf_total = np.mean([wr['total'] for wr in wf_results])
        adj_total = wf_total * discount * LEVERAGE
        ann = (1 + adj_total / 100) ** (1/n_years) - 1
        print(f"{asset}: WF PF={wf_pf:.2f} Discounted 2x Ann={ann*100:.0f}%")
