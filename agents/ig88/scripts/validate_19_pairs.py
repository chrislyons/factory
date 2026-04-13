"""
Validate 19 Pairs: Bootstrap CI and Walk-Forward
==================================================
For each viable pair, test:1. Bootstrap 95% CI for PF and Expectancy2. Walk-forward stability (IS vs OOS)
3. Minimum sample size check (n >= 10 for production)"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Optimal configurations from strategy_optimization.py
OPTIMAL_CONFIGS = {
    'AAVE':  {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.0, 'target': 2.0, 'bars': 15},
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 2.5, 'bars': 15},
    'ALGO':  {'strategy': 'BREAKOUT', 'lookback': 15, 'vol': 2.5, 'stop': 1.25, 'target': 4.0, 'bars': 20},
    'ARB':   {'rsi': 18, 'bb': 0.1, 'vol': 1.2, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 0.75, 'target': 1.5, 'bars': 15},
    'AVAX':  {'rsi': 18, 'bb': 0.05, 'vol': 1.5, 'stop': 0.75, 'target': 1.5, 'bars': 15},
    'DOT':   {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 0.5, 'target': 2.0, 'bars': 15},
    'FIL':   {'rsi': 25, 'bb': 0.05, 'vol': 2.0, 'stop': 0.5, 'target': 2.0, 'bars': 15},
    'GRT':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 0.75, 'target': 3.0, 'bars': 15},
    'IMX':   {'rsi': 25, 'bb': 0.05, 'vol': 1.5, 'stop': 0.75, 'target': 2.0, 'bars': 15},
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 2.0, 'stop': 1.25, 'target': 3.0, 'bars': 15},
    'LINK':  {'rsi': 15, 'bb': 0.05, 'vol': 1.2, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'MATIC': {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 3.0, 'bars': 15},
    'POL':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.0, 'target': 3.0, 'bars': 15},
    'SOL':   {'rsi': 15, 'bb': 0.05, 'vol': 1.2, 'stop': 0.5, 'target': 1.5, 'bars': 15},
    'SNX':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 0.5, 'target': 2.0, 'bars': 15},
    'SUI':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.0, 'target': 3.0, 'bars': 15},
    'UNI':   {'rsi': 15, 'bb': 0.05, 'vol': 1.2, 'stop': 0.75, 'target': 2.0, 'bars': 15},
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
    
    dc_upper = pd.Series(h).rolling(20).max().values
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio, dc_upper


def get_entries(pair, ind, cfg):
    c, h, l, rsi, bb_pct, atr, vol_ratio, dc_upper = ind
    
    if cfg.get('strategy') == 'BREAKOUT':
        entries = []
        for i in range(100, len(c)):
            if c[i] > dc_upper[i-1] and vol_ratio[i] > cfg['vol']:
                entries.append(i)
    else:
        # MR entries
        entries = []
        for i in range(100, len(c)):
            if (rsi[i] < cfg['rsi'] and 
                bb_pct[i] < cfg['bb'] and 
                vol_ratio[i] > cfg['vol']):
                entries.append(i)
    
    return entries


def backtest_trades(entries, ind, cfg):
    c, h, l = ind[0], ind[1], ind[2]
    atr = ind[5]
    stop, target, max_bars = cfg['stop'], cfg['target'], cfg['bars']
    
    trades = []
    for idx in entries:
        entry_bar = idx + 1
        if entry_bar >= len(c) - max_bars:
            continue
        
        entry_price = c[entry_bar]
        if np.isnan(entry_price) or entry_price == 0:
            continue
        
        stop_price = entry_price - atr[entry_bar] * stop
        target_price = entry_price + atr[entry_bar] * target
        
        for j in range(1, max_bars + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            if l[bar] <= stop_price:
                trades.append(-atr[entry_bar] * stop / entry_price - FRICTION)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * target / entry_price - FRICTION)
                break
        else:
            exit_price = c[min(entry_bar + max_bars, len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades)


def bootstrap_ci(data, n_bootstrap=1000, ci=0.95):
    """Calculate bootstrap confidence interval."""
    if len(data) < 5:
        return (0, 0, 0)
    
    bootstrapped = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(data, size=len(data), replace=True)
        if len(sample[sample > 0]) > 0 and len(sample[sample <= 0]) > 0:
            w = sample[sample > 0].sum()
            ls = abs(sample[sample <= 0].sum())
            if ls > 0:
                bootstrapped.append(w / ls)
            else:
                bootstrapped.append(9.99)
    
    bootstrapped = np.array(bootstrapped)
    lower = np.percentile(bootstrapped, (1 - ci) / 2 * 100)
    upper = np.percentile(bootstrapped, (1 + ci) / 2 * 100)
    mean = np.mean(bootstrapped)
    
    return mean, lower, upper


def walk_forward_test(entries, ind, cfg, split=0.7):
    """Split data in half and test IS vs OOS."""
    if len(entries) < 10:
        return None, None
    
    split_idx = int(len(entries) * split)
    is_entries = entries[:split_idx]
    oos_entries = entries[split_idx:]
    
    is_trades = backtest_trades(is_entries, ind, cfg)
    oos_trades = backtest_trades(oos_entries, ind, cfg)
    
    def calc_pf(t):
        if len(t) < 3:
            return 0
        w = t[t > 0]
        ls = t[t <= 0]
        if len(ls) == 0 or ls.sum() == 0:
            return 9.99
        return w.sum() / abs(ls.sum())
    
    return calc_pf(is_trades), calc_pf(oos_trades)


print("=" * 120)
print("VALIDATE 19 PAIRS: Bootstrap CI & Walk-Forward")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

results = []

print(f"\n{'Pair':<10} {'N':<6} {'PF':<8} {'95% CI':<20} {'IS PF':<10} {'OOS PF':<10} {'Verdict'}")
print("-" * 100)

for pair, cfg in OPTIMAL_CONFIGS.items():
    try:
        df = load_data(pair)
        ind = compute_indicators(df)
        entries = get_entries(pair, ind, cfg)
        
        trades = backtest_trades(entries, ind, cfg)
        
        if len(trades) < 3:
            print(f"{pair:<10} {len(trades):<6} (insufficient)")
            continue
        
        # Calculate PF
        w = trades[trades > 0]
        ls = trades[trades <= 0]
        pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99
        
        # Bootstrap CI
        mean_ci, lower_ci, upper_ci = bootstrap_ci(trades)
        
        # Walk-forward
        is_pf, oos_pf = walk_forward_test(entries, ind, cfg)
        
        # Verdict
        if len(trades) >= 10 and lower_ci > 1.0 and oos_pf > 1.0:
            verdict = "\033[92mPASS\033[0m"
            status = 'PASS'
        elif len(trades) >= 5 and lower_ci > 0.8 and (oos_pf is None or oos_pf > 0.8):
            verdict = "\033[93mWEAK\033[0m"
            status = 'WEAK'
        else:
            verdict = "\033[91mFAIL\033[0m"
            status = 'FAIL'
        
        results.append({
            'pair': pair,
            'n': len(trades),
            'pf': pf,
            'ci_lower': lower_ci,
            'ci_upper': upper_ci,
            'is_pf': is_pf,
            'oos_pf': oos_pf,
            'status': status,
        })
        
        ci_str = f"[{lower_ci:.2f}, {upper_ci:.2f}]"
        is_str = f"{is_pf:.2f}" if is_pf else "N/A"
        oos_str = f"{oos_pf:.2f}" if oos_pf else "N/A"
        
        print(f"{pair:<10} {len(trades):<6} {pf:<8.2f} {ci_str:<20} {is_str:<10} {oos_str:<10} {verdict}")
    
    except Exception as e:
        print(f"{pair:<10} ERROR: {e}")

# Summary
pass_count = len([r for r in results if r['status'] == 'PASS'])
weak_count = len([r for r in results if r['status'] == 'WEAK'])
fail_count = len([r for r in results if r['status'] == 'FAIL'])

print(f"\n{'=' * 120}")
print("VALIDATION SUMMARY")
print("=" * 120)

print(f"\nPASS: {pass_count}")
print(f"WEAK: {weak_count}")
print(f"FAIL: {fail_count}")

print(f"\nPRODUCTION-READY PAIRS (PASS):")
for r in sorted([r for r in results if r['status'] == 'PASS'], key=lambda x: x['pf'], reverse=True):
    print(f"  {r['pair']}: N={r['n']}, PF={r['pf']:.2f}, CI=[{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]")

print(f"\nNEEDS MORE DATA (WEAK):")
for r in sorted([r for r in results if r['status'] == 'WEAK'], key=lambda x: x['pf'], reverse=True):
    print(f"  {r['pair']}: N={r['n']}, PF={r['pf']:.2f}, CI=[{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]")

print(f"\nREMOVED (FAIL):")
for r in sorted([r for r in results if r['status'] == 'FAIL'], key=lambda x: x['pf'], reverse=True):
    print(f"  {r['pair']}: N={r['n']}, PF={r['pf']:.2f}, CI=[{r['ci_lower']:.2f}, {r['ci_upper']:.2f}]")
