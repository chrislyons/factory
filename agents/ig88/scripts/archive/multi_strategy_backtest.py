"""
Multi-Strategy Backtest Validation
====================================
Validates the multi-strategy approach (best strategy per pair).
Compares against single-strategy (MR-only) approach.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02  # 2% worst-case friction

# Optimal strategies per pair (from optimizer)
PAIR_STRATEGIES = {
    'ARB':  {'type': 'MR', 'rsi': 20, 'bb': 2.0, 'vol': 1.8, 'delay': 3, 'stop': 0.75, 'target': 3.0, 'bars': 15},
    'AVAX': {'type': 'MR', 'rsi': 25, 'bb': 1.5, 'vol': 1.5, 'delay': 2, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'SUI':  {'type': 'BO', 'vol': 1.5, 'delay': 1, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'NEAR': {'type': 'BO', 'vol': 1.5, 'delay': 1, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'SOL':  {'type': 'TF', 'adx': 25, 'vol': 1.2, 'delay': 2, 'stop': 1.5, 'target': 3.0, 'bars': 20},
    'AAVE': {'type': 'BO', 'vol': 1.5, 'delay': 1, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'OP':   {'type': 'MR', 'rsi': 30, 'bb': 2.0, 'vol': 1.3, 'delay': 2, 'stop': 0.5, 'target': 2.0, 'bars': 15},
    'POL':  {'type': 'BO', 'vol': 1.5, 'delay': 1, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'UNI':  {'type': 'BO', 'vol': 1.5, 'delay': 1, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'INJ':  {'type': 'BO', 'vol': 1.5, 'delay': 1, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'LINK': {'type': 'MR', 'rsi': 30, 'bb': 2.0, 'vol': 1.5, 'delay': 2, 'stop': 1.0, 'target': 2.5, 'bars': 15},
    'ATOM': {'type': 'MR', 'rsi': 30, 'bb': 2.0, 'vol': 1.5, 'delay': 2, 'stop': 1.0, 'target': 2.5, 'bars': 15},
}

# Single strategy for comparison (naive MR)
NAIVE_MR = {'type': 'MR', 'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'delay': 2, 'stop': 0.5, 'target': 1.5, 'bars': 16}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    v = df['volume'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower_20 = sma20 - std20 * 2
    bb_lower_15 = sma20 - std20 * 1.5
    bb_mid = sma20
    
    ema_12 = df['close'].ewm(span=12, adjust=False).mean().values
    ema_26 = df['close'].ewm(span=26, adjust=False).mean().values
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    plus_dm = np.maximum(np.diff(h, prepend=h[0]), 0)
    minus_dm = np.maximum(-np.diff(l, prepend=l[0]), 0)
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / atr
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(14).mean().values
    
    donchian_upper = pd.Series(h).rolling(20).max().values
    
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    return {
        'close': c, 'open': o, 'high': h, 'low': l,
        'rsi': rsi, 'bb_lower_20': bb_lower_20, 'bb_lower_15': bb_lower_15, 'bb_mid': bb_mid,
        'ema_12': ema_12, 'ema_26': ema_26, 'adx': adx, 'atr': atr,
        'donchian_upper': donchian_upper, 'vol_ratio': vol_ratio,
    }


def run_mr_backtest(ind, params, friction):
    """Run Mean Reversion backtest."""
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    rsi, atr, vol_ratio = ind['rsi'], ind['atr'], ind['vol_ratio']
    bb_key = 'bb_lower_15' if params.get('bb', 2.0) == 1.5 else 'bb_lower_20'
    bb_low = ind[bb_key]
    
    trades = []
    for i in range(100, len(c) - params['bars'] - 5):
        if np.isnan(rsi[i]) or np.isnan(bb_low[i]) or np.isnan(atr[i]):
            continue
        if rsi[i] < params['rsi'] and c[i] < bb_low[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - params['bars']:
                continue
            entry_price = o[entry_bar]
            stop_dist = atr[entry_bar] * params['stop'] / 100
            target_dist = atr[entry_bar] * params['target'] / 100
            stop_price = entry_price - atr[entry_bar] * params['stop'] / 100
            target_price = entry_price + atr[entry_bar] * params['target'] / 100
            for j in range(1, params['bars']):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - friction)
                    break
            else:
                exit_price = c[min(entry_bar + params['bars'], len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    return np.array(trades) if trades else np.array([])


def run_bo_backtest(ind, params, friction):
    """Run Breakout backtest."""
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    atr, vol_ratio = ind['atr'], ind['vol_ratio']
    donchian_upper = ind['donchian_upper']
    
    trades = []
    for i in range(100, len(c) - params['bars'] - 5):
        if np.isnan(donchian_upper[i]) or np.isnan(atr[i]):
            continue
        if c[i] > donchian_upper[i-1] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - params['bars']:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop']
            target_price = entry_price + atr[entry_bar] * params['target']
            for j in range(1, params['bars']):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - friction)
                    break
            else:
                exit_price = c[min(entry_bar + params['bars'], len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    return np.array(trades) if trades else np.array([])


def run_tf_backtest(ind, params, friction):
    """Run Trend Following backtest."""
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    ema_12, ema_26 = ind['ema_12'], ind['ema_26']
    adx, atr, vol_ratio = ind['adx'], ind['atr'], ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - params['bars'] - 5):
        if np.isnan(ema_12[i]) or np.isnan(ema_26[i]) or np.isnan(adx[i]):
            continue
        if (ema_12[i] > ema_26[i] and adx[i] > params['adx'] and
            c[i] < ema_12[i] and c[i] > ema_26[i] and vol_ratio[i] > params['vol']):
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - params['bars']:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop']
            target_price = entry_price + atr[entry_bar] * params['target']
            for j in range(1, params['bars']):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - friction)
                    break
            else:
                exit_price = c[min(entry_bar + params['bars'], len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    return np.array(trades) if trades else np.array([])


def calc_stats(t):
    if len(t) < 5:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'exp': round(float(t.mean() * 100), 3),
        'wr': round(float(len(w) / len(t) * 100), 1),
    }


print("=" * 100)
print("MULTI-STRATEGY vs NAIVE MR COMPARISON (2% friction)")
print("=" * 100)

multi_total_trades = []
naive_total_trades = []

print(f"\n{'Pair':<8} {'Strategy':<8} {'Multi N':<10} {'Multi Exp':<12} {'Multi PF':<10} | {'Naive N':<10} {'Naive Exp':<12} {'Naive PF':<10}")
print("-" * 100)

for pair, params in PAIR_STRATEGIES.items():
    df = load_data(pair)
    ind = compute_indicators(df)
    
    # Multi-strategy
    if params['type'] == 'MR':
        multi_trades = run_mr_backtest(ind, params, FRICTION)
    elif params['type'] == 'BO':
        multi_trades = run_bo_backtest(ind, params, FRICTION)
    else:  # TF
        multi_trades = run_tf_backtest(ind, params, FRICTION)
    
    # Naive MR
    naive_trades = run_mr_backtest(ind, NAIVE_MR, FRICTION)
    
    ms = calc_stats(multi_trades)
    ns = calc_stats(naive_trades)
    
    multi_total_trades.extend(multi_trades)
    naive_total_trades.extend(naive_trades)
    
    winner = "MULTI" if ms['exp'] > ns['exp'] else "NAIVE" if ns['exp'] > ms['exp'] else "TIE"
    print(f"{pair:<8} {params['type']:<8} {ms['n']:<10} {ms['exp']:>9.3f}%  {ms['pf']:<9.3f} | {ns['n']:<10} {ns['exp']:>9.3f}%  {ns['pf']:<9.3f}  {winner}")

# Portfolio totals
mt = np.array(multi_total_trades) if multi_total_trades else np.array([0])
nt = np.array(naive_total_trades) if naive_total_trades else np.array([0])

print(f"\n{'=' * 100}")
print("PORTFOLIO TOTALS")
print(f"{'=' * 100}")

print(f"\nMulti-Strategy:")
print(f"  Total trades: {len(mt)}")
print(f"  Avg Exp: {mt.mean()*100:.3f}%")
print(f"  Win Rate: {(mt > 0).mean()*100:.1f}%")
print(f"  Profit Factor: {mt[mt > 0].sum() / abs(mt[mt <= 0].sum()):.2f}" if len(mt[mt <= 0]) > 0 else "  Profit Factor: ∞")

print(f"\nNaive MR (single strategy):")
print(f"  Total trades: {len(nt)}")
print(f"  Avg Exp: {nt.mean()*100:.3f}%")
print(f"  Win Rate: {(nt > 0).mean()*100:.1f}%")
print(f"  Profit Factor: {nt[nt > 0].sum() / abs(nt[nt <= 0].sum()):.2f}" if len(nt[nt <= 0]) > 0 else "  Profit Factor: ∞")

improvement = ((mt.mean() - nt.mean()) / abs(nt.mean()) * 100) if nt.mean() != 0 else 0
print(f"\nImprovement: {improvement:+.0f}% expectancy")
