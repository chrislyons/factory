"""
FINAL VALIDATION: Entry Timing Edge
=====================================
Bulletproof confirmation of T1 edge with:
1. All 6 pairs
2. Multiple lookaheads
3. Both venues (Kraken 0.42%, Jupiter 0.25%)
4. Bootstrap significance
5. Walk-forward stability
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

def load_data(pair='SOL', timeframe='240m'):
    for p in [f'{pair}_USDT', f'{pair}USDT', pair]:
        path = DATA_DIR / f'binance_{p}_{timeframe}.parquet'
        if path.exists():
            return pd.read_parquet(path)
    return None

def compute_indicators(df):
    c = df['close'].values
    close_series = df['close']
    
    # RSI
    delta = close_series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    
    # BB 1σ
    sma20 = close_series.rolling(20).mean().values
    std20 = close_series.rolling(20).std().values
    bb_l = sma20 - std20
    bb_h = sma20 + std20
    
    # Volume
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    # ATR
    h, l, c_arr = df['high'].values, df['low'].values, df['close'].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c_arr, 1)), np.abs(l - np.roll(c_arr, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    return rsi, bb_l, bb_h, vol_ratio, atr, c_arr, df['open'].values, h, l

def run_backtest(df, entry_offset, friction=0.0025, lookahead=8):
    """Run MR strategy with specific entry offset."""
    rsi, bb_l, bb_h, vol_ratio, atr, c, o, h, l = compute_indicators(df)
    
    trades = []
    for i in range(100, len(c) - entry_offset - lookahead - 1):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        
        # MR Signal
        if not (rsi[i] < 35 and c[i] < bb_l[i] and vol_ratio[i] > 1.2):
            continue
        
        # Entry
        entry_bar = i + entry_offset
        if entry_bar >= len(c) - lookahead:
            continue
        
        # Skip if recovered
        if c[entry_bar] > bb_l[entry_bar]:
            continue
        if rsi[entry_bar] > 40:
            continue
        
        entry = o[entry_bar]
        
        # Stop/target
        atr_pct = atr[entry_bar] / entry if entry > 0 else 0.03
        if atr_pct < 0.02:
            stop_pct, target_pct = 0.015, 0.03
        elif atr_pct < 0.04:
            stop_pct, target_pct = 0.01, 0.075
        else:
            stop_pct, target_pct = 0.005, 0.075
        
        stop = entry * (1 - stop_pct)
        target = entry * (1 + target_pct)
        
        # Exit
        exited = False
        for j in range(1, lookahead + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            
            if l[bar] <= stop:
                trades.append(-stop_pct - friction)
                exited = True
                break
            elif h[bar] >= target:
                trades.append(target_pct - friction)
                exited = True
                break
        
        if not exited:
            exit_price = c[min(entry_bar + lookahead, len(c) - 1)]
            trades.append((exit_price - entry) / entry - friction)
    
    return np.array(trades) if trades else np.array([])

def calc_stats(trades):
    if len(trades) < 10:
        return None
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {
        'n': len(trades),
        'pf': round(pf, 3),
        'wr': round(len(w)/len(trades)*100, 1),
        'exp': round(trades.mean()*100, 3),
    }

def bootstrap_test(t0_trades, t1_trades, n_iter=2000):
    """Bootstrap significance test."""
    diffs = []
    for _ in range(n_iter):
        s0 = np.random.choice(t0_trades, size=len(t0_trades), replace=True)
        s1 = np.random.choice(t1_trades, size=len(t1_trades), replace=True)
        pf0 = s0[s0 > 0].sum() / abs(s0[s0 <= 0].sum()) if s0[s0 <= 0].sum() != 0 else 1
        pf1 = s1[s1 > 0].sum() / abs(s1[s1 <= 0].sum()) if s1[s1 <= 0].sum() != 0 else 1
        if pf0 < 50 and pf1 < 50:
            diffs.append(pf1 - pf0)
    
    diffs = np.array(diffs)
    return {
        'mean': round(diffs.mean(), 3),
        'ci_low': round(np.percentile(diffs, 2.5), 3),
        'ci_high': round(np.percentile(diffs, 97.5), 3),
        'p_value': round((diffs <= 0).mean(), 4),
    }

print("="*80)
print("FINAL ENTRY TIMING VALIDATION")
print("="*80)

pairs = ['SOL', 'BTC', 'ETH', 'NEAR', 'LINK', 'AVAX']

# Test 1: All pairs, both venues
print("\n--- TEST 1: ALL PAIRS (Jupiter 0.25% friction) ---\n")
print(f"{'Pair':>6} {'T0 n':>6} {'T0 PF':>7} {'T1 n':>6} {'T1 PF':>7} {'T2 n':>6} {'T2 PF':>7} {'Winner':>7}")
print("-" * 70)

all_t0 = []
all_t1 = []

for pair in pairs:
    df = load_data(pair)
    if df is None:
        continue
    
    t0 = run_backtest(df, 0, 0.0025)
    t1 = run_backtest(df, 1, 0.0025)
    t2 = run_backtest(df, 2, 0.0025)
    
    s0 = calc_stats(t0)
    s1 = calc_stats(t1)
    s2 = calc_stats(t2)
    
    all_t0.extend(t0)
    all_t1.extend(t1)
    
    winner = 'T1' if (s1 and s0 and s1['pf'] > s0['pf']) else 'T0'
    
    print(f"{pair:>6} {s0['n']:6} {s0['pf']:7.3f} {s1['n']:6} {s1['pf']:7.3f} {s2['n']:6} {s2['pf']:7.3f} {winner:>7}")

# Aggregate
all_t0 = np.array(all_t0)
all_t1 = np.array(all_t1)
s0 = calc_stats(all_t0)
s1 = calc_stats(all_t1)
print("-" * 70)
print(f"{'TOTAL':>6} {s0['n']:6} {s0['pf']:7.3f} {s1['n']:6} {s1['pf']:7.3f}")

# Test 2: Bootstrap significance
print("\n--- TEST 2: STATISTICAL SIGNIFICANCE ---\n")
sig = bootstrap_test(all_t0, all_t1)
print(f"T1 - T0 difference:")
print(f"  Mean: {sig['mean']:.3f}")
print(f"  95% CI: [{sig['ci_low']:.3f}, {sig['ci_high']:.3f}]")
print(f"  P(T1 <= T0): {sig['p_value']:.4f}")
print(f"  Result: {'SIGNIFICANT ***' if sig['p_value'] < 0.001 else ('Significant' if sig['p_value'] < 0.05 else 'Not significant')}")

# Test 3: Lookahead sensitivity
print("\n--- TEST 3: LOOKAHEAD SENSITIVITY (SOL) ---\n")
df_sol = load_data('SOL')
print(f"{'Lookahead':>10} {'T0 PF':>8} {'T1 PF':>8} {'T1 Better':>10}")
print("-" * 40)
for lk in [4, 6, 8, 12, 16]:
    t0 = run_backtest(df_sol, 0, 0.0025, lk)
    t1 = run_backtest(df_sol, 1, 0.0025, lk)
    s0 = calc_stats(t0)
    s1 = calc_stats(t1)
    better = '✓' if s1['pf'] > s0['pf'] else '✗'
    print(f"{lk:>10} {s0['pf']:>8.3f} {s1['pf']:>8.3f} {better:>10}")

# Test 4: Walk-forward (quarters)
print("\n--- TEST 4: WALK-FORWARD STABILITY (SOL) ---\n")
df_sol = load_data('SOL')
n = len(df_sol)
quarters = [
    ('Q1 (oldest)', df_sol.iloc[:n//4]),
    ('Q2', df_sol.iloc[n//4:n//2]),
    ('Q3', df_sol.iloc[n//2:3*n//4]),
    ('Q4 (newest)', df_sol.iloc[3*n//4:]),
]
print(f"{'Period':>12} {'T0 PF':>8} {'T1 PF':>8} {'Delta':>8} {'Winner':>7}")
print("-" * 50)
for name, qdf in quarters:
    t0 = run_backtest(qdf, 0, 0.0025)
    t1 = run_backtest(qdf, 1, 0.0025)
    s0 = calc_stats(t0)
    s1 = calc_stats(t1)
    delta = s1['pf'] - s0['pf']
    winner = 'T1' if s1['pf'] > s0['pf'] else 'T0'
    print(f"{name:>12} {s0['pf']:>8.3f} {s1['pf']:>8.3f} {delta:>+8.3f} {winner:>7}")

# Test 5: Venue comparison
print("\n--- TEST 5: VENUE COMPARISON ---\n")
print(f"{'Venue':>15} {'Friction':>10} {'T0 PF':>8} {'T1 PF':>8} {'T1 Profitable':>15}")
print("-" * 60)
for venue, friction in [('Kraken Spot', 0.0042), ('Jupiter Perps', 0.0025), ('Theoretical', 0.0)]:
    t0_all = []
    t1_all = []
    for pair in pairs[:3]:  # Quick test on 3 pairs
        df = load_data(pair)
        if df is None:
            continue
        t0_all.extend(run_backtest(df, 0, friction))
        t1_all.extend(run_backtest(df, 1, friction))
    
    s0 = calc_stats(np.array(t0_all))
    s1 = calc_stats(np.array(t1_all))
    profitable = 'YES ✓' if s1['pf'] > 1.0 else 'NO'
    print(f"{venue:>15} {friction*100:>9.2f}% {s0['pf']:>8.3f} {s1['pf']:>8.3f} {profitable:>15}")

print("\n" + "="*80)
print("VALIDATION COMPLETE")
print("="*80)
