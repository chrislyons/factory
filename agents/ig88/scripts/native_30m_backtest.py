#!/usr/bin/env python3
"""
ATR Breakout Walk-Forward on Native 30m Data.
Direct comparison: 30m native vs 60m native.
No resampling tricks.
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
FRICTION = 0.0007  # Hyperliquid RT

# Max hold in BARS (not hours)
MAX_HOLD_60M = 96    # 96 hours = 96 bars on 1h
MAX_HOLD_30M = 192   # 192 × 30min = 96 hours (same wall-clock time)


def run_wf(df: pd.DataFrame, max_hold_bars: int, friction: float, label: str) -> dict:
    """Walk-forward ATR BO backtest."""
    n = len(df)
    highs = df['high'].values.astype(float)
    lows = df['low'].values.astype(float)
    closes = df['close'].values.astype(float)

    # Donchian
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(DONCHIAN_PERIOD - 1, n):
        upper[i] = np.max(highs[i - DONCHIAN_PERIOD + 1: i + 1])
        lower[i] = np.min(lows[i - DONCHIAN_PERIOD + 1: i + 1])

    # True Range
    tr = np.zeros(n)
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    atr = np.full(n, np.nan)
    for i in range(ATR_PERIOD, n):
        atr[i] = np.mean(tr[i - ATR_PERIOD + 1: i + 1])

    # Walk-forward: 5 splits, train on first half of each split, test on second half
    min_bars = 2000
    if n < min_bars * 2:
        return {"trades": 0, "pf": 0, "label": label, "splits": 0}

    split_size = n // 5
    split_results = []

    for split in range(5):
        train_start = split * split_size
        test_start = train_start + split_size // 2
        test_end = min((split + 1) * split_size, n)

        if test_end - test_start < 200:
            continue

        trades = []
        in_pos = False
        entry_px = 0.0
        stop_px = 0.0
        highest = 0.0
        entry_bar = 0

        for i in range(test_start, test_end):
            if np.isnan(upper[i]) or np.isnan(atr[i]):
                continue

            if in_pos:
                if closes[i] > highest:
                    highest = closes[i]
                new_trail = highest * (1 - TRAIL_PCT)
                stop_px = max(stop_px, new_trail)

                bars_held = i - entry_bar
                if closes[i] <= stop_px or bars_held >= max_hold_bars:
                    ret = (stop_px - entry_px) / entry_px - friction
                    trades.append(ret)
                    in_pos = False
            else:
                if i > 0 and closes[i] > upper[i - 1]:
                    in_pos = True
                    entry_px = closes[i]
                    stop_px = entry_px - ATR_MULT_STOP * atr[i]
                    highest = closes[i]
                    entry_bar = i

        if trades:
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            gp = sum(wins) if wins else 0
            gl = abs(sum(losses)) if losses else 0.001
            pf = gp / gl

            split_results.append({
                "trades": len(trades),
                "wr": len(wins) / len(trades) * 100,
                "pf": pf,
                "avg_ret": np.mean(trades) * 100,
            })

    if not split_results:
        return {"trades": 0, "pf": 0, "label": label, "splits": 0}

    return {
        "trades": sum(s["trades"] for s in split_results),
        "avg_pf": round(np.mean([s["pf"] for s in split_results]), 2),
        "min_pf": round(min(s["pf"] for s in split_results), 2),
        "max_pf": round(max(s["pf"] for s in split_results), 2),
        "avg_wr": round(np.mean([s["wr"] for s in split_results]), 1),
        "avg_ret": round(np.mean([s["avg_ret"] for s in split_results]), 3),
        "splits": len(split_results),
        "label": label,
    }


# === MAIN ===
print("=== ATR BO: Native 30m vs Native 60m Walk-Forward ===\n")
print(f"Params: Donchian={DONCHIAN_PERIOD}, ATR={ATR_PERIOD}, Stop={ATR_MULT_STOP}x, Trail={TRAIL_PCT*100}%")
print(f"Friction: {FRICTION*100:.2f}% RT (Hyperliquid)")
print(f"Max hold: 96 wall-clock hours (96 bars @1h, 192 bars @30m)\n")

def ensure_datetime(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure df has a 'time' column (not just index)."""
    if 'time' not in df.columns:
        df = df.reset_index()
        for col in ['timestamp', 'datetime', 'index', 'level_0']:
            if col in df.columns:
                df = df.rename(columns={col: 'time'})
                break
    # If still no time, try index name
    if 'time' not in df.columns and df.index.name in ['timestamp', 'datetime']:
        df = df.reset_index()
        df = df.rename(columns={df.columns[0]: 'time'})
    if 'time' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['time']):
        if df['time'].dtype == 'int64':
            sample = df['time'].iloc[0]
            unit = 'ms' if sample > 1e12 else 's'
            df['time'] = pd.to_datetime(df['time'], unit=unit)
    return df

for asset in ASSETS:
    # Find 60m file — prioritize longest (most bars)
    f60 = None
    best_len = 0
    for f in DATA_DIR_60M.glob(f"*{asset}*_60m.parquet"):
        try:
            tmp = pd.read_parquet(f)
            if len(tmp) > best_len:
                best_len = len(tmp)
                f60 = f
        except:
            pass

    # Find 30m file
    f30 = DATA_DIR_30M / f"binance_{asset}USDT_30m.parquet"

    if not f60 or not f30.exists():
        print(f"{asset}: missing data file")
        continue

    df60 = pd.read_parquet(f60)
    df30 = pd.read_parquet(f30)
    df60 = ensure_datetime(df60).sort_values('time').reset_index(drop=True)
    df30 = ensure_datetime(df30).sort_values('time').reset_index(drop=True)

    print(f"\n{asset}:")
    print(f"  60m: {len(df60)} bars ({df60['time'].iloc[0].strftime('%Y-%m-%d')} to {df60['time'].iloc[-1].strftime('%Y-%m-%d')})")
    print(f"  30m: {len(df30)} bars ({df30['time'].iloc[0].strftime('%Y-%m-%d')} to {df30['time'].iloc[-1].strftime('%Y-%m-%d')})")

    r60 = run_wf(df60, MAX_HOLD_60M, FRICTION, f"{asset}_60m")
    r30 = run_wf(df30, MAX_HOLD_30M, FRICTION, f"{asset}_30m")

    pf60 = r60.get('avg_pf', 0)
    pf30 = r30.get('avg_pf', 0)
    improvement = ((pf30 / pf60) - 1) * 100 if pf60 > 0 else 0

    print(f"  60m native: PF={pf60:.2f} | MinPF={r60.get('min_pf', 0):.2f} | WR={r60.get('avg_wr', 0):.1f}% | Trades={r60.get('trades', 0)}")
    print(f"  30m native: PF={pf30:.2f} | MinPF={r30.get('min_pf', 0):.2f} | WR={r30.get('avg_wr', 0):.1f}% | Trades={r30.get('trades', 0)}")
    print(f"  30m vs 60m: {improvement:+.0f}%")

print("\n" + "=" * 60)
print("VERDICT:")
print("If 30m native PF > 60m native PF by >10%, the timeframe improvement is REAL.")
print("If <10%, the resampled test was noise — stay on 60m.")
