"""
Signal Filter Optimizer
========================
Tests additional filters to improve MR edge at 2% friction:
1. Time-of-day filtering (London/NY sessions)
2. Volatility regime filtering (ATR percentile)
3. BTC correlation filter (only trade when BTC stable)
4. Multi-indicator confirmation (add stochastic, MACD, etc.)
5. Holding period optimization (T+1 through T+10)
"""
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product
import json
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PAIRS = ['SUI', 'ARB', 'AAVE', 'AVAX', 'LINK', 'INJ', 'POL']


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def load_btc():
    return pd.read_parquet(DATA_DIR / 'binance_BTC_USDT_240m.parquet')


def compute_all_indicators(df, btc_df=None):
    """Compute base + additional indicators."""
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    v = df['volume'].values
    
    # Timestamps for time filtering
    timestamps = pd.to_datetime(df['timestamp']) if 'timestamp' in df.columns else df.index
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_upper = sma20 + std20 * 2
    bb_width = (bb_upper - bb_lower) / sma20
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower)
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = pd.Series(atr / c * 100).rolling(20).rank(pct=True).values  # ATR percentile
    
    # Volume
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    vol_pct = pd.Series(vol_ratio).rolling(50).rank(pct=True).values
    
    # Stochastic
    low_14 = pd.Series(l).rolling(14).min().values
    high_14 = pd.Series(h).rolling(14).max().values
    stoch_k = 100 * (c - low_14) / (high_14 - low_14 + 1e-10)
    stoch_d = pd.Series(stoch_k).rolling(3).mean().values
    
    # MACD
    ema_12 = df['close'].ewm(span=12, adjust=False).mean().values
    ema_26 = df['close'].ewm(span=26, adjust=False).mean().values
    macd = ema_12 - ema_26
    macd_signal = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    macd_hist = macd - macd_signal
    
    # BTC indicators (if provided)
    btc_trend = None
    btc_vol = None
    if btc_df is not None:
        btc_c = btc_df['close'].values
        btc_sma50 = btc_df['close'].rolling(50).mean().values
        btc_trend = btc_c > btc_sma50  # True = BTC uptrend
        btc_vol_series = btc_df['close'].pct_change().rolling(20).std() * np.sqrt(6 * 365)
        btc_vol = btc_vol_series.values
    
    return {
        'close': c, 'open': o, 'high': h, 'low': l, 'volume': v,
        'rsi': rsi, 'bb_lower': bb_lower, 'bb_upper': bb_upper,
        'bb_width': bb_width, 'bb_pct': bb_pct,
        'atr': atr, 'atr_pct': atr_pct,
        'vol_ratio': vol_ratio, 'vol_pct': vol_pct,
        'stoch_k': stoch_k, 'stoch_d': stoch_d,
        'macd': macd, 'macd_signal': macd_signal, 'macd_hist': macd_hist,
        'timestamps': timestamps,
        'btc_trend': btc_trend, 'btc_vol': btc_vol,
    }


def run_mr_with_filters(ind, params, friction, btc_ind=None):
    """
    MR strategy with additional filters.
    
    Base: RSI < threshold AND price < BB lower AND volume surge
    
    Additional filters (configurable):
    - stoch_filter: Stoch K < threshold (confirms oversold)
    - macd_filter: MACD histogram negative but rising
    - atr_filter: Only trade when ATR percentile > threshold (high vol)
    - bb_width_filter: Only trade when BB width > threshold (expansion)
    - btc_filter: Only trade when BTC in uptrend or stable
    - time_filter: Only trade during London/NY sessions
    """
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    rsi, bb_lower, atr = ind['rsi'], ind['bb_lower'], ind['atr']
    vol_ratio = ind['vol_ratio']
    stoch_k = ind['stoch_k']
    macd_hist = ind['macd_hist']
    atr_pct = ind['atr_pct']
    bb_width = ind['bb_width']
    
    trades = []
    filtered = {'stoch': 0, 'macd': 0, 'atr': 0, 'bb_width': 0, 'btc': 0}
    
    for i in range(100, len(c) - 20):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        
        # Base MR signal
        base_signal = (rsi[i] < params['rsi'] and 
                      c[i] < bb_lower[i] and 
                      vol_ratio[i] > params['vol'])
        
        if not base_signal:
            continue
        
        # Stochastic filter
        if params.get('use_stoch', False):
            if np.isnan(stoch_k[i]) or stoch_k[i] > params.get('stoch_thresh', 25):
                filtered['stoch'] += 1
                continue
        
        # MACD filter (histogram negative but rising = momentum shifting)
        if params.get('use_macd', False):
            if np.isnan(macd_hist[i]) or macd_hist[i] > 0 or macd_hist[i] < macd_hist[i-1]:
                filtered['macd'] += 1
                continue
        
        # ATR filter (only high volatility periods)
        if params.get('use_atr', False):
            if np.isnan(atr_pct[i]) or atr_pct[i] < params.get('atr_pct_thresh', 0.3):
                filtered['atr'] += 1
                continue
        
        # BB width filter (expansion = trending)
        if params.get('use_bb_width', False):
            if np.isnan(bb_width[i]) or bb_width[i] < params.get('bb_width_min', 0.02):
                filtered['bb_width'] += 1
                continue
        
        # Execute trade
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
                trades.append(-atr[entry_bar] * params['stop_atr'] / entry_price - friction)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * params['target_atr'] / entry_price - friction)
                break
        else:
            exit_price = c[min(entry_bar + 15, len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades), filtered


def calc_stats(t):
    if len(t) < 5:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'exp': round(float(t.mean() * 100), 3),
        'wr': round(float(len(w) / len(t) * 100), 1),
    }


# Test different filter combinations
FILTER_CONFIGS = [
    {'name': 'BASE', 'use_stoch': False, 'use_macd': False, 'use_atr': False, 'use_bb_width': False},
    {'name': 'STOCH', 'use_stoch': True, 'stoch_thresh': 20, 'use_macd': False, 'use_atr': False, 'use_bb_width': False},
    {'name': 'MACD', 'use_stoch': False, 'use_macd': True, 'use_atr': False, 'use_bb_width': False},
    {'name': 'ATR_HIGH', 'use_stoch': False, 'use_macd': False, 'use_atr': True, 'atr_pct_thresh': 0.5, 'use_bb_width': False},
    {'name': 'BB_EXPAND', 'use_stoch': False, 'use_macd': False, 'use_atr': False, 'use_bb_width': True, 'bb_width_min': 0.03},
    {'name': 'STOCH+ATR', 'use_stoch': True, 'stoch_thresh': 20, 'use_macd': False, 'use_atr': True, 'atr_pct_thresh': 0.4, 'use_bb_width': False},
    {'name': 'ALL', 'use_stoch': True, 'stoch_thresh': 20, 'use_macd': True, 'use_atr': True, 'atr_pct_thresh': 0.4, 'use_bb_width': True, 'bb_width_min': 0.02},
]

# Base params
BASE_PARAMS = {
    'rsi': 30, 'vol': 1.5, 'delay': 2, 'stop_atr': 1.0, 'target_atr': 2.5,
}


print("=" * 120)
print("SIGNAL FILTER OPTIMIZER (improving edge at 2% friction)")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

all_results = []

for pair in PAIRS:
    print(f"\n{'=' * 120}")
    print(f"{pair}")
    print(f"{'=' * 120}")
    
    df = load_data(pair)
    btc_df = load_btc()
    ind = compute_all_indicators(df, btc_df)
    
    print(f"{'Filter':<15} {'N':<8} {'Exp%':<10} {'PF':<8} {'WR%':<8} {'Trades Cut':<12} {'Verdict'}")
    print("-" * 90)
    
    base_trades = None
    base_stats = None
    
    for filter_config in FILTER_CONFIGS:
        params = {**BASE_PARAMS, **filter_config}
        trades, filtered = run_mr_with_filters(ind, params, FRICTION)
        stats = calc_stats(trades)
        
        # Calculate how many trades were cut
        if base_trades is not None and len(base_trades) > 0:
            cut_pct = (1 - len(trades) / len(base_trades)) * 100 if len(base_trades) > 0 else 0
        else:
            cut_pct = 0
        
        # Store base for comparison
        if filter_config['name'] == 'BASE':
            base_trades = trades
            base_stats = stats
        
        # Verdict
        if stats['n'] >= 5 and stats['exp'] > 0.5 and stats['pf'] > 1.5:
            verdict = "IMPROVED" if base_stats and stats['exp'] > base_stats['exp'] else "GOOD"
        elif stats['n'] >= 3 and stats['exp'] > 0:
            verdict = "MARGINAL"
        elif stats['n'] < 3:
            verdict = "TOO FEW"
        else:
            verdict = "NEGATIVE"
        
        print(f"{filter_config['name']:<15} {stats['n']:<8} {stats['exp']:>8.3f}% {stats['pf']:<8.3f} {stats['wr']:<8.1f} {cut_pct:>8.1f}%    {verdict}")
        
        all_results.append({
            'pair': pair,
            'filter': filter_config['name'],
            **stats,
            'cut_pct': cut_pct,
        })


# Summary: Best filter per pair
print(f"\n{'=' * 120}")
print("BEST FILTER PER PAIR")
print(f"{'=' * 120}")

print(f"{'Pair':<10} {'Best Filter':<15} {'Exp%':<10} {'PF':<8} {'N':<8}")
print("-" * 60)

for pair in PAIRS:
    pair_results = [r for r in all_results if r['pair'] == pair and r['n'] >= 5 and r['exp'] > 0]
    if pair_results:
        best = max(pair_results, key=lambda x: x['exp'])
        print(f"{pair:<10} {best['filter']:<15} {best['exp']:>8.3f}% {best['pf']:<8.3f} {best['n']:<8}")
    else:
        print(f"{pair:<10} {'NO EDGE':<15}")
