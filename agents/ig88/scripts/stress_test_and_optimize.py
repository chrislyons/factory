#!/usr/bin/env python3
"""
Year-by-year combined portfolio with realistic position sizing.
Tests worst-case periods (2018 bear, 2022 bear).
Also optimizes 4H SHORT ATR multiplier + trailing stop.
"""
import pandas as pd, numpy as np
from pathlib import Path
from scipy import stats

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

def load_and_resample(pair):
    f = DATA_DIR / f"binance_{pair}_60m.parquet"
    if not f.exists(): f = DATA_DIR / f"binance_{pair}_1h.parquet"
    if not f.exists(): return None, None
    df = pd.read_parquet(f)
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time').sort_index()
    df4h = df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    return df, df4h

def compute_atr(c, h, l, period=14):
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr).rolling(period).mean().values

def run_all_strategies(df, df4h):
    """Run all 4 strategy components, return list of (datetime, pnl) tuples."""
    results = []
    friction = 0.0014

    # === 1H LONG ===
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(c, h, l, 10)
    upper_dc = pd.Series(h).rolling(20).max().values
    sma = pd.Series(c).rolling(100).mean().values
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
                pnl = (exit_p - entry_price) / entry_price - friction
                results.append((df.index[i], pnl, "1h_L"))
                in_trade = False
        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]:
            in_trade = True; entry_price = c[i-1]; entry_bar = i; highest = h[i-1]

    # === 1H SHORT ===
    lower_dc = pd.Series(l).rolling(20).min().values
    in_trade = False
    entry_price = entry_bar = lowest = 0
    for i in range(120, len(c)):
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * 1.025
            hours = i - entry_bar
            if h[i] >= trail or hours >= 48:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - friction
                results.append((df.index[i], pnl, "1h_S"))
                in_trade = False
        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower_dc[i-2] - atr[i-1] * 1.5
            if c[i-1] < trigger:
                in_trade = True; entry_price = c[i-1]; entry_bar = i; lowest = l[i-1]

    # === 4H LONG ===
    c4, h4, l4 = df4h['close'].values, df4h['high'].values, df4h['low'].values
    atr4 = compute_atr(c4, h4, l4, 14)
    upper_dc4 = pd.Series(h4).rolling(20).max().values
    sma4 = pd.Series(c4).rolling(100).mean().values
    in_trade = False
    entry_price = entry_bar = highest = 0
    for i in range(120, len(c4)):
        if in_trade:
            highest = max(highest, h4[i])
            trail = highest * 0.985
            bars = i - entry_bar
            if l4[i] <= trail or bars >= 30:
                exit_p = trail if l4[i] <= trail else c4[i]
                pnl = (exit_p - entry_price) / entry_price - friction
                results.append((df4h.index[i], pnl, "4h_L"))
                in_trade = False
        if not in_trade and c4[i-1] > sma4[i-1] and c4[i-1] > upper_dc4[i-2]:
            in_trade = True; entry_price = c4[i-1]; entry_bar = i; highest = h4[i-1]

    # === 4H SHORT ===
    lower_dc4 = pd.Series(l4).rolling(20).min().values
    in_trade = False
    entry_price = entry_bar = lowest = 0
    for i in range(120, len(c4)):
        if in_trade:
            lowest = min(lowest, l4[i])
            trail = lowest * 1.025
            bars = i - entry_bar
            if h4[i] >= trail or bars >= 20:
                exit_p = trail if h4[i] >= trail else c4[i]
                pnl = (entry_price - exit_p) / entry_price - friction
                results.append((df4h.index[i], pnl, "4h_S"))
                in_trade = False
        if not in_trade and c4[i-1] < sma4[i-1]:
            trigger = lower_dc4[i-2] - atr4[i-1] * 1.5
            if c4[i-1] < trigger:
                in_trade = True; entry_price = c4[i-1]; entry_bar = i; lowest = l4[i-1]

    return results

# === RUN ===
PORTFOLIO = {
    "SOLUSDT": True, "AVAXUSDT": True, "ARBUSDT": True, "OPUSDT": True,
    "LINKUSDT": True, "RENDERUSDT": True, "NEARUSDT": True, "AAVEUSDT": True,
    "DOGEUSDT": True, "LTCUSDT": True, "BTCUSDT": True, "ETHUSDT": True,
}

all_trades = []
for pair in PORTFOLIO:
    df, df4h = load_and_resample(pair)
    if df is None: continue
    trades = run_all_strategies(df, df4h)
    all_trades.extend(trades)

all_trades.sort(key=lambda x: x[0])

# Year-by-year analysis
print("=" * 80)
print("YEAR-BY-YEAR COMBINED PORTFOLIO PERFORMANCE")
print("Position sizing: 2% risk, 5x leverage, 5 concurrent positions")
print("=" * 80)

RISK = 0.02  # 2% per trade
LEV = 5.0    # 5x leverage
CONCURRENT = 5

equity = 10000
peak = equity
max_dd_overall = 0
yearly_data = {}

for date, pnl, strat in all_trades:
    if date is None: continue
    yr = date.year
    if yr not in yearly_data:
        yearly_data[yr] = {"trades": 0, "wins": 0, "equity_start": equity, "max_equity": equity, "min_equity": equity}

    # Position sizing: risk% / concurrent * leverage
    effective_risk = RISK / CONCURRENT * LEV
    trade_return = pnl * effective_risk
    equity *= (1 + trade_return)

    peak = max(peak, equity)
    dd = (peak - equity) / peak
    max_dd_overall = max(max_dd_overall, dd)

    yearly_data[yr]["trades"] += 1
    if pnl > 0: yearly_data[yr]["wins"] += 1
    yearly_data[yr]["max_equity"] = max(yearly_data[yr]["max_equity"], equity)
    yearly_data[yr]["min_equity"] = min(yearly_data[yr]["min_equity"], equity)
    yearly_data[yr]["equity_end"] = equity

print(f"\n{'Year':>6s} {'Trades':>7s} {'WR':>6s} {'Return':>10s} {'Equity':>14s} {'MaxDD':>7s}")
print("-" * 58)

for yr in sorted(yearly_data.keys()):
    d = yearly_data[yr]
    ret = (d["equity_end"] / d["equity_start"] - 1) * 100
    wr = d["wins"] / d["trades"] * 100 if d["trades"] > 0 else 0
    yr_dd = (d["max_equity"] - d["min_equity"]) / d["max_equity"] * 100
    print(f"{yr:>6d} {d['trades']:>7d} {wr:>5.1f}% {ret:>+9.1f}% ${d['equity_end']:>13,.0f} {yr_dd:>6.1f}%")

total_ret = (equity / 10000 - 1) * 100
years = max(yearly_data.keys()) - min(yearly_data.keys()) + 1
ann_ret = ((equity / 10000) ** (1/years) - 1) * 100

print(f"\n{'=' * 58}")
print(f"TOTAL: {total_ret:+.0f}% over {years} years")
print(f"Annualized: {ann_ret:+.1f}%")
print(f"Final equity: ${equity:,.0f}")
print(f"Max drawdown: {max_dd_overall*100:.1f}%")
print(f"Sharpe (annualized, est.): {ann_ret / (max_dd_overall*100 * 10):.2f}")

# === 4H SHORT PARAMETER OPTIMIZATION ===
print(f"\n{'=' * 80}")
print("4H SHORT PARAMETER OPTIMIZATION (ATR mult × Trailing stop)")
print(f"{'=' * 80}")

atr_mults = [1.0, 1.5, 2.0, 2.5, 3.0]
trail_stops = [0.015, 0.02, 0.025, 0.03, 0.04]

best_pf = 0
best_params = (0, 0)

print(f"\n{'':>8s}", end="")
for ts in trail_stops:
    print(f"  trail={ts:.1%}", end="")
print()

for am in atr_mults:
    print(f"ATR={am:.1f}x ", end="")
    for ts in trail_stops:
        trades = []
        for pair in PORTFOLIO:
            df, df4h = load_and_resample(pair)
            if df4h is None: continue
            c4, h4, l4 = df4h['close'].values, df4h['high'].values, df4h['low'].values
            atr4 = compute_atr(c4, h4, l4, 14)
            lower_dc4 = pd.Series(l4).rolling(20).min().values
            sma4 = pd.Series(c4).rolling(100).mean().values
            in_trade = False
            ep = eb = lo = 0
            for i in range(120, len(c4)):
                if in_trade:
                    lo = min(lo, l4[i])
                    trail = lo * (1 + ts)
                    bars = i - eb
                    if h4[i] >= trail or bars >= 20:
                        xp = trail if h4[i] >= trail else c4[i]
                        pnl = (ep - xp) / ep - 0.0014
                        trades.append(pnl)
                        in_trade = False
                if not in_trade and c4[i-1] < sma4[i-1]:
                    trigger = lower_dc4[i-2] - atr4[i-1] * am
                    if c4[i-1] < trigger:
                        in_trade = True; ep = c4[i-1]; eb = i; lo = l4[i-1]

        if len(trades) > 10:
            pnls = np.array(trades)
            wr = (pnls > 0).mean() * 100
            wins = pnls[pnls > 0]
            losses = pnls[pnls <= 0]
            pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
            if pf > best_pf:
                best_pf = pf
                best_params = (am, ts)
            print(f"  {pf:>5.1f}({len(trades):>3d})", end="")
        else:
            print(f"    n/a ", end="")
    print()

print(f"\nBest: ATR {best_params[0]}x, trail {best_params[1]:.1%} → PF {best_pf:.2f}")
