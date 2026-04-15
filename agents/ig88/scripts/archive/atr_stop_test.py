"""
ATR-Based Stop Test
====================
Compare fixed percentage stops vs ATR-based stops.
ATR adapts to volatility, potentially reducing false stops in high-vol periods.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0133  # Use real-world friction estimate

PAIRS = {
    'SOL':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'target': 0.10},
    'NEAR': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'target': 0.125},
    'LINK': {'rsi': 30, 'bb': 2.0, 'vol': 1.8, 'entry': 2, 'target': 0.15},
    'AVAX': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'target': 0.125},
    'ATOM': {'rsi': 30, 'bb': 1.5, 'vol': 1.5, 'entry': 2, 'target': 0.125},
    'UNI':  {'rsi': 40, 'bb': 1.5, 'vol': 2.0, 'entry': 2, 'target': 0.15},
    'AAVE': {'rsi': 35, 'bb': 1.5, 'vol': 1.5, 'entry': 2, 'target': 0.15},
    'ARB':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'target': 0.15},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3, 'entry': 2, 'target': 0.15},
    'INJ':  {'rsi': 30, 'bb': 1.0, 'vol': 1.5, 'entry': 2, 'target': 0.075},
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8, 'entry': 2, 'target': 0.15},
    'POL':  {'rsi': 35, 'bb': 1.0, 'vol': 1.3, 'entry': 2, 'target': 0.10},
}

# Stop configurations to test
STOP_CONFIGS = [
    ('Fixed 0.5%', lambda entry, atr: entry * 0.005),
    ('Fixed 0.75%', lambda entry, atr: entry * 0.0075),
    ('Fixed 1.0%', lambda entry, atr: entry * 0.01),
    ('ATR 0.5x', lambda entry, atr: atr * 0.5),
    ('ATR 0.75x', lambda entry, atr: atr * 0.75),
    ('ATR 1.0x', lambda entry, atr: atr * 1.0),
    ('ATR 1.5x', lambda entry, atr: atr * 1.5),
]


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    bb_l = sma20 - std20 * 1.5
    
    return c, df['open'].values, h, l, rsi, bb_l, vol_ratio, atr


def run_backtest(c, o, h, l, rsi, bb_l, vol_ratio, atr, stop_fn, target_pct):
    """Run backtest with specified stop function."""
    trades = []
    
    for i in range(100, len(c) - 17):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]) or np.isnan(atr[i]):
            continue
        
        if rsi[i] < 30 and c[i] < bb_l[i] and vol_ratio[i] > 1.5:
            entry_bar = i + 2
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_dist = stop_fn(entry_price, atr[entry_bar])
            stop_price = entry_price - stop_dist
            target_price = entry_price * (1 + target_pct)
            
            for j in range(1, 16):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-stop_dist/entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(target_pct - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades) if trades else np.array([])


def calc_stats(trades):
    if len(trades) < 10:
        return {'n': len(trades), 'pf': 0, 'wr': 0, 'exp': 0, 'sharpe': 0, 'total': 0}
    t = trades
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(t)*100), 1),
        'exp': round(float(t.mean()*100), 3),
        'sharpe': round(float(sharpe), 2),
        'total': round(float(t.sum() * 100), 2),
    }


print("=" * 100)
print("ATR-BASED STOP TEST (with REAL friction = 1.33%)")
print("=" * 100)
print(f"\nTesting {len(PAIRS)} pairs x {len(STOP_CONFIGS)} stop configs")
print()

results = {}

for pair, params in PAIRS.items():
    df = load_data(pair)
    c, o, h, l, rsi, bb_l, vol_ratio, atr = compute_indicators(df)
    
    results[pair] = {}
    
    print(f"\n{'─' * 80}")
    print(f"{pair}")
    print(f"{'─' * 80}")
    print(f"{'Config':<15} {'N':<6} {'PF':<8} {'WR':<8} {'Exp%':<10} {'Sharpe':<8} {'Total%'}")
    print("─" * 65)
    
    for config_name, stop_fn in STOP_CONFIGS:
        trades = run_backtest(c, o, h, l, rsi, bb_l, vol_ratio, atr, stop_fn, params['target'])
        stats = calc_stats(trades)
        results[pair][config_name] = stats
        
        print(f"{config_name:<15} {stats['n']:<6} {stats['pf']:<8.3f} {stats['wr']:<7.1f}% {stats['exp']:<9.3f}% {stats['sharpe']:<7.2f} {stats['total']:.2f}%")


# ============================================================================
# WINNER ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("OPTIMAL STOP CONFIG BY PAIR")
print("=" * 100)

print(f"\n{'Pair':<10}", end='')
for config_name, _ in STOP_CONFIGS:
    print(f"{config_name:<15}", end='')
print(f"{'Winner':<15}")
print("-" * 120)

winners = {config: 0 for config, _ in STOP_CONFIGS}

for pair in PAIRS:
    print(f"{pair:<10}", end='')
    
    best_exp = -999
    best_config = ''
    
    for config_name, _ in STOP_CONFIGS:
        exp = results[pair][config_name]['exp']
        print(f"{exp:>8.3f}%      ", end='')
        if exp > best_exp:
            best_exp = exp
            best_config = config_name
    
    winners[best_config] += 1
    print(f"{best_config}")

print(f"\nWinner distribution:")
for config_name, _ in STOP_CONFIGS:
    bar = "█" * (winners[config_name] * 3)
    print(f"  {config_name:<15}: {winners[config_name]} pairs {bar}")

# Fixed vs ATR comparison
fixed_wins = sum(winners[c] for c, _ in STOP_CONFIGS if 'Fixed' in c)
atr_wins = sum(winners[c] for c, _ in STOP_CONFIGS if 'ATR' in c)
print(f"\nFixed stops won: {fixed_wins} pairs")
print(f"ATR stops won: {atr_wins} pairs")
