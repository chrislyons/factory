"""
MFI Diversification Test
=========================
Does MFI provide signals uncorrelated with MR?
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Validated MFI pairs
MFI_PAIRS = ['SUI', 'AVAX', 'INJ', 'POL', 'SOL']

# Validated MR pairs (for overlap check)
MR_PAIRS = ['ARB', 'ATOM', 'AVAX', 'AAVE', 'SUI']


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    v = df['volume'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # BB
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    
    # MFI
    tp = (h + l + c) / 3
    tp_diff = np.diff(tp, prepend=tp[0])
    mf_pos = np.where(tp_diff > 0, tp * v, 0)
    mf_neg = np.where(tp_diff <= 0, tp * v, 0)
    mf_ratio = pd.Series(mf_pos).rolling(14).sum() / (pd.Series(mf_neg).rolling(14).sum() + 1e-10)
    mfi = (100 - (100 / (1 + mf_ratio))).values
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Vol
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    return c, o, h, l, rsi, bb_lower, mfi, atr, vol_ratio


def run_mr_trades(c, o, h, l, rsi, bb_lower, atr, vol_ratio):
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]): continue
        if rsi[i] < 20 and c[i] < bb_lower[i] and vol_ratio[i] > 1.5:
            entry_bar = i + 2
            if entry_bar >= len(c) - 15: continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * 0.75
            target_price = entry_price + atr[entry_bar] * 2.5
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l): break
                if l[bar] <= stop_price:
                    trades.append({'idx': i, 'ret': -atr[entry_bar] * 0.75 / entry_price - FRICTION})
                    break
                if h[bar] >= target_price:
                    trades.append({'idx': i, 'ret': atr[entry_bar] * 2.5 / entry_price - FRICTION})
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append({'idx': i, 'ret': (exit_price - entry_price) / entry_price - FRICTION})
    return trades


def run_mfi_trades(c, o, h, l, mfi, atr, vol_ratio):
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(mfi[i]): continue
        if mfi[i] < 20 and vol_ratio[i] > 1.5:
            entry_bar = i + 2
            if entry_bar >= len(c) - 15: continue
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * 0.75
            target_price = entry_price + atr[entry_bar] * 2.5
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l): break
                if l[bar] <= stop_price:
                    trades.append({'idx': i, 'ret': -atr[entry_bar] * 0.75 / entry_price - FRICTION})
                    break
                if h[bar] >= target_price:
                    trades.append({'idx': i, 'ret': atr[entry_bar] * 2.5 / entry_price - FRICTION})
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append({'idx': i, 'ret': (exit_price - entry_price) / entry_price - FRICTION})
    return trades


print("=" * 100)
print("MFI DIVERSIFICATION TEST: Are MFI signals different from MR?")
print("=" * 100)

for pair in ['SUI', 'AVAX']:  # Pairs with both strategies
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, mfi, atr, vol_ratio = compute_indicators(df)
    
    mr_trades = run_mr_trades(c, o, h, l, rsi, bb_lower, atr, vol_ratio)
    mfi_trades = run_mfi_trades(c, o, h, l, mfi, atr, vol_ratio)
    
    mr_indices = {t['idx'] for t in mr_trades}
    mfi_indices = {t['idx'] for t in mfi_trades}
    
    overlap = mr_indices & mfi_indices
    mr_only = mr_indices - mfi_indices
    mfi_only = mfi_indices - mr_indices
    
    print(f"\n{pair}:")
    print(f"  MR signals: {len(mr_indices)}")
    print(f"  MFI signals: {len(mfi_indices)}")
    print(f"  Overlap: {len(overlap)}")
    print(f"  MR only: {len(mr_only)}")
    print(f"  MFI only: {len(mfi_only)}")
    
    if len(mr_indices) > 0:
        print(f"  Overlap rate: {len(overlap)/len(mr_indices)*100:.1f}% of MR")
    if len(mfi_indices) > 0:
        print(f"  MFI-only rate: {len(mfi_only)/len(mfi_indices)*100:.1f}% of MFI")

# Test combined portfolio with MFI
print(f"\n{'=' * 100}")
print("COMBINED PORTFOLIO: MR (5 pairs) + MFI (5 pairs)")
print(f"{'=' * 100}")

# MR trades
mr_all = []
for pair in MR_PAIRS:
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, mfi, atr, vol_ratio = compute_indicators(df)
    trades = run_mr_trades(c, o, h, l, rsi, bb_lower, atr, vol_ratio)
    mr_all.extend([(pair, t['ret']) for t in trades])

# MFI trades
mfi_all = []
for pair in MFI_PAIRS:
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, mfi, atr, vol_ratio = compute_indicators(df)
    trades = run_mfi_trades(c, o, h, l, mfi, atr, vol_ratio)
    mfi_all.extend([(pair, t['ret']) for t in trades])

# Combined (excluding pairs already in MR)
mfi_unique = [(p, r) for p, r in mfi_all if p not in MR_PAIRS]
combined = [(p, r) for p, r in mr_all] + mfi_unique

mr_rets = [r for _, r in mr_all]
mfi_rets = [r for _, r in mfi_unique]
combined_rets = [r for _, r in combined]

def calc_stats(rets):
    if len(rets) < 3:
        return {'n': len(rets), 'pf': 0, 'exp': 0, 'wr': 0}
    t = np.array(rets)
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}

mr_stats = calc_stats(mr_rets)
mfi_stats = calc_stats(mfi_rets)
comb_stats = calc_stats(combined_rets)

print(f"\n{'Strategy':<20} {'N':<8} {'Exp%':<10} {'PF':<8} {'WR%'}")
print("-" * 50)
print(f"{'MR Only':<20} {mr_stats['n']:<8} {mr_stats['exp']:>7.3f}%  {mr_stats['pf']:<8} {mr_stats['wr']}")
print(f"{'MFI Only (unique)':<20} {mfi_stats['n']:<8} {mfi_stats['exp']:>7.3f}%  {mfi_stats['pf']:<8} {mfi_stats['wr']}")
print(f"{'Combined':<20} {comb_stats['n']:<8} {comb_stats['exp']:>7.3f}%  {comb_stats['pf']:<8} {comb_stats['wr']}")

# Monte Carlo
print(f"\n{'=' * 100}")
print("MONTE CARLO (12 months)")
print(f"{'=' * 100}")

np.random.seed(42)
n_sim = 10000

for name, rets in [('MR Only', mr_rets), ('MFI Only', mfi_rets), ('Combined', combined_rets)]:
    if len(rets) == 0:
        continue
    arr = np.array(rets)
    results = []
    for _ in range(n_sim):
        sampled = np.random.choice(arr, size=max(10, int(len(arr) * 0.7)), replace=True)
        results.append(sampled.sum())
    results = np.array(results)
    
    print(f"\n{name} ({len(arr)} trades, ~{len(arr)/12:.1f}/month):")
    print(f"  Mean: {results.mean()*100:.1f}%")
    print(f"  Prob > 0: {(results > 0).mean()*100:.1f}%")
    print(f"  Prob > 50%: {(results > 0.5).mean()*100:.1f}%")
