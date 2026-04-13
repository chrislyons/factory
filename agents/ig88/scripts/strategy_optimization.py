"""
Strategy Optimization: Find What Works For ALL Pairs
=====================================================
Test all strategy types with parameter optimization on all 31 pairs.
Focus on finding ANY strategy that produces PF >= 1.5 with n >= 5.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from itertools import product

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

ALL_PAIRS = []
for f in sorted(DATA_DIR.glob('binance_*_USDT_240m.parquet')):
    pair = f.name.replace('binance_', '').replace('_USDT_240m.parquet', '')
    if pair not in ['BTC', 'ETH']:
        ALL_PAIRS.append(pair)


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_upper = sma20 + std20 * 2
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
    
    ema8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema21 = df['close'].ewm(span=21, adjust=False).mean().values
    ema55 = df['close'].ewm(span=55, adjust=False).mean().values
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    dc_upper = pd.Series(h).rolling(20).max().values
    dc_lower = pd.Series(l).rolling(20).min().values
    
    # RSI momentum (change in RSI)
    rsi_delta = np.diff(rsi, prepend=50)
    
    return {
        'c': c, 'h': h, 'l': l, 'o': o,
        'rsi': rsi, 'rsi_delta': rsi_delta,
        'bb_lower': bb_lower, 'bb_upper': bb_upper, 'bb_pct': bb_pct,
        'ema8': ema8, 'ema21': ema21, 'ema55': ema55,
        'atr': atr, 'vol_ratio': vol_ratio,
        'dc_upper': dc_upper, 'dc_lower': dc_lower,
    }


def backtest_trades(entries, ind, stop_atr, target_atr, max_bars):
    c, h, l, atr = ind['c'], ind['h'], ind['l'], ind['atr']
    trades = []
    
    for idx in entries:
        entry_bar = idx + 1
        if entry_bar >= len(c) - max_bars:
            continue
        
        entry_price = c[entry_bar]
        if np.isnan(entry_price) or entry_price == 0:
            continue
        
        stop_price = entry_price - atr[entry_bar] * stop_atr
        target_price = entry_price + atr[entry_bar] * target_atr
        
        for j in range(1, max_bars + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            if l[bar] <= stop_price:
                trades.append(-atr[entry_bar] * stop_atr / entry_price - FRICTION)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * target_atr / entry_price - FRICTION)
                break
        else:
            exit_price = c[min(entry_bar + max_bars, len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades)


def calc_pf(t):
    if len(t) < 5:
        return 0, 0
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return (9.99 if len(w) > 0 else 0), len(t)
    return w.sum() / abs(ls.sum()), len(t)


# STRATEGY GENERATORS
def strat_mr(ind, rsi_thresh=20, bb_thresh=0.1, vol_thresh=1.5):
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['rsi'][i] < rsi_thresh and 
            ind['bb_pct'][i] < bb_thresh and 
            ind['vol_ratio'][i] > vol_thresh):
            entries.append(i)
    return entries


def strat_trend_pullback(ind, vol_thresh=1.0):
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['ema8'][i] > ind['ema21'][i] > ind['ema55'][i] and
            ind['l'][i] <= ind['ema21'][i] * 1.01 and
            ind['c'][i] > ind['ema21'][i] and
            ind['vol_ratio'][i] > vol_thresh):
            entries.append(i)
    return entries


def strat_momentum_rsi(ind, rsi_low=40, rsi_high=60, vol_thresh=1.5):
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['rsi'][i] > rsi_high and 
            ind['rsi'][i-1] <= rsi_high and
            ind['rsi'][i-2] < rsi_low and
            ind['vol_ratio'][i] > vol_thresh):
            entries.append(i)
    return entries


def strat_breakout(ind, lookback=20, vol_thresh=2.0):
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['c'][i] > ind['dc_upper'][i-1] and
            ind['vol_ratio'][i] > vol_thresh):
            entries.append(i)
    return entries


def strat_ema_cross(ind, vol_thresh=1.2):
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['ema8'][i] > ind['ema21'][i] and
            ind['ema8'][i-1] <= ind['ema21'][i-1] and
            ind['vol_ratio'][i] > vol_thresh):
            entries.append(i)
    return entries


STRATEGIES = {
    'MR': (strat_mr, {
        'rsi_thresh': [15, 18, 20, 25],
        'bb_thresh': [0.05, 0.1, 0.15],
        'vol_thresh': [1.2, 1.5, 2.0],
    }),
    'TREND': (strat_trend_pullback, {
        'vol_thresh': [0.8, 1.0, 1.2],
    }),
    'MOMENTUM': (strat_momentum_rsi, {
        'rsi_low': [30, 40],
        'rsi_high': [55, 60, 65],
        'vol_thresh': [1.2, 1.5],
    }),
    'BREAKOUT': (strat_breakout, {
        'lookback': [15, 20, 25],
        'vol_thresh': [1.5, 2.0, 2.5],
    }),
    'EMA_CROSS': (strat_ema_cross, {
        'vol_thresh': [1.0, 1.2, 1.5],
    }),
}

# Stop/target configs to try
RR_CONFIGS = [
    (0.5, 1.5, 15), (0.5, 2.0, 15), (0.5, 2.5, 20),
    (0.75, 1.5, 15), (0.75, 2.0, 15), (0.75, 2.5, 20), (0.75, 3.0, 25),
    (1.0, 2.0, 15), (1.0, 2.5, 20), (1.0, 3.0, 25),
    (1.25, 2.5, 20), (1.25, 3.0, 25), (1.25, 4.0, 30),
]


print("=" * 120)
print("STRATEGY OPTIMIZATION: Find What Works For Each Pair")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Pairs: {len(ALL_PAIRS)} | Strategies: {len(STRATEGIES)} | R:R configs: {len(RR_CONFIGS)}")
print("=" * 120)

results = []

for pair in ALL_PAIRS:
    try:
        df = load_data(pair)
        if len(df) < 500:
            continue
        
        ind = compute_indicators(df)
        best_config = None
        best_score = 0
        
        for strat_name, (strat_fn, param_grid) in STRATEGIES.items():
            # Generate parameter combinations
            param_names = list(param_grid.keys())
            param_values = list(param_grid.values())
            
            for param_combo in product(*param_values):
                params = dict(zip(param_names, param_combo))
                
                entries = strat_fn(ind, **params)
                if len(entries) < 5:
                    continue
                
                for stop, target, bars in RR_CONFIGS:
                    trades = backtest_trades(entries, ind, stop, target, bars)
                    pf, n = calc_pf(trades)
                    
                    if n >= 5 and pf >= 1.5:
                        score = pf * np.log(n)  # Balance PF with sample size
                        
                        if score > best_score:
                            best_score = score
                            exp = trades.mean() * 100 if len(trades) > 0 else 0
                            best_config = {
                                'pair': pair,
                                'strategy': strat_name,
                                'params': params,
                                'stop': stop,
                                'target': target,
                                'bars': bars,
                                'n': n,
                                'pf': round(pf, 2),
                                'exp': round(exp, 3),
                                'wr': round(float((trades > 0).sum() / len(trades) * 100), 1),
                            }
        
        if best_config:
            results.append(best_config)
            rr = best_config['target'] / best_config['stop']
            print(f"{pair:<10} {best_config['strategy']:<12} N={best_config['n']:<3} PF={best_config['pf']:<6.2f} R:R=1:{rr:.0f} Exp={best_config['exp']:.2f}%")
        else:
            print(f"{pair:<10} NO VIABLE STRATEGY")
    
    except Exception as e:
        print(f"{pair:<10} ERROR: {e}")

# Summary
print(f"\n{'=' * 120}")
print(f"VIABLE PAIRS: {len(results)} / {len(ALL_PAIRS)}")
print("=" * 120)

results.sort(key=lambda x: x['pf'], reverse=True)

print(f"\n{'Pair':<10} {'Strategy':<12} {'Params':<30} {'Stop':<8} {'Target':<10} {'N':<6} {'PF':<8} {'Exp%':<10} {'WR%'}")
print("-" * 110)
for r in results:
    params_str = ', '.join([f"{k}={v}" for k, v in r['params'].items()])
    rr = r['target'] / r['stop']
    print(f"{r['pair']:<10} {r['strategy']:<12} {params_str:<30} {r['stop']:<8.2f} {r['target']:<10.2f} {r['n']:<6} {r['pf']:<8.2f} {r['exp']:<10.3f} {r['wr']}")

# Portfolio summary
print(f"\n{'=' * 120}")
print("PORTFOLIO SUMMARY")
print("=" * 120)

total_trades = sum(r['n'] for r in results)
avg_exp = np.mean([r['exp'] for r in results])
avg_pf = np.mean([r['pf'] for r in results])

print(f"Total viable pairs: {len(results)}")
print(f"Total expected trades: {total_trades}")
print(f"Average expectancy: {avg_exp:.3f}%")
print(f"Average PF: {avg_pf:.2f}")

# Pairs by strategy
print(f"\nPairs by Strategy:")
strat_counts = {}
for r in results:
    strat_counts[r['strategy']] = strat_counts.get(r['strategy'], 0) + 1
for strat, count in sorted(strat_counts.items(), key=lambda x: x[1], reverse=True):
    print(f"  {strat}: {count} pairs")
