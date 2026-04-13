"""
ARB 2026 Degradation Investigation
====================================
Is ARB's edge degrading in 2026? 
Or is it just noise from small sample size?
"""
import numpy as np
import pandas as pd
from pathlib import Path

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
    if not isinstance(df.index, pd.DatetimeIndex):
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


def run_mr_detailed(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, filter_session=None):
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
                    trades.append({
                        'date': i,
                        'pnl': -atr[entry_bar] * 0.75 / entry_price - FRICTION,
                        'exit': 'stop',
                        'rsi': rsi[i],
                        'atr_pct': atr[entry_bar] / entry_price * 100,
                    })
                    break
                if h[bar] >= target_price:
                    trades.append({
                        'date': i,
                        'pnl': atr[entry_bar] * 2.5 / entry_price - FRICTION,
                        'exit': 'target',
                        'rsi': rsi[i],
                        'atr_pct': atr[entry_bar] / entry_price * 100,
                    })
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append({
                    'date': i,
                    'pnl': (exit_price - entry_price) / entry_price - FRICTION,
                    'exit': 'time',
                    'rsi': rsi[i],
                    'atr_pct': atr[entry_bar] / entry_price * 100,
                })
    return trades


print("=" * 120)
print("ARB 2026 DEGRADATION INVESTIGATION")
print("=" * 120)

df = load_data('ARB')
c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)

# Get all trades with timestamps
trades = run_mr_detailed(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, ['ASIA', 'NY'])

# Convert bar indices to approximate dates (4h bars from start)
# ARB data starts around 2021 based on 5000 bars * 4h = 833 days
base_year = 2023  # Approximate

print(f"\nALL TRADES (Chronological):")
print(f"{'#':<4} {'Bar':<8} {'PnL%':<10} {'Exit':<8} {'RSI':<8} {'ATR%'}")
print("-" * 50)

for i, t in enumerate(trades):
    bar = t['date']
    approx_date = base_year + (bar * 4) / (365 * 24)
    print(f"{i+1:<4} {bar:<8} {t['pnl']*100:>+7.2f}%  {t['exit']:<8} {t['rsi']:<7.1f} {t['atr_pct']:.2f}")

# Rolling window analysis
print(f"\n{'=' * 120}")
print("ROLLING 5-TRADE WINDOW ANALYSIS")
print(f"{'=' * 120}")

results = np.array([t['pnl'] for t in trades])
print(f"\n{'Window End':<12} {'N':<6} {'Exp%':<10} {'PF':<8} {'WR%'}")
print("-" * 45)

for window in range(5, len(trades) + 1):
    window_results = results[window-5:window]
    w = window_results[window_results > 0]
    ls = window_results[window_results <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    wr = (window_results > 0).mean() * 100
    exp = window_results.mean() * 100
    bar = trades[window-1]['date']
    print(f"Trade {window:<4} {5:<6} {exp:>7.2f}%   {pf:<8.2f} {wr:.0f}%")

# Is 2026 degradation real?
print(f"\n{'=' * 120}")
print("2026 DEGRADATION ANALYSIS")
print(f"{'=' * 120}")

# Recent trades vs earlier trades
recent_idx = [i for i, t in enumerate(trades) if t['date'] > 4500]  # Recent ~2026
earlier_idx = [i for i, t in enumerate(trades) if t['date'] <= 4500]  # 2024-2025

print(f"\nRecent trades (bar > 4500, ~2026):")
if recent_idx:
    recent_results = results[recent_idx]
    w = recent_results[recent_results > 0]
    ls = recent_results[recent_results <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    print(f"  N: {len(recent_idx)}")
    print(f"  Exp: {recent_results.mean()*100:.2f}%")
    print(f"  PF: {pf:.2f}")
    print(f"  WR: {(recent_results > 0).mean()*100:.0f}%")
    
    print(f"\n  Trade details:")
    for i in recent_idx:
        print(f"    Bar {trades[i]['date']}: {trades[i]['pnl']*100:+.2f}% ({trades[i]['exit']})")

print(f"\nEarlier trades (bar <= 4500, ~2024-2025):")
if earlier_idx:
    earlier_results = results[earlier_idx]
    w = earlier_results[earlier_results > 0]
    ls = earlier_results[earlier_results <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    print(f"  N: {len(earlier_idx)}")
    print(f"  Exp: {earlier_results.mean()*100:.2f}%")
    print(f"  PF: {pf:.2f}")
    print(f"  WR: {(earlier_results > 0).mean()*100:.0f}%")

# Test if difference is statistically significant
print(f"\n{'=' * 120}")
print("SIGNIFICANCE TEST: Early vs Recent")
print(f"{'=' * 120}")

if recent_idx and earlier_idx:
    np.random.seed(42)
    n_perm = 10000
    
    early_mean = earlier_results.mean()
    recent_mean = recent_results.mean()
    diff = early_mean - recent_mean
    
    print(f"\nObserved difference: {diff*100:.3f}% (early - recent)")
    
    # Permutation test
    all_results = np.concatenate([earlier_results, recent_results])
    n_early = len(earlier_results)
    
    extreme_count = 0
    for _ in range(n_perm):
        np.random.shuffle(all_results)
        perm_early = all_results[:n_early]
        perm_recent = all_results[n_early:]
        perm_diff = perm_early.mean() - perm_recent.mean()
        if perm_diff >= diff:
            extreme_count += 1
    
    p_value = extreme_count / n_perm
    print(f"Permutation p-value: {p_value:.4f}")
    
    if p_value < 0.05:
        print("SIGNIFICANT: Early performance was better than recent")
    else:
        print("NOT SIGNIFICANT: Difference could be noise")

# Market context for 2026
print(f"\n{'=' * 120}")
print("MARKET CONTEXT: ARB in 2026")
print(f"{'=' * 120}")

# Check ARB's volatility and trend in 2026
df_2026 = df.iloc[-500:]  # Approximate 2026 data
c_2026 = df_2026['close'].values

returns = df_2026['close'].pct_change().dropna()
ema_20 = df_2026['close'].ewm(span=20).mean()
ema_50 = df_2026['close'].ewm(span=50).mean()

print(f"\n2026 Price Action (~500 bars):")
print(f"  Start: ${c_2026[0]:.4f}")
print(f"  End: ${c_2026[-1]:.4f}")
print(f"  Change: {(c_2026[-1]/c_2026[0]-1)*100:.1f}%")
print(f"  Volatility (4h): {returns.std()*100:.2f}%")
print(f"  Mean ATR: {atr[-500:].mean() / c_2026.mean() * 100:.2f}%")

# Compare to 2024-2025
df_early = df.iloc[500:4000]
returns_early = df_early['close'].pct_change().dropna()
atr_early = atr[500:4000]
c_early = df_early['close'].values

print(f"\n2024-2025 Price Action (~3500 bars):")
print(f"  Volatility (4h): {returns_early.std()*100:.2f}%")
print(f"  Mean ATR: {atr_early.mean() / c_early.mean() * 100:.2f}%")
