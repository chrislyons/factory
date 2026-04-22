#!/usr/bin/env python3
"""
Realistic Portfolio Returns with Position Sizing.
Uses fixed fractional sizing (1% risk per trade) and computes
annual returns, Sharpe, max drawdown, and profit targets.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
ATR_PERIOD = 10
DONCHIAN = 20
BB_PERIOD = 20
BB_STD = 2.0
ATR_MULT_SHORT = 1.5
TRAIL_LONG = 0.01
TRAIL_SHORT = 0.025
MAX_HOLD_LONG = 96
MAX_HOLD_SHORT = 48
MR_MAX_HOLD = 48
FRICTION = 0.0014
SMA_REGIME = 100

RISK_PER_TRADE = 0.01  # 1% of capital per trade
CAPITAL = 10000  # Starting capital


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


def run_all_strategies(df, pair):
    """Run all applicable strategies for a pair, return list of (date, pnl_pct, strategy)."""
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    upper_dc = pd.Series(h).rolling(DONCHIAN).max().values
    lower_dc = pd.Series(l).rolling(DONCHIAN).min().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values
    bb_sma = pd.Series(c).rolling(BB_PERIOD).mean().values
    bb_std = pd.Series(c).rolling(BB_PERIOD).std().values
    bb_lower = bb_sma - BB_STD * bb_std
    bb_upper = bb_sma + BB_STD * bb_std

    results = []

    # ATR LONG
    in_trade = False
    entry_price = entry_bar = highest = 0
    for i in range(max(DONCHIAN, SMA_REGIME) + 1, len(c)):
        if in_trade:
            highest = max(highest, h[i])
            trail = highest * (1 - TRAIL_LONG)
            hours = i - entry_bar
            if hours < 4 and atr[i] > 0:
                trail = max(trail, entry_price - atr[i] * 1.5)
            if l[i] <= trail or hours >= MAX_HOLD_LONG:
                exit_p = trail if l[i] <= trail else c[i]
                pnl = (exit_p - entry_price) / entry_price - FRICTION
                results.append((df.index[entry_bar], pnl, "ATR_L"))
                in_trade = False
        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]:
            in_trade = True
            entry_price = c[i-1]
            entry_bar = i
            highest = h[i-1]

    # ATR SHORT
    in_trade = False
    entry_price = entry_bar = lowest = 0
    for i in range(max(DONCHIAN, SMA_REGIME) + 1, len(c)):
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * (1 + TRAIL_SHORT)
            hours = i - entry_bar
            if h[i] >= trail or hours >= MAX_HOLD_SHORT:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                results.append((df.index[entry_bar], pnl, "ATR_S"))
                in_trade = False
        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower_dc[i-2] - atr[i-1] * ATR_MULT_SHORT
            if c[i-1] < trigger:
                in_trade = True
                entry_price = c[i-1]
                entry_bar = i
                lowest = l[i-1]

    # BB MR LONG
    in_trade = False
    entry_price = entry_bar = 0
    for i in range(BB_PERIOD + 1, len(c)):
        if in_trade:
            hours = i - entry_bar
            if c[i] >= bb_sma[i] or hours >= MR_MAX_HOLD:
                exit_p = max(bb_sma[i], c[i])
                if c[i] >= bb_upper[i]:
                    exit_p = bb_upper[i]
                pnl = (exit_p - entry_price) / entry_price - FRICTION
                results.append((df.index[entry_bar], pnl, "MR_L"))
                in_trade = False
        if not in_trade and l[i] <= bb_lower[i]:
            in_trade = True
            entry_price = bb_lower[i]
            entry_bar = i

    # BB MR SHORT
    in_trade = False
    entry_price = entry_bar = 0
    for i in range(BB_PERIOD + 1, len(c)):
        if in_trade:
            hours = i - entry_bar
            if c[i] <= bb_sma[i] or hours >= MR_MAX_HOLD:
                exit_p = min(bb_sma[i], c[i])
                if c[i] <= bb_lower[i]:
                    exit_p = bb_lower[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                results.append((df.index[entry_bar], pnl, "MR_S"))
                in_trade = False
        if not in_trade and h[i] >= bb_upper[i]:
            in_trade = True
            entry_price = bb_upper[i]
            entry_bar = i

    return results


# === BUILD PORTFOLIO ===
PORTFOLIO = {
    "AAVEUSDT": ["ATR_L", "ATR_S", "MR_L"],
    "ARBUSDT": ["ATR_L", "ATR_S"],
    "AVAXUSDT": ["ATR_L"],
    "DOGEUSDT": ["ATR_L", "ATR_S"],
    "LINKUSDT": ["ATR_L", "ATR_S", "MR_L"],
    "LTCUSDT": ["ATR_L", "ATR_S", "MR_L"],
    "NEARUSDT": ["ATR_L", "ATR_S", "MR_S"],
    "OPUSDT": ["ATR_L", "ATR_S", "MR_S"],
    "RENDERUSDT": ["ATR_L"],
    "SOLUSDT": ["ATR_L"],
    "WLDUSDT": ["ATR_L"],
}

all_trades = []
for pair, strats in PORTFOLIO.items():
    df = load_pair(pair)
    if df is None:
        continue
    trades = run_all_strategies(df, pair)
    for date, pnl, strat in trades:
        if strat in strats:
            all_trades.append({"date": date, "pnl": pnl, "strategy": strat, "pair": pair})

all_trades.sort(key=lambda x: x['date'])

# === SIMULATE WITH POSITION SIZING ===
print("=" * 90)
print(f"REALISTIC PORTFOLIO SIMULATION — {RISK_PER_TRADE*100:.0f}% Risk Per Trade, ${CAPITAL:,} Starting Capital")
print("=" * 90)

# Assume trades execute roughly sequentially (overlapping = diversification benefit)
# Use all trades chronologically, risking 1% of current equity each
equity = CAPITAL
peak = equity
max_dd = 0
monthly_equity = {}
yearly_pnl = {}

for t in all_trades:
    if t['date'] is None:
        continue
    # Each trade risks RISK_PER_TRADE of current equity
    pnl_dollar = equity * RISK_PER_TRADE * t['pnl'] / (abs(t['pnl']) if t['pnl'] != 0 else 1)
    # Simplified: just apply the return as a fraction of risk
    trade_return = t['pnl'] * RISK_PER_TRADE  # 1% risk * pct return
    equity *= (1 + trade_return)
    peak = max(peak, equity)
    dd = (peak - equity) / peak
    max_dd = max(max_dd, dd)

    yr = t['date'].year
    mo = t['date'].month
    key = f"{yr}-{mo:02d}"
    monthly_equity[key] = equity
    if yr not in yearly_pnl:
        yearly_pnl[yr] = {"trades": 0, "wins": 0, "total_return": 1.0}
    yearly_pnl[yr]["trades"] += 1
    if t['pnl'] > 0:
        yearly_pnl[yr]["wins"] += 1
    yearly_pnl[yr]["total_return"] *= (1 + trade_return)

# === RESULTS ===
print(f"\nFinal equity: ${equity:,.0f}")
print(f"Total return: {(equity/CAPITAL - 1)*100:+.1f}%")
print(f"Max drawdown: {max_dd*100:.1f}%")
print(f"Total trades: {len(all_trades)}")

years = max(t['date'].year for t in all_trades if t['date']) - min(t['date'].year for t in all_trades if t['date']) + 1
ann_ret = ((equity / CAPITAL) ** (1/years) - 1) * 100
print(f"Years: {years}")
print(f"Annualized return: {ann_ret:+.1f}%")

# Monthly stats
monthly_returns = sorted(monthly_equity.keys())
if len(monthly_returns) > 1:
    monthly_rets = []
    prev = CAPITAL
    for m in monthly_returns:
        ret = (monthly_equity[m] / prev - 1) * 100
        monthly_rets.append(ret)
        prev = monthly_equity[m]

    avg_monthly = np.mean(monthly_rets)
    std_monthly = np.std(monthly_rets)
    sharpe = avg_monthly / std_monthly * np.sqrt(12) if std_monthly > 0 else 0
    best_month = max(monthly_rets)
    worst_month = min(monthly_rets)
    win_months = sum(1 for r in monthly_rets if r > 0)

    print(f"\n--- Monthly Stats ---")
    print(f"Avg monthly return: {avg_monthly:+.2f}%")
    print(f"Std monthly return: {std_monthly:.2f}%")
    print(f"Sharpe ratio (annualized): {sharpe:.2f}")
    print(f"Best month: {best_month:+.2f}%")
    print(f"Worst month: {worst_month:+.2f}%")
    print(f"Winning months: {win_months}/{len(monthly_rets)} ({win_months/len(monthly_rets)*100:.0f}%)")

# Yearly breakdown
print(f"\n--- Yearly Breakdown ---")
print(f"{'Year':>6s}  {'Trades':>7s}  {'Return':>10s}  {'Equity':>12s}")
print("-" * 40)
for yr in sorted(yearly_pnl.keys()):
    d = yearly_pnl[yr]
    ret = (d['total_return'] - 1) * 100
    eq = CAPITAL * np.prod([yearly_pnl[y]['total_return'] for y in sorted(yearly_pnl.keys()) if y <= yr])
    print(f"{yr:>6d}  {d['trades']:>7d}  {ret:>+9.1f}%  ${eq:>11,.0f}")

# Realistic targets
print(f"\n\n--- REALISTIC TARGETS ---")
print(f"With {RISK_PER_TRADE*100:.0f}% risk per trade:")
print(f"  Annual return: {ann_ret:+.1f}%")
print(f"  Monthly return: {avg_monthly:+.2f}% (avg)")
print(f"  Max drawdown: {max_dd*100:.1f}%")
print(f"  Sharpe: {sharpe:.2f}")
print(f"  Final ${CAPITAL:,} after {years} years: ${equity:,.0f}")

# What-if: 2% risk
equity_2x = CAPITAL
for t in all_trades:
    if t['date'] is None:
        continue
    trade_return = t['pnl'] * 0.02
    equity_2x *= (1 + trade_return)
ann_2x = ((equity_2x / CAPITAL) ** (1/years) - 1) * 100
print(f"\n  With 2% risk: Annual return: {ann_2x:+.1f}%, Final: ${equity_2x:,.0f}")
