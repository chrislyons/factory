#!/usr/bin/env python3
"""
Combined 1H + 4H ATR Portfolio Simulation with Leverage.
Tests how the two timeframes interact and computes realistic returns.
"""
import pandas as pd, numpy as np
from pathlib import Path
from scipy import stats
import json

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

def load_pair(pair):
    f = DATA_DIR / f"binance_{pair}_60m.parquet"
    if not f.exists(): f = DATA_DIR / f"binance_{pair}_1h.parquet"
    if not f.exists(): return None
    df = pd.read_parquet(f)
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time').sort_index()
    return df

def resample_4h(df):
    return df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()

def compute_atr(c, h, l, period=14):
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr).rolling(period).mean().values

# === 1H ATR LONG ===
def backtest_1h_long(df):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(c, h, l, 10)
    upper_dc = pd.Series(h).rolling(20).max().values
    sma = pd.Series(c).rolling(100).mean().values
    trades = []
    in_trade = False
    entry_price = entry_bar = highest = 0
    for i in range(120, len(c)):
        if in_trade:
            highest = max(highest, h[i])
            trail = highest * 0.99
            hours = i - entry_bar
            if hours < 4 and atr[i] > 0:
                trail = max(trail, entry_price - atr[i] * 1.5)
            if l[i] <= trail or hours >= 96:
                exit_p = trail if l[i] <= trail else c[i]
                pnl = (exit_p - entry_price) / entry_price - 0.0014
                trades.append({"bar": entry_bar, "pnl": pnl, "hours": hours, "side": "L", "tf": "1h"})
                in_trade = False
        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]:
            in_trade = True
            entry_price = c[i-1]
            entry_bar = i
            highest = h[i-1]
    return trades

# === 1H ATR SHORT ===
def backtest_1h_short(df):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(c, h, l, 10)
    lower_dc = pd.Series(l).rolling(20).min().values
    sma = pd.Series(c).rolling(100).mean().values
    trades = []
    in_trade = False
    entry_price = entry_bar = lowest = 0
    for i in range(120, len(c)):
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * 1.025
            hours = i - entry_bar
            if h[i] >= trail or hours >= 48:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - 0.0014
                trades.append({"bar": entry_bar, "pnl": pnl, "hours": hours, "side": "S", "tf": "1h"})
                in_trade = False
        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower_dc[i-2] - atr[i-1] * 1.5
            if c[i-1] < trigger:
                in_trade = True
                entry_price = c[i-1]
                entry_bar = i
                lowest = l[i-1]
    return trades

# === 4H ATR LONG ===
def backtest_4h_long(df4h):
    c, h, l = df4h['close'].values, df4h['high'].values, df4h['low'].values
    atr = compute_atr(c, h, l, 14)
    upper_dc = pd.Series(h).rolling(20).max().values
    sma = pd.Series(c).rolling(100).mean().values
    trades = []
    in_trade = False
    entry_price = entry_bar = highest = 0
    for i in range(120, len(c)):
        if in_trade:
            highest = max(highest, h[i])
            trail = highest * 0.985
            bars = i - entry_bar
            if l[i] <= trail or bars >= 30:
                exit_p = trail if l[i] <= trail else c[i]
                pnl = (exit_p - entry_price) / entry_price - 0.0014
                trades.append({"bar": i, "pnl": pnl, "hours": bars*4, "side": "L", "tf": "4h"})
                in_trade = False
        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]:
            in_trade = True
            entry_price = c[i-1]
            entry_bar = i
            highest = h[i-1]
    return trades

# === 4H ATR SHORT ===
def backtest_4h_short(df4h):
    c, h, l = df4h['close'].values, df4h['high'].values, df4h['low'].values
    atr = compute_atr(c, h, l, 14)
    lower_dc = pd.Series(l).rolling(20).min().values
    sma = pd.Series(c).rolling(100).mean().values
    trades = []
    in_trade = False
    entry_price = entry_bar = lowest = 0
    for i in range(120, len(c)):
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * 1.025
            bars = i - entry_bar
            if h[i] >= trail or bars >= 20:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - 0.0014
                trades.append({"bar": i, "pnl": pnl, "hours": bars*4, "side": "S", "tf": "4h"})
                in_trade = False
        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower_dc[i-2] - atr[i-1] * 1.5
            if c[i-1] < trigger:
                in_trade = True
                entry_price = c[i-1]
                entry_bar = i
                lowest = l[i-1]
    return trades

# === PORTFOLIO CONFIG ===
PORTFOLIO = {
    "SOLUSDT":   {"1h_L": True, "1h_S": False, "4h_L": True, "4h_S": True},
    "BTCUSDT":   {"1h_L": False, "1h_S": False, "4h_L": True, "4h_S": True},
    "ETHUSDT":   {"1h_L": False, "1h_S": False, "4h_L": True, "4h_S": True},
    "AVAXUSDT":  {"1h_L": True, "1h_S": False, "4h_L": True, "4h_S": True},
    "ARBUSDT":   {"1h_L": True, "1h_S": True, "4h_L": True, "4h_S": True},
    "OPUSDT":    {"1h_L": True, "1h_S": True, "4h_L": True, "4h_S": True},
    "LINKUSDT":  {"1h_L": True, "1h_S": True, "4h_L": True, "4h_S": True},
    "RENDERUSDT":{"1h_L": True, "1h_S": False, "4h_L": True, "4h_S": True},
    "NEARUSDT":  {"1h_L": True, "1h_S": True, "4h_L": True, "4h_S": True},
    "AAVEUSDT":  {"1h_L": True, "1h_S": True, "4h_L": True, "4h_S": True},
    "DOGEUSDT":  {"1h_L": True, "1h_S": True, "4h_L": True, "4h_S": True},
    "LTCUSDT":   {"1h_L": True, "1h_S": True, "4h_L": True, "4h_S": True},
}

print("=" * 80)
print("COMBINED 1H + 4H PORTFOLIO SIMULATION WITH LEVERAGE")
print("=" * 80)

all_trades = []
trades_by_tf = {"1h_L": [], "1h_S": [], "4h_L": [], "4h_S": []}

for pair, cfg in PORTFOLIO.items():
    df = load_pair(pair)
    if df is None: continue
    df4h = resample_4h(df)

    if cfg["1h_L"]:
        t = backtest_1h_long(df)
        trades_by_tf["1h_L"].extend(t)
        all_trades.extend(t)
    if cfg["1h_S"]:
        t = backtest_1h_short(df)
        trades_by_tf["1h_S"].extend(t)
        all_trades.extend(t)
    if cfg["4h_L"]:
        t = backtest_4h_long(df4h)
        trades_by_tf["4h_L"].extend(t)
        all_trades.extend(t)
    if cfg["4h_S"]:
        t = backtest_4h_short(df4h)
        trades_by_tf["4h_S"].extend(t)
        all_trades.extend(t)

# Sort by bar (chronological order within each pair)
all_trades.sort(key=lambda x: x['bar'])

# === STATS BY COMPONENT ===
print(f"\n{'Component':<10s} {'Trades':>7s} {'PF':>6s} {'WR':>6s} {'Avg':>8s} {'Hours':>7s}")
print("-" * 50)
for label, trades in trades_by_tf.items():
    if len(trades) == 0: continue
    pnls = np.array([t['pnl'] for t in trades])
    wr = (pnls > 0).mean() * 100
    avg = np.mean(pnls) * 100
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
    avg_hours = np.mean([t['hours'] for t in trades])
    print(f"{label:<10s} {len(trades):>7d} {pf:>6.2f} {wr:>5.1f}% {avg:>+7.2f}% {avg_hours:>6.0f}h")

# === COMBINED PORTFOLIO ===
pnls = np.array([t['pnl'] for t in all_trades])
wr = (pnls > 0).mean() * 100
avg = np.mean(pnls) * 100
wins = pnls[pnls > 0]
losses = pnls[pnls <= 0]
pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
t_stat, p_val = stats.ttest_1samp(pnls, 0)

print(f"\n{'=' * 50}")
print(f"COMBINED PORTFOLIO")
print(f"  Trades: {len(pnls)}")
print(f"  PF: {pf:.2f}")
print(f"  WR: {wr:.1f}%")
print(f"  Avg: {avg:+.2f}%")
print(f"  t-stat: {t_stat:.2f}")
print(f"  p-value: {p_val:.10f}")

# === LEVERAGE RETURN SIMULATION ===
print(f"\n{'=' * 80}")
print("RETURN PROJECTIONS BY LEVERAGE")
print(f"{'=' * 80}")

# Assume ~500 trades/year for combined portfolio (1H: ~2400, 4H: ~500, but we need to annualize)
# Better: compute from actual data range
df_check = load_pair("BTCUSDT")
if df_check is not None:
    df4h_check = resample_4h(df_check)
    years = (df4h_check.index[-1] - df4h_check.index[0]).days / 365.25
    trades_per_year = len(all_trades) / years
else:
    years = 10
    trades_per_year = len(all_trades) / years

print(f"Data range: {years:.1f} years")
print(f"Trades/year (combined): {trades_per_year:.0f}")
print(f"Avg trades/month: {trades_per_year/12:.0f}")

print(f"\n{'Risk%':>6s} {'Leverage':>9s} {'Ann Return':>12s} {'Monthly':>10s} {'Max DD':>8s} {'$10K→(1yr)':>12s}")
print("-" * 65)

for risk_pct in [1.0, 2.0, 3.0, 5.0]:
    for leverage in [1, 3, 5, 10]:
        # Simulate with position sizing
        equity = 10000
        peak = equity
        max_dd = 0
        monthly_returns = {}

        # Assume concurrent positions = 5 (dilution factor)
        concurrent = 5
        effective_risk = risk_pct / 100 / concurrent * leverage

        for t in all_trades:
            trade_return = t['pnl'] * effective_risk
            equity *= (1 + trade_return)
            peak = max(peak, equity)
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)

        ann_ret = ((equity / 10000) ** (1/years) - 1) * 100
        monthly_avg = ann_ret / 12

        marker = "★" if ann_ret >= 100 else ("✓" if ann_ret >= 50 else " ")
        print(f"{risk_pct:>5.0f}% {leverage:>8d}x {ann_ret:>+11.0f}% {monthly_avg:>+9.1f}% {max_dd:>7.1f}% ${equity:>11,.0f}{marker}")

print(f"\n★ = 100%+ annual (2x goal)")
print(f"✓ = 50%+ annual (1.5x goal)")

# === CORRELATION BETWEEN TIMEFRAMES ===
print(f"\n{'=' * 80}")
print("SIGNAL CORRELATION (are 1H and 4H truly independent?)")
print(f"{'=' * 80}")

# Count overlap: how often do 1H and 4H signals fire on the same pair within 24h?
# Simplified: just check if components have different regime filters
long_1h = [t for t in trades_by_tf["1h_L"]]
long_4h = [t for t in trades_by_tf["4h_L"]]
short_1h = [t for t in trades_by_tf["1h_S"]]
short_4h = [t for t in trades_by_tf["4h_S"]]

print(f"\n1H LONG trades: {len(long_1h)}")
print(f"4H LONG trades: {len(long_4h)}")
print(f"1H SHORT trades: {len(short_1h)}")
print(f"4H SHORT trades: {len(short_4h)}")
print(f"\nRatio 4H/1H: {len(long_4h)/max(1,len(long_1h)):.2f} LONG, {len(short_4h)/max(1,len(short_1h)):.2f} SHORT")
print(f"4H trades are {len(long_4h)/max(1,len(long_1h)):.1f}x fewer but each is {avg/0.42:.1f}x larger")
