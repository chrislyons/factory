"""
Strategy Universe Test
=======================
Tests ALL major strategy types against 2% friction.
Finds the 4th strategy that works alongside MR.

ALREADY VALIDATED:
1. MR (Mean Reversion) - RSI<20, BB<2.0, Vol>1.5x

TESTING FOR 4TH:
2. Momentum (ROC + CCI)
3. Volatility Expansion (ATR spike + direction)
4. VWAP Reversion
5. Keltner Channel
6. Dual Timeframe Momentum
7. Volume Profile (high volume nodes)
8. Price Action (swing failures)
"""
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product
import json
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PAIRS = ['SUI', 'ARB', 'AAVE', 'AVAX', 'LINK', 'INJ', 'POL', 'SOL', 'NEAR', 'ATOM', 'UNI', 'OP']


def load_data(pair):
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if not path.exists():
        return None
    return pd.read_parquet(path)


def compute_indicators(df):
    """Compute all possible indicators."""
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
    bb_upper = sma20 + std20 * 2
    bb_lower = sma20 - std20 * 2
    bb_mid = sma20
    
    # EMAs
    ema_8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema_12 = df['close'].ewm(span=12, adjust=False).mean().values
    ema_21 = df['close'].ewm(span=21, adjust=False).mean().values
    ema_26 = df['close'].ewm(span=26, adjust=False).mean().values
    ema_50 = df['close'].ewm(span=50, adjust=False).mean().values
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_sma = pd.Series(tr).rolling(50).mean().values
    atr_ratio = atr / atr_sma  # ATR expansion ratio
    
    # Volume
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    vol_sma50 = pd.Series(v).rolling(50).mean().values
    
    # ROC (Rate of Change)
    roc_3 = df['close'].pct_change(3).values * 100
    roc_5 = df['close'].pct_change(5).values * 100
    roc_10 = df['close'].pct_change(10).values * 100
    roc_20 = df['close'].pct_change(20).values * 100
    
    # CCI
    tp = (h + l + c) / 3
    tp_series = pd.Series(tp)
    cci_sma = tp_series.rolling(20).mean().values
    cci_std = tp_series.rolling(20).std().values
    cci = (tp - cci_sma) / (0.015 * cci_std + 1e-10)
    
    # Stochastic
    low_14 = pd.Series(l).rolling(14).min().values
    high_14 = pd.Series(h).rolling(14).max().values
    stoch_k = 100 * (c - low_14) / (high_14 - low_14 + 1e-10)
    stoch_d = pd.Series(stoch_k).rolling(3).mean().values
    
    # Keltner Channels
    kelt_mid = df['close'].ewm(span=20, adjust=False).mean().values
    kelt_upper = kelt_mid + atr * 2
    kelt_lower = kelt_mid - atr * 2
    
    # VWAP (simplified - using rolling)
    tp_series = pd.Series(tp)
    v_series = pd.Series(v)
    vwap_num = (tp_series * v_series).rolling(20).sum().values
    vwap_den = v_series.rolling(20).sum().values
    vwap = vwap_num / (vwap_den + 1e-10)
    
    # Williams %R
    willr = -100 * (high_14 - c) / (high_14 - low_14 + 1e-10)
    
    # ADX
    plus_dm = np.maximum(np.diff(h, prepend=h[0]), 0)
    minus_dm = np.maximum(-np.diff(l, prepend=l[0]), 0)
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / atr
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(14).mean().values
    
    # MFI (Money Flow Index)
    tp_diff = np.diff(tp, prepend=tp[0])
    mf_pos = np.where(tp_diff > 0, tp * v, 0)
    mf_neg = np.where(tp_diff <= 0, tp * v, 0)
    mf_ratio = pd.Series(mf_pos).rolling(14).sum() / (pd.Series(mf_neg).rolling(14).sum() + 1e-10)
    mfi = (100 - (100 / (1 + mf_ratio))).values
    
    return {
        'close': c, 'open': o, 'high': h, 'low': l, 'volume': v,
        'rsi': rsi, 'bb_upper': bb_upper, 'bb_lower': bb_lower, 'bb_mid': bb_mid,
        'ema_8': ema_8, 'ema_12': ema_12, 'ema_21': ema_21, 'ema_26': ema_26, 'ema_50': ema_50,
        'atr': atr, 'atr_ratio': atr_ratio,
        'vol_ratio': vol_ratio, 'vol_sma50': vol_sma50,
        'roc_3': roc_3, 'roc_5': roc_5, 'roc_10': roc_10, 'roc_20': roc_20,
        'cci': cci,
        'stoch_k': stoch_k, 'stoch_d': stoch_d,
        'kelt_upper': kelt_upper, 'kelt_lower': kelt_lower, 'kelt_mid': kelt_mid,
        'willr': willr,
        'adx': adx,
        'mfi': mfi,
    }


def backtest_strategy(df, strategy_func, params, friction):
    """Generic backtest wrapper."""
    ind = compute_indicators(df)
    trades = strategy_func(ind, params)
    
    if len(trades) < 5:
        return {'n': len(trades), 'exp': 0, 'pf': 0, 'wr': 0, 'avg_win': 0, 'avg_loss': 0}
    
    trades = np.array(trades)
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    
    return {
        'n': len(trades),
        'exp': round(float(trades.mean() * 100), 3),
        'pf': round(float(w.sum() / abs(ls.sum())) if len(ls) > 0 and ls.sum() != 0 else 999, 2),
        'wr': round(float(len(w) / len(trades) * 100), 1),
        'avg_win': round(float(w.mean() * 100), 2) if len(w) > 0 else 0,
        'avg_loss': round(float(abs(ls.mean()) * 100), 2) if len(ls) > 0 else 0,
    }


# ============ STRATEGY DEFINITIONS ============

def strat_momentum_cci(ind, params):
    """
    MOMENTUM STRATEGY: CCI + ROC confirmation
    Entry: CCI < -100 (oversold) AND ROC turning positive
    Exit: CCI > 100 or stop/target
    """
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    cci = ind['cci']
    roc = ind['roc_5']
    atr = ind['atr']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(cci[i]) or np.isnan(roc[i]) or np.isnan(atr[i]):
            continue
        
        # Oversold momentum: CCI deep negative, ROC starting to turn
        if (cci[i] < params['cci_oversold'] and 
            roc[i] > params['roc_min'] and 
            vol_ratio[i] > params['vol']):
            
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop_atr']
            target_price = entry_price + atr[entry_bar] * params['target_atr']
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop_atr'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target_atr'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return trades


def strat_vol_expansion(ind, params):
    """
    VOLATILITY EXPANSION: Trade the breakout when ATR expands
    Entry: ATR ratio > threshold (expanding vol) + price direction
    Exit: ATR contracts or stop/target
    """
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    atr = ind['atr']
    atr_ratio = ind['atr_ratio']
    roc = ind['roc_3']
    ema_21 = ind['ema_21']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(atr_ratio[i]) or np.isnan(roc[i]) or np.isnan(ema_21[i]):
            continue
        
        # Volatility expanding + price bouncing off support
        if (atr_ratio[i] > params['atr_ratio_min'] and 
            vol_ratio[i] > params['vol'] and
            c[i] < ema_21[i] and  # Below EMA21 (oversold area)
            roc[i] > params['roc_min']):  # Starting to bounce
            
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop_atr']
            target_price = entry_price + atr[entry_bar] * params['target_atr']
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop_atr'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target_atr'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return trades


def strat_keltner_reversion(ind, params):
    """
    KELTNER REVERSION: Mean reversion using Keltner Channels
    Entry: Price below lower Keltner channel + oversold RSI
    Exit: Price returns to mid channel or stop/target
    """
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    kelt_lower = ind['kelt_lower']
    kelt_mid = ind['kelt_mid']
    rsi = ind['rsi']
    atr = ind['atr']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(kelt_lower[i]) or np.isnan(rsi[i]) or np.isnan(atr[i]):
            continue
        
        if (c[i] < kelt_lower[i] and 
            rsi[i] < params['rsi'] and 
            vol_ratio[i] > params['vol']):
            
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop_atr']
            target_price = entry_price + atr[entry_bar] * params['target_atr']
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop_atr'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target_atr'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return trades


def strat_stoch_failure(ind, params):
    """
    STOCHASTIC SWING FAILURE: SFX pattern
    Entry: Stoch makes new low but price doesn't follow (divergence)
    Exit: Stoch exits oversold or stop/target
    """
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    stoch_k = ind['stoch_k']
    stoch_d = ind['stoch_d']
    atr = ind['atr']
    vol_ratio = ind['vol_ratio']
    rsi = ind['rsi']
    
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(stoch_k[i]) or np.isnan(stoch_d[i]) or np.isnan(atr[i]):
            continue
        
        # Stochastic swing failure: K crosses above D while both oversold
        if (stoch_k[i] < params['stoch_oversold'] and 
            stoch_d[i] < params['stoch_oversold'] and
            stoch_k[i] > stoch_d[i] and  # K above D (bullish cross)
            stoch_k[i-1] <= stoch_d[i-1] and  # Cross just happened
            vol_ratio[i] > params['vol']):
            
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop_atr']
            target_price = entry_price + atr[entry_bar] * params['target_atr']
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop_atr'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target_atr'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return trades


def strat_mfi_reversion(ind, params):
    """
    MONEY FLOW INDEX REVERSION: Volume-weighted RSI
    Entry: MFI < 20 (extreme selling pressure)
    Exit: MFI > 50 or stop/target
    """
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    mfi = ind['mfi']
    atr = ind['atr']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(mfi[i]) or np.isnan(atr[i]):
            continue
        
        if (mfi[i] < params['mfi_oversold'] and 
            vol_ratio[i] > params['vol']):
            
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop_atr']
            target_price = entry_price + atr[entry_bar] * params['target_atr']
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop_atr'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target_atr'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return trades


def strat_ema_pullback(ind, params):
    """
    EMA PULLBACK: Trend continuation on pullback to EMA
    Entry: Price pulls back to EMA21 in uptrend (EMA8 > EMA21)
    Exit: Price makes new high or stop/target
    """
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    ema_8 = ind['ema_8']
    ema_21 = ind['ema_21']
    ema_50 = ind['ema_50']
    rsi = ind['rsi']
    atr = ind['atr']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(ema_8[i]) or np.isnan(ema_21[i]) or np.isnan(ema_50[i]):
            continue
        
        # Uptrend: EMA8 > EMA21 > EMA50
        # Pullback: Price touches EMA21
        if (ema_8[i] > ema_21[i] > ema_50[i] and
            c[i] < ema_21[i] and c[i] > ema_50[i] and  # Between EMA21 and EMA50
            rsi[i] < params['rsi_max'] and  # Not overbought
            vol_ratio[i] > params['vol']):
            
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop_atr']
            target_price = entry_price + atr[entry_bar] * params['target_atr']
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop_atr'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target_atr'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return trades


# Strategy configurations
STRATEGIES = {
    'MOMENTUM_CCI': {
        'func': strat_momentum_cci,
        'params': {
            'cci_oversold': [-150, -200, -250],
            'roc_min': [-1.0, 0, 1.0],
            'vol': [1.5, 2.0],
            'delay': [1, 2],
            'stop_atr': [0.75, 1.0, 1.5],
            'target_atr': [2.0, 2.5, 3.0],
        },
    },
    'VOL_EXPANSION': {
        'func': strat_vol_expansion,
        'params': {
            'atr_ratio_min': [1.2, 1.5, 2.0],
            'roc_min': [-2.0, 0, 2.0],
            'vol': [1.5, 2.0],
            'delay': [1, 2],
            'stop_atr': [0.75, 1.0, 1.5],
            'target_atr': [2.0, 2.5, 3.0],
        },
    },
    'KELTNER_REV': {
        'func': strat_keltner_reversion,
        'params': {
            'rsi': [20, 25, 30],
            'vol': [1.5, 2.0],
            'delay': [1, 2],
            'stop_atr': [0.75, 1.0, 1.5],
            'target_atr': [2.0, 2.5, 3.0],
        },
    },
    'STOCH_FAILURE': {
        'func': strat_stoch_failure,
        'params': {
            'stoch_oversold': [15, 20, 25],
            'vol': [1.5, 2.0],
            'delay': [1, 2],
            'stop_atr': [0.75, 1.0, 1.5],
            'target_atr': [2.0, 2.5, 3.0],
        },
    },
    'MFI_REV': {
        'func': strat_mfi_reversion,
        'params': {
            'mfi_oversold': [15, 20, 25],
            'vol': [1.5, 2.0],
            'delay': [1, 2],
            'stop_atr': [0.75, 1.0, 1.5],
            'target_atr': [2.0, 2.5, 3.0],
        },
    },
    'EMA_PULLBACK': {
        'func': strat_ema_pullback,
        'params': {
            'rsi_max': [50, 55, 60],
            'vol': [1.2, 1.5],
            'delay': [1, 2],
            'stop_atr': [0.75, 1.0, 1.5],
            'target_atr': [2.0, 2.5, 3.0],
        },
    },
}


print("=" * 120)
print("STRATEGY UNIVERSE TEST: Finding the 4th viable strategy at 2% friction")
print(f"Testing 6 strategy types x 12 pairs")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

results = {}

for strat_name, strat_config in STRATEGIES.items():
    print(f"\n{'=' * 120}")
    print(f"STRATEGY: {strat_name}")
    print(f"{'=' * 120}")
    
    strat_results = []
    
    for pair in PAIRS:
        df = load_data(pair)
        if df is None:
            continue
        
        # Grid search (sampled)
        keys = list(strat_config['params'].keys())
        values = list(strat_config['params'].values())
        all_combos = list(product(*values))
        
        np.random.seed(42)
        if len(all_combos) > 100:
            indices = np.random.choice(len(all_combos), 100, replace=False)
            combos = [all_combos[i] for i in indices]
        else:
            combos = all_combos
        
        best = None
        best_params = None
        
        for combo in combos:
            params = dict(zip(keys, combo))
            result = backtest_strategy(df, strat_config['func'], params, FRICTION)
            
            if result['n'] >= 10 and result['exp'] > 0:
                if best is None or result['exp'] > best['exp']:
                    best = result
                    best_params = params
        
        if best and best['n'] >= 10:
            strat_results.append({
                'pair': pair,
                'exp': best['exp'],
                'pf': best['pf'],
                'wr': best['wr'],
                'n': best['n'],
                'params': best_params,
            })
            print(f"  {pair:<8} Exp={best['exp']:>6.2f}% PF={best['pf']:>5.2f} N={best['n']:<4} WR={best['wr']:.0f}%")
        else:
            print(f"  {pair:<8} NO EDGE")
    
    # Summary
    if strat_results:
        avg_exp = np.mean([r['exp'] for r in strat_results])
        total_trades = sum([r['n'] for r in strat_results])
        viable_pairs = len(strat_results)
        
        results[strat_name] = {
            'results': strat_results,
            'avg_exp': avg_exp,
            'total_trades': total_trades,
            'viable_pairs': viable_pairs,
        }
        
        print(f"\n  SUMMARY: {viable_pairs} viable pairs, Avg Exp={avg_exp:.2f}%, Total trades={total_trades}")
    else:
        print(f"\n  SUMMARY: NO VIABLE PAIRS")


# Final ranking
print(f"\n{'=' * 120}")
print("STRATEGY RANKING (by number of viable pairs and average expectancy)")
print(f"{'=' * 120}")

ranked = sorted(results.items(), key=lambda x: (x[1]['viable_pairs'], x[1]['avg_exp']), reverse=True)

print(f"\n{'Rank':<6} {'Strategy':<20} {'Viable Pairs':<15} {'Avg Exp%':<12} {'Total Trades'}")
print("-" * 70)

for i, (name, data) in enumerate(ranked, 1):
    print(f"{i:<6} {name:<20} {data['viable_pairs']:<15} {data['avg_exp']:<12.2f} {data['total_trades']}")

print(f"\n{'=' * 120}")
print("RECOMMENDED 4TH STRATEGY")
print(f"{'=' * 120}")

if ranked:
    best_4th = ranked[0]
    print(f"\nBest: {best_4th[0]}")
    print(f"  Viable pairs: {best_4th[1]['viable_pairs']}")
    print(f"  Average expectancy: {best_4th[1]['avg_exp']:.2f}%")
    print(f"\nViable pairs:")
    for r in best_4th[1]['results']:
        print(f"  {r['pair']}: Exp={r['exp']:.2f}%, PF={r['pf']}, N={r['n']}")
