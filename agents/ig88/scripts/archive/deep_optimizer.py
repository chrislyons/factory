"""
Deep Optimizer: Finding Edge in High-Friction Environments
=============================================================
Strategy: Test much more aggressive parameters
- Deeper oversold (RSI < 20, < 15)
- Wider BB (2.5, 3.0 std)
- Higher targets (3x, 4x, 5x ATR)
- Tighter stops (0.5x, 0.75x ATR)
- Longer holds (20, 25 bars)

Goal: Find the rare setups that produce BIG moves to overcome friction.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product
import json
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PAIRS = ['SUI', 'ARB', 'AAVE', 'AVAX', 'LINK', 'INJ', 'POL']


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
    bb_lower_2 = sma20 - std20 * 2
    bb_lower_25 = sma20 - std20 * 2.5
    bb_lower_3 = sma20 - std20 * 3
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return {
        'close': c, 'open': o, 'high': h, 'low': l,
        'rsi': rsi,
        'bb_lower_2': bb_lower_2, 'bb_lower_25': bb_lower_25, 'bb_lower_3': bb_lower_3,
        'atr': atr, 'vol_ratio': vol_ratio,
    }


def run_mr_test(ind, params, friction):
    """Test MR with aggressive parameters."""
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    rsi, atr, vol_ratio = ind['rsi'], ind['atr'], ind['vol_ratio']
    
    # Select BB based on std parameter
    bb_key = f"bb_lower_{params['bb_std']}".replace('.', '')
    if bb_key not in ind:
        bb_key = 'bb_lower_2'
    bb_low = ind[bb_key]
    
    trades = []
    winners = []
    losers = []
    
    for i in range(100, len(c) - params['bars']):
        if np.isnan(rsi[i]) or np.isnan(bb_low[i]) or np.isnan(atr[i]):
            continue
        
        # Signal
        if rsi[i] < params['rsi'] and c[i] < bb_low[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - params['bars']:
                continue
            
            entry_price = o[entry_bar]
            stop_dist = atr[entry_bar] * params['stop_atr']
            target_dist = atr[entry_bar] * params['target_atr']
            stop_price = entry_price - stop_dist
            target_price = entry_price + target_dist
            
            for j in range(1, params['bars']):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    ret = -stop_dist / entry_price - friction
                    trades.append(ret)
                    losers.append(ret)
                    break
                if h[bar] >= target_price:
                    ret = target_dist / entry_price - friction
                    trades.append(ret)
                    winners.append(ret)
                    break
            else:
                exit_price = c[min(entry_bar + params['bars'], len(c) - 1)]
                ret = (exit_price - entry_price) / entry_price - friction
                trades.append(ret)
                if ret > 0:
                    winners.append(ret)
                else:
                    losers.append(ret)
    
    return np.array(trades), np.array(winners), np.array(losers)


def calc_stats(t, w, l):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0, 'avg_win': 0, 'avg_loss': 0, 'edge': 0}
    
    avg_win = w.mean() if len(w) > 0 else 0
    avg_loss = abs(l.mean()) if len(l) > 0 else 0
    wr = len(w) / len(t)
    edge = wr * avg_win - (1 - wr) * avg_loss  # Expected value per trade
    
    return {
        'n': len(t),
        'pf': round(float(w.sum() / abs(l.sum())) if abs(l.sum()) > 0 else 999, 3),
        'exp': round(float(t.mean() * 100), 3),
        'wr': round(float(wr * 100), 1),
        'avg_win': round(float(avg_win * 100), 2),
        'avg_loss': round(float(avg_loss * 100), 2),
        'edge': round(float(edge * 100), 3),
    }


# Parameter grid - aggressive values
PARAM_GRID = {
    'rsi': [25, 20, 15, 10],  # Deeper oversold
    'bb_std': [2.0, 2.5, 3.0],  # Deeper below BB
    'vol': [1.5, 2.0, 2.5],  # Higher volume requirement
    'delay': [1, 2],
    'stop_atr': [0.5, 0.75, 1.0],  # Tighter stops
    'target_atr': [2.0, 2.5, 3.0, 4.0, 5.0],  # Bigger targets
    'bars': [15, 20, 25],
}


print("=" * 120)
print("DEEP OPTIMIZER: Finding edge with aggressive parameters (2% friction)")
print(f"Testing RSI<25, BB<3.0std, Targets 3-5x ATR")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

results = {}

for pair in PAIRS:
    df = load_data(pair)
    ind = compute_indicators(df)
    
    best_edge = -999
    best_params = None
    best_stats = None
    n_tested = 0
    
    # Grid search (sampled)
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    all_combos = list(product(*values))
    
    np.random.seed(42)
    if len(all_combos) > 500:
        indices = np.random.choice(len(all_combos), 500, replace=False)
        combos = [all_combos[i] for i in indices]
    else:
        combos = all_combos
    
    for combo in combos:
        params = dict(zip(keys, combo))
        trades, winners, losers = run_mr_test(ind, params, FRICTION)
        stats = calc_stats(trades, winners, losers)
        n_tested += 1
        
        # Only consider if we have enough trades and positive edge
        if stats['n'] >= 10 and stats['edge'] > best_edge:
            best_edge = stats['edge']
            best_params = params
            best_stats = stats
    
    results[pair] = {
        'params': best_params,
        'stats': best_stats,
        'n_tested': n_tested,
    }
    
    if best_stats and best_stats['n'] >= 10:
        print(f"{pair:<8} RSI<{best_params['rsi']} BB{best_params['bb_std']} Vol>{best_params['vol']} "
              f"Stop{best_params['stop_atr']}x Target{best_params['target_atr']}x {best_params['bars']}bars | "
              f"N={best_stats['n']} Exp={best_stats['exp']:.2f}% PF={best_stats['pf']:.2f} "
              f"WR={best_stats['wr']:.0f}% Win={best_stats['avg_win']:.1f}% Loss={best_stats['avg_loss']:.1f}% Edge={best_stats['edge']:.3f}%")
    else:
        print(f"{pair:<8} NO EDGE (n_tested={n_tested})")


# Portfolio summary
print(f"\n{'=' * 120}")
print("PORTFOLIO SUMMARY (optimized per pair)")
print(f"{'=' * 120}")

all_trades = []
for pair, res in results.items():
    if res['params']:
        df = load_data(pair)
        ind = compute_indicators(df)
        trades, _, _ = run_mr_test(ind, res['params'], FRICTION)
        all_trades.extend(trades)

if all_trades:
    arr = np.array(all_trades)
    w = arr[arr > 0]
    l = arr[arr <= 0]
    
    print(f"\nCombined: {len(arr)} trades")
    print(f"  Exp: {arr.mean()*100:.3f}%")
    print(f"  PF: {w.sum()/abs(l.sum()):.2f}" if len(l) > 0 else "  PF: inf")
    print(f"  WR: {(arr > 0).mean()*100:.1f}%")
    print(f"  Avg Win: {w.mean()*100:.2f}%")
    print(f"  Avg Loss: {abs(l.mean())*100:.2f}%")
    
    # Monte Carlo
    np.random.seed(42)
    n_sim = 1000
    returns = []
    for _ in range(n_sim):
        sampled = np.random.choice(arr, size=24, replace=True)  # 2 trades/month x 12 months
        returns.append(sampled.sum())
    returns = np.array(returns)
    
    print(f"\nMonte Carlo (12 months, 2 trades/month):")
    print(f"  Mean: {returns.mean()*100:.1f}%")
    print(f"  Median: {np.median(returns)*100:.1f}%")
    print(f"  Prob > 0: {(returns > 0).mean()*100:.1f}%")
    print(f"  Prob > 20%: {(returns > 0.20).mean()*100:.1f}%")
