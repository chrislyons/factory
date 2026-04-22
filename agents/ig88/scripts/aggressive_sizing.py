#!/usr/bin/env python3
"""
Aggressive position sizing to find optimal risk+leverage for 2x+ returns.
Runs the combined portfolio at various risk levels.
"""
import pandas as pd, numpy as np
from pathlib import Path

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

def run_strategies(df, df4h):
    results = []
    friction = 0.0014
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    atr = compute_atr(c, h, l, 10)
    upper_dc = pd.Series(h).rolling(20).max().values
    sma = pd.Series(c).rolling(100).mean().values

    # 1H LONG
    it = False; ep = eb = hi = 0
    for i in range(120, len(c)):
        if it:
            hi = max(hi, h[i]); trail = hi * 0.99; hrs = i - eb
            if hrs < 4 and atr[i] > 0: trail = max(trail, ep - atr[i]*1.5)
            if l[i] <= trail or hrs >= 96:
                xp = trail if l[i] <= trail else c[i]
                results.append((df.index[i], (xp-ep)/ep-friction)); it = False
        if not it and c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]:
            it = True; ep = c[i-1]; eb = i; hi = h[i-1]

    # 1H SHORT
    lower_dc = pd.Series(l).rolling(20).min().values
    it = False; ep = eb = lo = 0
    for i in range(120, len(c)):
        if it:
            lo = min(lo, l[i]); trail = lo * 1.025; hrs = i - eb
            if h[i] >= trail or hrs >= 48:
                xp = trail if h[i] >= trail else c[i]
                results.append((df.index[i], (ep-xp)/ep-friction)); it = False
        if not it and c[i-1] < sma[i-1]:
            trigger = lower_dc[i-2] - atr[i-1] * 1.5
            if c[i-1] < trigger: it = True; ep = c[i-1]; eb = i; lo = l[i-1]

    # 4H LONG
    c4, h4, l4 = df4h['close'].values, df4h['high'].values, df4h['low'].values
    atr4 = compute_atr(c4, h4, l4, 14)
    upper_dc4 = pd.Series(h4).rolling(20).max().values
    sma4 = pd.Series(c4).rolling(100).mean().values
    it = False; ep = eb = hi = 0
    for i in range(120, len(c4)):
        if it:
            hi = max(hi, h4[i]); trail = hi * 0.985; bars = i - eb
            if l4[i] <= trail or bars >= 30:
                xp = trail if l4[i] <= trail else c4[i]
                results.append((df4h.index[i], (xp-ep)/ep-friction)); it = False
        if not it and c4[i-1] > sma4[i-1] and c4[i-1] > upper_dc4[i-2]:
            it = True; ep = c4[i-1]; eb = i; hi = h4[i-1]

    # 4H SHORT
    lower_dc4 = pd.Series(l4).rolling(20).min().values
    it = False; ep = eb = lo = 0
    for i in range(120, len(c4)):
        if it:
            lo = min(lo, l4[i]); trail = lo * 1.025; bars = i - eb
            if h4[i] >= trail or bars >= 20:
                xp = trail if h4[i] >= trail else c4[i]
                results.append((df4h.index[i], (ep-xp)/ep-friction)); it = False
        if not it and c4[i-1] < sma4[i-1]:
            trigger = lower_dc4[i-2] - atr4[i-1] * 1.5
            if c4[i-1] < trigger: it = True; ep = c4[i-1]; eb = i; lo = l4[i-1]

    return results

# Load all data
pairs = ["SOLUSDT","BTCUSDT","ETHUSDT","AVAXUSDT","ARBUSDT","OPUSDT",
         "LINKUSDT","RENDERUSDT","NEARUSDT","AAVEUSDT","DOGEUSDT","LTCUSDT"]
all_trades = []
for pair in pairs:
    df, df4h = load_and_resample(pair)
    if df is None: continue
    all_trades.extend(run_strategies(df, df4h))
all_trades.sort(key=lambda x: x[0])

# Simulate at various risk+leverage combos
# Key insight: with N concurrent positions, effective risk = risk_pct / N * leverage
# We need to find the right concurrent position assumption

print("=" * 90)
print("AGGRESSIVE RETURN PROJECTIONS — Combined 1H+4H Portfolio")
print(f"Total backtest trades: {len(all_trades)}")
print("=" * 90)

# Test with different concurrent position assumptions
for concurrent in [3, 5, 8]:
    print(f"\n--- {concurrent} Concurrent Positions ---")
    print(f"{'Risk%':>6s} {'Lev':>4s} {'Eff.Risk':>9s} {'Ann.Ret':>9s} {'MaxDD':>7s} {'Sharpe':>7s} {'$10K→':>12s} {'Verdict':>10s}")
    print("-" * 72)

    for risk_pct in [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]:
        for lev in [1, 3, 5]:
            eff_risk = risk_pct / 100 / concurrent * lev
            equity = 10000
            peak = equity
            max_dd = 0
            monthly_rets = []
            prev_eq = equity

            for date, pnl in all_trades:
                trade_return = pnl * eff_risk
                equity *= (1 + trade_return)
                peak = max(peak, equity)
                dd = (peak - equity) / peak
                max_dd = max(max_dd, dd)

            years = 9.5  # ~2017-2026
            ann_ret = ((equity / 10000) ** (1/years) - 1) * 100

            # Estimate Sharpe: ann_ret / (max_dd * 10) — rough approximation
            sharpe = ann_ret / (max_dd * 100 * 10) if max_dd > 0 else 0

            verdict = ""
            if ann_ret >= 200: verdict = "★ AGGRESSIVE"
            elif ann_ret >= 100: verdict = "★ 2x+"
            elif ann_ret >= 50: verdict = "✓ GOOD"
            elif ann_ret >= 20: verdict = "OK"

            if ann_ret >= 15:  # Only show meaningful results
                print(f"{risk_pct:>5.0f}% {lev:>3d}x {eff_risk*100:>8.2f}% {ann_ret:>+8.0f}% {max_dd*100:>6.1f}% {sharpe:>6.2f} ${equity:>11,.0f} {verdict}")

# Find the optimal for Chris's target
print(f"\n{'=' * 90}")
print("RECOMMENDED CONFIGURATION FOR 2x+ ANNUAL RETURNS")
print(f"{'=' * 90}")

# Find minimum risk+leverage for 100%+ annual with max concurrent=5
best = None
for risk_pct in np.arange(1, 15, 0.5):
    for lev in [1, 3, 5, 10]:
        eff_risk = risk_pct / 100 / 5 * lev
        equity = 10000
        peak = equity
        max_dd = 0
        for date, pnl in all_trades:
            equity *= (1 + pnl * eff_risk)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak)
        years = 9.5
        ann_ret = ((equity / 10000) ** (1/years) - 1) * 100
        if ann_ret >= 100 and max_dd < 0.25:  # 2x+ with DD < 25%
            if best is None or (risk_pct + lev) < (best[0] + best[1]):
                best = (risk_pct, lev, ann_ret, max_dd, equity)

if best:
    print(f"\nMinimum config for 2x+ with DD < 25%:")
    print(f"  Risk: {best[0]}% per trade")
    print(f"  Leverage: {best[1]}x")
    print(f"  Expected annual: {best[2]:+.0f}%")
    print(f"  Max drawdown: {best[3]*100:.1f}%")
    print(f"  $10K after 10 years: ${best[4]:,.0f}")
else:
    print("\nNo config found meeting criteria. Need higher risk or leverage.")
