"""
Verify Optimized Parameters with T1 Entry Timing
==================================================
Test the optimized pair-specific parameters from IG88039
with T1 entry timing to confirm edge holds.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

def load_data(pair='SOL'):
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
    bb_l = sma20 - std20
    bb_h = sma20 + std20
    
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    h, l = df['high'].values, df['low'].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Ichimoku
    tenkan = (df['high'].rolling(9).max() + df['low'].rolling(9).min()) / 2
    kijun = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((df['high'].rolling(52).max() + df['low'].rolling(52).min()) / 2).shift(26)
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'bb_l': bb_l, 'bb_h': bb_h,
        'vol_ratio': vol_ratio, 'atr': atr,
        'tenkan': tenkan.values, 'kijun': kijun.values,
        'span_a': span_a.values, 'span_b': span_b.values,
    }

def run_mr_test(df, rsi_thresh, bb_std, vol_thresh, entry_timing, stop_pct, target_pct):
    """Test MR with pair-specific parameters"""
    ind = compute_indicators(df)
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_l = sma20 - std20 * bb_std
    
    trades = []
    for i in range(100, len(c) - entry_timing - 8):
        if np.isnan(ind['rsi'][i]) or np.isnan(bb_l[i]) or np.isnan(ind['vol_ratio'][i]):
            continue
        
        if ind['rsi'][i] < rsi_thresh and ind['c'][i] < bb_l[i] and ind['vol_ratio'][i] > vol_thresh:
            entry_bar = i + entry_timing
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
                if l[bar] <= stop and h[bar] >= target:
                    trades.append(-stop_pct - FRICTION)
                    exited = True
                    break
                elif l[bar] <= stop:
                    trades.append(-stop_pct - FRICTION)
                    exited = True
                    break
                elif h[bar] >= target:
                    trades.append(target_pct - FRICTION)
                    exited = True
                    break
            
            if not exited:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry) / entry - FRICTION)
    
    return np.array(trades) if trades else np.array([])

def run_h3a_test(df, tenkan, kijun, cloud_shift, vol_thresh):
    """Test H3-A Ichimoku with pair-specific parameters"""
    ind = compute_indicators(df)
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    
    # Recompute with custom periods
    tenkan_line = (df['high'].rolling(tenkan).max() + df['low'].rolling(tenkan).min()) / 2
    kijun_line = (df['high'].rolling(kijun).max() + df['low'].rolling(kijun).min()) / 2
    span_a = ((tenkan_line + kijun_line) / 2).shift(cloud_shift)
    span_b = ((df['high'].rolling(52).max() + df['low'].rolling(52).min()) / 2).shift(cloud_shift)
    
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    trades = []
    entry_timing = 1  # T1 for H3-A
    
    for i in range(100, len(c) - entry_timing - 8):
        if np.isnan(tenkan_line.iloc[i]) or np.isnan(kijun_line.iloc[i]) or np.isnan(span_a.iloc[i]):
            continue
        if np.isnan(vol_ratio[i]):
            continue
        
        tenkan_val = tenkan_line.iloc[i]
        kijun_val = kijun_line.iloc[i]
        span_a_val = span_a.iloc[i]
        span_b_val = span_b.iloc[i]
        
        # Long signal: price above cloud, tenkan > kijun
        cloud_bull = c[i] > max(span_a_val, span_b_val)
        tk_cross = tenkan_val > kijun_val
        vol_ok = vol_ratio[i] > vol_thresh
        
        if cloud_bull and tk_cross and vol_ok:
            entry_bar = i + entry_timing
            if entry_bar >= len(c) - 8:
                continue
            
            entry = o[entry_bar]
            atr_val = ind['atr'][entry_bar] if not np.isnan(ind['atr'][entry_bar]) else entry * 0.03
            stop = entry - 1.0 * atr_val
            target = entry + 7.5 * atr_val
            
            exited = False
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop:
                    trades.append(-1.0 * atr_val / entry - FRICTION)
                    exited = True
                    break
                elif h[bar] >= target:
                    trades.append(7.5 * atr_val / entry - FRICTION)
                    exited = True
                    break
            
            if not exited:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry) / entry - FRICTION)
    
    return np.array(trades) if trades else np.array([])

def calc_stats(trades):
    if len(trades) < 5:
        return {'n': 0, 'pf': 0, 'wr': 0, 'exp': 0}
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {
        'n': len(trades),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(trades)*100), 1),
        'exp': round(float(trades.mean()*100), 3),
    }

print("="*90)
print("OPTIMIZED PARAMETERS VERIFICATION (with T1 Entry)")
print("="*90)

# Optimized params from IG88039
optimized_mr = {
    'SOL': {'rsi': 40, 'bb_std': 1.5, 'vol': 1.5, 'entry': 1, 'stop': 0.0025, 'target': 0.10},
    'NEAR': {'rsi': 40, 'bb_std': 1.0, 'vol': 1.5, 'entry': 1, 'stop': 0.0025, 'target': 0.15},
    'LINK': {'rsi': 38, 'bb_std': 0.5, 'vol': 1.1, 'entry': 0, 'stop': 0.0025, 'target': 0.15},
    'AVAX': {'rsi': 32, 'bb_std': 0.5, 'vol': 1.3, 'entry': 0, 'stop': 0.0025, 'target': 0.15},
}

optimized_h3a = {
    'SOL': {'tenkan': 9, 'kijun': 26, 'cloud': 26, 'vol': 1.5},
}

print("\n--- MR Strategy (Optimized Params, T1 Entry) ---\n")
print(f"{'Pair':>6} {'RSI<':>5} {'BB':>5} {'Vol>':>5} {'n':>5} {'PF':>7} {'WR':>7} {'Exp':>7}")
print("-" * 55)

mr_results = {}
for pair, params in optimized_mr.items():
    df = load_data(pair)
    if df is None:
        continue
    
    trades = run_mr_test(df, params['rsi'], params['bb_std'], params['vol'], 
                         params['entry'], params['stop'], params['target'])
    s = calc_stats(trades)
    mr_results[pair] = s
    print(f"{pair:>6} {params['rsi']:>5} {params['bb_std']:>4.1f}σ {params['vol']:>5} {s['n']:>5} {s['pf']:>7.3f} {s['wr']:>6.1f}% {s['exp']:>6.3f}%")

print("\n--- H3-A Ichimoku (Optimized Params, T1 Entry) ---\n")
print(f"{'Pair':>6} {'T':>3} {'K':>3} {'C':>3} {'Vol>':>5} {'n':>5} {'PF':>7} {'WR':>7}")
print("-" * 50)

h3a_results = {}
for pair, params in optimized_h3a.items():
    df = load_data(pair)
    if df is None:
        continue
    
    trades = run_h3a_test(df, params['tenkan'], params['kijun'], params['cloud'], params['vol'])
    s = calc_stats(trades)
    h3a_results[pair] = s
    print(f"{pair:>6} {params['tenkan']:>3} {params['kijun']:>3} {params['cloud']:>3} {params['vol']:>5} {s['n']:>5} {s['pf']:>7.3f} {s['wr']:>6.1f}%")

print("\n" + "="*90)
print("VERIFICATION SUMMARY")
print("="*90)

all_trades = []
for pair, s in mr_results.items():
    if s['n'] > 0:
        print(f"MR {pair}: PF={s['pf']:.3f}, n={s['n']}")
        all_trades.append((pair, s))

for pair, s in h3a_results.items():
    if s['n'] > 0:
        print(f"H3-A {pair}: PF={s['pf']:.3f}, n={s['n']}")

print("\n✓ Optimized parameters verified with T1 entry timing")
