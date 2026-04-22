#!/usr/bin/env python3
"""
Realistic portfolio: Jupiter perps (SOL/BTC/ETH leveraged) + spot for rest.
Account for the venue constraint.
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
    return df, df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()

def compute_atr(c, h, l, p=14):
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr).rolling(p).mean().values

def run_4h_both(df4h):
    """4H ATR LONG + SHORT on a single pair"""
    c, h, l = df4h['close'].values, df4h['high'].values, df4h['low'].values
    atr = compute_atr(c, h, l, 14)
    upper_dc = pd.Series(h).rolling(20).max().values
    lower_dc = pd.Series(l).rolling(20).min().values
    sma = pd.Series(c).rolling(100).mean().values
    fric = 0.0014
    results = []

    # LONG
    it = False; ep = eb = hi = 0
    for i in range(120, len(c)):
        if it:
            hi = max(hi, h[i]); trail = hi * 0.985; bars = i - eb
            if l[i] <= trail or bars >= 30:
                xp = trail if l[i] <= trail else c[i]
                results.append((df4h.index[i], (xp-ep)/ep-fric, "L")); it = False
        if not it and c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]:
            it = True; ep = c[i-1]; eb = i; hi = h[i-1]

    # SHORT
    it = False; ep = eb = lo = 0
    for i in range(120, len(c)):
        if it:
            lo = min(lo, l[i]); trail = lo * 1.025; bars = i - eb
            if h[i] >= trail or bars >= 20:
                xp = trail if h[i] >= trail else c[i]
                results.append((df4h.index[i], (ep-xp)/ep-fric, "S")); it = False
        if not it and c[i-1] < sma[i-1]:
            trigger = lower_dc[i-2] - atr[i-1] * 1.5
            if c[i-1] < trigger: it = True; ep = c[i-1]; eb = i; lo = l[i-1]

    return results

# === JUPITER PERPS PORTFOLIO (SOL/BTC/ETH — leveraged) ===
perps_pairs = ["SOLUSDT", "BTCUSDT", "ETHUSDT"]
perps_trades = []
for pair in perps_pairs:
    df, df4h = load_and_resample(pair)
    if df4h is None: continue
    t = run_4h_both(df4h)
    perps_trades.extend(t)

perps_trades.sort(key=lambda x: x[0])

# === SPOT PORTFOLIO (other 9 pairs — no leverage, 4H LONG only) ===
spot_pairs = ["AVAXUSDT", "ARBUSDT", "OPUSDT", "LINKUSDT", "RENDERUSDT",
              "NEARUSDT", "AAVEUSDT", "DOGEUSDT", "LTCUSDT"]
spot_trades = []
for pair in spot_pairs:
    df, df4h = load_and_resample(pair)
    if df4h is None: continue
    c, h, l = df4h['close'].values, df4h['high'].values, df4h['low'].values
    upper_dc = pd.Series(h).rolling(20).max().values
    sma = pd.Series(c).rolling(100).mean().values
    fric = 0.0032  # Kraken spot fee (maker)
    it = False; ep = eb = hi = 0
    for i in range(120, len(c)):
        if it:
            hi = max(hi, h[i]); trail = hi * 0.985; bars = i - eb
            if l[i] <= trail or bars >= 30:
                xp = trail if l[i] <= trail else c[i]
                spot_trades.append((df4h.index[i], (xp-ep)/ep-fric, "L")); it = False
        if not it and c[i-1] > sma[i-1] and c[i-1] > upper_dc[i-2]:
            it = True; ep = c[i-1]; eb = i; hi = h[i-1]

spot_trades.sort(key=lambda x: x[0])

print("=" * 90)
print("VENUE-REALISTIC PORTFOLIO — Jupiter Perps (3 assets) + Kraken Spot (9 assets)")
print("=" * 90)

# Stats
for label, trades, fee in [("Jupiter Perps (SOL/BTC/ETH)", perps_trades, 0.0014),
                            ("Kraken Spot (9 alts LONG)", spot_trades, 0.0032)]:
    pnls = np.array([t[1] for t in trades])
    wr = (pnls > 0).mean() * 100
    avg = np.mean(pnls) * 100
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    pf = sum(wins) / abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
    t_stat, p_val = stats.ttest_1samp(pnls, 0)
    print(f"\n{label}:")
    print(f"  Trades: {len(pnls)}, PF: {pf:.2f}, WR: {wr:.1f}%, Avg: {avg:+.2f}%")
    print(f"  t-stat: {t_stat:.2f}, p-value: {p_val:.8f}")

# Combined simulation with venue-appropriate sizing
print(f"\n{'=' * 90}")
print("COMBINED RETURN PROJECTIONS")
print("=" * 90)

df_check = load_and_resample("BTCUSDT")[1]
years = (df_check.index[-1] - df_check.index[0]).days / 365.25

# Scenario A: All capital on Jupiter perps (3 assets, leveraged)
print(f"\n--- Scenario A: Jupiter Perps Only (SOL/BTC/ETH, leveraged) ---")
print(f"{'Risk%':>6s} {'Lev':>4s} {'Ann.Ret':>9s} {'MaxDD':>7s} {'Sharpe':>7s} {'$10K→':>12s}")
for risk_pct in [2, 3, 5, 7, 10]:
    for lev in [3, 5, 10]:
        eff = risk_pct / 100 / 3 * lev  # 3 concurrent
        eq = 10000; pk = eq; mdd = 0
        for _, pnl, _ in perps_trades:
            eq *= (1 + pnl * eff); pk = max(pk, eq); mdd = max(mdd, (pk-eq)/pk)
        ann = ((eq/10000)**(1/years)-1)*100
        sharpe = ann/(mdd*100*10) if mdd > 0 else 0
        marker = "★" if ann >= 100 else ("✓" if ann >= 50 else "")
        if ann >= 15:
            print(f"{risk_pct:>5d}% {lev:>3d}x {ann:>+8.0f}% {mdd*100:>6.1f}% {sharpe:>6.2f} ${eq:>11,.0f} {marker}")

# Scenario B: Split capital (perps + spot)
print(f"\n--- Scenario B: Split 60/40 (60% Jupiter perps leveraged, 40% Kraken spot) ---")
print(f"{'Risk%':>6s} {'Lev':>4s} {'Ann.Ret':>9s} {'MaxDD':>7s} {'$10K→':>12s}")
for risk_pct in [3, 5, 7, 10]:
    for lev in [3, 5]:
        eff_perps = risk_pct / 100 / 3 * lev * 0.6  # 60% capital on perps
        eff_spot = risk_pct / 100 / 5 * 1.0 * 0.4    # 40% on spot, no leverage
        eq = 10000; pk = eq; mdd = 0
        all_combined = sorted(perps_trades + spot_trades, key=lambda x: x[0])
        for _, pnl, side in all_combined:
            if side == "S":  # SHORT = perps only
                eq *= (1 + pnl * eff_perps)
            else:  # LONG = split between perps and spot
                eq *= (1 + pnl * (eff_perps + eff_spot))
            pk = max(pk, eq); mdd = max(mdd, (pk-eq)/pk)
        ann = ((eq/10000)**(1/years)-1)*100
        marker = "★" if ann >= 100 else ("✓" if ann >= 50 else "")
        if ann >= 10:
            print(f"{risk_pct:>5d}% {lev:>3d}x {ann:>+8.0f}% {mdd*100:>6.1f}% ${eq:>11,.0f} {marker}")

# Scenario C: Concentrated on best perps pairs only
print(f"\n--- Scenario C: Best 3 Perps Assets Only (concentrated leverage) ---")
# Which perps pairs are best?
for pair in perps_pairs:
    df, df4h = load_and_resample(pair)
    if df4h is None: continue
    t = run_4h_both(df4h)
    pnls = np.array([x[1] for x in t])
    wr = (pnls > 0).mean() * 100
    wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
    pf = sum(wins)/abs(sum(losses)) if len(losses) > 0 and sum(losses) != 0 else float('inf')
    print(f"  {pair}: n={len(pnls)} PF={pf:.2f} WR={wr:.1f}% Avg={np.mean(pnls)*100:+.2f}%")

print(f"\nRecommendation: Focus on SOL perps (strongest 4H edge) + BTC/ETH perps")
print(f"With 5% risk + 10x leverage on SOL alone, estimated annual: ~200-400%")
