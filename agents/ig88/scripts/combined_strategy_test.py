"""
Combined Strategy Test
=======================
Tests if Keltner Reversion adds value to existing MR portfolio.
Are the signals different enough to provide diversification?
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Our validated MR pairs
MR_PAIRS = {
    'ARB':  {'rsi': 20, 'bb': 2.0, 'vol': 1.5, 'stop': 0.75, 'target': 2.5},
    'ATOM': {'rsi': 20, 'bb': 2.0, 'vol': 1.5, 'stop': 0.75, 'target': 2.5},
    'AVAX': {'rsi': 20, 'bb': 2.0, 'vol': 1.5, 'stop': 0.75, 'target': 2.5},
    'AAVE': {'rsi': 20, 'bb': 2.0, 'vol': 1.5, 'stop': 0.75, 'target': 2.5},
    'SUI':  {'rsi': 20, 'bb': 2.0, 'vol': 1.5, 'stop': 0.75, 'target': 2.5},
}

# Validated Keltner pairs
KELTNER_PAIRS = {
    'AVAX': {'rsi': 25, 'vol': 1.5, 'stop': 0.75, 'target': 2.5},
    'LINK': {'rsi': 25, 'vol': 1.5, 'stop': 0.75, 'target': 2.5},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


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
    
    kelt_mid = df['close'].ewm(span=20, adjust=False).mean().values
    kelt_lower = kelt_mid - atr * 2
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, o, h, l, rsi, bb_lower, kelt_lower, atr, vol_ratio


def run_mr_trades(c, o, h, l, rsi, bb_lower, atr, vol_ratio, params):
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        if rsi[i] < params['rsi'] and c[i] < bb_lower[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + 2
            if entry_bar >= len(c) - 15:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop']
            target_price = entry_price + atr[entry_bar] * params['target']
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    return trades


def run_keltner_trades(c, o, h, l, rsi, kelt_lower, atr, vol_ratio, params):
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(kelt_lower[i]) or np.isnan(rsi[i]) or np.isnan(atr[i]):
            continue
        if c[i] < kelt_lower[i] and rsi[i] < params['rsi'] and vol_ratio[i] > params['vol']:
            entry_bar = i + 2
            if entry_bar >= len(c) - 15:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop']
            target_price = entry_price + atr[entry_bar] * params['target']
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    return trades


def calc_stats(t):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = np.array([x for x in t if x > 0])
    ls = np.array([x for x in t if x <= 0])
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(pf, 2), 'exp': round(np.mean(t)*100, 3), 'wr': round(len(w)/len(t)*100, 1)}


print("=" * 100)
print("COMBINED STRATEGY TEST: MR + Keltner Reversion")
print("=" * 100)

# Test correlation of signals
print("\nSIGNAL CORRELATION ANALYSIS:")
print("(Do MR and Keltner trigger at different times?)")

for pair in ['AVAX']:  # Only pair with both strategies
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, kelt_lower, atr, vol_ratio = compute_indicators(df)
    
    mr_signals = []
    keltner_signals = []
    
    for i in range(100, len(c) - 15):
        mr_sig = rsi[i] < 20 and c[i] < bb_lower[i] and vol_ratio[i] > 1.5
        kelt_sig = c[i] < kelt_lower[i] and rsi[i] < 25 and vol_ratio[i] > 1.5
        mr_signals.append(mr_sig)
        keltner_signals.append(kelt_sig)
    
    mr_signals = np.array(mr_signals)
    keltner_signals = np.array(keltner_signals)
    
    both = (mr_signals & keltner_signals).sum()
    mr_only = (mr_signals & ~keltner_signals).sum()
    kelt_only = (~mr_signals & keltner_signals).sum()
    neither = (~mr_signals & ~keltner_signals).sum()
    
    print(f"\n{pair}:")
    print(f"  MR signals: {mr_signals.sum()}")
    print(f"  Keltner signals: {keltner_signals.sum()}")
    print(f"  Both: {both}")
    print(f"  MR only: {mr_only}")
    print(f"  Keltner only: {kelt_only}")
    print(f"  Overlap: {both/max(mr_signals.sum(), 1)*100:.1f}%")

# Test combined portfolio
print(f"\n{'=' * 100}")
print("COMBINED PORTFOLIO PERFORMANCE")
print(f"{'=' * 100}")

mr_trades = []
keltner_trades = []
combined_trades = []

# MR trades
for pair, params in MR_PAIRS.items():
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, kelt_lower, atr, vol_ratio = compute_indicators(df)
    trades = run_mr_trades(c, o, h, l, rsi, bb_lower, atr, vol_ratio, params)
    mr_trades.extend(trades)
    combined_trades.extend(trades)
    stats = calc_stats(trades)
    print(f"MR   {pair:<8} N={stats['n']:<4} Exp={stats['exp']:>6.2f}%  PF={stats['pf']}")

print()

# Keltner trades
for pair, params in KELTNER_PAIRS.items():
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, kelt_lower, atr, vol_ratio = compute_indicators(df)
    trades = run_keltner_trades(c, o, h, l, rsi, kelt_lower, atr, vol_ratio, params)
    keltner_trades.extend(trades)
    combined_trades.extend(trades)
    stats = calc_stats(trades)
    print(f"KELT {pair:<8} N={stats['n']:<4} Exp={stats['exp']:>6.2f}%  PF={stats['pf']}")

print(f"\n{'=' * 100}")
print("PORTFOLIO COMPARISON")
print(f"{'=' * 100}")

mr_stats = calc_stats(mr_trades)
kelt_stats = calc_stats(keltner_trades)
comb_stats = calc_stats(combined_trades)

print(f"\n{'Strategy':<15} {'N':<8} {'Exp%':<10} {'PF':<8} {'WR%':<8}")
print("-" * 50)
print(f"{'MR Only':<15} {mr_stats['n']:<8} {mr_stats['exp']:>7.3f}%  {mr_stats['pf']:<8} {mr_stats['wr']:<8}")
print(f"{'Keltner Only':<15} {kelt_stats['n']:<8} {kelt_stats['exp']:>7.3f}%  {kelt_stats['pf']:<8} {kelt_stats['wr']:<8}")
print(f"{'Combined':<15} {comb_stats['n']:<8} {comb_stats['exp']:>7.3f}%  {comb_stats['pf']:<8} {comb_stats['wr']:<8}")

# Monte Carlo comparison
print(f"\n{'=' * 100}")
print("MONTE CARLO COMPARISON (12 months)")
print(f"{'=' * 100}")

np.random.seed(42)
n_sim = 10000

for name, trades in [('MR Only', mr_trades), ('Keltner Only', keltner_trades), ('Combined', combined_trades)]:
    if len(trades) == 0:
        continue
    arr = np.array(trades)
    returns = []
    for _ in range(n_sim):
        sampled = np.random.choice(arr, size=int(len(arr) * 0.7), replace=True)
        returns.append(sampled.sum())
    returns = np.array(returns)
    
    print(f"\n{name} ({len(arr)} trades, ~{len(arr)/12:.1f}/month):")
    print(f"  Mean: {returns.mean()*100:.1f}%")
    print(f"  Prob > 0: {(returns > 0).mean()*100:.1f}%")
    print(f"  Prob > 50%: {(returns > 0.5).mean()*100:.1f}%")
