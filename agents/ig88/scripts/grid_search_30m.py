#!/usr/bin/env python3
"""
30m Parameter Grid Search — native data, proper scaling.
Hypothesis: Donchian 20 @ 30m covers only 10h vs 20h @ 1h. Need equivalent lookback.

Tests:
1. Equivalent lookback: Donchian 40 @ 30m = Donchian 20 @ 1h (same 20h window)
2. Shorter: Donchian 20 @ 30m (10h) — maybe more responsive
3. Longer: Donchian 60 @ 30m (30h) — maybe smoother
4. ATR scaling: ATR 20 @ 30m = ATR 10 @ 1h (same 10h window)
5. Stop distance: 1.5x, 2.0x, 2.5x ATR
6. Trailing: 1.5%, 2.0%, 2.5%
7. Hybrid: 30m entry, 60m regime filter
"""

import numpy as np
import pandas as pd
from pathlib import Path
import json

DATA_DIR_30M = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/30m")
DATA_DIR_60M = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
OUT_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/grid_search_30m")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ASSETS = ["ETH", "AVAX", "SOL", "LINK", "NEAR"]
FRICTION = 0.0007
MAX_HOLD_H = 96


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


def run_backtest(df, donchian, atr_period, atr_mult, trail_pct, max_hold_bars):
    """Single-pass ATR BO backtest on full dataset."""
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
            new_trail = highest * (1 - trail_pct)
            stop_px = max(stop_px, new_trail)
            if c[i] <= stop_px or (i - entry_bar) >= max_hold_bars:
                trades.append((stop_px - entry_px) / entry_px - FRICTION)
                in_pos = False
        else:
            if i > 0 and c[i] > upper[i - 1]:
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

    # Max drawdown on equity curve
    equity = np.cumsum(trades)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    max_dd = np.max(dd) if len(dd) > 0 else 0

    return {
        "trades": len(trades),
        "pf": round(gp / gl, 2),
        "wr": round(len(wins) / len(trades) * 100, 1),
        "avg_ret": round(np.mean(trades) * 100, 3),
        "max_dd": round(max_dd * 100, 2),
        "total_ret": round(sum(trades) * 100, 1),
    }


# === GRID ===
# Core insight: at 30m, Donchian 40 ≈ Donchian 20 at 1h (same lookback hours)
# But maybe shorter/longer works better with 30m's finer granularity
PARAMS_GRID = {
    "donchian": [10, 20, 40, 60],
    "atr_period": [10, 20],
    "atr_mult": [1.5, 2.0, 2.5],
    "trail_pct": [0.015, 0.02, 0.025],
}

MAX_HOLD_30M = MAX_HOLD_H * 2  # 192 bars

# === MAIN ===
print("=== 30m Parameter Grid Search (Native Data) ===\n")

# Load 30m data
data_30m = {}
for asset in ASSETS:
    f30 = DATA_DIR_30M / f"binance_{asset}USDT_30m.parquet"
    if f30.exists():
        df = ensure_datetime(pd.read_parquet(f30)).sort_values('time').reset_index(drop=True)
        data_30m[asset] = df
        print(f"  {asset}: {len(df)} 30m bars loaded")

# Also load 60m for baseline
data_60m = {}
for asset in ASSETS:
    for f in DATA_DIR_60M.glob(f"*{asset}*_60m.parquet"):
        df = ensure_datetime(pd.read_parquet(f))
        if len(df) > data_60m.get(asset, pd.DataFrame()).shape[0]:
            data_60m[asset] = df

# Baseline: 60m with standard params
print("\n--- BASELINE: 60m Donchian 20 / ATR 10 / 2.0x / 2.0% ---")
for asset in ASSETS:
    if asset in data_60m:
        df = data_60m[asset]
        r = run_backtest(df, 20, 10, 2.0, 0.02, 96)
        if r:
            print(f"  {asset:5s}: PF={r['pf']:.2f} WR={r['wr']:.1f}% Trades={r['trades']}")

# Grid search on 30m
print("\n--- GRID SEARCH: 30m ---")
total_combos = len(PARAMS_GRID['donchian']) * len(PARAMS_GRID['atr_period']) * len(PARAMS_GRID['atr_mult']) * len(PARAMS_GRID['trail_pct'])
print(f"Testing {total_combos} combinations × {len(ASSETS)} assets\n")

all_results = {}

for dc in PARAMS_GRID['donchian']:
    for ap in PARAMS_GRID['atr_period']:
        for am in PARAMS_GRID['atr_mult']:
            for tp in PARAMS_GRID['trail_pct']:
                key = f"D{dc}_A{ap}_S{am}_T{tp}"
                asset_results = {}
                all_pass = True

                for asset in ASSETS:
                    if asset not in data_30m:
                        continue
                    r = run_backtest(data_30m[asset], dc, ap, am, tp, MAX_HOLD_30M)
                    if r and r['trades'] >= 20:
                        asset_results[asset] = r
                    else:
                        all_pass = False

                if len(asset_results) >= 3:
                    avg_pf = np.mean([r['pf'] for r in asset_results.values()])
                    min_pf = min(r['pf'] for r in asset_results.values())
                    all_results[key] = {
                        "params": {"donchian": dc, "atr": ap, "atr_mult": am, "trail": tp},
                        "avg_pf": round(avg_pf, 2),
                        "min_pf": round(min_pf, 2),
                        "assets": asset_results,
                    }

# Sort by average PF
sorted_results = sorted(all_results.items(), key=lambda x: x[1]['avg_pf'], reverse=True)

print(f"=== TOP 20 COMBINATIONS (by avg PF) ===\n")
print(f"{'Rank':4s} {'Params':20s} {'AvgPF':6s} {'MinPF':6s}", end="")
for a in ASSETS:
    print(f" {a:5s}", end="")
print()
print("-" * 75)

for i, (key, res) in enumerate(sorted_results[:20]):
    p = res['params']
    label = f"D{p['donchian']} A{p['atr']} S{p['atr_mult']} T{p['trail']*100:.0f}%"
    print(f"{i+1:4d} {label:20s} {res['avg_pf']:6.2f} {res['min_pf']:6.2f}", end="")
    for a in ASSETS:
        pf = res['assets'].get(a, {}).get('pf', 0)
        print(f" {pf:5.2f}", end="")
    print()

# Compare best 30m vs baseline 60m
print("\n=== BEST 30m vs BASELINE 60m ===\n")
if sorted_results:
    best_key, best = sorted_results[0]
    p = best['params']
    print(f"Best 30m: D{p['donchian']} A{p['atr']} S{p['atr_mult']} T{p['trail']*100:.0f}%")
    print(f"{'Asset':6s} {'60m PF':8s} {'30m PF':8s} {'Winner':8s}")
    print("-" * 35)
    for asset in ASSETS:
        # 60m baseline
        r60 = run_backtest(data_60m.get(asset, pd.DataFrame()), 20, 10, 2.0, 0.02, 96) if asset in data_60m else None
        r30 = best['assets'].get(asset)
        pf60 = r60['pf'] if r60 else 0
        pf30 = r30['pf'] if r30 else 0
        winner = "30m" if pf30 > pf60 else "60m" if pf60 > pf30 else "TIE"
        print(f"{asset:6s} {pf60:8.2f} {pf30:8.2f} {winner:8s}")

# Save results
with open(OUT_DIR / "grid_results.json", "w") as f:
    json.dump(sorted_results[:50], f, indent=2, default=str)
print(f"\nTop 50 saved to {OUT_DIR / 'grid_results.json'}")
