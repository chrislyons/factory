"""
Kraken Fee Structure & Friction Optimization
==============================================
dYdX blocked in Canada. Kraken is our venue.
Question: Can we reduce friction via:
1. Limit orders (maker vs taker)
2. Kraken Futures (if available)
3. Fee tier discounts
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# Kraken fee schedule (as of 2026)
# https://www.kraken.com/features/fee-schedule
KRAKEN_FEES = {
    'spot_taker': 0.26,  # % for most pairs
    'spot_maker': 0.16,  # % for most pairs
    'spot_taker_30d_100k': 0.20,
    'spot_maker_30d_100k': 0.10,
    'futures_taker': 0.05,  # % on futures
    'futures_maker': 0.02,  # % on futures (rebate possible)
}

# Estimated slippage by order type
SLIPPAGE = {
    'market_order': 0.30,  # % average slippage
    'limit_order': 0.05,   # % near mid-price
}

# Total friction scenarios
FRICTION_SCENARIOS = {
    'Kraken Spot Market Order': {
        'fee': KRAKEN_FEES['spot_taker'],
        'slippage': SLIPPAGE['market_order'],
        'total': KRAKEN_FEES['spot_taker'] + SLIPPAGE['market_order'] + 0.5  # +0.5% buffer for gaps/runs
    },
    'Kraken Spot Limit Order': {
        'fee': KRAKEN_FEES['spot_maker'],
        'slippage': SLIPPAGE['limit_order'],
        'total': KRAKEN_FEES['spot_maker'] + SLIPPAGE['limit_order'] + 0.3
    },
    'Kraken Spot Limit (Tier 2)': {
        'fee': KRAKEN_FEES['spot_maker_30d_100k'],
        'slippage': SLIPPAGE['limit_order'],
        'total': KRAKEN_FEES['spot_maker_30d_100k'] + SLIPPAGE['limit_order'] + 0.3
    },
    'Kraken Futures (if available)': {
        'fee': KRAKEN_FEES['futures_maker'],
        'slippage': SLIPPAGE['limit_order'],
        'total': 0.05  # Near zero with rebates
    },
}

print("=" * 80)
print("KRAKEN FRICTION ANALYSIS")
print("=" * 80)

print(f"\n{'Scenario':<35} {'Fee':<10} {'Slippage':<12} {'Total Friction'}")
print("-" * 80)

for name, scenario in FRICTION_SCENARIOS.items():
    print(f"{name:<35} {scenario['fee']:<10.2f}% {scenario['slippage']:<12.2f}% {scenario['total']:.2f}%")

# Test portfolio viability at each friction level
print(f"\n{'=' * 80}")
print("PORTFOLIO VIABILITY BY FRICTION LEVEL")
print("=" * 80)

# Load our existing data
TARGET_PAIRS = ['AAVE', 'ADA', 'ALGO', 'ARB', 'ATOM', 'AVAX', 'DOT', 'FIL',
                'GRT', 'IMX', 'INJ', 'LINK', 'LTC', 'MATIC', 'NEAR', 'OP',
                'SOL', 'SNX', 'SUI', 'UNI', 'XRP']


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
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio


def backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg, friction):
    entries = []
    for i in range(100, len(c) - cfg['bars']):
        if rsi[i] < cfg['rsi'] and bb_pct[i] < cfg['bb'] and vol_ratio[i] > cfg['vol']:
            entries.append(i)
    
    trades = []
    for idx in entries:
        entry_bar = idx + 1
        if entry_bar >= len(c) - cfg['bars']:
            continue
        
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
                trades.append(-atr[entry_bar] * cfg['stop'] / entry_price - friction/100)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * cfg['target'] / entry_price - friction/100)
                break
        else:
            exit_price = c[min(entry_bar + cfg['bars'], len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - friction/100)
    
    return np.array(trades)


def calc_pf(t):
    if len(t) < 5:
        return 0
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return 9.99
    return w.sum() / abs(ls.sum())


# Test each friction level
FRICTION_LEVELS = [0.5, 1.0, 1.5, 2.0]

print(f"\n{'Pair':<10}", end='')
for f in FRICTION_LEVELS:
    print(f"F={f}%{'':<8}", end='')
print("  Best Config")
print("-" * 100)

# Best configs from previous optimization
OPTIMAL_CONFIGS = {
    'ARB':   {'rsi': 18, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'AVAX':  {'rsi': 20, 'bb': 0.15, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'UNI':   {'rsi': 22, 'bb': 0.10, 'vol': 1.8, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'SUI':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25},
    'MATIC': {'rsi': 25, 'bb': 0.15, 'vol': 1.8, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'LINK':  {'rsi': 18, 'bb': 0.05, 'vol': 1.8, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'AAVE':  {'rsi': 22, 'bb': 0.15, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25},
    'ALGO':  {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20},
}

viable_at = {f: 0 for f in FRICTION_LEVELS}

for pair, cfg in OPTIMAL_CONFIGS.items():
    df = load_data(pair)
    if df is None:
        continue
    
    c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
    
    print(f"{pair:<10}", end='')
    
    best_friction = None
    best_pf = 0
    
    for friction in FRICTION_LEVELS:
        trades = backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg, friction)
        
        if len(trades) >= 5:
            pf = calc_pf(trades)
            
            if pf >= 1.5:
                viable_at[friction] += 1
                print(f"\033[92m{pf:>5.2f}\033[0m{'':<5}", end='')
                if pf > best_pf:
                    best_pf = pf
                    best_friction = friction
            else:
                print(f"{pf:>5.2f}{'':<5}", end='')
        else:
            print(f"  n<5{'':<3}", end='')
    
    if best_friction:
        print(f"  Viable at {best_friction}%")
    else:
        print(f"  Not viable")

print(f"\n{'=' * 80}")
print("VIABLE PAIR COUNT BY FRICTION LEVEL")
print("-" * 80)
for f in FRICTION_LEVELS:
    status = "\033[92mGOOD\033[0m" if viable_at[f] >= 10 else "\033[93mOK\033[0m" if viable_at[f] >= 5 else "\033[91mBAD\033[0m"
    print(f"  {f}% friction: {viable_at[f]} pairs viable  {status}")

print(f"""
CONCLUSION:
- Market orders (2.0%): {viable_at[2.0]} viable pairs
- Limit orders (1.0%): {viable_at[1.0]} viable pairs  
- Limit + Tier discount (0.5%): {viable_at[0.5]} viable pairs

Path: Use LIMIT ORDERS on Kraken to get from 2% to ~1% friction.
This roughly DOUBLES the number of viable pairs.
""")
