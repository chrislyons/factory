"""
Comprehensive Entry Timing Validation v2
=========================================
Fixed entry timing logic - T0 vs T1 must have different entry points.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0042

def load_data(pair='SOL', timeframe='240m'):
    """Load data with multiple naming conventions."""
    for p in [f'{pair}_USDT', f'{pair}USDT', pair]:
        path = DATA_DIR / f'binance_{p}_{timeframe}.parquet'
        if path.exists():
            return pd.read_parquet(path)
    return None

def run_timing_test(df, entry_offset, lookahead=8, friction=0.0042):
    """
    Run backtest with specific entry timing.
    
    entry_offset: 
        0 = enter at signal bar close (end of same bar)
        1 = enter at next bar open (T1)
        2 = enter 2 bars later (T2)
    
    The KEY difference: entry_offset determines WHEN we can enter after signal forms.
    """
    c = df['close'].values
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    
    # Precompute RSI
    close_series = df['close']
    delta = close_series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    
    # Precompute BB
    sma20 = close_series.rolling(20).mean().values
    std20 = close_series.rolling(20).std().values
    bb_l = sma20 - std20
    bb_h = sma20 + std20
    
    # Precompute ATR
    tr1 = h - l
    tr2 = np.abs(h - np.roll(c, 1))
    tr3 = np.abs(l - np.roll(c, 1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = (atr / c) * 100
    
    trades = []
    skipped_same = 0
    skipped_recovered = 0
    
    for i in range(100, len(c) - lookahead - 2):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(atr_pct[i]):
            continue
        
        # Signal conditions (on bar i)
        long_signal = rsi[i] < 35 and c[i] < bb_l[i]
        short_signal = rsi[i] > 65 and c[i] > bb_h[i]
        
        if not long_signal and not short_signal:
            continue
        
        # Entry bar (based on offset)
        entry_bar = i + entry_offset
        if entry_bar >= len(c) - lookahead:
            continue
        
        # Entry price = open of entry bar
        entry = o[entry_bar]
        
        # Check if signal still valid at entry (don't trade recovered signals)
        if long_signal:
            if c[entry_bar] > bb_l[entry_bar]:  # Price recovered above BB
                skipped_recovered += 1
                continue
        else:  # short_signal
            if c[entry_bar] < bb_h[entry_bar]:  # Price recovered below BB
                skipped_recovered += 1
                continue
        
        # Volatility-based stop/target
        atr_val = atr_pct[entry_bar] if not np.isnan(atr_pct[entry_bar]) else 3.0
        if atr_val < 2.0:
            stop_pct, target_pct = 0.015, 0.03
        elif atr_val < 4.0:
            stop_pct, target_pct = 0.01, 0.075
        else:
            stop_pct, target_pct = 0.005, 0.075
        
        # Set stop/target
        if long_signal:
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
        else:
            stop = entry * (1 + stop_pct)
            target = entry * (1 - target_pct)
        
        # Check subsequent bars for exit
        exited = False
        for j in range(1, lookahead + 1):
            check_bar = entry_bar + j
            if check_bar >= len(c):
                break
            
            bar_h = h[check_bar]
            bar_l = l[check_bar]
            
            if long_signal:
                hit_stop = bar_l <= stop
                hit_target = bar_h >= target
                
                if hit_stop and hit_target:
                    ret = -stop_pct - friction
                    trades.append(ret)
                    exited = True
                    break
                elif hit_stop:
                    ret = -stop_pct - friction
                    trades.append(ret)
                    exited = True
                    break
                elif hit_target:
                    ret = target_pct - friction
                    trades.append(ret)
                    exited = True
                    break
            else:
                hit_stop = bar_h >= stop
                hit_target = bar_l <= target
                
                if hit_stop and hit_target:
                    ret = -stop_pct - friction
                    trades.append(ret)
                    exited = True
                    break
                elif hit_stop:
                    ret = -stop_pct - friction
                    trades.append(ret)
                    exited = True
                    break
                elif hit_target:
                    ret = target_pct - friction
                    trades.append(ret)
                    exited = True
                    break
        
        if not exited:
            exit_price = c[min(entry_bar + lookahead, len(c) - 1)]
            if long_signal:
                ret = (exit_price - entry) / entry - friction
            else:
                ret = (entry - exit_price) / entry - friction
            trades.append(ret)
    
    return np.array(trades) if trades else np.array([]), skipped_recovered

def compute_stats(trades):
    """Compute performance statistics."""
    if len(trades) < 10:
        return {'n': len(trades), 'pf': np.nan, 'wr': np.nan, 'exp': np.nan, 'sharpe': np.nan}
    
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    wr = len(w) / len(trades) * 100
    exp = trades.mean() * 100
    sharpe = trades.mean() / trades.std() if trades.std() > 0 else 0
    
    return {'n': len(trades), 'pf': round(pf, 3), 'wr': round(wr, 1), 'exp': round(exp, 3), 'sharpe': round(sharpe, 3)}

def bootstrap_ci(trades, n_bootstrap=1000):
    """Bootstrap PF distribution."""
    if len(trades) < 50:
        return []
    
    pfs = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(trades, size=len(trades), replace=True)
        w = sample[sample > 0]
        ls = sample[sample <= 0]
        if len(ls) > 0 and ls.sum() != 0:
            pf = w.sum() / abs(ls.sum())
            if pf < 50:
                pfs.append(pf)
    return pfs

print("="*80)
print("ENTRY TIMING VALIDATION v2")
print("="*80)

pairs = ['SOL', 'BTC', 'ETH', 'NEAR', 'LINK', 'AVAX']
offsets = [0, 1, 2, 3]
offset_labels = ['T0 (same bar)', 'T1 (1 bar)', 'T2 (2 bars)', 'T3 (3 bars)']

# ===============================
# TEST 1: All pairs, all offsets
# ===============================
print("\n--- TEST 1: ALL PAIRS ---\n")
print(f"{'Pair':>6}", end='')
for label in offset_labels:
    print(f" {label:>12}", end='')
print()
print("-" * 70)

all_results = {}
for pair in pairs:
    df = load_data(pair, '240m')
    if df is None:
        print(f"{pair:>6}: NO DATA")
        continue
    
    print(f"{pair:>6}", end='')
    pair_results = {}
    for offset, label in zip(offsets, offset_labels):
        trades, skipped = run_timing_test(df, offset)
        s = compute_stats(trades)
        pair_results[label] = {'trades': trades, 'stats': s, 'skipped': skipped}
        pf_str = f"{s['pf']:.3f}" if not np.isnan(s['pf']) else "N/A"
        print(f" {pf_str:>12}", end='')
    
    all_results[pair] = pair_results
    print()

# ===============================
# TEST 2: Aggregate statistics
# ===============================
print("\n--- TEST 2: AGGREGATE STATISTICS ---\n")

for offset, label in zip(offsets, offset_labels):
    all_trades = []
    for pair in pairs:
        if pair in all_results:
            all_trades.extend(all_results[pair][label]['trades'])
    
    all_trades = np.array(all_trades)
    if len(all_trades) > 0:
        s = compute_stats(all_trades)
        print(f"{label:>15}: n={s['n']}, PF={s['pf']:.3f}, WR={s['wr']:.1f}%, Exp={s['exp']:.3f}%, Sharpe={s['sharpe']:.3f}")

# ===============================
# TEST 3: T1 vs T0 comparison
# ===============================
print("\n--- TEST 3: T1 vs T0 EDGE ---\n")

for pair in pairs:
    if pair not in all_results:
        continue
    t0 = all_results[pair]['T0 (same bar)']['stats']
    t1 = all_results[pair]['T1 (1 bar)']['stats']
    t2 = all_results[pair]['T2 (2 bars)']['stats']
    
    if np.isnan(t0['pf']) or np.isnan(t1['pf']):
        continue
    
    delta = t1['pf'] - t0['pf']
    best = 'T1' if t1['pf'] > t0['pf'] and t1['pf'] > t2['pf'] else ('T0' if t0['pf'] > t1['pf'] else 'T2')
    print(f"{pair:>6}: T0={t0['pf']:.3f}, T1={t1['pf']:.3f}, T2={t2['pf']:.3f}, Delta={delta:+.3f}, Best={best}")

# ===============================
# TEST 4: Statistical significance (SOL)
# ===============================
print("\n--- TEST 4: BOOTSTRAP SIGNIFICANCE (SOL) ---\n")

if 'SOL' in all_results:
    t0_trades = all_results['SOL']['T0 (same bar)']['trades']
    t1_trades = all_results['SOL']['T1 (1 bar)']['trades']
    
    if len(t0_trades) > 50 and len(t1_trades) > 50:
        # Bootstrap each
        pfs_t0 = bootstrap_ci(t0_trades)
        pfs_t1 = bootstrap_ci(t1_trades)
        
        if pfs_t0 and pfs_t1:
            pfs_t0 = np.array(pfs_t0)
            pfs_t1 = np.array(pfs_t1)
            
            print(f"T0: mean PF = {pfs_t0.mean():.3f}, 95% CI = [{np.percentile(pfs_t0, 2.5):.3f}, {np.percentile(pfs_t0, 97.5):.3f}]")
            print(f"T1: mean PF = {pfs_t1.mean():.3f}, 95% CI = [{np.percentile(pfs_t1, 2.5):.3f}, {np.percentile(pfs_t1, 97.5):.3f}]")
            
            # Bootstrap difference
            diffs = []
            for _ in range(1000):
                s0 = np.random.choice(t0_trades, size=len(t0_trades), replace=True)
                s1 = np.random.choice(t1_trades, size=len(t1_trades), replace=True)
                
                pf0 = s0[s0 > 0].sum() / abs(s0[s0 <= 0].sum()) if s0[s0 <= 0].sum() != 0 else 1.0
                pf1 = s1[s1 > 0].sum() / abs(s1[s1 <= 0].sum()) if s1[s1 <= 0].sum() != 0 else 1.0
                
                if pf0 < 50 and pf1 < 50:
                    diffs.append(pf1 - pf0)
            
            diffs = np.array(diffs)
            p_value = (diffs <= 0).mean()
            
            print(f"\nT1 - T0 difference:")
            print(f"  Mean: {diffs.mean():.3f}")
            print(f"  95% CI: [{np.percentile(diffs, 2.5):.3f}, {np.percentile(diffs, 97.5):.3f}]")
            print(f"  P(T1 <= T0): {p_value:.4f}")
            print(f"  {'SIGNIFICANT (T1 > T0)' if p_value < 0.05 else 'NOT SIGNIFICANT'}")

# ===============================
# TEST 5: Temporal split
# ===============================
print("\n--- TEST 5: TEMPORAL SPLIT (SOL) ---\n")

if 'SOL' in pairs:
    df_sol = load_data('SOL', '240m')
    if df_sol is not None:
        n = len(df_sol)
        splits = [
            ('Q1 (oldest)', df_sol.iloc[:n//4]),
            ('Q2', df_sol.iloc[n//4:n//2]),
            ('Q3', df_sol.iloc[n//2:3*n//4]),
            ('Q4 (newest)', df_sol.iloc[3*n//4:]),
        ]
        
        print(f"{'Period':>12} {'T0 PF':>8} {'T1 PF':>8} {'T2 PF':>8} {'Best':>6}")
        print("-" * 50)
        
        for name, split_df in splits:
            results = {}
            for offset, label in zip([0, 1, 2], ['T0', 'T1', 'T2']):
                trades, _ = run_timing_test(split_df, offset)
                s = compute_stats(trades)
                results[label] = s['pf']
            
            best = max(results, key=results.get) if not any(np.isnan(v) for v in results.values()) else 'N/A'
            print(f"{name:>12} {results.get('T0', 0):>8.3f} {results.get('T1', 0):>8.3f} {results.get('T2', 0):>8.3f} {best:>6}")

# ===============================
# TEST 6: Regime split
# ===============================
print("\n--- TEST 6: VOLATILITY REGIME (SOL) ---\n")

if 'SOL' in pairs:
    df_sol = load_data('SOL', '240m')
    if df_sol is not None:
        df_sol = df_sol.copy()
        df_sol['atr'] = (df_sol['high'] - df_sol['low']).rolling(14).mean()
        df_sol['atr_pct'] = (df_sol['atr'] / df_sol['close']) * 100
        
        threshold = df_sol['atr_pct'].dropna().quantile(0.5)
        
        high_vol = df_sol[df_sol['atr_pct'] > threshold]
        low_vol = df_sol[df_sol['atr_pct'] <= threshold]
        
        print(f"High Volatility (ATR > {threshold:.2f}%):")
        for offset, label in zip([0, 1, 2], ['T0', 'T1', 'T2']):
            trades, _ = run_timing_test(high_vol, offset)
            s = compute_stats(trades)
            print(f"  {label}: n={s['n']}, PF={s['pf']:.3f}, Exp={s['exp']:.3f}%")
        
        print(f"\nLow Volatility (ATR <= {threshold:.2f}%):")
        for offset, label in zip([0, 1, 2], ['T0', 'T1', 'T2']):
            trades, _ = run_timing_test(low_vol, offset)
            s = compute_stats(trades)
            print(f"  {label}: n={s['n']}, PF={s['pf']:.3f}, Exp={s['exp']:.3f}%")

print("\n" + "="*80)
print("TESTS COMPLETE")
print("="*80)
