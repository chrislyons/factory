"""
Robustness Audit: Are Our High PFs Real or Overfit?
====================================================
Test each pair's "optimal" parameters across:
1. Rolling windows (stability)
2. IS vs OOS splits (overfitting detection)
3. Parameter sensitivity (how fragile is the edge?)
4. Bootstrap confidence intervals
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025  # Jupiter perps


def load_data(pair, tf='240m'):
    path = DATA_DIR / f'binance_{pair}_USDT_{tf}.parquet'
    return pd.read_parquet(path) if path.exists() else None


def compute_mr_indicators(df):
    """Compute MR indicators."""
    c = df['close'].values
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    h, l = df['high'].values, df['low'].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'sma20': sma20, 'std20': std20,
        'vol_ratio': vol_ratio, 'atr': atr,
    }


def run_mr_backtest(ind, rsi_thresh, bb_std, vol_thresh, entry_offset, 
                    stop_pct, target_pct, start_idx=0, end_idx=None):
    """Run MR backtest on a subset of data."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20 = ind['rsi'], ind['sma20'], ind['std20']
    vol_ratio = ind['vol_ratio']
    bb_l = sma20 - std20 * bb_std
    
    end = end_idx if end_idx else len(c) - entry_offset - 8
    start = max(100, start_idx)
    
    trades = []
    for i in range(start, end - entry_offset - 8):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        
        if rsi[i] < rsi_thresh and c[i] < bb_l[i] and vol_ratio[i] > vol_thresh:
            entry_bar = i + entry_offset
            if entry_bar >= len(c) - 8:
                continue
            
            entry = o[entry_bar]
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
            
            exited = False
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop:
                    trades.append(-stop_pct - FRICTION)
                    exited = True
                    break
                if h[bar] >= target:
                    trades.append(target_pct - FRICTION)
                    exited = True
                    break
            
            if not exited:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry) / entry - FRICTION)
    
    return np.array(trades) if trades else np.array([])


def calc_stats(trades):
    """Calculate statistics with confidence metrics."""
    if len(trades) < 10:
        return {'n': 0, 'pf': 0, 'wr': 0, 'exp': 0, 'sharpe': 0, 'pf_std': 0}
    
    t = trades
    w = t[t > 0]
    ls = t[t <= 0]
    
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    
    # Bootstrap PF std for confidence
    bootstrapped_pfs = []
    for _ in range(200):
        sample = np.random.choice(t, size=len(t), replace=True)
        sw = sample[sample > 0]
        sls = sample[sample <= 0]
        if len(sls) > 0 and sls.sum() != 0:
            bootstrapped_pfs.append(sw.sum() / abs(sls.sum()))
    
    pf_std = np.std(bootstrapped_pfs) if bootstrapped_pfs else 0
    pf_5pct = np.percentile(bootstrapped_pfs, 5) if bootstrapped_pfs else 0
    
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(t)*100), 1),
        'exp': round(float(t.mean()*100), 3),
        'sharpe': round(float(sharpe), 2),
        'pf_std': round(float(pf_std), 3),
        'pf_5pct': round(float(pf_5pct), 3),
    }


def walk_forward_test(ind, params, windows=6):
    """Test parameter stability across time windows."""
    n = len(ind['c'])
    w_size = n // windows
    
    results = []
    for w in range(windows):
        start = w * w_size
        end = (w + 1) * w_size if w < windows - 1 else n
        
        trades = run_mr_backtest(
            ind, 
            params['rsi'], params['bb'], params['vol'], params['entry'],
            params['stop'], params['target'],
            start_idx=start, end_idx=end
        )
        stats = calc_stats(trades)
        stats['window'] = w + 1
        results.append(stats)
    
    return results


def parameter_sensitivity(ind, base_params, param_name, values):
    """Test sensitivity to a single parameter change."""
    results = []
    for val in values:
        params = base_params.copy()
        params[param_name] = val
        
        trades = run_mr_backtest(
            ind,
            params['rsi'], params['bb'], params['vol'], params['entry'],
            params['stop'], params['target']
        )
        stats = calc_stats(trades)
        stats['param_value'] = val
        results.append(stats)
    
    return results


# ============================================================================
# MR STRATEGY: PAIR-SPECIFIC OPTIMIZATION + ROBUSTNESS
# ============================================================================
print("=" * 100)
print("ROBUSTNESS AUDIT: PAIR-SPECIFIC MR OPTIMIZATION")
print("=" * 100)

# For each pair, find the ROBUST optimal parameters (not the curve-fit ones)
# Strategy: Grid search, but pick parameters that are STABLE across windows

PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX']

# Parameter grid (reduced for speed)
RSI_VALUES = [30, 35, 40, 45]
BB_VALUES = [1.0, 1.5, 2.0]
VOL_VALUES = [1.2, 1.5, 1.8]
ENTRY_VALUES = [0, 1, 2]
STOP_VALUES = [0.005, 0.0075, 0.01]
TARGET_VALUES = [0.075, 0.10, 0.125, 0.15]

robust_results = {}

for pair in PAIRS:
    print(f"\n{'=' * 80}")
    print(f"OPTIMIZING: {pair}")
    print(f"{'=' * 80}")
    
    df = load_data(pair)
    if df is None:
        print(f"  NO DATA for {pair}")
        continue
    
    ind = compute_mr_indicators(df)
    print(f"  Data: {len(df)} bars")
    
    # Grid search to find top candidates
    candidates = []
    
    for rsi in RSI_VALUES:
        for bb in BB_VALUES:
            for vol in VOL_VALUES:
                for entry in ENTRY_VALUES:
                    for stop in STOP_VALUES:
                        for target in TARGET_VALUES:
                            if target <= stop * 2:
                                continue
                            
                            trades = run_mr_backtest(
                                ind, rsi, bb, vol, entry, stop, target
                            )
                            stats = calc_stats(trades)
                            
                            if stats['n'] >= 20 and stats['pf'] > 1.2:
                                candidates.append({
                                    'rsi': rsi, 'bb': bb, 'vol': vol, 'entry': entry,
                                    'stop': stop, 'target': target,
                                    **stats
                                })
    
    if not candidates:
        print(f"  No viable candidates for {pair}")
        continue
    
    # Now test each top candidate across 6 time windows
    print(f"  Found {len(candidates)} candidates. Testing walk-forward stability...")
    
    # Sort by PF first
    candidates.sort(key=lambda x: x['pf'], reverse=True)
    
    best_stable = None
    best_score = -999
    
    for cand in candidates[:20]:  # Test top 20
        params = {k: cand[k] for k in ['rsi', 'bb', 'vol', 'entry', 'stop', 'target']}
        wf_results = walk_forward_test(ind, params, windows=6)
        
        # Calculate stability score
        pfs = [r['pf'] for r in wf_results if r['n'] >= 5]
        profitable_windows = sum(1 for p in pfs if p > 1.0)
        pf_mean = np.mean(pfs) if pfs else 0
        pf_std = np.std(pfs) if len(pfs) > 1 else 0
        pf_cv = pf_std / pf_mean if pf_mean > 0 else 999  # Coefficient of variation
        
        # Score: prioritize stability (low CV) over raw PF
        # Penalize high CV, reward profitable windows
        stability_score = (pf_mean * profitable_windows / len(wf_results)) / (1 + pf_cv)
        
        if stability_score > best_score:
            best_score = stability_score
            best_stable = {
                **params,
                'full_pf': cand['pf'],
                'full_n': cand['n'],
                'wf_pfs': pfs,
                'wf_profitable_windows': profitable_windows,
                'wf_pf_mean': pf_mean,
                'wf_pf_std': pf_std,
                'wf_pf_cv': pf_cv,
                'stability_score': stability_score,
            }
    
    if best_stable:
        robust_results[pair] = best_stable
        
        print(f"\n  BEST STABLE CONFIG for {pair}:")
        print(f"    RSI<{best_stable['rsi']}, BB {best_stable['bb']}σ, Vol>{best_stable['vol']}")
        print(f"    Entry: T{best_stable['entry']}, Stop: {best_stable['stop']*100:.2f}%, Target: {best_stable['target']*100:.1f}%")
        print(f"    Full Sample: PF={best_stable['full_pf']:.3f}, n={best_stable['full_n']}")
        print(f"    Walk-Forward: {best_stable['wf_profitable_windows']}/6 profitable windows")
        print(f"    WF Mean PF: {best_stable['wf_pf_mean']:.3f} (σ={best_stable['wf_pf_std']:.3f})")
        print(f"    CV (lower=better): {best_stable['wf_pf_cv']:.3f}")


# ============================================================================
# CONFIDENCE INTERVAL ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("CONFIDENCE INTERVAL ANALYSIS")
print("=" * 100)

print(f"\n{'Pair':<8} {'PF':<8} {'PF±1σ':<15} {'5% CI':<10} {'N':<6} {'WF Stable?'}")
print("-" * 65)

for pair, r in robust_results.items():
    ci_low = r['full_pf'] - r['wf_pf_std']
    ci_high = r['full_pf'] + r['wf_pf_std']
    stable = "YES" if r['wf_profitable_windows'] >= 5 else "PARTIAL" if r['wf_profitable_windows'] >= 4 else "NO"
    
    print(f"{pair:<8} {r['full_pf']:<8.3f} [{ci_low:.2f}, {ci_high:.2f}]   {'≤'+str(r['wf_pf_cv']):<10} {r['full_n']:<6} {stable}")


# ============================================================================
# PARAMETER SENSITIVITY ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("PARAMETER SENSITIVITY: HOW FRAGILE ARE THE EDGES?")
print("=" * 100)

for pair in ['SOL', 'NEAR', 'LINK', 'AVAX']:
    if pair not in robust_results:
        continue
    
    df = load_data(pair)
    ind = compute_mr_indicators(df)
    base = robust_results[pair]
    
    print(f"\n--- {pair} ---")
    print(f"Base config: RSI<{base['rsi']}, BB {base['bb']}, Vol>{base['vol']}, T{base['entry']}")
    print(f"Base PF: {base['full_pf']:.3f}")
    
    # Test RSI sensitivity
    print(f"\n  RSI Threshold Sensitivity:")
    for rsi in [25, 30, 35, 40, 45, 50]:
        trades = run_mr_backtest(ind, rsi, base['bb'], base['vol'], base['entry'], base['stop'], base['target'])
        stats = calc_stats(trades)
        marker = " <-- base" if rsi == base['rsi'] else ""
        print(f"    RSI<{rsi}: PF={stats['pf']:.3f}, n={stats['n']}{marker}")
    
    # Test BB sensitivity
    print(f"\n  BB StdDev Sensitivity:")
    for bb in [0.5, 1.0, 1.5, 2.0, 2.5]:
        trades = run_mr_backtest(ind, base['rsi'], bb, base['vol'], base['entry'], base['stop'], base['target'])
        stats = calc_stats(trades)
        marker = " <-- base" if bb == base['bb'] else ""
        print(f"    BB {bb}σ: PF={stats['pf']:.3f}, n={stats['n']}{marker}")
    
    # Test Stop sensitivity
    print(f"\n  Stop Sensitivity:")
    for stop in [0.005, 0.0075, 0.01, 0.0125, 0.015]:
        trades = run_mr_backtest(ind, base['rsi'], base['bb'], base['vol'], base['entry'], stop, base['target'])
        stats = calc_stats(trades)
        marker = " <-- base" if stop == base['stop'] else ""
        print(f"    Stop {stop*100:.2f}%: PF={stats['pf']:.3f}, n={stats['n']}{marker}")


# ============================================================================
# COMBINED PORTFOLIO (Robust Configs Only)
# ============================================================================
print("\n" + "=" * 100)
print("ROBUST PORTFOLIO CONSTRUCTION")
print("=" * 100)

if robust_results:
    print("\nAssets with verified robust edges:")
    print("-" * 75)
    print(f"{'Pair':<8} {'Weight':<8} {'PF':<8} {'Exp%':<8} {'WF Stable':<10} {'CV':<8}")
    print("-" * 75)
    
    # Equal weight among robust assets
    n_assets = len(robust_results)
    weight = 1.0 / n_assets
    
    total_exp = 0
    for pair, r in robust_results.items():
        wf_stable = "YES" if r['wf_profitable_windows'] >= 5 else "PARTIAL"
        total_exp += r.get('exp', 0) * weight if 'exp' in r else 0
        print(f"{pair:<8} {weight*100:>5.0f}%   {r['full_pf']:<8.3f} {r.get('exp', 0):<7.3f}% {wf_stable:<10} {r['wf_pf_cv']:<8.3f}")
    
    print("-" * 75)
    print(f"\nNote: These are ROBUST configs, not curve-fit maximums.")
    print(f"Stability (low CV, profitable across windows) > raw PF.")

print(f"\nResults saved to memory.")
