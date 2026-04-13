"""
Final Portfolio: 12-Pair MR Strategy (Simplified)
==================================================
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PORTFOLIO = {
    'ARB':   {'rsi': 18, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 2.5, 'tier': 'STRONG'},
    'AVAX':  {'rsi': 20, 'bb': 0.15, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 2.5, 'tier': 'STRONG'},
    'UNI':   {'rsi': 22, 'bb': 0.10, 'vol': 1.8, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 2.0, 'tier': 'STRONG'},
    'SUI':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25, 'size': 2.0, 'tier': 'STRONG'},
    'MATIC': {'rsi': 25, 'bb': 0.15, 'vol': 1.8, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 2.0, 'tier': 'STRONG'},
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'LINK':  {'rsi': 18, 'bb': 0.05, 'vol': 1.8, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'AAVE':  {'rsi': 22, 'bb': 0.15, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 1.0, 'tier': 'WEAK'},
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25, 'size': 1.0, 'tier': 'WEAK'},
    'ALGO':  {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 1.0, 'tier': 'WEAK'},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def get_trades(pair, cfg):
    df = load_data(pair)
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


print("=" * 110)
print("FINAL PORTFOLIO: 12-Pair MR Strategy")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 110)

all_trades = []

print(f"\n{'Pair':<10} {'Tier':<8} {'Size':<8} {'N':<6} {'PF':<8} {'Exp%':<10} {'WR%'}")
print("-" * 60)

for pair, cfg in PORTFOLIO.items():
    trades = get_trades(pair, cfg)
    
    if len(trades) > 0:
        w = trades[trades > 0]
        ls = trades[trades <= 0]
        pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99
        exp = trades.mean() * 100
        wr = (trades > 0).sum() / len(trades) * 100
        
        all_trades.extend(trades.tolist())
        print(f"{pair:<10} {cfg['tier']:<8} {cfg['size']:<8.1f} {len(trades):<6} {pf:<8.2f} {exp:<10.2f} {wr:.1f}%")

# Portfolio totals
all_trades = np.array(all_trades)
w = all_trades[all_trades > 0]
ls = all_trades[all_trades <= 0]
pf_total = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99

print(f"\n{'=' * 110}")
print("PORTFOLIO TOTALS")
print(f"Total trades: {len(all_trades)}")
print(f"Portfolio PF: {pf_total:.2f}")
print(f"Average expectancy: {all_trades.mean()*100:.3f}%")
print(f"Win rate: {(all_trades > 0).sum() / len(all_trades) * 100:.1f}%")

# Save config
config_file = Path('/Users/nesbitt/dev/factory/agents/ig88/config/portfolio_v3.json')
config_file.parent.mkdir(parents=True, exist_ok=True)
with open(config_file, 'w') as f:
    json.dump(PORTFOLIO, f, indent=2)
print(f"\nConfig saved: {config_file}")
