"""
Test DOGE: Can Optimized R:R Make It Viable?
=============================================
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


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


def backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg):
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


def calc_pf(t):
    if len(t) < 5:
        return 0
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return 9.99
    return w.sum() / abs(ls.sum())


print("=" * 120)
print("DOGE R:R OPTIMIZATION")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

df = load_data('DOGE')
print(f"DOGE: {len(df)} bars")
c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)

print(f"\n{'RSI':<8} {'BB':<8} {'Vol':<8} {'Stop':<8} {'Target':<10} {'R:R':<8} {'Bars':<8} {'N':<8} {'PF':<10} {'Exp%':<10}")
print("-" * 100)

best = None

for rsi_t in [18, 20, 22, 25, 28, 30]:
    for bb_t in [0.05, 0.1, 0.15, 0.2]:
        for vol_t in [1.0, 1.2, 1.5]:
            for stop in [0.75, 1.0, 1.25]:
                for target in [2.0, 2.5, 3.0, 4.0]:
                    for bars in [15, 20, 25]:
                        cfg = {'rsi': rsi_t, 'bb': bb_t, 'vol': vol_t, 'stop': stop, 'target': target, 'bars': bars}
                        trades = backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg)
                        
                        if len(trades) < 8:
                            continue
                        
                        pf = calc_pf(trades)
                        
                        if pf >= 1.5:
                            exp = trades.mean() * 100
                            rr = target / stop
                            print(f"{rsi_t:<8} {bb_t:<8} {vol_t:<8} {stop:<8.2f} {target:<10.2f} 1:{rr:<5.0f} {bars:<8} {len(trades):<8} {pf:<10.2f} {exp:<10.2f}")
                            
                            if best is None or pf > best['pf']:
                                best = {**cfg, 'n': len(trades), 'pf': pf, 'exp': exp}

print(f"\n{'=' * 120}")
if best:
    print(f"BEST CONFIG: RSI<{best['rsi']}, BB<{best['bb']}, Vol>{best['vol']}, S={best['stop']}, T={best['target']}")
    print(f"N={best['n']}, PF={best['pf']:.2f}, Exp={best['exp']:.2f}%")
    print(f"\nNote: Need n >= 10 for statistical validity. DOGE on 4h is borderline.")
else:
    print("NO VIABLE CONFIG FOUND (n >= 8, PF >= 1.5)")
    print("\nDOGE edge is weak even with optimization.")
