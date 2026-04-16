#!/usr/bin/env python3
"""
Fair comparison: 30m vs 60m on the SAME time window (2023-06 to 2026-04).
This eliminates the "different market regime" confound.
"""

import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR_30M = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/30m")
DATA_DIR_60M = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

ASSETS = ["ETH", "AVAX", "SOL", "LINK", "NEAR"]

DONCHIAN_PERIOD = 20
ATR_PERIOD = 10
ATR_MULT_STOP = 2.0
TRAIL_PCT = 0.02
FRICTION = 0.0007

MAX_HOLD_60M = 96
MAX_HOLD_30M = 192


def ensure_datetime(df: pd.DataFrame) -> pd.DataFrame:
    if 'time' not in df.columns:
        df = df.reset_index()
        for col in ['timestamp', 'datetime', 'index', 'level_0']:
            if col in df.columns:
                df = df.rename(columns={col: 'time'})
                break
    if 'time' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['time']):
        if df['time'].dtype == 'int64':
            sample = df['time'].iloc[0]
            unit = 'ms' if sample > 1e12 else 's'
            df['time'] = pd.to_datetime(df['time'], unit=unit)
    return df


def run_wf(df, max_hold, friction):
    n = len(df)
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    c = df['close'].values.astype(float)

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(DONCHIAN_PERIOD - 1, n):
        upper[i] = np.max(h[i - DONCHIAN_PERIOD + 1: i + 1])
        lower[i] = np.min(l[i - DONCHIAN_PERIOD + 1: i + 1])

    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))

    atr = np.full(n, np.nan)
    for i in range(ATR_PERIOD, n):
        atr[i] = np.mean(tr[i - ATR_PERIOD + 1: i + 1])

    # Single walk-forward: use all data as test (enough bars)
    trades = []
    in_pos = False
    entry_px = stop_px = highest = 0.0
    entry_bar = 0

    start = max(DONCHIAN_PERIOD + 2, ATR_PERIOD + 2, 50)

    for i in range(start, n):
        if np.isnan(upper[i]) or np.isnan(atr[i]):
            continue
        if in_pos:
            if c[i] > highest: highest = c[i]
            stop_px = max(stop_px, highest * (1 - TRAIL_PCT))
            if c[i] <= stop_px or (i - entry_bar) >= max_hold:
                trades.append((stop_px - entry_px) / entry_px - friction)
                in_pos = False
        else:
            if i > 0 and c[i] > upper[i-1]:
                in_pos = True
                entry_px = c[i]
                stop_px = entry_px - ATR_MULT_STOP * atr[i]
                highest = c[i]
                entry_bar = i

    if not trades:
        return {"trades": 0, "pf": 0, "wr": 0}

    wins = [t for t in trades if t > 0]
    gp = sum(wins) if wins else 0
    gl = abs(sum(t for t in trades if t <= 0)) or 0.001
    return {
        "trades": len(trades),
        "pf": round(gp / gl, 2),
        "wr": round(len(wins) / len(trades) * 100, 1),
        "avg_ret": round(np.mean(trades) * 100, 3),
    }


# === MAIN ===
print("=== FAIR COMPARISON: 30m vs 60m on SAME window (2023-06 to 2026-04) ===\n")

for asset in ASSETS:
    f60 = None
    best_len = 0
    for f in DATA_DIR_60M.glob(f"*{asset}*_60m.parquet"):
        tmp = pd.read_parquet(f)
        if len(tmp) > best_len:
            best_len = len(tmp)
            f60 = f

    f30 = DATA_DIR_30M / f"binance_{asset}USDT_30m.parquet"
    if not f60 or not f30.exists():
        continue

    df60 = ensure_datetime(pd.read_parquet(f60)).sort_values('time').reset_index(drop=True)
    df30 = ensure_datetime(pd.read_parquet(f30)).sort_values('time').reset_index(drop=True)

    # Trim 60m to same window as 30m
    start_30 = df30['time'].iloc[0]
    end_30 = df30['time'].iloc[-1]
    df60_trimmed = df60[(df60['time'] >= start_30) & (df60['time'] <= end_30)].reset_index(drop=True)

    print(f"\n{asset}:")
    print(f"  30m window: {start_30.strftime('%Y-%m-%d')} to {end_30.strftime('%Y-%m-%d')}")
    print(f"  60m trimmed: {len(df60_trimmed)} bars (was {len(df60)})")
    print(f"  30m: {len(df30)} bars")

    r60 = run_wf(df60_trimmed, MAX_HOLD_60M, FRICTION)
    r30 = run_wf(df30, MAX_HOLD_30M, FRICTION)

    pf60 = r60['pf']
    pf30 = r30['pf']
    delta = ((pf30 / pf60) - 1) * 100 if pf60 > 0 else 0

    print(f"  60m: PF={pf60:.2f} WR={r60['wr']:.1f}% Trades={r60['trades']}")
    print(f"  30m: PF={pf30:.2f} WR={r30['wr']:.1f}% Trades={r30['trades']}")
    print(f"  30m vs 60m: {delta:+.0f}%")

print("\n" + "=" * 60)
print("This is the REAL test — same time window, same market regime.")
