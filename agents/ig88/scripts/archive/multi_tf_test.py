"""
Multi-Timeframe Confirmation Test
==================================
Hypothesis: Combining 4h entry with 1d trend filter reduces false signals
and improves win rate even if total signals decrease.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Pairs with both 4h and 1d data
PAIRS = ['ATOM', 'AVAX', 'GRT', 'INJ', 'LINK', 'NEAR', 'UNI', 'XRP',
         'AAVE', 'ALGO', 'ARB', 'DOGE', 'FIL', 'IMX', 'LTC', 'MATIC',
         'SOL', 'SNX', 'SUI', 'UNI']


def load_4h(pair):
    try:
        return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')
    except:
        return None


def load_1d(pair):
    try:
        return pd.read_parquet(DATA_DIR / f'binance_{pair}_USD_1440m.parquet')
    except:
        return None


def compute_4h_indicators(df):
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
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio


def compute_1d_trend(df):
    """Compute daily trend filter."""
    c = df['close'].values
    ema8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema21 = df['close'].ewm(span=21, adjust=False).mean().values
    ema55 = df['close'].ewm(span=55, adjust=False).mean().values
    
    # Daily trend direction: 1=up, -1=down, 0=neutral
    trend = np.zeros(len(c))
    trend[ema8 > ema21] = 0.5  # Short-term bullish
    trend[ema8 > ema21] += 0.5  # Medium-term bullish
    trend[ema21 > ema55] += 1.0  # Long-term bullish
    
    return trend


def backtest_mr_no_filter(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg):
    """MR without daily filter."""
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


def backtest_mr_with_daily_filter(c4, h4, l4, rsi4, bb4, atr4, vol4, daily_trend, cfg, min_trend):
    """MR with daily trend filter - only take shorts when daily is bullish (MR bounce)."""
    entries = []
    for i in range(100, len(c4) - cfg['bars']):
        if rsi4[i] < cfg['rsi'] and bb4[i] < cfg['bb'] and vol4[i] > cfg['vol']:
            # Map 4h index to daily index (1d = 6 bars of 4h)
            daily_idx = min(i // 6, len(daily_trend) - 1)
            if daily_trend[daily_idx] >= min_trend:
                entries.append(i)
    
    trades = []
    for idx in entries:
        entry_bar = idx + 1
        entry_price = c4[entry_bar]
        if np.isnan(entry_price) or entry_price == 0:
            continue
        
        stop_price = entry_price - atr4[entry_bar] * cfg['stop']
        target_price = entry_price + atr4[entry_bar] * cfg['target']
        
        for j in range(1, cfg['bars'] + 1):
            bar = entry_bar + j
            if bar >= len(l4):
                break
            if l4[bar] <= stop_price:
                trades.append(-atr4[entry_bar] * cfg['stop'] / entry_price - FRICTION)
                break
            if h4[bar] >= target_price:
                trades.append(atr4[entry_bar] * cfg['target'] / entry_price - FRICTION)
                break
        else:
            exit_price = c4[min(entry_bar + cfg['bars'], len(c4) - 1)]
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
print("MULTI-TIMEFRAME CONFIRMATION: 4h Entry + 1d Trend Filter")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

print(f"\n{'Pair':<10} {'No Filter':<20} {'Daily Bullish':<20} {'Filter Effect'}")
print(f"{'':10} {'N':<6} {'PF':<8} {'Exp%':<8} {'N':<6} {'PF':<8} {'Exp%':<8}")
print("-" * 90)

for pair in PAIRS:
    df_4h = load_4h(pair)
    df_1d = load_1d(pair)
    
    if df_4h is None or df_1d is None:
        continue
    
    c4, h4, l4, rsi4, bb4, atr4, vol4 = compute_4h_indicators(df_4h)
    daily_trend = compute_1d_trend(df_1d)
    
    cfg = {'rsi': 25, 'bb': 0.15, 'vol': 1.2, 'stop': 1.0, 'target': 2.5, 'bars': 20}
    
    # No filter
    trades_no_filter = backtest_mr_no_filter(c4, h4, l4, rsi4, bb4, atr4, vol4, cfg)
    stats_no_filter = calc_stats(trades_no_filter)
    
    # With daily bullish filter (min_trend >= 2 means both short and medium-term bullish)
    trades_filtered = backtest_mr_with_daily_filter(c4, h4, l4, rsi4, bb4, atr4, vol4, daily_trend, cfg, 2)
    stats_filtered = calc_stats(trades_filtered)
    
    # Filter effect
    if stats_no_filter['pf'] > 0 and stats_filtered['pf'] > 0:
        pf_change = ((stats_filtered['pf'] / stats_no_filter['pf']) - 1) * 100
        effect = f"PF {pf_change:+.0f}%"
    else:
        effect = "-"
    
    print(f"{pair:<10} {stats_no_filter['n']:<6} {stats_no_filter['pf']:<8.2f} {stats_no_filter['exp']:<8.2f} {stats_filtered['n']:<6} {stats_filtered['pf']:<8.2f} {stats_filtered['exp']:<8.2f} {effect}")

print(f"\n{'=' * 120}")
print("CONCLUSION: Does daily trend filter improve edge?")
print("=" * 120)
