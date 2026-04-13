"""
Expand Signals: Relax Criteria to Get More Trades
===================================================
Problem: Only 4 pairs pass validation because signals are too rare.
Solution: Relax RSI threshold, BB threshold, Volume threshold to get more samples.
Goal: Get n >= 15 for each pair while maintaining PF >= 1.5
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Pairs we're trying to get working
TARGET_PAIRS = [
    'AAVE', 'ALGO', 'ARB', 'ATOM', 'AVAX', 'DOT', 'FIL', 'GRT', 
    'IMX', 'INJ', 'LINK', 'LTC', 'MATIC', 'NEAR', 'OP', 'POL', 
    'SOL', 'SNX', 'SUI', 'UNI', 'ADA', 'DOGE', 'STX', 'XRP',
    'MKR', 'LDO', 'TRX', 'BNB'
]


def load_data(pair):
    try:
        return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')
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
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio, ema8, ema21


def backtest_mr(c, h, l, rsi, bb_pct, atr, rsi_thresh, bb_thresh, vol_thresh, stop, target, max_bars):
    entries = []
    for i in range(100, len(c) - max_bars):
        if rsi[i] < rsi_thresh and bb_pct[i] < bb_thresh and vol_ratio[i] > vol_thresh:
            entries.append(i)
    
    trades = []
    for idx in entries:
        entry_bar = idx + 1
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


print("=" * 120)
print("EXPAND SIGNALS: Relax Criteria For More Trades")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

# Parameter grid
RSI_THRESHOLDS = [18, 20, 22, 25, 28, 30]
BB_THRESHOLDS = [0.05, 0.1, 0.15, 0.2]
VOL_THRESHOLDS = [1.2, 1.5, 1.8]
STOP_TARGETS = [
    (0.75, 2.0, 15),
    (1.0, 2.5, 20),
    (1.0, 3.0, 25),
    (1.25, 2.5, 20),
]

results = []

for pair in TARGET_PAIRS:
    df = load_data(pair)
    if df is None or len(df) < 500:
        continue
    
    c, h, l, rsi, bb_pct, atr, vol_ratio, ema8, ema21 = compute_indicators(df)
    
    best_config = None
    best_score = 0
    
    for rsi_t in RSI_THRESHOLDS:
        for bb_t in BB_THRESHOLDS:
            for vol_t in VOL_THRESHOLDS:
                for stop, target, bars in STOP_TARGETS:
                    trades = backtest_mr(c, h, l, rsi, bb_pct, atr, rsi_t, bb_t, vol_t, stop, target, bars)
                    n = len(trades)
                    
                    if n < 10:  # Need at least 10 trades
                        continue
                    
                    pf = calc_pf(trades)
                    
                    if pf >= 1.5:
                        # Score: PF * log(n) - penalize weak PF
                        score = pf * np.log(n) if pf < 10 else 10 * np.log(n)
                        
                        if score > best_score:
                            best_score = score
                            exp = trades.mean() * 100
                            best_config = {
                                'pair': pair,
                                'rsi': rsi_t,
                                'bb': bb_t,
                                'vol': vol_t,
                                'stop': stop,
                                'target': target,
                                'bars': bars,
                                'n': n,
                                'pf': round(pf, 2),
                                'exp': round(exp, 3),
                                'wr': round(float((trades > 0).sum() / n * 100), 1),
                            }
    
    if best_config:
        results.append(best_config)
        rr = best_config['target'] / best_config['stop']
        print(f"{pair:<10} RSI<{best_config['rsi']:<3} BB<{best_config['bb']:.2f} Vol>{best_config['vol']:.1f} S={best_config['stop']:.2f} T={best_config['target']:.2f} N={best_config['n']:<3} PF={best_config['pf']:<6.2f}")
    else:
        print(f"{pair:<10} NO VIABLE CONFIG (n>=10, PF>=1.5)")

# Summary
print(f"\n{'=' * 120}")
print(f"VIABLE PAIRS WITH RELAXED CRITERIA (n>=10, PF>=1.5): {len(results)}")
print("=" * 120)

if results:
    results.sort(key=lambda x: x['pf'], reverse=True)
    
    print(f"\n{'Pair':<10} {'RSI':<6} {'BB':<6} {'Vol':<6} {'Stop':<8} {'Target':<10} {'R:R':<8} {'N':<6} {'PF':<8} {'Exp%':<10} {'WR%'}")
    print("-" * 90)
    for r in results:
        rr = r['target'] / r['stop']
        print(f"{r['pair']:<10} {r['rsi']:<6} {r['bb']:<6} {r['vol']:<6} {r['stop']:<8.2f} {r['target']:<10.2f} 1:{rr:<5.0f} {r['n']:<6} {r['pf']:<8.2f} {r['exp']:<10.3f} {r['wr']}")
    
    print(f"\nTotal viable pairs: {len(results)}")
    print(f"Total expected trades: {sum(r['n'] for r in results)}")
