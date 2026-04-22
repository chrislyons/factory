#!/usr/bin/env python3
"""
Full Portfolio Simulation — ATR BO (L+S) + BB MR (regime-gated)
Simulates the complete strategy portfolio across all regimes.
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


def run_atr_long(df, sma_col, regime_series):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    upper = pd.Series(h).rolling(DONCHIAN).max().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values
    trades, in_trade = [], False
    entry_price = entry_bar = highest = 0
    for i in range(max(DONCHIAN, SMA_REGIME) + 1, len(c)):
        regime = regime_series.iloc[i] if i < len(regime_series) else "UNKNOWN"
        if in_trade:
            highest = max(highest, h[i])
            trail = highest * (1 - TRAIL_LONG)
            hours = i - entry_bar
            if hours < 4 and atr[i] > 0:
                trail = max(trail, entry_price - atr[i] * 1.5)
            if l[i] <= trail or hours >= MAX_HOLD_LONG:
                exit_p = trail if l[i] <= trail else c[i]
                pnl = (exit_p - entry_price) / entry_price - FRICTION
                trades.append({"pnl": pnl, "strategy": "ATR_L", "regime": regime})
                in_trade = False
        if not in_trade and c[i-1] > sma[i-1] and c[i-1] > upper[i-2]:
            in_trade = True
            entry_price = c[i-1]
            entry_bar = i
            highest = h[i-1]
    return trades


def run_atr_short(df, regime_series):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(df)
    lower = pd.Series(l).rolling(DONCHIAN).min().values
    sma = pd.Series(c).rolling(SMA_REGIME).mean().values
    trades, in_trade = [], False
    entry_price = entry_bar = lowest = 0
    for i in range(max(DONCHIAN, SMA_REGIME) + 1, len(c)):
        regime = regime_series.iloc[i] if i < len(regime_series) else "UNKNOWN"
        if in_trade:
            lowest = min(lowest, l[i])
            trail = lowest * (1 + TRAIL_SHORT)
            hours = i - entry_bar
            if h[i] >= trail or hours >= MAX_HOLD_SHORT:
                exit_p = trail if h[i] >= trail else c[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                trades.append({"pnl": pnl, "strategy": "ATR_S", "regime": regime})
                in_trade = False
        if not in_trade and c[i-1] < sma[i-1]:
            trigger = lower[i-2] - atr[i-1] * ATR_MULT_SHORT
            if c[i-1] < trigger:
                in_trade = True
                entry_price = c[i-1]
                entry_bar = i
                lowest = l[i-1]
    return trades


def run_bb_mr_long(df, regime_series, allowed_regimes=["BULL", "CHOP"]):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    sma = pd.Series(c).rolling(BB_PERIOD).mean().values
    std = pd.Series(c).rolling(BB_PERIOD).std().values
    lower_bb = sma - BB_STD * std
    upper_bb = sma + BB_STD * std
    trades, in_trade = [], False
    entry_price = entry_bar = 0
    for i in range(BB_PERIOD + 1, len(c)):
        regime = regime_series.iloc[i] if i < len(regime_series) else "UNKNOWN"
        if regime not in allowed_regimes:
            if in_trade:
                pnl = (c[i] - entry_price) / entry_price - FRICTION
                trades.append({"pnl": pnl, "strategy": "MR_L", "regime": regime})
                in_trade = False
            continue
        if in_trade:
            hours = i - entry_bar
            if c[i] >= sma[i] or hours >= MR_MAX_HOLD:
                exit_p = max(sma[i], c[i])
                if c[i] >= upper_bb[i]:
                    exit_p = upper_bb[i]
                pnl = (exit_p - entry_price) / entry_price - FRICTION
                trades.append({"pnl": pnl, "strategy": "MR_L", "regime": regime})
                in_trade = False
        if not in_trade and l[i] <= lower_bb[i]:
            in_trade = True
            entry_price = lower_bb[i]
            entry_bar = i
    return trades


def run_bb_mr_short(df, regime_series, allowed_regimes=["BEAR", "CHOP"]):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    sma = pd.Series(c).rolling(BB_PERIOD).mean().values
    std = pd.Series(c).rolling(BB_PERIOD).std().values
    lower_bb = sma - BB_STD * std
    upper_bb = sma + BB_STD * std
    trades, in_trade = [], False
    entry_price = entry_bar = 0
    for i in range(BB_PERIOD + 1, len(c)):
        regime = regime_series.iloc[i] if i < len(regime_series) else "UNKNOWN"
        if regime not in allowed_regimes:
            if in_trade:
                pnl = (entry_price - c[i]) / entry_price - FRICTION
                trades.append({"pnl": pnl, "strategy": "MR_S", "regime": regime})
                in_trade = False
            continue
        if in_trade:
            hours = i - entry_bar
            if c[i] <= sma[i] or hours >= MR_MAX_HOLD:
                exit_p = min(sma[i], c[i])
                if c[i] <= lower_bb[i]:
                    exit_p = lower_bb[i]
                pnl = (entry_price - exit_p) / entry_price - FRICTION
                trades.append({"pnl": pnl, "strategy": "MR_S", "regime": regime})
                in_trade = False
        if not in_trade and h[i] >= upper_bb[i]:
            in_trade = True
            entry_price = upper_bb[i]
            entry_bar = i
    return trades


def analyze_dicts(trades):
    if not trades:
        return {"n": 0, "pf": 0, "wr": 0, "avg": 0, "cumul": 0}
    pnls = [t['pnl'] for t in trades]
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else float('inf')
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    cumul = (np.prod([1+p for p in pnls]) - 1) * 100
    return {"n": len(pnls), "pf": pf, "wr": wr, "avg": np.mean(pnls) * 100, "cumul": cumul}


def analyze_floats(pnls):
    if not pnls:
        return {"n": 0, "pf": 0, "wr": 0, "avg": 0, "cumul": 0}
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else float('inf')
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    cumul = (np.prod([1+p for p in pnls]) - 1) * 100
    return {"n": len(pnls), "pf": pf, "wr": wr, "avg": np.mean(pnls) * 100, "cumul": cumul}


# === PORTFOLIO DEFINITION ===
# ATR BO LONG: 11 pairs (confirmed)
ATR_LONG_PAIRS = [
    "AVAXUSDT", "LINKUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT",
    "NEARUSDT", "WLDUSDT", "RENDERUSDT", "ARBUSDT", "OPUSDT", "AAVEUSDT"
]

# ATR BO SHORT: 7 pairs (WF-confirmed)
ATR_SHORT_PAIRS = [
    "ARBUSDT", "OPUSDT", "LINKUSDT", "DOGEUSDT", "NEARUSDT", "AAVEUSDT", "LTCUSDT"
]

# BB MR LONG: regime-gated to BULL+CHOP (5 confirmed from WF)
MR_LONG_PAIRS = [
    "LINKUSDT", "LTCUSDT", "AAVEUSDT"  # WF-passed
]

# BB MR SHORT: regime-gated to BEAR+CHOP (2 confirmed from WF)
MR_SHORT_PAIRS = [
    "NEARUSDT", "OPUSDT"  # WF-passed
]

# === MAIN ===
print("=" * 100)
print("FULL PORTFOLIO SIMULATION — ATR BO + BB MR (Regime-Gated)")
print("=" * 100)

btc = load_pair("BTCUSDT")
regimes = classify_regimes(btc)

all_trades = []  # (pair, strategy, pnl)
pair_results = {}

for pair in sorted(set(ATR_LONG_PAIRS + ATR_SHORT_PAIRS + MR_LONG_PAIRS + MR_SHORT_PAIRS)):
    df = load_pair(pair)
    if df is None:
        continue

    regime_aligned = regimes.reindex(df.index, method='ffill')
    trades_combined = []

    if pair in ATR_LONG_PAIRS:
        t = run_atr_long(df, None, regime_aligned)
        trades_combined.extend(t)

    if pair in ATR_SHORT_PAIRS:
        t = run_atr_short(df, regime_aligned)
        trades_combined.extend(t)

    if pair in MR_LONG_PAIRS:
        t = run_bb_mr_long(df, regime_aligned, ["BULL", "CHOP"])
        trades_combined.extend(t)

    if pair in MR_SHORT_PAIRS:
        t = run_bb_mr_short(df, regime_aligned, ["BEAR", "CHOP"])
        trades_combined.extend(t)

    if trades_combined:
        pair_results[pair] = trades_combined
        all_trades.extend([(pair, t.get('strategy', 'unknown'), t['pnl']) for t in trades_combined])

        # Per strategy within pair
        strategies = {}
        for t in trades_combined:
            s = t.get('strategy', 'unknown')
            if s not in strategies:
                strategies[s] = []
            strategies[s].append(t['pnl'])

        parts = []
        for s, pnls in sorted(strategies.items()):
            gp = sum(p for p in pnls if p > 0)
            gl = abs(sum(p for p in pnls if p < 0))
            pf = gp / gl if gl > 0 else float('inf')
            parts.append(f"{s}: n={len(pnls):3d} PF={pf:.2f}")

        print(f"{pair:12s}  {' | '.join(parts)}")


# === FULL PORTFOLIO ANALYSIS ===
print("\n\n" + "=" * 100)
print("PORTFOLIO PERFORMANCE SUMMARY")
print("=" * 100)

all_pnls = [t[2] for t in all_trades]
gp = sum(p for p in all_pnls if p > 0)
gl = abs(sum(p for p in all_pnls if p < 0))
cpf = gp / gl if gl > 0 else float('inf')
wr = sum(1 for p in all_pnls if p > 0) / len(all_pnls) * 100
cumul = (np.prod([1+p for p in all_pnls]) - 1) * 100

print(f"\nTotal trades: {len(all_pnls)}")
print(f"Combined PF: {cpf:.2f}")
print(f"Win rate: {wr:.1f}%")
print(f"Average per trade: {np.mean(all_pnls)*100:+.2f}%")
print(f"Cumulative return: {cumul:+.1f}%")

# Per-strategy breakdown
print("\n--- By Strategy ---")
for strat in ["ATR_L", "ATR_S", "MR_L", "MR_S"]:
        strat_pnls = [t[2] for t in all_trades if t[1] == strat]
        if strat_pnls:
            s = analyze_floats(strat_pnls)
        print(f"  {strat:6s}  n={s['n']:5d}  PF={s['pf']:5.2f}  WR={s['wr']:5.1f}%  Avg={s['avg']:+.2f}%  Cumul={s['cumul']:+.1f}%")

# Per-regime breakdown
print("\n--- By Regime ---")
for pair, trades in pair_results.items():
    df = load_pair(pair)
    if df is None:
        continue
    regime_aligned = regimes.reindex(df.index, method='ffill')

for regime in ["BULL", "BEAR", "CHOP"]:
    regime_trades = []
    for pair, trades_list in pair_results.items():
        for t in trades_list:
            if t.get('regime') == regime:
                regime_trades.append(t['pnl'])
    if regime_trades:
        s = analyze_floats(regime_trades)
        print(f"  {regime:6s}  n={s['n']:5d}  PF={s['pf']:5.2f}  WR={s['wr']:5.1f}%  Avg={s['avg']:+.2f}%  Cumul={s['cumul']:+.1f}%")

# Drawdown analysis
print("\n--- Drawdown Analysis ---")
running = 1.0
peak = 1.0
max_dd = 0
for pnl in all_pnls:
    running *= (1 + pnl)
    peak = max(peak, running)
    dd = (peak - running) / peak
    max_dd = max(max_dd, dd)
print(f"  Max drawdown: {max_dd*100:.1f}%")
print(f"  Return/MaxDD: {cumul/max_dd:.1f}x" if max_dd > 0 else "  No drawdown")

# Trade frequency estimate
years = 4.5  # approximate
trades_per_year = len(all_pnls) / years
trades_per_month = trades_per_year / 12
print(f"\n  Trades/year: ~{trades_per_year:.0f}")
print(f"  Trades/month: ~{trades_per_month:.0f}")

# Annualized return estimate (rough)
ann_ret = ((1 + cumul/100) ** (1/years) - 1) * 100
print(f"  Annualized return (rough): {ann_ret:+.1f}%")
