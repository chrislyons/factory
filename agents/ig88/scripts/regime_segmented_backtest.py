#!/usr/bin/env python3
"""
Regime-Segmented Backtest: How do LONG and SHORT strategies perform
in bull, bear, and choppy markets?

Defines regimes using BTC SMA50/SMA200 crossover:
- BULL: BTC close > SMA50 > SMA200
- BEAR: BTC close < SMA50 < SMA200
- CHOP: Everything else

Then backtests ATR BO LONG and SHORT in each regime segment.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

DONCHIAN = 20
ATR_PERIOD = 10
ATR_MULT_SHORT = 1.5
TRAIL_LONG = 0.01
TRAIL_SHORT = 0.025
MAX_HOLD_LONG = 96
MAX_HOLD_SHORT = 48
FRICTION = 0.0014
SMA_REGIME = 100


def load_pair(pair):
    for pat in [f"binance_{pair}_60m.parquet", f"binance_{pair}_1h.parquet"]:
        f = DATA_DIR / pat
        if f.exists():
            df = pd.read_parquet(f)
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df = df.set_index('time').sort_index()
                return df
    return None


def compute_atr(df):
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr, index=df.index).rolling(ATR_PERIOD).mean().values


def classify_regimes(btc_df):
    """Classify each bar as BULL, BEAR, or CHOP using BTC SMA50/200."""
    c = btc_df['close'].values
    sma50 = pd.Series(c).rolling(50).mean().values
    sma200 = pd.Series(c).rolling(200).mean().values

    regimes = []
    for i in range(len(c)):
        if i < 200:
            regimes.append("UNKNOWN")
        elif c[i] > sma50[i] > sma200[i]:
            regimes.append("BULL")
        elif c[i] < sma50[i] < sma200[i]:
            regimes.append("BEAR")
        else:
            regimes.append("CHOP")
    return pd.Series(regimes, index=btc_df.index)


def run_long(df, regime_series):
    """Run ATR BO LONG and tag each trade with its regime."""
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    upper = pd.Series(h).rolling(DONCHIAN).max().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values

    trades = []
    in_trade = False
    entry_price = entry_bar = highest = 0
    entry_regime = ""

    for i in range(max(DONCHIAN, SMA_REGIME, 200) + 1, len(c)):
        if in_trade:
            highest = max(highest, h[i])
            trail = highest * (1 - TRAIL_LONG)
            hours = i - entry_bar
            if hours < 4 and atr[i] > 0:
                trail = max(trail, entry_price - atr[i] * 1.5)
            if l[i] <= trail or hours >= MAX_HOLD_LONG:
                exit_p = trail if l[i] <= trail else c[i]
                pnl = (exit_p - entry_price) / entry_price - FRICTION
                trades.append({"pnl": pnl, "regime": entry_regime,
                               "entry_bar": entry_bar, "exit_bar": i})
                in_trade = False

        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper[i-2]:
            in_trade = True
            entry_price = c[i-1]
            entry_bar = i
            highest = h[i-1]
            # Get regime at entry (use BTC regime if available)
            if i < len(regime_series):
                entry_regime = regime_series.iloc[i]
            else:
                entry_regime = "UNKNOWN"

    return trades


def run_short(df, regime_series):
    """Run ATR BO SHORT and tag each trade with its regime."""
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    lower = pd.Series(l).rolling(DONCHIAN).min().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values

    trades = []
    in_trade = False
    entry_price = entry_bar = lowest = 0
    entry_regime = ""

    for i in range(max(DONCHIAN, SMA_REGIME, 200) + 1, len(c)):
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * (1 + TRAIL_SHORT)
            hours = i - entry_bar
            if h[i] >= trail or hours >= MAX_HOLD_SHORT:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                trades.append({"pnl": pnl, "regime": entry_regime,
                               "entry_bar": entry_bar, "exit_bar": i})
                in_trade = False

        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower[i-2] - atr[i-1] * ATR_MULT_SHORT
            if c[i-1] < trigger:
                in_trade = True
                entry_price = c[i-1]
                entry_bar = i
                lowest = l[i-1]
                if i < len(regime_series):
                    entry_regime = regime_series.iloc[i]
                else:
                    entry_regime = "UNKNOWN"

    return trades


def summarize_trades(trades, label):
    if not trades:
        print(f"  {label}: 0 trades")
        return
    pnls = [t['pnl'] for t in trades]
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else float('inf')
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    avg = np.mean(pnls) * 100
    total_ret = (np.prod([1+p for p in pnls]) - 1) * 100
    print(f"  {label:20s}: n={len(trades):4d}  PF={pf:5.2f}  WR={wr:5.1f}%  Avg={avg:+.2f}%  Cumul={total_ret:+.1f}%")


# === MAIN ===
print("=" * 90)
print("REGIME-SEGMENTED BACKTEST — ATR Breakout LONG and SHORT")
print("=" * 90)

# Load BTC for regime classification
btc = load_pair("BTCUSDT")
if btc is None:
    print("FATAL: No BTC data")
    exit(1)

btc_regimes = classify_regimes(btc)

# Print regime distribution
print(f"\nBTC regime distribution (full history, {len(btc)} bars):")
for r in ["BULL", "BEAR", "CHOP", "UNKNOWN"]:
    n = (btc_regimes == r).sum()
    pct = n / len(btc_regimes) * 100
    print(f"  {r:8s}: {n:6d} bars ({pct:.1f}%)")

# Regime periods (approximate dates)
print("\nApproximate regime periods:")
current = None
start_idx = 0
for i in range(200, len(btc_regimes)):
    if btc_regimes.iloc[i] != current:
        if current is not None:
            start_date = btc.index[start_idx].strftime('%Y-%m-%d')
            end_date = btc.index[i-1].strftime('%Y-%m-%d')
            bars = i - start_idx
            print(f"  {current:8s}  {start_date} → {end_date}  ({bars} bars)")
        current = btc_regimes.iloc[i]
        start_idx = i

# Final period
start_date = btc.index[start_idx].strftime('%Y-%m-%d')
end_date = btc.index[-1].strftime('%Y-%m-%d')
print(f"  {current:8s}  {start_date} → {end_date}  ({len(btc)-start_idx} bars)")

# Run backtests on key assets
ASSETS = [
    ("ETHUSDT", "LONG"), ("ETHUSDT", "SHORT"),
    ("AVAXUSDT", "LONG"), ("AVAXUSDT", "SHORT"),
    ("LINKUSDT", "LONG"), ("LINKUSDT", "SHORT"),
    ("SOLUSDT", "LONG"), ("SOLUSDT", "SHORT"),
    ("ARBUSDT", "SHORT"), ("OPUSDT", "SHORT"),
    ("DOGEUSDT", "LONG"), ("LTCUSDT", "LONG"),
]

print("\n\n" + "=" * 90)
print("PERFORMANCE BY REGIME (trades entered during each regime)")
print("=" * 90)

for pair, direction in ASSETS:
    df = load_pair(pair)
    if df is None:
        continue

    # Align regime series to pair's index
    regime_aligned = btc_regimes.reindex(df.index, method='ffill')

    if direction == "LONG":
        trades = run_long(df, regime_aligned)
    else:
        trades = run_short(df, regime_aligned)

    print(f"\n{pair} {direction}:")
    summarize_trades(trades, "ALL")

    for regime in ["BULL", "BEAR", "CHOP"]:
        regime_trades = [t for t in trades if t['regime'] == regime]
        summarize_trades(regime_trades, regime)


# === DRAWDOWN ANALYSIS ===
print("\n\n" + "=" * 90)
print("2022 BEAR MARKET STRESS TEST (Nov 2021 → Nov 2022)")
print("=" * 90)

# Find 2022 bear period in BTC
bear_mask = (btc.index >= '2021-11-01') & (btc.index <= '2022-12-01')
btc_bear = btc.loc[bear_mask]
btc_ret = (btc_bear['close'].iloc[-1] / btc_bear['close'].iloc[0] - 1) * 100
print(f"\nBTC buy-and-hold 2022 bear: {btc_ret:+.1f}%")

for pair in ["ETHUSDT", "AVAXUSDT", "LINKUSDT", "SOLUSDT"]:
    df = load_pair(pair)
    if df is None:
        continue
    regime_aligned = btc_regimes.reindex(df.index, method='ffill')

    # LONG in bear
    long_trades = run_long(df, regime_aligned)
    bear_long = [t for t in long_trades
                 if '2021-11-01' <= df.index[min(t['entry_bar'], len(df)-1)].strftime('%Y-%m-%d') <= '2022-12-01']

    # SHORT in bear
    short_trades = run_short(df, regime_aligned)
    bear_short = [t for t in short_trades
                  if '2021-11-01' <= df.index[min(t['entry_bar'], len(df)-1)].strftime('%Y-%m-%d') <= '2022-12-01']

    # Asset B&H
    pair_mask = (df.index >= '2021-11-01') & (df.index <= '2022-12-01')
    pair_bear = df.loc[pair_mask]
    if len(pair_bear) > 0:
        pair_ret = (pair_bear['close'].iloc[-1] / pair_bear['close'].iloc[0] - 1) * 100
    else:
        pair_ret = 0

    print(f"\n{pair} (B&H: {pair_ret:+.1f}%):")
    summarize_trades(bear_long, "LONG in bear")
    summarize_trades(bear_short, "SHORT in bear")

    if bear_long and bear_short:
        lpnl = [t['pnl'] for t in bear_long]
        spnl = [t['pnl'] for t in bear_short]
        combined = lpnl + spnl
        gp = sum(p for p in combined if p > 0)
        gl = abs(sum(p for p in combined if p < 0))
        cpf = gp / gl if gl > 0 else float('inf')
        cret = (np.prod([1+p for p in combined]) - 1) * 100
        print(f"  COMBINED (L+S):  PF={cpf:.2f}  Cumul={cret:+.1f}%")


# === 2024 BULL STRESS TEST ===
print("\n\n" + "=" * 90)
print("2024 BULL MARKET TEST (Oct 2023 → Mar 2025)")
print("=" * 90)

bull_mask = (btc.index >= '2023-10-01') & (btc.index <= '2025-03-31')
btc_bull = btc.loc[bull_mask]
if len(btc_bull) > 0:
    btc_ret = (btc_bull['close'].iloc[-1] / btc_bull['close'].iloc[0] - 1) * 100
    print(f"\nBTC buy-and-hold 2024 bull: {btc_ret:+.1f}%")

for pair in ["ETHUSDT", "AVAXUSDT", "LINKUSDT", "SOLUSDT"]:
    df = load_pair(pair)
    if df is None:
        continue
    regime_aligned = btc_regimes.reindex(df.index, method='ffill')

    long_trades = run_long(df, regime_aligned)
    bull_long = [t for t in long_trades
                 if '2023-10-01' <= df.index[min(t['entry_bar'], len(df)-1)].strftime('%Y-%m-%d') <= '2025-03-31']

    short_trades = run_short(df, regime_aligned)
    bull_short = [t for t in short_trades
                  if '2023-10-01' <= df.index[min(t['entry_bar'], len(df)-1)].strftime('%Y-%m-%d') <= '2025-03-31']

    pair_mask = (df.index >= '2023-10-01') & (df.index <= '2025-03-31')
    pair_bull = df.loc[pair_mask]
    if len(pair_bull) > 0:
        pair_ret = (pair_bull['close'].iloc[-1] / pair_bull['close'].iloc[0] - 1) * 100
    else:
        pair_ret = 0

    print(f"\n{pair} (B&H: {pair_ret:+.1f}%):")
    summarize_trades(bull_long, "LONG in bull")
    summarize_trades(bull_short, "SHORT in bull")
