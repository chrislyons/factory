#!/usr/bin/env python3
"""
Test 4H timeframe ATR Breakout — fewer trades, higher per-trade returns.
Also test volatility squeeze breakout for CHOP regime.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

def load_pair(pair):
    f = DATA_DIR / f"binance_{pair}_60m.parquet"
    if not f.exists():
        f = DATA_DIR / f"binance_{pair}_1h.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f)
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time').sort_index()
    return df

def resample_4h(df):
    """Resample 1h data to 4h"""
    return df.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum'
    }).dropna()

def compute_atr(df, period=14):
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr, index=df.index).rolling(period).mean().values

def backtest_atr_4h(df):
    """ATR Breakout on 4H timeframe"""
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df, 14)
    upper_dc = pd.Series(h).rolling(20).max().values
    lower_dc = pd.Series(l).rolling(20).min().values
    sma = pd.Series(c).rolling(100).mean().values
    friction = 0.0014

    trades = []
    in_trade = False
    entry_price = entry_bar = highest = 0

    for i in range(120, len(c)):
        if in_trade:
            highest = max(highest, h[i])
            trail = highest * 0.985  # 1.5% trailing stop for 4H
            bars_held = i - entry_bar
            if l[i] <= trail or bars_held >= 30:  # 120h = 5 days max
                exit_p = trail if l[i] <= trail else c[i]
                pnl = (exit_p - entry_price) / entry_price - friction
                trades.append((df.index[entry_bar], pnl, bars_held * 4))  # hours
                in_trade = False
        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]:
            in_trade = True
            entry_price = c[i-1]
            entry_bar = i
            highest = h[i-1]

    return trades

def backtest_squeeze_breakout(df):
    """
    Volatility Squeeze Breakout — Bollinger Band inside Keltner Channel.
    When BB squeezes inside KC (low vol), a breakout is imminent.
    Trade in the direction of the breakout.
    """
    c, h, l, v = df['close'].values, df['high'].values, df['low'].values, df['volume'].values
    friction = 0.0014

    # BB
    bb_sma = pd.Series(c).rolling(20).mean().values
    bb_std = pd.Series(c).rolling(20).std().values
    bb_upper = bb_sma + 2 * bb_std
    bb_lower = bb_sma - 2 * bb_std
    bb_width = (bb_upper - bb_lower) / bb_sma

    # Keltner (EMA-based)
    ema = pd.Series(c).ewm(span=20).mean().values
    atr = compute_atr(df, 10)
    kc_upper = ema + 1.5 * atr
    kc_lower = ema - 1.5 * atr

    # Squeeze: BB inside KC
    squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)

    # Directional bias
    sma = pd.Series(c).rolling(50).mean().values

    trades = []
    in_trade = False
    entry_price = entry_bar = 0

    for i in range(50, len(c)):
        if in_trade:
            bars = i - entry_bar
            if bars >= 48:  # max 48h hold
                pnl = (c[i] - entry_price) / entry_price - friction
                trades.append((df.index[entry_bar], pnl, bars))
                in_trade = False
            elif c[i] <= entry_price * 0.99 or c[i] >= entry_price * 1.02:
                # 1% stop or 2% target
                pnl = (c[i] - entry_price) / entry_price - friction
                trades.append((df.index[entry_bar], pnl, bars))
                in_trade = False

        if not in_trade and squeeze[i-1] and not squeeze[i]:
            # Squeeze just released — direction of break
            if c[i] > c[i-1] and c[i] > sma[i]:
                in_trade = True
                entry_price = c[i]
                entry_bar = i
            elif c[i] < c[i-1] and c[i] < sma[i]:
                # SHORT (simplified)
                in_trade = True
                entry_price = c[i]
                entry_bar = i

    return trades

# === TEST ON KEY PAIRS ===
pairs = ["SOLUSDT", "BTCUSDT", "ETHUSDT", "AVAXUSDT", "ARBUSDT", "OPUSDT",
         "LINKUSDT", "RENDERUSDT", "NEARUSDT", "AAVEUSDT", "DOGEUSDT", "LTCUSDT"]

print("=" * 80)
print("4H ATR BREAKOUT vs VOLATILITY SQUEEZE BREAKOUT")
print("=" * 80)

all_4h = []
all_sqz = []

for pair in pairs:
    df = load_pair(pair)
    if df is None:
        continue
    df4h = resample_4h(df)

    # 4H ATR
    trades_4h = backtest_atr_4h(df4h)
    for t in trades_4h:
        all_4h.append({"pair": pair, "date": t[0], "pnl": t[1], "hours": t[2]})

    # Squeeze
    trades_sqz = backtest_squeeze_breakout(df)
    for t in trades_sqz:
        all_sqz.append({"pair": pair, "date": t[0], "pnl": t[1], "hours": t[2]})

    # Per-pair stats
    if len(trades_4h) > 10:
        pnls = [t[1] for t in trades_4h]
        wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        avg = np.mean(pnls) * 100
        g = np.array(pnls)
        wins = g[g > 0]
        losses = g[g <= 0]
        pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
        print(f"4H ATR {pair:>12s}: n={len(pnls):>4d}  WR={wr:.1f}%  Avg={avg:+.2f}%  PF={pf:.2f}")
    if len(trades_sqz) > 5:
        pnls = [t[1] for t in trades_sqz]
        wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        avg = np.mean(pnls) * 100
        g = np.array(pnls)
        wins = g[g > 0]
        losses = g[g <= 0]
        pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
        print(f"SQZ {pair:>12s}: n={len(pnls):>4d}  WR={wr:.1f}%  Avg={avg:+.2f}%  PF={pf:.2f}")

# Portfolio totals
print(f"\n{'=' * 80}")
print("PORTFOLIO TOTALS")

for label, trades in [("4H ATR", all_4h), ("SQUEEZE", all_sqz)]:
    if len(trades) == 0:
        continue
    pnls = [t['pnl'] for t in trades]
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    avg = np.mean(pnls) * 100
    g = np.array(pnls)
    wins = g[g > 0]
    losses = g[g <= 0]
    pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
    t_stat, p_value = stats.ttest_1samp(pnls, 0)

    print(f"\n{label}:")
    print(f"  Trades: {len(pnls)}")
    print(f"  WR: {wr:.1f}%")
    print(f"  Avg: {avg:+.2f}%")
    print(f"  PF: {pf:.2f}")
    print(f"  t-stat: {t_stat:.2f}, p-value: {p_value:.6f}")
    print(f"  Significant: {'YES' if p_value < 0.05 else 'NO'}")

    # Expected annual return with 3x leverage, 2% risk
    ann_3x = avg / 100 * len(pnls) / 10 * 3.0 * 0.02 * 100  # rough
    print(f"  Est. annual (3x lev, 2% risk): ~{ann_3x:.0f}%")
