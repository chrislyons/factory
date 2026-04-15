"""
Final Validation: 12 Pairs with Bootstrap CI
==============================================
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Optimal configs from expand_signals.py
CONFIGS = {
    'ARB':   {'rsi': 18, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'SUI':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25},
    'MATIC': {'rsi': 25, 'bb': 0.15, 'vol': 1.8, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'AVAX':  {'rsi': 20, 'bb': 0.15, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'UNI':   {'rsi': 22, 'bb': 0.10, 'vol': 1.8, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25},
    'ALGO':  {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'LINK':  {'rsi': 18, 'bb': 0.05, 'vol': 1.8, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'AAVE':  {'rsi': 22, 'bb': 0.15, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_upper = sma20 + std20 * 2
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio


def get_trades(pair, cfg):
    df = load_data(pair)
    c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
    
    entries = []
    for i in range(100, len(c) - cfg['bars']):
        if rsi[i] < cfg['rsi'] and bb_pct[i] < cfg['bb'] and vol_ratio[i] > cfg['vol']:
            entries.append(i)
    
    trades = []
    for idx in entries:
        entry_bar = idx + 1
        entry_price = c[entry_bar]
        if np.isnan(entry_price) or entry_price == 0:
            continue
        
        stop_price = entry_price - atr[entry_bar] * cfg['stop']
        target_price = entry_price + atr[entry_bar] * cfg['target']
        
        for j in range(1, cfg['bars'] + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            if l[bar] <= stop_price:
                trades.append(-atr[entry_bar] * cfg['stop'] / entry_price - FRICTION)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * cfg['target'] / entry_price - FRICTION)
                break
        else:
            exit_price = c[min(entry_bar + cfg['bars'], len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades)


def bootstrap_ci(data, n_bootstrap=5000):
    if len(data) < 5:
        return 0, 0, 0, 0
    
    bootstrapped_pfs = []
    bootstrapped_exps = []
    
    for _ in range(n_bootstrap):
        sample = np.random.choice(data, size=len(data), replace=True)
        w = sample[sample > 0]
        ls = sample[sample <= 0]
        
        if len(ls) > 0 and ls.sum() != 0:
            bootstrapped_pfs.append(w.sum() / abs(ls.sum()))
        bootstrapped_exps.append(sample.mean() * 100)
    
    pf_arr = np.array(bootstrapped_pfs)
    exp_arr = np.array(bootstrapped_exps)
    
    return {
        'pf_median': np.median(pf_arr),
        'pf_5': np.percentile(pf_arr, 5),
        'pf_95': np.percentile(pf_arr, 95),
        'exp_median': np.median(exp_arr),
        'exp_5': np.percentile(exp_arr, 5),
        'exp_95': np.percentile(exp_arr, 95),
        'prob_positive': (exp_arr > 0).mean(),
    }


print("=" * 130)
print("FINAL VALIDATION: 12 Pairs with Bootstrap CI")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 130)

results = []

print(f"\n{'Pair':<10} {'N':<6} {'PF':<8} {'PF 95% CI':<20} {'Exp%':<10} {'Exp 95% CI':<20} {'Prob>0'}")
print("-" * 110)

for pair, cfg in CONFIGS.items():
    trades = get_trades(pair, cfg)
    
    if len(trades) < 5:
        print(f"{pair:<10} {len(trades):<6} (insufficient)")
        continue
    
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99
    exp = trades.mean() * 100
    wr = (trades > 0).sum() / len(trades) * 100
    
    ci = bootstrap_ci(trades)
    
    # Verdict
    if ci['pf_5'] > 1.0 and ci['prob_positive'] > 0.85:
        verdict = 'STRONG'
    elif ci['pf_5'] > 0.8 and ci['prob_positive'] > 0.75:
        verdict = 'MODERATE'
    else:
        verdict = 'WEAK'
    
    results.append({
        'pair': pair,
        'n': len(trades),
        'pf': pf,
        'exp': exp,
        'wr': wr,
        'ci': ci,
        'verdict': verdict,
        'cfg': cfg,
    })
    
    pf_ci = f"[{ci['pf_5']:.2f}, {ci['pf_95']:.2f}]"
    exp_ci = f"[{ci['exp_5']:.2f}%, {ci['exp_95']:.2f}%]"
    
    print(f"{pair:<10} {len(trades):<6} {pf:<8.2f} {pf_ci:<20} {exp:<10.2f} {exp_ci:<20} {ci['prob_positive']:.0%}  {verdict}")

# Summary
print(f"\n{'=' * 130}")
print("PORTFOLIO SUMMARY")
print("=" * 130)

strong = [r for r in results if r['verdict'] == 'STRONG']
moderate = [r for r in results if r['verdict'] == 'MODERATE']
weak = [r for r in results if r['verdict'] == 'WEAK']

print(f"\nSTRONG (PF_5 > 1.0, Prob>0 > 85%): {len(strong)} pairs")
for r in sorted(strong, key=lambda x: x['pf'], reverse=True):
    print(f"  {r['pair']}: N={r['n']}, PF={r['pf']:.2f}, Exp={r['exp']:.2f}%")

print(f"\nMODERATE (PF_5 > 0.8, Prob>0 > 75%): {len(moderate)} pairs")
for r in sorted(moderate, key=lambda x: x['pf'], reverse=True):
    print(f"  {r['pair']}: N={r['n']}, PF={r['pf']:.2f}, Exp={r['exp']:.2f}%")

print(f"\nWEAK: {len(weak)} pairs")
for r in sorted(weak, key=lambda x: x['pf'], reverse=True):
    print(f"  {r['pair']}: N={r['n']}, PF={r['pf']:.2f}, Exp={r['exp']:.2f}%")

print(f"\n{'=' * 130}")
print("PRODUCTION CONFIG")
print("=" * 130)

production_pairs = [r for r in results if r['verdict'] in ['STRONG', 'MODERATE']]

print(f"\nTotal pairs: {len(production_pairs)}")
print(f"Total expected trades: {sum(r['n'] for r in production_pairs)}")
print(f"Average expectancy: {np.mean([r['exp'] for r in production_pairs]):.3f}%")
print(f"Average PF: {np.mean([r['pf'] for r in production_pairs]):.2f}")

print(f"\n{'Pair':<10} {'Size':<8} {'RSI':<6} {'BB':<6} {'Vol':<6} {'Stop':<8} {'Target':<10} {'Bars':<8}")
print("-" * 70)

# Position sizing based on PF and sample size
for r in production_pairs:
    if r['verdict'] == 'STRONG' and r['n'] >= 15:
        size = 2.5
    elif r['verdict'] == 'STRONG':
        size = 2.0
    else:
        size = 1.5
    
    cfg = r['cfg']
    print(f"{r['pair']:<10} {size:<8.1f} {cfg['rsi']:<6} {cfg['bb']:<6} {cfg['vol']:<6} {cfg['stop']:<8.2f} {cfg['target']:<10.2f} {cfg['bars']:<8}")
