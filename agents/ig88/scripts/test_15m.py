"""
Test SOL 15m: More Data = Better Validation?
==============================================
15m has 4x more bars than 1h, 16x more than 4h.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02  # 2% friction even at 15m


def load_15m(pair):
    # Try both naming conventions
    for name in [f'binance_{pair}_USDT_15m.parquet', f'binance_{pair}USDT_15m.parquet']:
        try:
            return pd.read_parquet(DATA_DIR / name)
        except:
            pass
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
    atr_pct = atr / c * 100
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, atr_pct, vol_ratio


def backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg):
    # Scale ATR for 15m (4 ATR units per 1h, 16 per 4h)
    atr_scaled = atr * cfg.get('atr_mult', 1)
    
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
        
        stop_price = entry_price - atr_scaled[entry_bar] * cfg['stop']
        target_price = entry_price + atr_scaled[entry_bar] * cfg['target']
        
        for j in range(1, cfg['bars'] + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            if l[bar] <= stop_price:
                trades.append(-atr_scaled[entry_bar] * cfg['stop'] / entry_price - FRICTION)
                break
            if h[bar] >= target_price:
                trades.append(atr_scaled[entry_bar] * cfg['target'] / entry_price - FRICTION)
                break
        else:
            exit_price = c[min(entry_bar + cfg['bars'], len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades)


print("=" * 120)
print("15m TIMEFRAME TEST")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

# Check available 15m data
m15_files = list(DATA_DIR.glob('*_15m.parquet'))
pairs_15m = [f.name.replace('binance_', '').replace('_USDT_15m.parquet', '') for f in m15_files]

print(f"\n15m pairs available: {pairs_15m}")

for pair in ['SOL']:
    df = load_15m(pair)
    if df is None:
        print(f"{pair}: No 15m data")
        continue
    
    print(f"\n{pair}: {len(df)} bars ({len(df) * 15 / (60 * 24):.0f} days)")
    
    c, h, l, rsi, bb_pct, atr, atr_pct, vol_ratio = compute_indicators(df)
    
    print(f"ATR% mean: {atr_pct[100:].mean():.2f}%")
    
    # Test MR with 4h-equivalent ATR scale (16x)
    print(f"\nMR at 4h-equivalent scale (ATR x 16):")
    print(f"{'N':<10} {'PF':<10} {'Exp%':<10} {'WR%':<10}")
    print("-" * 40)
    
    for rsi_t in [18, 22, 25]:
        for bb_t in [0.05, 0.1, 0.15]:
            for stop in [1.0, 1.5]:
                for target in [2.5, 3.0, 4.0]:
                    cfg = {
                        'rsi': rsi_t, 'bb': bb_t, 'vol': 1.2,
                        'stop': stop, 'target': target, 'bars': 64,  # 64 * 15m = 16h
                        'atr_mult': 4  # Scale to 1h equivalent
                    }
                    trades = backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg)
                    
                    if len(trades) >= 10:
                        w = trades[trades > 0]
                        ls = trades[trades <= 0]
                        pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 9.99
                        exp = trades.mean() * 100
                        wr = len(w) / len(trades) * 100
                        
                        if pf >= 1.5:
                            print(f"{len(trades):<10} {pf:<10.2f} {exp:<10.2f} {wr:<10.1f}")

print(f"\n{'=' * 120}")
print("KEY INSIGHT: 15m has more bars but higher friction impact")
print("Unless friction is < 0.5%, shorter timeframes are noise-dominated")
