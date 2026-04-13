"""
Test All Pairs on Daily Timeframe
===================================
Daily bars = 6x larger than 4h.
Same % friction but proportionally smaller impact vs ATR.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Get all daily pairs
daily_pairs = []
for f in sorted(DATA_DIR.glob('binance_*_USD_1440m.parquet')):
    pair = f.name.replace('binance_', '').replace('_USD_1440m.parquet', '')
    daily_pairs.append(pair)

print(f"Daily pairs available: {len(daily_pairs)}")
print(f"Pairs: {daily_pairs}")


def load_data(pair):
    try:
        return pd.read_parquet(DATA_DIR / f'binance_{pair}_USD_1440m.parquet')
    except:
        return None


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
    
    ema8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema21 = df['close'].ewm(span=21, adjust=False).mean().values
    ema55 = df['close'].ewm(span=55, adjust=False).mean().values
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = atr / c * 100
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, ema8, ema21, ema55, atr, atr_pct, vol_ratio


def backtest_mr(c, h, l, atr, rsi, bb_pct, vol_ratio, cfg):
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


def backtest_trend(c, h, l, atr, ema8, ema21, ema55, vol_ratio, cfg):
    entries = []
    for i in range(100, len(c) - cfg['bars']):
        if not (ema8[i] > ema21[i] > ema55[i]):
            continue
        if vol_ratio[i] < cfg.get('vol', 1.0):
            continue
        pullback = (c[i] - ema21[i]) / ema21[i]
        if -0.03 <= pullback <= 0.005 and c[i] > ema21[i]:
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


def calc_pf(t):
    if len(t) < 5:
        return 0
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return 9.99
    return w.sum() / abs(ls.sum())


print(f"\n{'=' * 130}")
print("DAILY TIMEFRAME TEST: MR + Trend")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 130)

print(f"\n{'Pair':<10} {'Bars':<8} {'ATR%':<10} {'MR PF':<12} {'MR N':<8} {'Trend PF':<12} {'Trend N':<10} {'Best'}")
print("-" * 90)

results = []

for pair in daily_pairs:
    df = load_data(pair)
    if df is None or len(df) < 500:
        continue
    
    c, h, l, rsi, bb_pct, ema8, ema21, ema55, atr, atr_pct, vol_ratio = compute_indicators(df)
    
    atr_mean = atr_pct[100:].mean()
    
    # Test MR: RSI<25, BB<0.15, Vol>1.2
    mr_cfg = {'rsi': 25, 'bb': 0.15, 'vol': 1.2, 'stop': 1.0, 'target': 2.5, 'bars': 20}
    mr_trades = backtest_mr(c, h, l, atr, rsi, bb_pct, vol_ratio, mr_cfg)
    mr_pf = calc_pf(mr_trades) if len(mr_trades) >= 5 else 0
    
    # Test Trend: EMA 8>21>55
    trend_cfg = {'stop': 1.5, 'target': 4.0, 'bars': 20, 'vol': 1.0}
    trend_trades = backtest_trend(c, h, l, atr, ema8, ema21, ema55, vol_ratio, trend_cfg)
    trend_pf = calc_pf(trend_trades) if len(trend_trades) >= 5 else 0
    
    # Determine best
    if mr_pf >= 1.5 and mr_pf >= trend_pf:
        best = 'MR'
        best_pf = mr_pf
    elif trend_pf >= 1.5:
        best = 'TREND'
        best_pf = trend_pf
    else:
        best = '-'
        best_pf = 0
    
    print(f"{pair:<10} {len(df):<8} {atr_mean:<10.2f} {mr_pf:<12.2f} {len(mr_trades):<8} {trend_pf:<12.2f} {len(trend_trades):<10} {best}")
    
    if best_pf >= 1.5:
        results.append({
            'pair': pair,
            'strategy': best,
            'pf': best_pf,
            'n': len(mr_trades) if best == 'MR' else len(trend_trades),
            'atr_pct': atr_mean,
        })

# Summary
print(f"\n{'=' * 130}")
print(f"VIABLE DAILY PAIRS (PF >= 1.5, n >= 5): {len(results)}")
print("=" * 130)

if results:
    results.sort(key=lambda x: x['pf'], reverse=True)
    print(f"\n{'Pair':<10} {'Strategy':<10} {'PF':<10} {'N':<8} {'ATR%':<10}")
    print("-" * 50)
    for r in results:
        print(f"{r['pair']:<10} {r['strategy']:<10} {r['pf']:<10.2f} {r['n']:<8} {r['atr_pct']:<10.2f}")
    
    new_pairs = [r for r in results if r['pair'] not in ['ARB', 'AVAX', 'UNI', 'SUI', 'MATIC', 
                                                          'INJ', 'LINK', 'AAVE', 'ADA', 'ATOM', 
                                                          'ALGO', 'LTC']]
    print(f"\nNEW pairs to add to portfolio: {[r['pair'] for r in new_pairs]}")
