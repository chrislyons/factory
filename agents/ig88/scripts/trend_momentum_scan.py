"""
Trend & Momentum Scan: Find Strategies for Remaining Pairs
============================================================
MR only works on 5-12 pairs. Let's test:
1. TREND: EMA crossover + pullback to EMA21
2. MOMENTUM: RSI crossing key levels
3. BREAKOUT: Donchian breakout with volume

Target: Pairs with n>=10, PF>=1.5, bootstrap PF_5>1.0
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Pairs we need strategies for (excluding the 5 MR-strong pairs)
WEAK_PAIRS = ['AAVE', 'ADA', 'ALGO', 'ATOM', 'DOT', 'FIL', 'GRT', 'IMX', 
              'INJ', 'LINK', 'LTC', 'NEAR', 'OP', 'POL', 'SOL', 'SNX', 'UNI',
              'XRP', 'DOGE', 'STX', 'MKR', 'LDO', 'TRX', 'BNB']

# Also include some that might work better with trend
ALSO_TEST = ['BTC', 'ETH']


def load_data(pair):
    try:
        return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')
    except:
        return None


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    
    ema8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema21 = df['close'].ewm(span=21, adjust=False).mean().values
    ema55 = df['close'].ewm(span=55, adjust=False).mean().values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    # ADX
    up_move = np.diff(h, prepend=h[0])
    down_move = np.diff(l, prepend=l[0])
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    atr_smooth = pd.Series(tr).rolling(14).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / (atr_smooth + 1e-10)
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / (atr_smooth + 1e-10)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = pd.Series(dx).rolling(14).mean().values
    
    dc_upper = pd.Series(h).rolling(20).max().values
    
    return c, h, l, ema8, ema21, ema55, rsi, atr, vol_ratio, adx, dc_upper


def trend_entries(c, h, l, ema8, ema21, ema55, rsi, vol_ratio, adx, 
                  ema_align='8>21>55', pullback_pct=0.02, min_adx=20, min_vol=1.0):
    """Trend following entries."""
    entries = []
    for i in range(100, len(c) - 5):
        # EMA alignment
        if ema_align == '8>21>55':
            if not (ema8[i] > ema21[i] > ema55[i]):
                continue
        elif ema_align == '21>55':
            if not (ema21[i] > ema55[i]):
                continue
        
        # ADX filter
        if adx[i] < min_adx:
            continue
        
        # Volume filter
        if vol_ratio[i] < min_vol:
            continue
        
        # Pullback to EMA21
        pullback = (c[i] - ema21[i]) / ema21[i]
        if -pullback_pct <= pullback <= 0.01:  # Near or slightly below EMA21
            if c[i] > ema21[i]:  # Close above EMA21 (held support)
                entries.append(i)
    
    return entries


def momentum_entries(c, rsi, ema8, ema21, vol_ratio, 
                     rsi_low=40, rsi_high=60, min_vol=1.5):
    """Momentum entries (RSI crossing up)."""
    entries = []
    for i in range(100, len(c) - 5):
        # RSI crossing above rsi_high
        if rsi[i] > rsi_high and rsi[i-1] <= rsi_high:
            # EMA confirmation
            if ema8[i] > ema21[i]:
                if vol_ratio[i] > min_vol:
                    entries.append(i)
    return entries


def breakout_entries(c, h, dc_upper, vol_ratio, lookback=20, min_vol=2.0):
    """Breakout entries."""
    entries = []
    dc = pd.Series(h).rolling(lookback).max().values
    for i in range(100, len(c) - 5):
        if c[i] > dc[i-1] and vol_ratio[i] > min_vol:
            entries.append(i)
    return entries


def backtest(entries, c, h, l, atr, stop, target, max_bars):
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


def calc_pf(t):
    if len(t) < 3:
        return 0
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return 9.99
    return w.sum() / abs(ls.sum())


def bootstrap_pf5(t, n_bootstrap=2000):
    if len(t) < 5:
        return 0
    pfs = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(t, size=len(t), replace=True)
        w = sample[sample > 0]
        ls = sample[sample <= 0]
        if len(ls) > 0 and ls.sum() != 0:
            pfs.append(w.sum() / abs(ls.sum()))
    return np.percentile(pfs, 5) if pfs else 0


print("=" * 130)
print("TREND & MOMENTUM SCAN: Find Strategies for More Pairs")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 130)

STRATEGIES = [
    # (name, entry_fn, stop, target, bars, params)
    ('TREND_82155', lambda c,h,l,e8,e21,e55,rsi,at,vr,ad: trend_entries(c,h,l,e8,e21,e55,rsi,vr,ad, '8>21>55', 0.02, 20, 1.0), 1.0, 3.0, 25),
    ('TREND_2155', lambda c,h,l,e8,e21,e55,rsi,at,vr,ad: trend_entries(c,h,l,e8,e21,e55,rsi,vr,ad, '21>55', 0.02, 20, 1.0), 1.0, 3.0, 25),
    ('TREND_LOOSE', lambda c,h,l,e8,e21,e55,rsi,at,vr,ad: trend_entries(c,h,l,e8,e21,e55,rsi,vr,ad, '21>55', 0.03, 15, 0.8), 1.0, 2.5, 20),
    ('MOM_RSI60', lambda c,h,l,e8,e21,e55,rsi,at,vr,ad: momentum_entries(c,rsi,e8,e21,vr, 40, 60, 1.5), 0.75, 2.0, 15),
    ('MOM_RSI55', lambda c,h,l,e8,e21,e55,rsi,at,vr,ad: momentum_entries(c,rsi,e8,e21,vr, 35, 55, 1.2), 0.75, 2.0, 15),
    ('BREAKOUT_20', lambda c,h,l,e8,e21,e55,rsi,at,vr,ad: breakout_entries(c,h,None,vr, 20, 2.0), 1.0, 2.5, 15),
    ('BREAKOUT_15', lambda c,h,l,e8,e21,e55,rsi,at,vr,ad: breakout_entries(c,h,None,vr, 15, 1.5), 1.0, 2.5, 15),
]

results = []

for pair in WEAK_PAIRS + ALSO_TEST:
    df = load_data(pair)
    if df is None or len(df) < 500:
        continue
    
    c, h, l, ema8, ema21, ema55, rsi, atr, vol_ratio, adx, dc_upper = compute_indicators(df)
    
    best = None
    
    for strat_name, entry_fn, stop, target, bars in STRATEGIES:
        entries = entry_fn(c, h, l, ema8, ema21, ema55, rsi, atr, vol_ratio, adx)
        
        if len(entries) < 8:
            continue
        
        trades = backtest(entries, c, h, l, atr, stop, target, bars)
        
        if len(trades) < 8:
            continue
        
        pf = calc_pf(trades)
        pf5 = bootstrap_pf5(trades)
        
        if pf >= 1.5 and pf5 > 1.0:
            exp = trades.mean() * 100
            score = pf * np.log(len(trades))
            
            if best is None or score > best['score']:
                best = {
                    'pair': pair,
                    'strategy': strat_name,
                    'n': len(trades),
                    'pf': pf,
                    'pf5': pf5,
                    'exp': exp,
                    'wr': (trades > 0).sum() / len(trades) * 100,
                    'stop': stop,
                    'target': target,
                    'bars': bars,
                    'score': score,
                }
    
    if best:
        results.append(best)
        print(f"{best['pair']:<10} {best['strategy']:<15} N={best['n']:<3} PF={best['pf']:<6.2f} PF5={best['pf5']:<6.2f} Exp={best['exp']:.2f}%")
    else:
        # print(f"{pair:<10} NO STRATEGY PASSED")
        pass

# Summary
print(f"\n{'=' * 130}")
print(f"NEW VIABLE PAIRS FROM TREND/MOMENTUM: {len(results)}")
print("=" * 130)

if results:
    results.sort(key=lambda x: x['pf'], reverse=True)
    print(f"\n{'Pair':<10} {'Strategy':<15} {'N':<6} {'PF':<8} {'PF5':<8} {'Exp%':<10} {'WR%'}")
    print("-" * 70)
    for r in results:
        print(f"{r['pair']:<10} {r['strategy']:<15} {r['n']:<6} {r['pf']:<8.2f} {r['pf5']:<8.2f} {r['exp']:<10.2f} {r['wr']}")

print(f"\nTotal pairs now: 5 (MR) + {len(results)} (Trend/Momentum) = {5 + len(results)}")
