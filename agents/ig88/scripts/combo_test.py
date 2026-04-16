#!/usr/bin/env python3
"""Combinatorial indicator test for ETH ATR breakout strategy."""

import pandas as pd
import numpy as np
import json
from pathlib import Path

# ── Load data ──────────────────────────────────────────────────────────────
DATA_PATH = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h/binance_ETHUSDT_60m.parquet")
OUT_PATH = Path("/Users/nesbitt/dev/factory/agents/ig88/data/indicator_combos.json")

df = pd.read_parquet(DATA_PATH)
df['time'] = pd.to_datetime(df['time'], unit='s')
df = df.sort_values('time').reset_index(drop=True)
print(f"Loaded {len(df)} bars: {df['time'].iloc[0]} → {df['time'].iloc[-1]}")

# ── Compute all indicators ─────────────────────────────────────────────────
# Donchian(20) - use high/low channels
df['dc_upper'] = df['high'].rolling(20).max()
df['dc_lower'] = df['low'].rolling(20).min()

# True Range & ATR(10)
df['prev_close'] = df['close'].shift(1)
df['tr'] = np.maximum(
    df['high'] - df['low'],
    np.maximum(
        abs(df['high'] - df['prev_close']),
        abs(df['low'] - df['prev_close'])
    )
)
df['atr'] = df['tr'].rolling(10).mean()

# Volume SMA(20) for volume filter
df['vol_sma20'] = df['volume'].rolling(20).mean()

# ADX(14)
def compute_adx(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0.0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0.0)
    tr = df['tr'].values
    # smoothed
    atr_s = pd.Series(tr).rolling(period).sum()
    plus_di = 100 * pd.Series(plus_dm).rolling(period).sum() / atr_s
    minus_di = 100 * pd.Series(minus_dm).rolling(period).sum() / atr_s
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(period).mean()
    return adx

df['adx'] = compute_adx(df, 14)

# RSI(14)
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))

df['rsi'] = compute_rsi(df['close'], 14)

# SMA(50)
df['sma50'] = df['close'].rolling(50).mean()

print("Indicators computed.")

# ── Define filter conditions (all as boolean series) ───────────────────────
# Each filter is a function that returns a boolean Series for "filter passes"
filters = {
    "baseline": lambda d: pd.Series(True, index=d.index),
    "volume": lambda d: d['volume'] > 1.5 * d['vol_sma20'],
    "adx": lambda d: d['adx'] > 25,
    "rsi": lambda d: d['rsi'] < 70,
    "sma50": lambda d: d['close'] > d['sma50'],
    "volume+adx": lambda d: (d['volume'] > 1.5 * d['vol_sma20']) & (d['adx'] > 25),
    "volume+rsi": lambda d: (d['volume'] > 1.5 * d['vol_sma20']) & (d['rsi'] < 70),
    "all": lambda d: (d['volume'] > 1.5 * d['vol_sma20']) & (d['adx'] > 25) & (d['rsi'] < 70) & (d['close'] > d['sma50']),
}

# ── Backtest engine ────────────────────────────────────────────────────────
def backtest(df_slice, filter_fn):
    """
    Donchian(20) breakout, ATR(10) initial stop, 2% trailing, 96h max hold.
    Close-based stops (stop checked at close, exit at next bar open).
    """
    n = len(df_slice)
    op = df_slice['open'].values
    hi = df_slice['high'].values
    lo = df_slice['low'].values
    cl = df_slice['close'].values
    dc_up = df_slice['dc_upper'].values
    atr_v = df_slice['atr'].values
    filt = filter_fn(df_slice).values

    trades = []
    in_pos = False
    entry_price = 0.0
    stop_price = 0.0
    entry_bar = 0
    trail_pct = 0.02
    max_hold = 96  # bars

    for i in range(20, n):  # need enough history for indicators
        if in_pos:
            # Update trailing stop: 2% below highest close since entry
            highest_since_entry = np.max(cl[entry_bar:i+1])
            trail_stop = highest_since_entry * (1 - trail_pct)
            stop_price = max(stop_price, trail_stop)

            # Check stop hit at close
            hit_stop = cl[i] <= stop_price
            hit_time = (i - entry_bar) >= max_hold

            if hit_stop or hit_time:
                exit_price = op[i+1] if i+1 < n else cl[i]
                pnl_pct = (exit_price - entry_price) / entry_price
                trades.append(pnl_pct)
                in_pos = False

        if not in_pos and i < n - 1:
            # Entry: close breaks above Donchian upper
            if cl[i] > dc_up[i-1] and filt[i]:
                entry_price = op[i+1] if i+1 < n else cl[i]
                stop_price = entry_price - atr_v[i]  # ATR initial stop
                entry_bar = i + 1
                in_pos = True

    # If still in position at end, close at last price
    if in_pos:
        exit_price = cl[-1]
        pnl_pct = (exit_price - entry_price) / entry_price
        trades.append(pnl_pct)

    return trades

# ── Walk-forward split runner ──────────────────────────────────────────────
def run_walk_forward(df, filter_fn, train_pct):
    """
    Use first train_pct% for parameter validation (we keep params fixed),
    test on remaining. Report test-period stats.
    """
    split_idx = int(len(df) * train_pct / 100)
    # We run on full data but only report results from the test portion
    # To keep it simple: run on test period only (need prior 20 bars for Donchian)
    n = len(df)
    test_start = max(split_idx, 20)  # ensure enough lookback
    df_test = df.iloc[test_start:].copy().reset_index(drop=True)
    if len(df_test) < 100:
        return None

    trades = backtest(df_test, filter_fn)
    if len(trades) == 0:
        return {"trades": 0, "pf": 0.0, "avg_pnl": 0.0, "win_rate": 0.0, "total_return": 0.0}

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 1e-10
    pf = gross_profit / gross_loss if gross_loss > 0 else 0.0

    return {
        "trades": len(trades),
        "pf": round(pf, 4),
        "avg_pnl": round(np.mean(trades) * 100, 4),
        "win_rate": round(len(wins) / len(trades) * 100, 2),
        "total_return": round(sum(trades) * 100, 4),
    }

# ── Run all combinations ───────────────────────────────────────────────────
walk_forward_pcts = [50, 60, 70, 80]
results = {}

for filter_name, filter_fn in filters.items():
    results[filter_name] = {}
    for wf_pct in walk_forward_pcts:
        stats = run_walk_forward(df, filter_fn, wf_pct)
        if stats:
            results[filter_name][f"wf_{wf_pct}pct"] = stats
    print(f"Done: {filter_name} → {results[filter_name]}")

# ── Compute improvement vs baseline ────────────────────────────────────────
baseline = results.get("baseline", {})
report = {}

for filter_name, wf_results in results.items():
    report[filter_name] = {}
    for wf_key, stats in wf_results.items():
        bl = baseline.get(wf_key, {})
        bl_pf = bl.get("pf", 0)
        pf_val = stats["pf"]
        improvement = round(pf_val - bl_pf, 4)
        pct_improvement = round((pf_val - bl_pf) / bl_pf * 100, 2) if bl_pf > 0 else 0

        report[filter_name][wf_key] = {
            **stats,
            "baseline_pf": bl_pf,
            "pf_improvement": improvement,
            "pf_improvement_pct": pct_improvement,
        }

# ── Save results ───────────────────────────────────────────────────────────
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_PATH, 'w') as f:
    json.dump(report, f, indent=2)
print(f"\nResults saved to {OUT_PATH}")

# ── Print summary table ────────────────────────────────────────────────────
print("\n" + "=" * 100)
print(f"{'Filter':<16} {'WF%':<6} {'Trades':>7} {'PF':>8} {'WinRate':>8} {'AvgPnL':>8} {'vsBase':>8} {'Improv%':>8}")
print("=" * 100)
for filter_name in filters:
    for wf_pct in walk_forward_pcts:
        wf_key = f"wf_{wf_pct}pct"
        r = report.get(filter_name, {}).get(wf_key, {})
        if not r:
            continue
        print(f"{filter_name:<16} {wf_pct:<6} {r.get('trades',0):>7} {r.get('pf',0):>8.2f} {r.get('win_rate',0):>7.1f}% {r.get('avg_pnl',0):>7.3f}% {r.get('pf_improvement',0):>+8.4f} {r.get('pf_improvement_pct',0):>+7.1f}%")
    print("-" * 100)
