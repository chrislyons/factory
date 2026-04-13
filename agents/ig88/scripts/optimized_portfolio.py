"""
Optimized Portfolio: Pair-Specific Session Filters
===================================================
Apply ASIA filter only where it improves expectancy.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02


def get_session(hour):
    if 0 <= hour < 8: return 'ASIA'
    elif 8 <= hour < 13: return 'LONDON'
    elif 13 <= hour < 16: return 'LONDON_NY'
    elif 16 <= hour < 21: return 'NY'
    else: return 'OFF_HOURS'


def load_data(pair):
    df = pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')
    if isinstance(df.index, pd.DatetimeIndex):
        df['session'] = df.index.hour.map(get_session)
    else:
        df = df.reset_index()
        df['session'] = [(i * 4) % 24 for i in range(len(df))]
        df['session'] = df['session'].map(get_session)
    return df


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    session = df['session'].values
    
    return c, o, h, l, rsi, bb_lower, atr, vol_ratio, session


def run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, filter_session=None):
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        if filter_session and session[i] not in filter_session:
            continue
        if rsi[i] < 20 and c[i] < bb_lower[i] and vol_ratio[i] > 1.5:
            entry_bar = i + 2
            if entry_bar >= len(c) - 15:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * 0.75
            target_price = entry_price + atr[entry_bar] * 2.5
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l): break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * 0.75 / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * 2.5 / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    return np.array(trades)


def calc_stats(t):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


print("=" * 120)
print("OPTIMIZED PORTFOLIO: Pair-Specific Session Filters")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

# Test pairs with their optimal session
candidates = ['ARB', 'ATOM', 'AVAX', 'AAVE', 'SUI', 'LINK', 'BTC', 'INJ', 'OP', 'POL']

# Find optimal session per pair
print("\nFINDING OPTIMAL SESSION PER PAIR:")
print(f"\n{'Pair':<10} {'ALL':<15} {'ASIA':<15} {'ASIA+NY':<15} {'Best Filter'}")
print("-" * 70)

pair_configs = {}

for pair in candidates:
    try:
        df = load_data(pair)
    except:
        continue
    
    c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
    
    # Test different filters
    filters = {
        'ALL': None,
        'ASIA': ['ASIA'],
        'ASIA+NY': ['ASIA', 'NY'],
        'NY': ['NY'],
    }
    
    best_filter = None
    best_score = -999
    
    results = {}
    for name, f in filters.items():
        trades = run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, f)
        if len(trades) >= 5:
            stats = calc_stats(trades)
            # Score = expectancy * log(trades) to balance quality vs quantity
            score = stats['exp'] * np.log(max(1, stats['n']))
            results[name] = (stats, score)
            if score > best_score:
                best_score = score
                best_filter = name
    
    # Display
    row = f"{pair:<10}"
    for name in ['ALL', 'ASIA', 'ASIA+NY']:
        if name in results:
            s = results[name][0]
            row += f"N={s['n']:<2} {s['exp']:>5.2f}%  "
        else:
            row += f"{'N/A':<12}"
    row += f"  {best_filter}"
    print(row)
    
    pair_configs[pair] = best_filter

# Build optimized portfolio
print(f"\n{'=' * 120}")
print("OPTIMIZED PORTFOLIO")
print(f"{'=' * 120}")

all_trades = []
print(f"\n{'Pair':<10} {'Filter':<12} {'N':<8} {'Exp%':<10} {'PF':<8} {'WR%'}")
print("-" * 55)

for pair, filter_name in pair_configs.items():
    try:
        df = load_data(pair)
    except:
        continue
    
    c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
    filter_val = None if filter_name == 'ALL' else [filter_name] if filter_name != 'ASIA+NY' else ['ASIA', 'NY']
    
    trades = run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, filter_val)
    stats = calc_stats(trades)
    
    if stats['n'] >= 5:
        all_trades.extend(trades.tolist())
        print(f"{pair:<10} {filter_name:<12} {stats['n']:<8} {stats['exp']:>7.3f}%  {stats['pf']:<8.2f} {stats['wr']}")

# Portfolio totals
all_trades = np.array(all_trades)
if len(all_trades) >= 5:
    w = all_trades[all_trades > 0]
    ls = all_trades[all_trades <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 else 999
    
    print(f"\n{'=' * 120}")
    print("PORTFOLIO TOTALS")
    print(f"{'=' * 120}")
    print(f"Total trades: {len(all_trades)}")
    print(f"Expectancy: {all_trades.mean()*100:.3f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Win Rate: {(all_trades > 0).mean()*100:.1f}%")
    print(f"Avg Win: {w.mean()*100:.2f}%")
    print(f"Avg Loss: {abs(ls.mean())*100:.2f}%")
    
    # Monte Carlo
    np.random.seed(42)
    mc = []
    trades_per_month = len(all_trades) / 12
    for _ in range(10000):
        n_trades = max(5, int(trades_per_month * 12))
        sampled = np.random.choice(all_trades, size=n_trades, replace=True)
        mc.append(sampled.sum())
    mc = np.array(mc)
    
    print(f"\nMonte Carlo (12mo, ~{trades_per_month:.1f} trades/month):")
    print(f"  Mean: {mc.mean()*100:.1f}%")
    print(f"  Median: {np.median(mc)*100:.1f}%")
    print(f"  5th pctl: {np.percentile(mc, 5)*100:.1f}%")
    print(f"  Prob > 0: {(mc > 0).mean()*100:.1f}%")
    print(f"  Prob > 50%: {(mc > 0.5).mean()*100:.1f}%")
    print(f"  Prob > 100%: {(mc > 1.0).mean()*100:.1f}%")
