"""
SHORT-Side Strategy Test
=========================
Complement to LONG MR - trades OVERBOUGHT conditions for short exposure.
May provide true diversification in bearish regimes.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PAIRS = ['SUI', 'ARB', 'AAVE', 'AVAX', 'LINK', 'INJ', 'POL', 'SOL', 'NEAR', 'ATOM', 'UNI', 'OP']


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
    
    # BB
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_upper = sma20 + std20 * 2
    
    # EMAs
    ema_8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema_21 = df['close'].ewm(span=21, adjust=False).mean().values
    ema_50 = df['close'].ewm(span=50, adjust=False).mean().values
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Vol
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    # Stochastic (overbought)
    low_14 = pd.Series(l).rolling(14).min().values
    high_14 = pd.Series(h).rolling(14).max().values
    stoch_k = 100 * (c - low_14) / (high_14 - low_14 + 1e-10)
    stoch_d = pd.Series(stoch_k).rolling(3).mean().values
    
    return c, o, h, l, rsi, bb_upper, ema_8, ema_21, ema_50, atr, vol_ratio, stoch_k, stoch_d


def strat_short_mr(c, o, h, l, rsi, bb_upper, atr, vol_ratio, params):
    """SHORT Mean Reversion: Short at overbought + BB upper"""
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_upper[i]): continue
        if rsi[i] > params['rsi'] and c[i] > bb_upper[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15: continue
            entry_price = o[entry_bar]
            stop_price = entry_price + atr[entry_bar] * params['stop']  # Stop ABOVE for short
            target_price = entry_price - atr[entry_bar] * params['target']  # Target BELOW
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(h): break
                if h[bar] >= stop_price:  # Hit stop (price went up)
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - FRICTION)
                    break
                if l[bar] <= target_price:  # Hit target (price went down)
                    trades.append(atr[entry_bar] * params['target'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((entry_price - exit_price) / entry_price - FRICTION)  # Short P&L inverted
    return trades


def strat_trend_short(c, o, h, l, ema_8, ema_21, ema_50, rsi, atr, vol_ratio, params):
    """Trend Short: EMA bearish alignment + pullback to EMA21"""
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(ema_8[i]) or np.isnan(ema_21[i]) or np.isnan(ema_50[i]): continue
        # Downtrend: EMA8 < EMA21 < EMA50
        # Pullback: Price touches EMA21 from below
        if (ema_8[i] < ema_21[i] < ema_50[i] and
            c[i] > ema_21[i] and c[i] < ema_50[i] and
            rsi[i] > params['rsi_min'] and
            vol_ratio[i] > params['vol']):
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15: continue
            entry_price = o[entry_bar]
            stop_price = entry_price + atr[entry_bar] * params['stop']
            target_price = entry_price - atr[entry_bar] * params['target']
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(h): break
                if h[bar] >= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - FRICTION)
                    break
                if l[bar] <= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((entry_price - exit_price) / entry_price - FRICTION)
    return trades


def strat_stoch_short(c, o, h, l, stoch_k, stoch_d, atr, vol_ratio, params):
    """Stochastic Overbought: K crosses below D while overbought"""
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(stoch_k[i]) or np.isnan(stoch_d[i]): continue
        if (stoch_k[i] > params['stoch_overbought'] and 
            stoch_d[i] > params['stoch_overbought'] and
            stoch_k[i] < stoch_d[i] and
            stoch_k[i-1] >= stoch_d[i-1] and
            vol_ratio[i] > params['vol']):
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15: continue
            entry_price = o[entry_bar]
            stop_price = entry_price + atr[entry_bar] * params['stop']
            target_price = entry_price - atr[entry_bar] * params['target']
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(h): break
                if h[bar] >= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - FRICTION)
                    break
                if l[bar] <= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((entry_price - exit_price) / entry_price - FRICTION)
    return trades


def calc_stats(trades):
    if len(trades) < 5:
        return {'n': len(trades), 'pf': 0, 'exp': 0, 'wr': 0}
    t = np.array(trades)
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


# Strategy configs
SHORT_STRATEGIES = {
    'SHORT_MR': {
        'func': lambda c,o,h,l,r,b,u,a,v,p: strat_short_mr(c,o,h,l,r,b,a,v,p),
        'grid': {
            'rsi': [70, 75, 80],
            'vol': [1.3, 1.5, 2.0],
            'delay': [1, 2],
            'stop': [0.5, 0.75, 1.0],
            'target': [2.0, 2.5, 3.0],
        },
    },
    'TREND_SHORT': {
        'func': lambda c,o,h,l,e8,e21,e50,r,a,v,p: strat_trend_short(c,o,h,l,e8,e21,e50,r,a,v,p),
        'grid': {
            'rsi_min': [40, 45, 50],
            'vol': [1.2, 1.5],
            'delay': [1, 2],
            'stop': [0.75, 1.0, 1.5],
            'target': [1.5, 2.0, 2.5],
        },
    },
    'STOCH_SHORT': {
        'func': lambda c,o,h,l,sk,sd,a,v,p: strat_stoch_short(c,o,h,l,sk,sd,a,v,p),
        'grid': {
            'stoch_overbought': [75, 80, 85],
            'vol': [1.3, 1.5],
            'delay': [1, 2],
            'stop': [0.5, 0.75, 1.0],
            'target': [2.0, 2.5, 3.0],
        },
    },
}


print("=" * 120)
print("SHORT-SIDE STRATEGY TEST: Finding complementary short strategies")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

for strat_name, strat_config in SHORT_STRATEGIES.items():
    print(f"\n{'=' * 120}")
    print(f"STRATEGY: {strat_name}")
    print(f"{'=' * 120}")
    
    print(f"\n{'Pair':<8} {'Data':<8} {'N':<6} {'Exp%':<10} {'PF':<8} {'WR%':<8} {'Verdict'}")
    print("-" * 65)
    
    viable_pairs = []
    
    for pair in PAIRS:
        df = load_data(pair)
        if df is None:
            print(f"{pair:<8} NO DATA")
            continue
        
        n = len(df)
        train_end = int(n * 0.6)
        
        ind = compute_indicators(df)
        c, o, h, l, rsi, bb_upper, ema_8, ema_21, ema_50, atr, vol_ratio, stoch_k, stoch_d = ind
        
        # Grid search on train
        keys = list(strat_config['grid'].keys())
        values = list(strat_config['grid'].values())
        all_combos = list(product(*values))
        
        np.random.seed(42)
        if len(all_combos) > 100:
            indices = np.random.choice(len(all_combos), 100, replace=False)
            combos = [all_combos[i] for i in indices]
        else:
            combos = all_combos
        
        best_exp = -999
        best_n = 0
        
        for combo in combos:
            params = dict(zip(keys, combo))
            
            if strat_name == 'SHORT_MR':
                trades = strat_short_mr(c[:train_end], o[:train_end], h[:train_end], l[:train_end],
                                         rsi[:train_end], bb_upper[:train_end], atr[:train_end], 
                                         vol_ratio[:train_end], params)
            elif strat_name == 'TREND_SHORT':
                trades = strat_trend_short(c[:train_end], o[:train_end], h[:train_end], l[:train_end],
                                           ema_8[:train_end], ema_21[:train_end], ema_50[:train_end],
                                           rsi[:train_end], atr[:train_end], vol_ratio[:train_end], params)
            else:
                trades = strat_stoch_short(c[:train_end], o[:train_end], h[:train_end], l[:train_end],
                                           stoch_k[:train_end], stoch_d[:train_end], atr[:train_end],
                                           vol_ratio[:train_end], params)
            
            stats = calc_stats(trades)
            if stats['n'] >= 5 and stats['exp'] > best_exp:
                best_exp = stats['exp']
                best_n = stats['n']
        
        # Test on full data
        if best_exp > 0:
            if strat_name == 'SHORT_MR':
                trades = strat_short_mr(c, o, h, l, rsi, bb_upper, atr, vol_ratio,
                                         dict(zip(keys, [combo[keys.index(k)] for k in keys])))
            elif strat_name == 'TREND_SHORT':
                trades = strat_trend_short(c, o, h, l, ema_8, ema_21, ema_50, rsi, atr, vol_ratio,
                                            dict(zip(keys, [combo[keys.index(k)] for k in keys])))
            else:
                trades = strat_stoch_short(c, o, h, l, stoch_k, stoch_d, atr, vol_ratio,
                                            dict(zip(keys, [combo[keys.index(k)] for k in keys])))
            
            stats = calc_stats(trades)
            
            if stats['n'] >= 10 and stats['exp'] > 0:
                verdict = "VIABLE"
                viable_pairs.append((pair, stats))
            else:
                verdict = "WEAK"
                stats = calc_stats([])  # Reset for display
        else:
            verdict = "NO EDGE"
            stats = calc_stats([])
        
        print(f"{pair:<8} {n:<8} {stats['n']:<6} {stats['exp']:>7.2f}%  {stats['pf']:<8.2f} {stats['wr']:<8.1f} {verdict}")
    
    if viable_pairs:
        print(f"\n  VIABLE PAIRS ({len(viable_pairs)}):")
        for pair, stats in viable_pairs:
            print(f"    {pair}: Exp={stats['exp']:.2f}%, PF={stats['pf']}, N={stats['n']}, WR={stats['wr']}%")
