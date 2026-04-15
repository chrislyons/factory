#!/usr/bin/env python3
"""
Regime Filter for Mean Reversion Portfolio
===========================================
Problem: MR strategies blow up in trending regimes.
Solution: Filter entries using regime detection.

Test: Does filtering MR entries during strong trends improve PF?
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.01  # 1%

PORTFOLIO = {
    'ARB':   {'rsi': 18, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 2.5, 'tier': 'STRONG'},
    'SUI':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25, 'size': 2.5, 'tier': 'STRONG'},
    'AVAX':  {'rsi': 20, 'bb': 0.15, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 2.5, 'tier': 'STRONG'},
    'MATIC': {'rsi': 25, 'bb': 0.15, 'vol': 1.8, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 2.5, 'tier': 'STRONG'},
    'UNI':   {'rsi': 22, 'bb': 0.10, 'vol': 1.8, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 2.0, 'tier': 'STRONG'},
    'DOT':   {'rsi': 20, 'bb': 0.10, 'vol': 1.0, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.5, 'tier': 'MEDIUM'},
    'ALGO':  {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 1.5, 'tier': 'MEDIUM'},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25, 'size': 1.5, 'tier': 'MEDIUM'},
    'FIL':   {'rsi': 20, 'bb': 0.10, 'vol': 1.0, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.5, 'tier': 'MEDIUM'},
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'LINK':  {'rsi': 18, 'bb': 0.05, 'vol': 1.8, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'AAVE':  {'rsi': 22, 'bb': 0.15, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 1.0, 'tier': 'WEAK'},
    'SNX':   {'rsi': 22, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
}


def load_data(pair):
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if path.exists():
        return pd.read_parquet(path)
    return None


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_pct = (c - (sma20 - std20 * 2)) / (std20 * 4 + 1e-10)
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Volume
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    # EMAs for regime detection
    ema8 = pd.Series(c).ewm(span=8, adjust=False).mean().values
    ema21 = pd.Series(c).ewm(span=21, adjust=False).mean().values
    ema55 = pd.Series(c).ewm(span=55, adjust=False).mean().values
    
    # ADX for trend strength
    plus_dm = np.maximum(np.diff(h, prepend=h[0]), 0)
    minus_dm = np.maximum(-np.diff(l, prepend=l[0]), 0)
    plus_dm = np.where((plus_dm > minus_dm), plus_dm, 0)
    minus_dm = np.where((minus_dm > plus_dm), minus_dm, 0)
    atr_smooth = pd.Series(tr).rolling(14).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / (atr_smooth + 1e-10)
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / (atr_smooth + 1e-10)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = pd.Series(dx).rolling(14).mean().values
    
    # 20-bar momentum
    c_series = pd.Series(c)
    momentum = ((c_series / c_series.shift(20)) - 1) * 100
    momentum = momentum.fillna(0).values
    
    return {
        'close': c, 'rsi': rsi, 'bb_pct': bb_pct, 'atr': atr, 'vol_ratio': vol_ratio,
        'ema8': ema8, 'ema21': ema21, 'ema55': ema55,
        'adx': adx, 'plus_di': plus_di, 'minus_di': minus_di,
        'momentum': momentum
    }


def is_favorable_regime(ind, i, adx_threshold=45, max_ema_spread=0.12):
    """
    Filter only EXTREME trends where MR consistently fails.
    
    MR works in moderate trends (buying dips).
    MR fails in extreme parabolic moves (catching falling knives).
    
    Only filter the worst cases - ADX > 45 or EMA spread > 12%.
    """
    # Filter extreme trends only
    if ind['adx'][i] > adx_threshold:
        return False
    
    # EMA spread - extreme divergence = parabolic move = MR fails
    ema_spread = abs(ind['ema21'][i] - ind['ema55'][i]) / ind['ema55'][i]
    if ema_spread > max_ema_spread:
        return False
    
    return True


def backtest(entries, ind, cfg, friction=FRICTION):
    """Backtest with ATR-based stops."""
    c = ind['close']
    h_raw = load_data(cfg['pair'])['high'].values if 'pair' in cfg else None
    l_raw = load_data(cfg['pair'])['low'].values if 'pair' in cfg else None
    
    trades = []
    for idx in entries:
        entry_bar = idx + 1
        if entry_bar >= len(c) - cfg['bars']:
            continue
        
        entry_price = c[entry_bar]
        atr = ind['atr'][entry_bar]
        
        stop_price = entry_price - atr * cfg['stop']
        target_price = entry_price + atr * cfg['target']
        
        for j in range(1, cfg['bars'] + 1):
            bar = entry_bar + j
            if bar >= len(c):
                break
            # Simplified - using close as proxy
            if c[bar] <= stop_price:
                trades.append(-atr * cfg['stop'] / entry_price - friction)
                break
            if c[bar] >= target_price:
                trades.append(atr * cfg['target'] / entry_price - friction)
                break
        else:
            exit_price = c[min(entry_bar + cfg['bars'], len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades)


def calc_pf(t):
    if len(t) < 5:
        return 0
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return 9.99
    return w.sum() / abs(ls.sum())


print("=" * 100)
print("REGIME FILTER: RANGE DETECTION FOR MR STRATEGIES")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

print(f"\n{'Pair':<10} {'No Filter':<20} {'+ Regime Filter':<20} {'Improvement'}")
print("-" * 80)

results = []
total_no_filter = []
total_with_filter = []

for pair, cfg in PORTFOLIO.items():
    df = load_data(pair)
    if df is None:
        continue
    
    ind = compute_indicators(df)
    ind['pair'] = pair
    
    # Find MR entries (no regime filter)
    entries_no_filter = []
    for i in range(100, len(ind['close']) - cfg['bars']):
        if ind['rsi'][i] < cfg['rsi'] and ind['bb_pct'][i] < cfg['bb'] and ind['vol_ratio'][i] > cfg['vol']:
            entries_no_filter.append(i)
    
    # Find MR entries (with regime filter)
    entries_with_filter = []
    for i in range(100, len(ind['close']) - cfg['bars']):
        if ind['rsi'][i] < cfg['rsi'] and ind['bb_pct'][i] < cfg['bb'] and ind['vol_ratio'][i] > cfg['vol']:
            if is_favorable_regime(ind, i):
                entries_with_filter.append(i)
    
    # Backtest both
    trades_no_filter = backtest(entries_no_filter, ind, cfg)
    trades_with_filter = backtest(entries_with_filter, ind, cfg)
    
    pf_no_filter = calc_pf(trades_no_filter)
    pf_with_filter = calc_pf(trades_with_filter)
    
    n_no = len(trades_no_filter)
    n_with = len(trades_with_filter)
    
    improvement = ""
    if pf_with_filter > pf_no_filter:
        improvement = f"\033[92m+{((pf_with_filter/pf_no_filter - 1) * 100):.0f}%\033[0m"
    elif pf_with_filter < pf_no_filter:
        improvement = f"\033[91m-{((1 - pf_with_filter/pf_no_filter) * 100):.0f}%\033[0m"
    else:
        improvement = "0%"
    
    print(f"{pair:<10} PF={pf_no_filter:.2f} (n={n_no}){'':<4} PF={pf_with_filter:.2f} (n={n_with}){'':<4} {improvement}")
    
    if n_no >= 5:
        total_no_filter.extend(trades_no_filter)
    if n_with >= 5:
        total_with_filter.extend(trades_with_filter)
    
    results.append({
        'pair': pair,
        'pf_no_filter': pf_no_filter,
        'pf_with_filter': pf_with_filter,
        'n_no': n_no,
        'n_with': n_with,
        'filter_rate': (1 - n_with/n_no) * 100 if n_no > 0 else 0
    })

# Portfolio summary
total_no = np.array(total_no_filter) if total_no_filter else np.array([])
total_with = np.array(total_with_filter) if total_with_filter else np.array([])

print(f"\n{'=' * 100}")
print("PORTFOLIO SUMMARY")
print("=" * 100)

if len(total_no) > 0 and len(total_with) > 0:
    print(f"\n{'Metric':<25} {'No Filter':<15} {'With Filter':<15} {'Change'}")
    print("-" * 70)
    
    pf_no = calc_pf(total_no)
    pf_with = calc_pf(total_with)
    
    exp_no = total_no.mean() * 100
    exp_with = total_with.mean() * 100
    
    wr_no = (total_no > 0).sum() / len(total_no) * 100
    wr_with = (total_with > 0).sum() / len(total_with) * 100
    
    print(f"{'Total trades':<25} {len(total_no):<15} {len(total_with):<15} {len(total_with)-len(total_no)}")
    print(f"{'Profit Factor':<25} {pf_no:<15.2f} {pf_with:<15.2f} {((pf_with/pf_no-1)*100):+.1f}%")
    print(f"{'Expectancy %':<25} {exp_no:<15.3f} {exp_with:<15.3f} {exp_with-exp_no:+.3f}")
    print(f"{'Win Rate %':<25} {wr_no:<15.1f} {wr_with:<15.1f} {wr_with-wr_no:+.1f}%")
    
    avg_filter_rate = np.mean([r['filter_rate'] for r in results])
    print(f"\nAverage trades filtered out: {avg_filter_rate:.1f}%")
    print("(Trades skipped because regime was trending, not ranging)")
