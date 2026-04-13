"""
Expand Pair Universe: Test Additional Altcoins for MR Edge
==========================================================
Using the robust MR parameters (RSI<30, BB 1.5-2.0, Vol>1.8, T1/T2, Stop 0.5-1%)
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

# Additional pairs to test
NEW_PAIRS = ['FTM', 'MATIC', 'DOT', 'ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI']

# Robust parameters from audit
PARAMS = {
    'rsi': 30,
    'bb': 1.5,
    'vol': 1.8,
    'entry': 1,  # T1
    'stop': 0.005,  # 0.5% (test both MEV-risk and MEV-safe)
    'target': 0.10,
}


def load_data(pair):
    """Load 4h data for a pair."""
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if path.exists():
        return pd.read_parquet(path)
    return None


def compute_indicators(df):
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


def run_backtest(ind, rsi, bb, vol, entry, stop, target):
    """Run MR backtest."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi_arr, sma20, std20 = ind['rsi'], ind['sma20'], ind['std20']
    vol_ratio = ind['vol_ratio']
    bb_l = sma20 - std20 * bb
    
    trades = []
    for i in range(100, len(c) - entry - 8):
        if np.isnan(rsi_arr[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        
        if rsi_arr[i] < rsi and c[i] < bb_l[i] and vol_ratio[i] > vol:
            entry_bar = i + entry
            if entry_bar >= len(c) - 8:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price * (1 - stop)
            target_price = entry_price * (1 + target)
            
            exited = False
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-stop - FRICTION)
                    exited = True
                    break
                if h[bar] >= target_price:
                    trades.append(target - FRICTION)
                    exited = True
                    break
            
            if not exited:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades) if trades else np.array([])


def calc_stats(trades):
    if len(trades) < 10:
        return {'n': 0, 'pf': 0, 'wr': 0, 'exp': 0, 'sharpe': 0}
    t = trades
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(t)*100), 1),
        'exp': round(float(t.mean()*100), 3),
        'sharpe': round(float(sharpe), 2),
    }


def walk_forward_stability(ind, rsi, bb, vol, entry, stop, target, windows=4):
    """Test stability across time windows."""
    n = len(ind['c'])
    w_size = n // windows
    
    pfs = []
    for w in range(windows):
        start = w * w_size
        end = (w + 1) * w_size if w < windows - 1 else n
        
        trades = run_backtest(
            {k: v[start:end] if isinstance(v, np.ndarray) else v for k, v in ind.items()},
            rsi, bb, vol, entry, stop, target
        )
        stats = calc_stats(trades)
        pfs.append(stats['pf'])
    
    profitable = sum(1 for p in pfs if p > 1.0)
    return profitable, pfs


print("=" * 100)
print("EXPANDING PAIR UNIVERSE: Testing Additional Altcoins")
print("=" * 100)

print(f"\n{'Pair':<8} {'Bars':<8} {'N':<6} {'PF (0.5%)':<12} {'PF (0.75%)':<12} {'PF (1.0%)':<12} {'WF':<8} {'Verdict'}")
print("-" * 90)

viable_pairs = []

for pair in NEW_PAIRS:
    df = load_data(pair)
    if df is None:
        print(f"{pair:<8} NO DATA")
        continue
    
    ind = compute_indicators(df)
    
    # Test three stop levels
    results = {}
    for stop in [0.005, 0.0075, 0.01]:
        trades = run_backtest(ind, PARAMS['rsi'], PARAMS['bb'], PARAMS['vol'], 
                              PARAMS['entry'], stop, PARAMS['target'])
        results[stop] = calc_stats(trades)
    
    # Walk-forward with 0.75% stop (middle ground)
    wf_profitable, wf_pfs = walk_forward_stability(
        ind, PARAMS['rsi'], PARAMS['bb'], PARAMS['vol'],
        PARAMS['entry'], 0.0075, PARAMS['target']
    )
    
    # Verdict
    s05 = results[0.005]
    s075 = results[0.0075]
    s10 = results[0.01]
    
    if s075['pf'] > 1.5 and wf_profitable >= 3:
        verdict = "STRONG"
    elif s075['pf'] > 1.2 and wf_profitable >= 2:
        verdict = "MARGINAL"
    elif s10['pf'] > 1.0:
        verdict = "WEAK"
    else:
        verdict = "FAIL"
    
    if verdict in ["STRONG", "MARGINAL"]:
        viable_pairs.append({
            'pair': pair,
            'n_bars': len(df),
            'pf_05': s05, 'pf_075': s075, 'pf_10': s10,
            'wf_profitable': wf_profitable, 'wf_pfs': wf_pfs,
        })
    
    print(f"{pair:<8} {len(df):<8} {s075['n']:<6} {s05['pf']:<12.3f} {s075['pf']:<12.3f} {s10['pf']:<12.3f} {wf_profitable}/4   {verdict}")


# ============================================================================
# VIABLE PAIR DEEP DIVE
# ============================================================================
print("\n" + "=" * 100)
print("VIABLE PAIR OPTIMIZATION")
print("=" * 100)

for v in viable_pairs:
    pair = v['pair']
    df = load_data(pair)
    ind = compute_indicators(df)
    
    print(f"\n--- {pair} ---")
    print(f"  Data: {v['n_bars']} bars")
    print(f"  Walk-Forward: {v['wf_profitable']}/4 profitable windows")
    print(f"  WF PFS: {[round(p, 2) for p in v['wf_pfs']]}")
    
    # Optimize parameters for this specific pair
    best_pf = 0
    best_params = None
    
    for rsi in [25, 30, 35]:
        for bb in [1.0, 1.5, 2.0]:
            for vol in [1.5, 1.8, 2.0]:
                trades = run_backtest(ind, rsi, bb, vol, 1, 0.0075, 0.10)
                stats = calc_stats(trades)
                
                if stats['n'] >= 20 and stats['pf'] > best_pf:
                    best_pf = stats['pf']
                    best_params = {'rsi': rsi, 'bb': bb, 'vol': vol, **stats}
    
    if best_params:
        print(f"  Optimized: RSI<{best_params['rsi']}, BB {best_params['bb']}σ, Vol>{best_params['vol']}")
        print(f"  PF: {best_params['pf']:.3f}, n={best_params['n']}, Exp={best_params['exp']:.3f}%")


# ============================================================================
# EXPANDED PORTFOLIO
# ============================================================================
print("\n" + "=" * 100)
print("EXPANDED PORTFOLIO CONSTRUCTION")
print("=" * 100)

# Original pairs (confirmed robust)
original = ['SOL', 'NEAR', 'LINK', 'AVAX']
expanded = [v['pair'] for v in viable_pairs]
all_pairs = original + expanded

print(f"\nOriginal pairs: {', '.join(original)}")
print(f"New viable pairs: {', '.join(expanded) if expanded else 'NONE'}")
print(f"Total universe: {len(all_pairs)} pairs")

if expanded:
    print("\nRecommended Expanded Portfolio:")
    print("-" * 60)
    
    # Equal weight for now
    weight = 1.0 / len(all_pairs)
    
    for pair in all_pairs:
        df = load_data(pair)
        if df is None:
            continue
        ind = compute_indicators(df)
        
        trades = run_backtest(ind, PARAMS['rsi'], PARAMS['bb'], PARAMS['vol'],
                              PARAMS['entry'], 0.0075, PARAMS['target'])
        stats = calc_stats(trades)
        
        print(f"{pair:<8} {weight*100:>5.0f}%   PF={stats['pf']:.3f}, Exp={stats['exp']:.3f}%")
else:
    print("\nNo additional pairs found. Current 4-pair universe is optimal.")
    print("Next step: Optimize within existing pairs (exits, sizing, regime filters).")
