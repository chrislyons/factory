"""
High-Friction Strategy Optimizer
==================================
Designs strategies that work with 1.5-2% transaction costs.
Tests multiple indicator combinations per pair to find maximum edge.

KEY INSIGHT: With 2% friction, we need:
- Large moves (>5%) to have any expectancy
- High win rates OR very high win/loss ratios
- Tight stops to limit losses (but not too tight to get stopped by noise)
"""
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product
from concurrent.futures import ProcessPoolExecutor
import json
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
RESULTS_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/optimization')
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX', 'ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']

# Friction levels to test
FRICTION_LEVELS = [0.015, 0.0175, 0.02]  # 1.5%, 1.75%, 2.0%

# Strategy templates - each is a combination of indicators
STRATEGY_TEMPLATES = {
    'MR_RSI_BB': {
        'name': 'Mean Reversion (RSI + Bollinger)',
        'entry_type': 'reversion',
        'indicators': ['rsi', 'bb_lower', 'volume'],
    },
    'MR_RSI_KAMA': {
        'name': 'Mean Reversion (RSI + KAMA)',
        'entry_type': 'reversion',
        'indicators': ['rsi', 'kama', 'volume'],
    },
    'MR_STOCH_BB': {
        'name': 'Mean Reversion (Stochastic + BB)',
        'entry_type': 'reversion',
        'indicators': ['stoch_k', 'bb_lower', 'volume'],
    },
    'TF_ICHIMOKU': {
        'name': 'Trend Following (Ichimoku)',
        'entry_type': 'trend',
        'indicators': ['ichimoku', 'adx', 'volume'],
    },
    'TF_MA_CROSS': {
        'name': 'Trend Following (MA Cross)',
        'entry_type': 'trend',
        'indicators': ['ema_fast', 'ema_slow', 'adx'],
    },
    'TF_MOMENTUM': {
        'name': 'Trend Following (Momentum)',
        'entry_type': 'trend',
        'indicators': ['roc', 'adx', 'volume'],
    },
    'BRK_BREAKOUT': {
        'name': 'Breakout (Channel)',
        'entry_type': 'breakout',
        'indicators': ['donchian', 'volume', 'atr'],
    },
    'BRK_VOLUME': {
        'name': 'Breakout (Volume Surge)',
        'entry_type': 'breakout',
        'indicators': ['volume_surge', 'bb_width', 'atr'],
    },
}

# Parameter ranges for optimization
PARAM_RANGES = {
    'rsi_period': [7, 14, 21],
    'rsi_oversold': [20, 25, 30, 35],
    'bb_period': [15, 20, 25],
    'bb_std': [1.5, 2.0, 2.5],
    'stoch_period': [9, 14, 21],
    'kama_period': [20, 30, 40],
    'ema_fast': [8, 12, 15],
    'ema_slow': [21, 26, 34],
    'adx_threshold': [20, 25, 30],
    'volume_mult': [1.2, 1.5, 1.8, 2.0],
    'entry_delay': [1, 2, 3],
    'stop_atr_mult': [0.5, 0.75, 1.0, 1.5, 2.0],
    'target_atr_mult': [1.5, 2.0, 2.5, 3.0],
    'exit_bars': [10, 15, 20, 25],
}


def load_data(pair):
    """Load 4h data for a pair."""
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if not path.exists():
        return None
    return pd.read_parquet(path)


def compute_all_indicators(df):
    """Compute all possible indicators for a dataframe."""
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    v = df['volume'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi_14 = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # RSI with different periods
    gain_7 = delta.clip(lower=0).ewm(com=6, min_periods=7).mean()
    loss_7 = (-delta.clip(upper=0)).ewm(com=6, min_periods=7).mean()
    rsi_7 = np.where(loss_7 > 0, 100 - (100 / (1 + gain_7 / loss_7)), 50)
    
    gain_21 = delta.clip(lower=0).ewm(com=20, min_periods=21).mean()
    loss_21 = (-delta.clip(upper=0)).ewm(com=20, min_periods=21).mean()
    rsi_21 = np.where(loss_21 > 0, 100 - (100 / (1 + gain_21 / loss_21)), 50)
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_upper = sma20 + std20 * 2
    bb_middle = sma20
    bb_lower = sma20 - std20 * 2
    bb_lower_15 = sma20 - std20 * 1.5
    bb_lower_25 = sma20 - std20 * 2.5
    bb_width = (bb_upper - bb_lower) / sma20
    
    # Stochastic
    low_14 = df['low'].rolling(14).min().values
    high_14 = df['high'].rolling(14).max().values
    stoch_k = 100 * (c - low_14) / (high_14 - low_14)
    stoch_d = pd.Series(stoch_k).rolling(3).mean().values
    
    # KAMA (simplified)
    er_num = abs(df['close'] - df['close'].shift(1))
    er_den = df['close'].diff().abs().rolling(10).sum()
    er = (er_num / er_den).clip(0, 1).fillna(0.5)
    fast_sc = 2 / (2 + 1)
    slow_sc = 2 / (30 + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
    kama = df['close'].ewm(alpha=0.1, adjust=False).mean().values  # Simplified
    
    # EMAs
    ema_8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema_12 = df['close'].ewm(span=12, adjust=False).mean().values
    ema_15 = df['close'].ewm(span=15, adjust=False).mean().values
    ema_21 = df['close'].ewm(span=21, adjust=False).mean().values
    ema_26 = df['close'].ewm(span=26, adjust=False).mean().values
    ema_34 = df['close'].ewm(span=34, adjust=False).mean().values
    
    # ADX
    plus_dm = np.maximum(np.diff(h, prepend=h[0]), 0)
    minus_dm = np.maximum(-np.diff(l, prepend=l[0]), 0)
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr_14 = pd.Series(tr).rolling(14).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / atr_14
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / atr_14
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(14).mean().values
    
    # ROC (Rate of Change)
    roc_5 = df['close'].pct_change(5).values * 100
    roc_10 = df['close'].pct_change(10).values * 100
    roc_20 = df['close'].pct_change(20).values * 100
    
    # Donchian Channel
    donchian_upper = pd.Series(h).rolling(20).max().values
    donchian_lower = pd.Series(l).rolling(20).min().values
    donchian_mid = (donchian_upper + donchian_lower) / 2
    
    # Volume
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    vol_surge = vol_ratio > 1.5
    
    # ATR
    atr = pd.Series(tr).rolling(14).mean().values
    
    return {
        'rsi_7': rsi_7, 'rsi_14': rsi_14, 'rsi_21': rsi_21,
        'bb_upper': bb_upper, 'bb_middle': bb_middle, 'bb_lower': bb_lower,
        'bb_lower_15': bb_lower_15, 'bb_lower_25': bb_lower_25,
        'bb_width': bb_width,
        'stoch_k': stoch_k, 'stoch_d': stoch_d,
        'kama': kama,
        'ema_8': ema_8, 'ema_12': ema_12, 'ema_15': ema_15,
        'ema_21': ema_21, 'ema_26': ema_26, 'ema_34': ema_34,
        'adx': adx,
        'roc_5': roc_5, 'roc_10': roc_10, 'roc_20': roc_20,
        'donchian_upper': donchian_upper, 'donchian_lower': donchian_lower,
        'vol_ratio': vol_ratio, 'vol_surge': vol_surge,
        'atr': atr,
        'close': c, 'open': o, 'high': h, 'low': l,
    }


def test_mr_strategy(ind, params, friction):
    """
    Mean Reversion strategy: Buy oversold bounces.
    Entry: RSI < threshold AND price < BB lower AND volume surge
    Exit: Target or stop or time
    """
    rsi_key = f"rsi_{params.get('rsi_period', 14)}"
    rsi = ind.get(rsi_key, ind['rsi_14'])
    
    bb_std = params.get('bb_std', 2.0)
    if bb_std == 1.5:
        bb_low = ind['bb_lower_15']
    elif bb_std == 2.5:
        bb_low = ind['bb_lower_25']
    else:
        bb_low = ind['bb_lower']
    
    vol_mult = params.get('volume_mult', 1.5)
    entry_delay = params.get('entry_delay', 2)
    stop_atr = params.get('stop_atr_mult', 1.0)
    target_atr = params.get('target_atr_mult', 2.0)
    exit_bars = params.get('exit_bars', 15)
    rsi_thresh = params.get('rsi_oversold', 30)
    
    c = ind['close']
    o = ind['open']
    h = ind['high']
    l = ind['low']
    atr = ind['atr']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - exit_bars - 5):
        if np.isnan(rsi[i]) or np.isnan(bb_low[i]) or np.isnan(atr[i]):
            continue
        
        if rsi[i] < rsi_thresh and c[i] < bb_low[i] and vol_ratio[i] > vol_mult:
            entry_bar = i + entry_delay
            if entry_bar >= len(c) - exit_bars:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * stop_atr
            target_price = entry_price + atr[entry_bar] * target_atr
            
            for j in range(1, exit_bars):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * stop_atr / entry_price - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * target_atr / entry_price - friction)
                    break
            else:
                exit_price = c[min(entry_bar + exit_bars, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades) if trades else np.array([])


def test_tf_strategy(ind, params, friction):
    """
    Trend Following strategy: Trade with the trend on pullbacks.
    Entry: EMA cross + ADX > threshold + pullback to EMA
    Exit: Trailing stop or reversal
    """
    ema_fast_key = f"ema_{params.get('ema_fast', 12)}"
    ema_slow_key = f"ema_{params.get('ema_slow', 26)}"
    
    ema_fast = ind.get(ema_fast_key, ind['ema_12'])
    ema_slow = ind.get(ema_slow_key, ind['ema_26'])
    adx = ind['adx']
    atr = ind['atr']
    
    adx_thresh = params.get('adx_threshold', 25)
    entry_delay = params.get('entry_delay', 2)
    stop_atr = params.get('stop_atr_mult', 1.5)
    target_atr = params.get('target_atr_mult', 3.0)
    exit_bars = params.get('exit_bars', 20)
    vol_mult = params.get('volume_mult', 1.2)
    
    c = ind['close']
    o = ind['open']
    h = ind['high']
    l = ind['low']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - exit_bars - 5):
        if np.isnan(ema_fast[i]) or np.isnan(ema_slow[i]) or np.isnan(adx[i]):
            continue
        
        # Bullish: fast EMA > slow EMA, ADX strong, pullback to fast EMA
        if ema_fast[i] > ema_slow[i] and adx[i] > adx_thresh:
            if c[i] < ema_fast[i] and c[i] > ema_slow[i]:  # Pullback zone
                if vol_ratio[i] > vol_mult:
                    entry_bar = i + entry_delay
                    if entry_bar >= len(c) - exit_bars:
                        continue
                    
                    entry_price = o[entry_bar]
                    stop_price = entry_price - atr[entry_bar] * stop_atr
                    target_price = entry_price + atr[entry_bar] * target_atr
                    
                    for j in range(1, exit_bars):
                        bar = entry_bar + j
                        if bar >= len(l):
                            break
                        if l[bar] <= stop_price:
                            trades.append(-atr[entry_bar] * stop_atr / entry_price - friction)
                            break
                        if h[bar] >= target_price:
                            trades.append(atr[entry_bar] * target_atr / entry_price - friction)
                            break
                    else:
                        exit_price = c[min(entry_bar + exit_bars, len(c) - 1)]
                        trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades) if trades else np.array([])


def test_breakout_strategy(ind, params, friction):
    """
    Breakout strategy: Trade channel breakouts with volume confirmation.
    """
    donchian_upper = ind['donchian_upper']
    atr = ind['atr']
    
    entry_delay = params.get('entry_delay', 1)
    stop_atr = params.get('stop_atr_mult', 1.0)
    target_atr = params.get('target_atr_mult', 2.5)
    exit_bars = params.get('exit_bars', 15)
    vol_mult = params.get('volume_mult', 1.5)
    
    c = ind['close']
    o = ind['open']
    h = ind['high']
    l = ind['low']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - exit_bars - 5):
        if np.isnan(donchian_upper[i]) or np.isnan(atr[i]):
            continue
        
        # Breakout: price closes above Donchian upper
        if c[i] > donchian_upper[i-1] and vol_ratio[i] > vol_mult:
            entry_bar = i + entry_delay
            if entry_bar >= len(c) - exit_bars:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * stop_atr
            target_price = entry_price + atr[entry_bar] * target_atr
            
            for j in range(1, exit_bars):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * stop_atr / entry_price - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * target_atr / entry_price - friction)
                    break
            else:
                exit_price = c[min(entry_bar + exit_bars, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades) if trades else np.array([])


def calc_stats(trades):
    """Calculate performance statistics."""
    if len(trades) < 10:
        return {'n': len(trades), 'pf': 0, 'exp': 0, 'wr': 0, 'sharpe': 0, 'max_dd': 0}
    
    t = trades
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    cumsum = np.cumsum(t)
    max_dd = np.max(np.maximum.accumulate(cumsum) - cumsum)
    
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'exp': round(float(t.mean() * 100), 3),
        'wr': round(float(len(w) / len(t) * 100), 1),
        'sharpe': round(float(sharpe), 2),
        'max_dd': round(float(max_dd * 100), 2),
    }


def optimize_pair(pair, strategy_type, friction):
    """
    Grid search for optimal parameters for a pair+strategy combination.
    """
    df = load_data(pair)
    if df is None:
        return None
    
    ind = compute_all_indicators(df)
    
    # Define parameter grid based on strategy type
    if strategy_type == 'MR':
        param_grid = {
            'rsi_period': [7, 14, 21],
            'rsi_oversold': [20, 25, 30, 35],
            'bb_std': [1.5, 2.0, 2.5],
            'volume_mult': [1.3, 1.5, 1.8],
            'entry_delay': [1, 2, 3],
            'stop_atr_mult': [0.5, 0.75, 1.0],
            'target_atr_mult': [1.5, 2.0, 2.5, 3.0],
            'exit_bars': [10, 15, 20],
        }
        test_func = test_mr_strategy
    elif strategy_type == 'TF':
        param_grid = {
            'ema_fast': [8, 12, 15],
            'ema_slow': [21, 26, 34],
            'adx_threshold': [20, 25, 30],
            'volume_mult': [1.0, 1.2, 1.5],
            'entry_delay': [1, 2, 3],
            'stop_atr_mult': [1.0, 1.5, 2.0],
            'target_atr_mult': [2.0, 3.0, 4.0],
            'exit_bars': [15, 20, 25],
        }
        test_func = test_tf_strategy
    elif strategy_type == 'BREAKOUT':
        param_grid = {
            'volume_mult': [1.2, 1.5, 2.0],
            'entry_delay': [0, 1, 2],
            'stop_atr_mult': [0.75, 1.0, 1.5],
            'target_atr_mult': [2.0, 2.5, 3.0],
            'exit_bars': [10, 15, 20],
        }
        test_func = test_breakout_strategy
    else:
        return None
    
    # Grid search
    best_result = None
    best_params = None
    n_tested = 0
    
    # Generate all combinations (limit to 100 random samples for speed)
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    all_combos = list(product(*values))
    
    # Random sample if too many
    if len(all_combos) > 200:
        np.random.seed(42)
        indices = np.random.choice(len(all_combos), 200, replace=False)
        combos = [all_combos[i] for i in indices]
    else:
        combos = all_combos
    
    for combo in combos:
        params = dict(zip(keys, combo))
        trades = test_func(ind, params, friction)
        stats = calc_stats(trades)
        n_tested += 1
        
        if stats['n'] >= 20 and stats['exp'] > 0 and stats['pf'] > 1.0:
            if best_result is None or stats['exp'] > best_result['exp']:
                best_result = stats
                best_params = params
    
    return {
        'pair': pair,
        'strategy': strategy_type,
        'friction': friction,
        'best_params': best_params,
        'best_stats': best_result,
        'n_tested': n_tested,
    }


def main():
    print("=" * 100)
    print("HIGH-FRICTION STRATEGY OPTIMIZER")
    print(f"Testing 12 pairs x 3 strategy types x 3 friction levels")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    
    strategy_types = ['MR', 'TF', 'BREAKOUT']
    
    all_results = []
    
    for friction in FRICTION_LEVELS:
        print(f"\n{'=' * 100}")
        print(f"FRICTION LEVEL: {friction*100:.1f}%")
        print(f"{'=' * 100}")
        
        for pair in PAIRS:
            print(f"\n{pair}:", end=' ')
            
            pair_best = None
            
            for strategy in strategy_types:
                result = optimize_pair(pair, strategy, friction)
                if result and result['best_stats']:
                    all_results.append(result)
                    exp = result['best_stats']['exp']
                    pf = result['best_stats']['pf']
                    n = result['best_stats']['n']
                    
                    if pair_best is None or exp > pair_best['exp']:
                        pair_best = result['best_stats']
                        pair_best['strategy'] = strategy
                        pair_best['params'] = result['best_params']
                    
                    print(f"{strategy}: Exp={exp:.2f}% PF={pf:.2f} n={n}", end=' | ')
                else:
                    print(f"{strategy}: NO EDGE", end=' | ')
            
            if pair_best:
                verdict = "PASS" if pair_best['exp'] > 0.5 and pair_best['pf'] > 1.2 else "MARGINAL" if pair_best['exp'] > 0 else "FAIL"
                print(f"-> Best: {pair_best['strategy']} Exp={pair_best['exp']:.2f}% [{verdict}]")
            else:
                print("-> NO VIABLE STRATEGY")
    
    # Save results
    results_path = RESULTS_DIR / f"optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    
    # Summary table
    print(f"\n{'=' * 100}")
    print("OPTIMIZATION SUMMARY")
    print(f"{'=' * 100}")
    
    print(f"\n{'Pair':<8}", end='')
    for f in FRICTION_LEVELS:
        print(f"F{f*100:.0f}%{' '*10}", end='')
    print()
    print("-" * 80)
    
    for pair in PAIRS:
        print(f"{pair:<8}", end='')
        for friction in FRICTION_LEVELS:
            # Find best for this pair+friction
            best = None
            for r in all_results:
                if r['pair'] == pair and r['friction'] == friction and r['best_stats']:
                    if best is None or r['best_stats']['exp'] > best['exp']:
                        best = r['best_stats']
            if best and best['exp'] > 0:
                print(f"+{best['exp']:.2f}% PF{best['pf']:.1f}", end='    ')
            else:
                print(f"{'NO EDGE':>14}", end='')
        print()
    
    print(f"\nResults saved to: {results_path}")


if __name__ == '__main__':
    main()
