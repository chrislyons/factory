#!/usr/bin/env python3
"""
Annualized Portfolio Stats — realistic numbers for position sizing.
Computes per-year PnL assuming equal capital allocation across active sleeves.
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
    c = btc_df['close'].values
    sma50 = pd.Series(c).rolling(50).mean().values
    sma200 = pd.Series(c).rolling(200).mean().values
    regimes = pd.Series("UNKNOWN", index=btc_df.index)
    for i in range(200, len(c)):
        if c[i] > sma50[i] > sma200[i]:
            regimes.iloc[i] = "BULL"
        elif c[i] < sma50[i] < sma200[i]:
            regimes.iloc[i] = "BEAR"
        else:
            regimes.iloc[i] = "CHOP"
    return regimes


def run_atr_long(df):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    upper = pd.Series(h).rolling(DONCHIAN).max().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values
    trades, in_trade = [], False
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
                trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i,
                               "date": df.index[entry_bar] if entry_bar < len(df) else None})
                in_trade = False
        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper[i-2]:
            in_trade = True
            entry_price = c[i-1]
            entry_bar = i
            highest = h[i-1]
    return trades


def run_atr_short(df):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    lower = pd.Series(l).rolling(DONCHIAN).min().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values
    trades, in_trade = [], False
    entry_price = entry_bar = lowest = 0
    for i in range(max(DONCHIAN, SMA_REGIME) + 1, len(c)):
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * (1 + TRAIL_SHORT)
            hours = i - entry_bar
            if h[i] >= trail or hours >= MAX_HOLD_SHORT:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i,
                               "date": df.index[entry_bar] if entry_bar < len(df) else None})
                in_trade = False
        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower[i-2] - atr[i-1] * ATR_MULT_SHORT
            if c[i-1] < trigger:
                in_trade = True
                entry_price = c[i-1]
                entry_bar = i
                lowest = l[i-1]
    return trades


def run_bb_mr_long(df, allowed_regimes):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    sma = pd.Series(c).rolling(BB_PERIOD).mean().values
    std = pd.Series(c).rolling(BB_PERIOD).std().values
    lower_bb = sma - BB_STD * std
    upper_bb = sma + BB_STD * std
    trades, in_trade = [], False
    entry_price = entry_bar = 0
    for i in range(BB_PERIOD + 1, len(c)):
        if in_trade:
            hours = i - entry_bar
            if c[i] >= sma[i] or hours >= MR_MAX_HOLD:
                exit_p = max(sma[i], c[i])
                if c[i] >= upper_bb[i]:
                    exit_p = upper_bb[i]
                pnl = (exit_p - entry_price) / entry_price - FRICTION
                trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i,
                               "date": df.index[entry_bar] if entry_bar < len(df) else None})
                in_trade = False
        if not in_trade and l[i] <= lower_bb[i]:
            in_trade = True
            entry_price = lower_bb[i]
            entry_bar = i
    return trades


def run_bb_mr_short(df, allowed_regimes):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    sma = pd.Series(c).rolling(BB_PERIOD).mean().values
    std = pd.Series(c).rolling(BB_PERIOD).std().values
    lower_bb = sma - BB_STD * std
    upper_bb = sma + BB_STD * std
    trades, in_trade = [], False
    entry_price = entry_bar = 0
    for i in range(BB_PERIOD + 1, len(c)):
        if in_trade:
            hours = i - entry_bar
            if c[i] <= sma[i] or hours >= MR_MAX_HOLD:
                exit_p = min(sma[i], c[i])
                if c[i] <= lower_bb[i]:
                    exit_p = lower_bb[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                trades.append({"pnl": pnl, "entry_bar": entry_bar, "exit_bar": i,
                               "date": df.index[entry_bar] if entry_bar < len(df) else None})
                in_trade = False
        if not in_trade and h[i] >= upper_bb[i]:
            in_trade = True
            entry_price = upper_bb[i]
            entry_bar = i
    return trades


# === BUILD FULL PORTFOLIO WITH TIMESTAMPS ===
btc = load_pair("BTCUSDT")
regimes = classify_regimes(btc)

PORTFOLIO = {
    # pair: [(strategy_name, runner_function, params)]
    "AAVEUSDT": [("ATR_L", run_atr_long, {}), ("ATR_S", run_atr_short, {}),
                  ("MR_L", run_bb_mr_long, {"allowed_regimes": ["BULL", "CHOP"]})],
    "ARBUSDT": [("ATR_L", run_atr_long, {}), ("ATR_S", run_atr_short, {})],
    "AVAXUSDT": [("ATR_L", run_atr_long, {})],
    "DOGEUSDT": [("ATR_L", run_atr_long, {}), ("ATR_S", run_atr_short, {})],
    "LINKUSDT": [("ATR_L", run_atr_long, {}), ("ATR_S", run_atr_short, {}),
                  ("MR_L", run_bb_mr_long, {"allowed_regimes": ["BULL", "CHOP"]})],
    "LTCUSDT": [("ATR_L", run_atr_long, {}), ("ATR_S", run_atr_short, {}),
                 ("MR_L", run_bb_mr_long, {"allowed_regimes": ["BULL", "CHOP"]})],
    "NEARUSDT": [("ATR_L", run_atr_long, {}), ("ATR_S", run_atr_short, {}),
                  ("MR_S", run_bb_mr_short, {"allowed_regimes": ["BEAR", "CHOP"]})],
    "OPUSDT": [("ATR_L", run_atr_long, {}), ("ATR_S", run_atr_short, {}),
                ("MR_S", run_bb_mr_short, {"allowed_regimes": ["BEAR", "CHOP"]})],
    "RENDERUSDT": [("ATR_L", run_atr_long, {})],
    "SOLUSDT": [("ATR_L", run_atr_long, {})],
    "WLDUSDT": [("ATR_L", run_atr_long, {})],
}

all_trades = []  # (date, pnl, strategy, pair)
for pair, strategies in PORTFOLIO.items():
    df = load_pair(pair)
    if df is None:
        continue
    for strat_name, runner, params in strategies:
        trades = runner(df, **params) if params else runner(df)
        for t in trades:
            all_trades.append({
                "date": t.get("date"),
                "pnl": t['pnl'],
                "strategy": strat_name,
                "pair": pair
            })

# Sort by entry date
all_trades = sorted(all_trades, key=lambda x: x['date'] if x['date'] else pd.Timestamp.min)

print("=" * 90)
print("ANNUALIZED PORTFOLIO PERFORMANCE")
print("=" * 90)

# Group by year
years = {}
for t in all_trades:
    if t['date'] is None:
        continue
    yr = t['date'].year
    if yr not in years:
        years[yr] = []
    years[yr].append(t['pnl'])

print(f"\n{'Year':>6s}  {'Trades':>7s}  {'PF':>6s}  {'WR':>6s}  {'Avg':>7s}  {'Return':>10s}  {'MaxDD':>7s}")
print("-" * 60)

portfolio_pnls = []
for yr in sorted(years.keys()):
    pnls = years[yr]
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else float('inf')
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    avg = np.mean(pnls) * 100

    # Monthly return (compound within year)
    monthly = {}
    for t in all_trades:
        if t['date'] and t['date'].year == yr:
            m = t['date'].month
            if m not in monthly:
                monthly[m] = []
            monthly[m].append(t['pnl'])

    monthly_returns = []
    for m in sorted(monthly.keys()):
        m_pnls = monthly[m]
        m_ret = (np.prod([1+p for p in m_pnls]) - 1) * 100
        monthly_returns.append(m_ret)

    annual_ret = (np.prod([1+r/100 for r in monthly_returns]) - 1) * 100

    # Max monthly drawdown
    peak = 100
    equity = 100
    max_dd = 0
    for m_ret in monthly_returns:
        equity *= (1 + m_ret/100)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)

    print(f"{yr:>6d}  {len(pnls):>7d}  {pf:>6.2f}  {wr:>5.1f}%  {avg:>+6.2f}%  {annual_ret:>+9.1f}%  {max_dd:>6.1f}%")
    portfolio_pnls.extend(pnls)

# Overall
print("-" * 60)
gp = sum(p for p in portfolio_pnls if p > 0)
gl = abs(sum(p for p in portfolio_pnls if p < 0))
cpf = gp / gl if gl > 0 else float('inf')
cwr = sum(1 for p in portfolio_pnls if p > 0) / len(portfolio_pnls) * 100
cavg = np.mean(portfolio_pnls) * 100
print(f"{'ALL':>6s}  {len(portfolio_pnls):>7d}  {cpf:>6.2f}  {cwr:>5.1f}%  {cavg:>+6.2f}%")

# Per-strategy annualized
print("\n\n--- Per-Strategy Annualized Returns ---")
for strat in ["ATR_L", "ATR_S", "MR_L", "MR_S"]:
    strat_trades = [t for t in all_trades if t['strategy'] == strat]
    if not strat_trades:
        continue
    strat_years = {}
    for t in strat_trades:
        if t['date']:
            yr = t['date'].year
            if yr not in strat_years:
                strat_years[yr] = []
            strat_years[yr].append(t['pnl'])

    print(f"\n{strat}:")
    for yr in sorted(strat_years.keys()):
        pnls = strat_years[yr]
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        pf = gp / gl if gl > 0 else float('inf')
        ret = (np.prod([1+p for p in pnls]) - 1) * 100
        print(f"  {yr}: n={len(pnls):4d}  PF={pf:.2f}  Return={ret:+.1f}%")

# Realistic annual return estimate
print("\n\n--- REALISTIC ANNUAL RETURN ESTIMATE ---")
# Use geometric mean of annual returns (2022-2026 full years)
full_year_returns = []
for yr in [2022, 2023, 2024, 2025]:
    if yr in years:
        pnls = years[yr]
        ret = (np.prod([1+p for p in pnls]) - 1) * 100
        full_year_returns.append(ret)

if full_year_returns:
    # Geometric mean
    geo_mean = (np.prod([1+r/100 for r in full_year_returns]) ** (1/len(full_year_returns)) - 1) * 100
    # Arithmetic mean
    arith_mean = np.mean(full_year_returns)
    print(f"  Full year returns: {[f'{r:+.1f}%' for r in full_year_returns]}")
    print(f"  Geometric mean annual return: {geo_mean:+.1f}%")
    print(f"  Arithmetic mean annual return: {arith_mean:+.1f}%")
    print(f"  Best year: {max(full_year_returns):+.1f}%")
    print(f"  Worst year: {min(full_year_returns):+.1f}%")
