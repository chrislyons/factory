"""
Test Weak Pairs on 1h Timeframe
=================================
More bars = more signals = better validation.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

WEAK_PAIRS = ['INJ', 'LINK', 'AAVE', 'ADA', 'ATOM', 'ALGO', 'LTC', 'DOT', 'SOL', 'OP']


def load_1h(pair):
    try:
        return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_60m.parquet')
    except:
        return None


def load_4h(pair):
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
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio


def get_trades(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg, bars_per_candle):
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
        
        # Scale ATR by bars_per_candle (4h has ~4x the range of 1h)
        atr_scaled = atr[entry_bar] * bars_per_candle
        
        stop_price = entry_price - atr_scaled * cfg['stop']
        target_price = entry_price + atr_scaled * cfg['target']
        
        for j in range(1, cfg['bars'] + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            if l[bar] <= stop_price:
                trades.append(-atr_scaled * cfg['stop'] / entry_price - FRICTION)
                break
            if h[bar] >= target_price:
                trades.append(atr_scaled * cfg['target'] / entry_price - FRICTION)
                break
        else:
            exit_price = c[min(entry_bar + cfg['bars'], len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades)


# Configs from portfolio
CONFIGS = {
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.25, 'target': 2.50},
    'LINK':  {'rsi': 18, 'bb': 0.05, 'vol': 1.8, 'stop': 1.00, 'target': 2.50},
    'AAVE':  {'rsi': 22, 'bb': 0.15, 'vol': 1.5, 'stop': 0.75, 'target': 2.00},
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 2.50},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00},
    'ALGO':  {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 0.75, 'target': 2.00},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 2.50},
}


print("=" * 100)
print("TEST WEAK PAIRS ON 1h TIMEFRAME")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

print(f"\n{'Pair':<10} {'4h N':<8} {'4h PF':<8} {'1h N':<8} {'1h PF':<8} {'Combined'}")
print("-" * 60)

for pair, cfg in CONFIGS.items():
    cfg_4h = cfg.copy()
    cfg_4h['bars'] = 20  # 20 * 4h = 80h
    
    # 4h data
    df_4h = load_4h(pair)
    if df_4h is not None:
        c4, h4, l4, rsi4, bb4, atr4, vol4 = compute_indicators(df_4h)
        trades_4h = get_trades(c4, h4, l4, rsi4, bb4, atr4, vol4, cfg_4h, 1)
        n_4h = len(trades_4h)
        if n_4h > 0:
            w = trades_4h[trades_4h > 0]
            ls = trades_4h[trades_4h <= 0]
            pf_4h = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99
        else:
            pf_4h = 0
    else:
        n_4h = 0
        pf_4h = 0
    
    # 1h data (scale targets by 4x for similar ATR%)
    df_1h = load_1h(pair)
    if df_1h is not None and len(df_1h) > 500:
        c1, h1, l1, rsi1, bb1, atr1, vol1 = compute_indicators(df_1h)
        
        # Adjust config for 1h: bars * 4, stop/target same (ATR already scaled)
        cfg_1h = cfg.copy()
        cfg_1h['bars'] = 80  # 80 * 1h = 80h (same as 20 * 4h)
        
        trades_1h = get_trades(c1, h1, l1, rsi1, bb1, atr1, vol1, cfg_1h, 4)
        n_1h = len(trades_1h)
        
        if n_1h > 0:
            w = trades_1h[trades_1h > 0]
            ls = trades_1h[trades_1h <= 0]
            pf_1h = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99
        else:
            pf_1h = 0
    else:
        n_1h = 0
        pf_1h = 0
        trades_1h = np.array([])
    
    # Combined
    all_trades = np.concatenate([trades_4h, trades_1h]) if n_1h > 0 else trades_4h
    if len(all_trades) > 0:
        w = all_trades[all_trades > 0]
        ls = all_trades[all_trades <= 0]
        pf_combined = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99
    else:
        pf_combined = 0
    
    print(f"{pair:<10} {n_4h:<8} {pf_4h:<8.2f} {n_1h:<8} {pf_1h:<8.2f} N={len(all_trades)} PF={pf_combined:.2f}")

print("\nKEY INSIGHT: 1h data provides more samples for validation")
print("But 1h signals are NOISIER - higher friction impact")
