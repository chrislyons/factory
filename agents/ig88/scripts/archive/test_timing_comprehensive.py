"""
Comprehensive Entry Timing Validation
=====================================
Test: Is the T1 edge robust across:
1. Timeframes (4h, 2h, 1h)
2. Market regimes (high/low volatility periods)
3. Time periods (early vs recent data)
4. Different signal types (RSI+BB vs RSI only vs BB only)
5. Statistical significance (bootstrap confidence intervals)

Goal: Prove the edge is real, not noise.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json
from scipy import stats

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0042

def load_data(pair='SOL', timeframe='240m'):
    """Load data with multiple naming conventions."""
    for p in [f'{pair}_USDT', f'{pair}USDT', pair]:
        path = DATA_DIR / f'binance_{p}_{timeframe}.parquet'
        if path.exists():
            return pd.read_parquet(path)
    return None

def compute_rsi(close, period=14):
    """RSI calculation."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, min_periods=period).mean()
    return 100 - (100 / (1 + gain / loss))

def compute_bb(close, period=20, std_dev=1.0):
    """Bollinger Bands."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return sma - std * std_dev, sma + std * std_dev

def compute_atr(high, low, close, period=14):
    """ATR calculation."""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def get_stop_target(atr_pct):
    """Adaptive stop/target based on volatility."""
    if atr_pct < 2.0:
        return 0.015, 0.03
    elif atr_pct < 4.0:
        return 0.01, 0.075
    else:
        return 0.005, 0.075

def run_timing_test(df, entry_offset, signal_type='rsi_bb', lookahead=8, friction=0.0042):
    """
    Run backtest with specific entry timing.
    
    entry_offset: 0 = T0, 1 = T1 (next bar), 2 = T2, etc.
    signal_type: 'rsi_bb', 'rsi_only', 'bb_only'
    """
    df = df.copy()
    c = df['close'].values
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    
    # Compute indicators
    df['rsi'] = compute_rsi(df['close'])
    bb_l, bb_h = compute_bb(df['close'])
    df['bb_lower'] = bb_l
    df['bb_upper'] = bb_h
    df['atr'] = compute_atr(df['high'], df['low'], df['close'])
    df['atr_pct'] = (df['atr'] / df['close']) * 100
    
    rsi = df['rsi'].values
    bbl = df['bb_lower'].values
    bbh = df['bb_upper'].values
    atr_pct = df['atr_pct'].values
    
    trades = []
    
    for i in range(100, len(c) - lookahead - entry_offset - 2):
        if pd.isna(rsi[i]) or pd.isna(bbl[i]) or pd.isna(atr_pct[i]):
            continue
        
        atr_val = atr_pct[i] if not pd.isna(atr_pct[i]) else 3.0
        stop_pct, target_pct = get_stop_target(atr_val)
        
        # Determine signal
        long_signal = False
        short_signal = False
        
        if signal_type == 'rsi_bb':
            long_signal = rsi[i] < 35 and c[i] < bbl[i]
            short_signal = rsi[i] > 65 and c[i] > bbh[i]
        elif signal_type == 'rsi_only':
            long_signal = rsi[i] < 35
            short_signal = rsi[i] > 65
        elif signal_type == 'bb_only':
            long_signal = c[i] < bbl[i]
            short_signal = c[i] > bbh[i]
        
        if not long_signal and not short_signal:
            continue
        
        # Check if signal persists to entry point
        if entry_offset == 0:
            # Enter at current bar open (optimistic)
            entry = o[i + 1] if i + 1 < len(c) else c[i]
            entry_bar = i + 1
        else:
            # Wait entry_offset bars
            entry_bar = i + entry_offset
            if entry_bar >= len(c):
                continue
            entry = o[entry_bar]
        
        # For RSI signals, check if signal still valid at entry
        if signal_type in ['rsi_bb', 'rsi_only']:
            entry_rsi = rsi[entry_bar] if entry_bar < len(rsi) else 50
            if long_signal and entry_rsi > 40:  # RSI recovered, skip
                continue
            if short_signal and entry_rsi < 60:  # RSI recovered, skip
                continue
        
        # For BB signals, check if price still beyond BB
        if signal_type in ['rsi_bb', 'bb_only']:
            entry_bb = bbl[entry_bar] if long_signal else bbh[entry_bar]
            if pd.isna(entry_bb):
                continue
            if long_signal and c[entry_bar] > entry_bb:
                continue  # Price recovered, skip
            if short_signal and c[entry_bar] < entry_bb:
                continue  # Price recovered, skip
        
        # Set stop/target based on entry price
        if long_signal:
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
        else:
            stop = entry * (1 + stop_pct)
            target = entry * (1 - target_pct)
        
        # Check subsequent bars for exit (start AFTER entry bar)
        exited = False
        for j in range(1, lookahead + 1):
            check_bar = entry_bar + j
            if check_bar >= len(c):
                break
            
            bar_h = h[check_bar]
            bar_l = l[check_bar]
            
            if long_signal:
                # Long: stop below, target above
                if bar_l <= stop and bar_h >= target:
                    ret = -stop_pct - friction
                    trades.append(ret)
                    exited = True
                    break
                elif bar_l <= stop:
                    ret = -stop_pct - friction
                    trades.append(ret)
                    exited = True
                    break
                elif bar_h >= target:
                    ret = target_pct - friction
                    trades.append(ret)
                    exited = True
                    break
            else:
                # Short: stop above, target below
                if bar_h >= stop and bar_l <= target:
                    ret = -stop_pct - friction
                    trades.append(ret)
                    exited = True
                    break
                elif bar_h >= stop:
                    ret = -stop_pct - friction
                    trades.append(ret)
                    exited = True
                    break
                elif bar_l <= target:
                    ret = target_pct - friction
                    trades.append(ret)
                    exited = True
                    break
        
        if not exited and entry_bar + lookahead < len(c):
            exit_price = c[entry_bar + lookahead]
            if long_signal:
                ret = (exit_price - entry) / entry - friction
            else:
                ret = (entry - exit_price) / entry - friction
            trades.append(ret)
    
    return np.array(trades) if trades else np.array([])

def compute_stats(trades):
    """Compute performance statistics."""
    if len(trades) < 10:
        return {'n': len(trades), 'pf': np.nan, 'wr': np.nan, 'exp': np.nan, 'sharpe': np.nan, 'avg': np.nan}
    
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    wr = len(w) / len(trades) * 100
    exp = trades.mean() * 100
    sharpe = trades.mean() / trades.std() if trades.std() > 0 else 0
    
    return {'n': len(trades), 'pf': round(pf, 2), 'wr': round(wr, 1), 'exp': round(exp, 3), 'sharpe': round(sharpe, 3), 'avg': round(exp, 3)}

def bootstrap_ci(trades, n_bootstrap=1000, confidence=0.95):
    """Bootstrap confidence interval for PF."""
    if len(trades) < 50:
        return np.nan, np.nan
    
    bootstrapped_pfs = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(trades, size=len(trades), replace=True)
        w = sample[sample > 0]
        ls = sample[sample <= 0]
        if len(ls) > 0 and ls.sum() != 0:
            pf = w.sum() / abs(ls.sum())
            if pf < 100:  # Cap outliers
                bootstrapped_pfs.append(pf)
    
    if not bootstrapped_pfs:
        return np.nan, np.nan
    
    alpha = (1 - confidence) / 2 * 100
    ci_low = np.percentile(bootstrapped_pfs, alpha)
    ci_high = np.percentile(bootstrapped_pfs, 100 - alpha)
    
    return round(ci_low, 2), round(ci_high, 2)

# ===============================
# TEST 1: Multi-timeframe validation
# ===============================
print("="*80)
print("TEST 1: MULTI-TIMEFRAME VALIDATION")
print("Is T1 edge consistent across 1h, 2h, 4h candles?")
print("="*80)

pairs = ['SOL', 'BTC', 'ETH', 'NEAR', 'LINK', 'AVAX']
timeframes = {'1h': '60m', '2h': '120m', '4h': '240m'}
offsets = [0, 1, 2]
offset_labels = ['T0', 'T1', 'T2']

results_tftf = {}

for tf_name, tf_code in timeframes.items():
    print(f"\n--- {tf_name} Timeframe ---")
    print(f"{'Pair':>6} {'T0 PF':>8} {'T1 PF':>8} {'T2 PF':>8} {'T1-T0':>8} {'Edge':>10}")
    print("-" * 55)
    
    for pair in pairs:
        df = load_data(pair, tf_code)
        if df is None:
            continue
        
        row = {}
        for offset, label in zip(offsets, offset_labels):
            trades = run_timing_test(df, offset)
            stats = compute_stats(trades)
            row[label] = stats
        
        t0_pf = row['T0']['pf']
        t1_pf = row['T1']['pf']
        t2_pf = row['T2']['pf']
        delta = t1_pf - t0_pf if not (np.isnan(t0_pf) or np.isnan(t1_pf)) else np.nan
        edge = "T1 ✓" if t1_pf > 1.0 and t0_pf < 1.0 else ("T1 best" if t1_pf > t0_pf and t1_pf > t2_pf else "—")
        
        print(f"{pair:>6} {t0_pf:>8.2f} {t1_pf:>8.2f} {t2_pf:>8.2f} {delta:>+8.2f} {edge:>10}")

# ===============================
# TEST 2: Regime-dependent timing
# ===============================
print("\n" + "="*80)
print("TEST 2: REGIME-DEPENDENT TIMING")
print("Does T1 edge hold in both high and low volatility regimes?")
print("="*80)

df_sol = load_data('SOL', '240m')
if df_sol is not None:
    df_sol['atr_pct'] = (compute_atr(df_sol['high'], df_sol['low'], df_sol['close']) / df_sol['close']) * 100
    
    # Split by ATR percentile
    atr_threshold = df_sol['atr_pct'].dropna().quantile(0.5)
    
    high_vol = df_sol[df_sol['atr_pct'] > atr_threshold]
    low_vol = df_sol[df_sol['atr_pct'] <= atr_threshold]
    
    print(f"\nHigh Volatility (ATR > {atr_threshold:.2f}%):")
    for offset, label in zip(offsets, offset_labels):
        trades = run_timing_test(high_vol, offset)
        s = compute_stats(trades)
        print(f"  {label}: n={s['n']}, PF={s['pf']}, WR={s['wr']}%, Exp={s['exp']}%")
    
    print(f"\nLow Volatility (ATR <= {atr_threshold:.2f}%):")
    for offset, label in zip(offsets, offset_labels):
        trades = run_timing_test(low_vol, offset)
        s = compute_stats(trades)
        print(f"  {label}: n={s['n']}, PF={s['pf']}, WR={s['wr']}%, Exp={s['exp']}%")

# ===============================
# TEST 3: Temporal stability (early vs recent)
# ===============================
print("\n" + "="*80)
print("TEST 3: TEMPORAL STABILITY")
print("Is T1 edge decaying over time?")
print("="*80)

if df_sol is not None:
    df_sorted = df_sol.sort_index()
    n_bars = len(df_sorted)
    
    # Split into quarters
    q1 = df_sorted.iloc[:n_bars//4]
    q2 = df_sorted.iloc[n_bars//4:n_bars//2]
    q3 = df_sorted.iloc[n_bars//2:3*n_bars//4]
    q4 = df_sorted.iloc[3*n_bars//4:]
    
    quarters = [('Q1 (oldest)', q1), ('Q2', q2), ('Q3', q3), ('Q4 (newest)', q4)]
    
    print(f"\n{'Period':>15} {'T0 PF':>8} {'T1 PF':>8} {'T2 PF':>8} {'T1 Edge':>10}")
    print("-" * 55)
    
    for name, qdf in quarters:
        results = {}
        for offset, label in zip(offsets, offset_labels):
            trades = run_timing_test(qdf, offset)
            s = compute_stats(trades)
            results[label] = s
        
        edge = "✓ Yes" if results['T1']['pf'] > results['T0']['pf'] else "✗ No"
        print(f"{name:>15} {results['T0']['pf']:>8.2f} {results['T1']['pf']:>8.2f} {results['T2']['pf']:>8.2f} {edge:>10}")

# ===============================
# TEST 4: Signal type comparison
# ===============================
print("\n" + "="*80)
print("TEST 4: SIGNAL TYPE COMPARISON")
print("Does T1 edge apply to different signal types?")
print("="*80)

signal_types = ['rsi_bb', 'rsi_only', 'bb_only']

print(f"\n{'Signal':>10} {'T0 PF':>8} {'T1 PF':>8} {'T2 PF':>8} {'T1 Best':>10}")
print("-" * 50)

df_sol = load_data('SOL', '240m')
if df_sol is not None:
    for sig in signal_types:
        results = {}
        for offset, label in zip(offsets, offset_labels):
            trades = run_timing_test(df_sol, offset, signal_type=sig)
            s = compute_stats(trades)
            results[label] = s
        
        t1_best = results['T1']['pf'] > results['T0']['pf'] and results['T1']['pf'] > results['T2']['pf']
        print(f"{sig:>10} {results['T0']['pf']:>8.2f} {results['T1']['pf']:>8.2f} {results['T2']['pf']:>8.2f} {'✓' if t1_best else '✗':>10}")

# ===============================
# TEST 5: Statistical significance
# ===============================
print("\n" + "="*80)
print("TEST 5: STATISTICAL SIGNIFICANCE")
print("Bootstrap CI for T0 vs T1 performance difference")
print("="*80)

df_sol = load_data('SOL', '240m')
if df_sol is not None:
    print("\nSOL 4h - 1000 bootstrap iterations:")
    
    trades_t0 = run_timing_test(df_sol, 0)
    trades_t1 = run_timing_test(df_sol, 1)
    
    # Bootstrap CI for each
    ci_t0 = bootstrap_ci(trades_t0)
    ci_t1 = bootstrap_ci(trades_t1)
    
    print(f"  T0: PF = {compute_stats(trades_t0)['pf']:.2f}, 95% CI = [{ci_t0[0]:.2f}, {ci_t0[1]:.2f}]")
    print(f"  T1: PF = {compute_stats(trades_t1)['pf']:.2f}, 95% CI = [{ci_t1[0]:.2f}, {ci_t1[1]:.2f}]")
    
    # Bootstrap the DIFFERENCE
    print("\n  Bootstrap test: T1 - T0 performance difference")
    n_boot = 1000
    diffs = []
    
    for _ in range(n_boot):
        s0 = np.random.choice(trades_t0, size=len(trades_t0), replace=True)
        s1 = np.random.choice(trades_t1, size=len(trades_t1), replace=True)
        
        pf0 = s0[s0 > 0].sum() / abs(s0[s0 <= 0].sum()) if s0[s0 <= 0].sum() != 0 else 1.0
        pf1 = s1[s1 > 0].sum() / abs(s1[s1 <= 0].sum()) if s1[s1 <= 0].sum() != 1.0 else 1.0
        
        if pf0 < 50 and pf1 < 50:
            diffs.append(pf1 - pf0)
    
    diffs = np.array(diffs)
    ci_diff_low = np.percentile(diffs, 2.5)
    ci_diff_high = np.percentile(diffs, 97.5)
    p_value = (diffs <= 0).mean()  # P(T1 <= T0)
    
    print(f"    Mean difference: {diffs.mean():.3f}")
    print(f"    95% CI: [{ci_diff_low:.3f}, {ci_diff_high:.3f}]")
    print(f"    P(T1 <= T0): {p_value:.4f}")
    print(f"    {'SIGNIFICANT' if p_value < 0.05 else 'NOT SIGNIFICANT'} at α=0.05")
    print(f"    {'T1 is statistically better' if ci_diff_low > 0 else 'Cannot confirm T1 > T0'}")

# ===============================
# TEST 6: Lookahead sensitivity
# ===============================
print("\n" + "="*80)
print("TEST 6: LOOKAHEAD SENSITIVITY")
print("How does exit timing affect the edge?")
print("="*80)

if df_sol is not None:
    lookaheads = [4, 6, 8, 12, 16]
    
    print(f"\n{'Lookahead':>10} {'T0 PF':>8} {'T1 PF':>8} {'T1 Better':>10}")
    print("-" * 40)
    
    for lk in lookaheads:
        t0 = run_timing_test(df_sol, 0, lookahead=lk)
        t1 = run_timing_test(df_sol, 1, lookahead=lk)
        
        s0 = compute_stats(t0)
        s1 = compute_stats(t1)
        
        better = "✓" if s1['pf'] > s0['pf'] else "✗"
        print(f"{lk:>10} {s0['pf']:>8.2f} {s1['pf']:>8.2f} {better:>10}")

print("\n" + "="*80)
print("TESTS COMPLETE")
print("="*80)
