"""
Multi-Strategy Scan: Find What Works For Each Pair
====================================================
Test multiple strategy types on all pairs:
1. Mean Reversion (RSI + BB + Volume)
2. Trend Following (EMA crossover + ADX)
3. Momentum (RSI momentum + Volume)
4. Breakout (Donchian + Volume)
5. Volatility (ATR expansion + direction)

For each pair, report which strategy has highest PF with n>=5.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02  # Realistic friction

# Get all available 240m pairs (excluding BTC/ETH as benchmarks)
ALL_PAIRS = []
for f in sorted(DATA_DIR.glob('binance_*_USDT_240m.parquet')):
    pair = f.name.replace('binance_', '').replace('_USDT_240m.parquet', '')
    if pair not in ['BTC', 'ETH']:  # Exclude benchmarks
        ALL_PAIRS.append(pair)


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    v = df['volume'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_upper = sma20 + std20 * 2
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower)
    
    # EMAs
    ema8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema21 = df['close'].ewm(span=21, adjust=False).mean().values
    ema55 = df['close'].ewm(span=55, adjust=False).mean().values
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = atr / c * 100
    
    # Volume
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    # ADX (simplified)
    up_move = np.diff(h, prepend=h[0])
    down_move = np.diff(l, prepend=l[0])
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    atr_smooth = pd.Series(tr).rolling(14).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / atr_smooth
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / atr_smooth
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = pd.Series(dx).rolling(14).mean().values
    
    # Donchian Channels
    dc_upper = pd.Series(h).rolling(20).max().values
    dc_lower = pd.Series(l).rolling(20).min().values
    
    return {
        'c': c, 'o': o, 'h': h, 'l': l, 'v': v,
        'rsi': rsi, 'bb_lower': bb_lower, 'bb_upper': bb_upper, 'bb_pct': bb_pct,
        'ema8': ema8, 'ema21': ema21, 'ema55': ema55,
        'atr': atr, 'atr_pct': atr_pct,
        'vol_ratio': vol_ratio, 'adx': adx,
        'dc_upper': dc_upper, 'dc_lower': dc_lower,
    }


def backtest_trades(entries, ind, stop_atr, target_atr, max_bars):
    """Run backtest given entry indices."""
    c, h, l = ind['c'], ind['h'], ind['l']
    atr = ind['atr']
    
    trades = []
    for entry_idx in entries:
        entry_bar = entry_idx + 1
        if entry_bar >= len(c) - max_bars:
            continue
        
        entry_price = c[entry_bar]
        if np.isnan(entry_price) or entry_price == 0:
            continue
        
        stop_dist = atr[entry_bar] * stop_atr
        target_dist = atr[entry_bar] * target_atr
        stop_price = entry_price - stop_dist
        target_price = entry_price + target_dist
        
        # Check for stop/target within max bars
        for j in range(1, max_bars + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            if l[bar] <= stop_price:
                trades.append(-stop_dist / entry_price - FRICTION)
                break
            if h[bar] >= target_price:
                trades.append(target_dist / entry_price - FRICTION)
                break
        else:
            # Time exit
            exit_price = c[min(entry_bar + max_bars, len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades)


def calc_stats(t):
    if len(t) < 5:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        pf = 9.99
    else:
        pf = w.sum() / abs(ls.sum())
    return {
        'n': len(t),
        'pf': round(float(pf), 2),
        'exp': round(float(t.mean() * 100), 3),
        'wr': round(float(len(w) / len(t) * 100), 1),
    }


# STRATEGY FUNCTIONS
def strat_mr(ind):
    """Mean Reversion: RSI<20 + BB<0.1 + Volume>1.5"""
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['rsi'][i] < 20 and 
            ind['bb_pct'][i] < 0.1 and 
            ind['vol_ratio'][i] > 1.5):
            entries.append(i)
    return entries, 0.75, 2.5, 15


def strat_trend_follow(ind):
    """Trend Following: EMA8>EMA21>EMA55 + ADX>25 + pullback to EMA21"""
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['ema8'][i] > ind['ema21'][i] > ind['ema55'][i] and
            ind['adx'][i] > 25 and
            ind['l'][i] <= ind['ema21'][i] * 1.005 and
            ind['c'][i] > ind['ema21'][i]):
            entries.append(i)
    return entries, 1.0, 3.0, 20


def strat_momentum_long(ind):
    """Momentum Long: RSI crossing above 50 + Volume spike + EMA8>EMA21"""
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['rsi'][i] > 50 and ind['rsi'][i-1] <= 50 and
            ind['vol_ratio'][i] > 1.5 and
            ind['ema8'][i] > ind['ema21'][i]):
            entries.append(i)
    return entries, 0.75, 2.0, 15


def strat_breakout(ind):
    """Breakout: Close above Donchian upper + Volume spike"""
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['c'][i] > ind['dc_upper'][i-1] and
            ind['vol_ratio'][i] > 2.0):
            entries.append(i)
    return entries, 1.0, 2.5, 15


def strat_ema_crossover(ind):
    """EMA Crossover: Fast EMA crosses above slow EMA"""
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['ema8'][i] > ind['ema21'][i] and 
            ind['ema8'][i-1] <= ind['ema21'][i-1] and
            ind['vol_ratio'][i] > 1.2):
            entries.append(i)
    return entries, 0.75, 1.5, 10


def strat_rsi_reversal(ind):
    """RSI Reversal: RSI<30 then crosses back above 30"""
    entries = []
    for i in range(100, len(ind['c'])):
        if (ind['rsi'][i] > 30 and ind['rsi'][i-1] <= 30 and
            ind['rsi'][i-2] < 25):
            entries.append(i)
    return entries, 0.75, 2.0, 15


STRATEGIES = {
    'MR_RSI20': strat_mr,
    'TREND': strat_trend_follow,
    'MOMENTUM': strat_momentum_long,
    'BREAKOUT': strat_breakout,
    'EMA_CROSS': strat_ema_crossover,
    'RSI_REVERSAL': strat_rsi_reversal,
}


print("=" * 120)
print("MULTI-STRATEGY SCAN: Finding What Works For Each Pair")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Pairs: {len(ALL_PAIRS)} | Strategies: {len(STRATEGIES)} | Friction: {FRICTION*100:.0f}%")
print("=" * 120)

# Results matrix
results = {}

print(f"\n{'Pair':<10}", end='')
for strat_name in STRATEGIES:
    print(f"{strat_name:<16}", end='')
print("BEST")
print("-" * 110)

for pair in ALL_PAIRS:
    try:
        df = load_data(pair)
        if len(df) < 500:
            continue
        
        ind = compute_indicators(df)
        results[pair] = {}
        
        best_strat = None
        best_pf = 0
        
        print(f"{pair:<10}", end='')
        
        for strat_name, strat_fn in STRATEGIES.items():
            entries, stop, target, bars = strat_fn(ind)
            trades = backtest_trades(entries, ind, stop, target, bars)
            stats = calc_stats(trades)
            results[pair][strat_name] = stats
            
            # Display
            if stats['n'] >= 5:
                pf = stats['pf']
                print(f"N={stats['n']:<2} PF={pf:<5.2f} ", end='')
                if pf > best_pf:
                    best_pf = pf
                    best_strat = strat_name
            else:
                print(f"N={stats['n']:<2} {'---':<10} ", end='')
        
        print(f"  -> {best_strat or 'NONE'} (PF={best_pf:.2f})")
    
    except Exception as e:
        print(f"{pair:<10} ERROR: {e}")

# Summary: Pairs with valid strategies
print(f"\n{'=' * 120}")
print("SUMMARY: Pairs With Valid Strategies (PF >= 1.5, n >= 5)")
print("=" * 120)

viable_pairs = []
for pair in results:
    for strat_name, stats in results[pair].items():
        if stats['n'] >= 5 and stats['pf'] >= 1.5:
            viable_pairs.append({
                'pair': pair,
                'strategy': strat_name,
                'n': stats['n'],
                'pf': stats['pf'],
                'exp': stats['exp'],
                'wr': stats['wr'],
            })

# Sort by PF
viable_pairs.sort(key=lambda x: x['pf'], reverse=True)

print(f"\n{'Pair':<10} {'Strategy':<16} {'N':<6} {'PF':<8} {'Exp%':<10} {'WR%'}")
print("-" * 60)
for v in viable_pairs:
    print(f"{v['pair']:<10} {v['strategy']:<16} {v['n']:<6} {v['pf']:<8.2f} {v['exp']:<10.3f} {v['wr']}")

print(f"\nTotal viable pairs: {len(set(v['pair'] for v in viable_pairs))}")
print(f"Total viable combinations: {len(viable_pairs)}")
