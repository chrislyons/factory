"""
BTC/ETH Daily: Test Majors on Higher Timeframe
================================================
Daily bars = 6x larger range than 4h.
Same 2% friction but targets are proportionally larger.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02


def load_data(pair, timeframe='1440m'):
    try:
        return pd.read_parquet(DATA_DIR / f'binance_{pair}_USD_{timeframe}.parquet')
    except:
        return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_{timeframe}.parquet')


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
    atr_pct = atr / c * 100
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, o, rsi, bb_pct, ema8, ema21, ema55, atr, atr_pct, vol_ratio


def backtest_mr(c, h, l, atr, rsi, bb_pct, vol_ratio, cfg):
    """MR strategy with pair-specific R:R."""
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


def backtest_trend(c, h, l, atr, ema8, ema21, ema55, rsi, vol_ratio, cfg):
    """Trend following: EMA alignment + pullback."""
    entries = []
    for i in range(100, len(c) - cfg['bars']):
        if not (ema8[i] > ema21[i] > ema55[i]):
            continue
        if vol_ratio[i] < cfg.get('vol', 1.0):
            continue
        # Pullback to EMA21
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


def calc_stats(t):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean() * 100), 3), 'wr': round(float(len(w) / len(t) * 100), 1)}


print("=" * 120)
print("BTC/ETH DAILY: Test Majors on Higher Timeframe")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

# Test BTC and ETH on daily
for pair in ['BTC', 'ETH']:
    print(f"\n{'=' * 60}")
    print(f"{pair} DAILY")
    print(f"{'=' * 60}")
    
    df = load_data(pair)
    print(f"Data: {len(df)} bars ({len(df)/365:.1f} years)")
    
    c, h, l, o, rsi, bb_pct, ema8, ema21, ema55, atr, atr_pct, vol_ratio = compute_indicators(df)
    
    print(f"\nATR% mean: {atr_pct[100:].mean():.2f}%")
    
    # Test MR with various R:R
    print(f"\nMR Strategy (RSI<20 + BB<0.1 + Vol>1.5):")
    print(f"{'Stop':<10} {'Target':<10} {'R:R':<10} {'Bars':<10} {'N':<8} {'PF':<10} {'Exp%':<10} {'WR%'}")
    print("-" * 80)
    
    for stop in [0.75, 1.0, 1.25]:
        for target in [2.0, 2.5, 3.0, 4.0]:
            for bars in [10, 15, 20]:
                cfg = {'rsi': 20, 'bb': 0.1, 'vol': 1.5, 'stop': stop, 'target': target, 'bars': bars}
                trades = backtest_mr(c, h, l, atr, rsi, bb_pct, vol_ratio, cfg)
                stats = calc_stats(trades)
                
                if stats['n'] >= 5 and stats['pf'] >= 1.5:
                    rr = target / stop
                    print(f"{stop:<10.2f} {target:<10.2f} 1:{rr:<7.0f} {bars:<10} {stats['n']:<8} {stats['pf']:<10.2f} {stats['exp']:<10.3f} {stats['wr']}%")
    
    # Test Trend
    print(f"\nTrend Strategy (EMA 8>21>55 + Pullback):")
    print(f"{'Stop':<10} {'Target':<10} {'R:R':<10} {'Bars':<10} {'N':<8} {'PF':<10} {'Exp%':<10} {'WR%'}")
    print("-" * 80)
    
    for stop in [1.0, 1.5, 2.0]:
        for target in [3.0, 4.0, 5.0]:
            for bars in [15, 20, 30]:
                cfg = {'stop': stop, 'target': target, 'bars': bars, 'vol': 1.0}
                trades = backtest_trend(c, h, l, atr, ema8, ema21, ema55, rsi, vol_ratio, cfg)
                stats = calc_stats(trades)
                
                if stats['n'] >= 5 and stats['pf'] >= 1.5:
                    rr = target / stop
                    print(f"{stop:<10.2f} {target:<10.2f} 1:{rr:<7.0f} {bars:<10} {stats['n']:<8} {stats['pf']:<10.2f} {stats['exp']:<10.3f} {stats['wr']}%")

print(f"\n{'=' * 120}")
print("CONCLUSION")
print("=" * 120)
print("""
BTC/ETH on daily have LARGER bars = larger ATR = targets hit more often.
But signals are RARE on daily (20+ year history, ~7300 bars).
If viable, these pairs add HIGH CONVICTION even with few trades.
""")
