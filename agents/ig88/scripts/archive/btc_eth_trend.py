#!/usr/bin/env python3
"""
BTC/ETH Trend Following Strategy Development
==============================================
BTC/ETH don't mean-revert on 4H - they trend.
Need different strategy class for these majors.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

def load_data(pair):
    for name in [f'binance_{pair}_USD_1440m.parquet', f'binance_{pair}_USDT_240m.parquet']:
        path = DATA_DIR / name
        if path.exists():
            return pd.read_parquet(path), '1d' if '1440m' in name else '4h'
    return None, None


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    
    # EMAs
    ema8 = pd.Series(c).ewm(span=8, adjust=False).mean().values
    ema13 = pd.Series(c).ewm(span=13, adjust=False).mean().values
    ema21 = pd.Series(c).ewm(span=21, adjust=False).mean().values
    ema34 = pd.Series(c).ewm(span=34, adjust=False).mean().values
    ema55 = pd.Series(c).ewm(span=55, adjust=False).mean().values
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = atr / c * 100
    
    # ADX components
    plus_dm = np.diff(h, prepend=h[0])
    minus_dm = -np.diff(l, prepend=l[0])
    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)
    
    atr_smooth = pd.Series(tr).rolling(14).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / (atr_smooth + 1e-10)
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / (atr_smooth + 1e-10)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = pd.Series(dx).rolling(14).mean().values
    
    # Volume
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / (vol_sma + 1)
    
    # RSI for overbought exits
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    return {
        'close': c, 'high': h, 'low': l,
        'ema8': ema8, 'ema13': ema13, 'ema21': ema21, 'ema34': ema34, 'ema55': ema55,
        'atr': atr, 'atr_pct': atr_pct,
        'adx': adx, 'plus_di': plus_di, 'minus_di': minus_di,
        'vol_ratio': vol_ratio, 'rsi': rsi
    }


def trend_pullback_entry(ind, min_adx=20):
    """
    Trend + Pullback Entry:
    - EMA alignment (8>21>55 for long)
    - ADX > threshold (trending)
    - Price pulls back to EMA21
    """
    c = ind['close']
    entries = []
    
    for i in range(100, len(c) - 30):
        # EMA alignment
        if not (ind['ema8'][i] > ind['ema21'][i] > ind['ema55'][i]):
            continue
        
        # ADX filter
        if ind['adx'][i] < min_adx:
            continue
        
        # Pullback to EMA21 zone (within 1 ATR)
        pullback_dist = (c[i] - ind['ema21'][i]) / ind['ema21'][i]
        if -0.03 <= pullback_dist <= 0.005:
            # Price held above EMA21
            if c[i] > ind['ema21'][i] * 0.98:
                entries.append(i)
    
    return entries


def momentum_entry(ind):
    """
    Momentum Entry:
    - RSI crosses above 50
    - EMA8 crosses above EMA21
    - Volume confirmation
    """
    c = ind['close']
    entries = []
    
    for i in range(100, len(c) - 30):
        # RSI crossing up through 50
        if ind['rsi'][i] > 50 and ind['rsi'][i-1] <= 50:
            # EMA confirmation
            if ind['ema8'][i] > ind['ema21'][i]:
                # Volume spike
                if ind['vol_ratio'][i] > 1.2:
                    entries.append(i)
    
    return entries


def breakout_entry(ind):
    """
    Breakout Entry:
    - Price breaks 20-bar high
    - Volume confirmation
    - EMA20 as dynamic support
    """
    c = ind['close']
    h = ind['high']
    
    # 20-bar rolling high
    high_20 = pd.Series(h).rolling(20).max().values
    
    entries = []
    for i in range(100, len(c) - 30):
        # Break above 20-bar high
        if c[i] > high_20[i-1] and c[i-1] <= high_20[i-2]:
            # Volume confirmation
            if ind['vol_ratio'][i] > 1.5:
                # Above EMA21
                if c[i] > ind['ema21'][i]:
                    entries.append(i)
    
    return entries


def backtest(entries, ind, stop_atr=2.0, target_atr=4.0, max_bars=30, friction=0.01):
    """Backtest with ATR-based stops."""
    c = ind['close']
    h = ind['high']
    l = ind['low']
    atr = ind['atr']
    
    trades = []
    
    for idx in entries:
        entry_bar = idx + 1
        if entry_bar >= len(c) - max_bars:
            continue
        
        entry_price = c[entry_bar]
        stop_price = entry_price - atr[entry_bar] * stop_atr
        target_price = entry_price + atr[entry_bar] * target_atr
        
        for j in range(1, max_bars + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            
            if l[bar] <= stop_price:
                trades.append(-stop_atr * atr[entry_bar] / entry_price - friction)
                break
            if h[bar] >= target_price:
                trades.append(target_atr * atr[entry_bar] / entry_price - friction)
                break
        else:
            exit_price = c[min(entry_bar + max_bars, len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades)


def calc_stats(trades):
    if len(trades) < 3:
        return {'n': len(trades), 'pf': 0, 'exp': 0, 'wr': 0}
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99
    return {
        'n': len(trades),
        'pf': round(float(pf), 2),
        'exp': round(float(trades.mean() * 100), 3),
        'wr': round(float(len(w) / len(trades) * 100), 1)
    }


print("=" * 90)
print("BTC/ETH TREND FOLLOWING STRATEGY DEVELOPMENT")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 90)

for pair in ['BTC', 'ETH']:
    print(f"\n{'=' * 60}")
    print(f"{pair}")
    print(f"{'=' * 60}")
    
    df, tf = load_data(pair)
    if df is None:
        print("No data")
        continue
    
    print(f"Timeframe: {tf} | Bars: {len(df)}")
    
    ind = compute_indicators(df)
    
    print(f"\nATR%: {ind['atr_pct'][100:].mean():.2f}%")
    print(f"ADX mean: {ind['adx'][100:].mean():.1f}")
    
    # Test each strategy
    strategies = [
        ('Trend+Pullback (ADX>20)', lambda: trend_pullback_entry(ind, 20), 2.0, 4.0, 30),
        ('Trend+Pullback (ADX>25)', lambda: trend_pullback_entry(ind, 25), 2.0, 4.0, 30),
        ('Momentum', lambda: momentum_entry(ind), 1.5, 3.0, 20),
        ('Breakout', lambda: breakout_entry(ind), 1.5, 3.0, 20),
    ]
    
    print(f"\n{'Strategy':<30} {'N':<8} {'PF':<10} {'Exp%':<10} {'WR%':<10} {'Verdict'}")
    print("-" * 80)
    
    for name, entry_fn, stop, target, bars in strategies:
        entries = entry_fn()
        trades = backtest(entries, ind, stop, target, bars)
        stats = calc_stats(trades)
        
        if stats['n'] >= 5:
            if stats['pf'] >= 1.5 and stats['exp'] > 0:
                verdict = "\033[92mVIABLE\033[0m"
            else:
                verdict = "weak"
        else:
            verdict = "n<5"
        
        print(f"{name:<30} {stats['n']:<8} {stats['pf']:<10.2f} {stats['exp']:<10.3f} {stats['wr']:<10.1f} {verdict}")

print(f"""
{'=' * 90}
CONCLUSION
{'=' * 90}

BTC/ETH require TREND strategies, not mean reversion.
Key filters: ADX > 20-25, EMA alignment, pullback entries.

If we find viable configs, can add BTC/ETH to portfolio.
""")
