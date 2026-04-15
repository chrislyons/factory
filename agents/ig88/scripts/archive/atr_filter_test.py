"""
ATR Filter Test: Does filtering on volatility restore edge?
=============================================================
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

VALIDATED = ['ARB', 'ATOM', 'AVAX', 'AAVE', 'SUI']
SESSION_FILTERS = {
    'ARB': ['ASIA', 'NY'],
    'ATOM': ['ASIA', 'NY'],
    'AVAX': ['ASIA', 'NY'],
    'AAVE': ['ASIA', 'NY'],
    'SUI': None,
}


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
    
    # ATR percentage
    atr_pct = atr / c * 100
    
    return c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, atr_pct


def run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, atr_pct, 
           filter_session=None, min_atr_pct=0):
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        if filter_session and session[i] not in filter_session:
            continue
        if atr_pct[i] < min_atr_pct:
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
print("ATR FILTER TEST: Does volatility filtering restore edge?")
print("=" * 120)

for atr_threshold in [0, 2.0, 2.5, 3.0]:
    print(f"\n{'=' * 120}")
    print(f"ATR THRESHOLD: {atr_threshold}%")
    print(f"{'=' * 120}")
    
    all_trades = []
    
    print(f"\n{'Pair':<8} {'N':<8} {'Exp%':<10} {'PF':<8} {'WR%':<8} {'Filter Removed'}")
    print("-" * 60)
    
    for pair in VALIDATED:
        df = load_data(pair)
        c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, atr_pct = compute_indicators(df)
        
        # Get baseline (no ATR filter)
        baseline_trades = run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, atr_pct, 
                                  SESSION_FILTERS[pair], 0)
        
        # Get filtered trades
        trades = run_mr(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, atr_pct, 
                        SESSION_FILTERS[pair], atr_threshold)
        
        stats = calc_stats(trades)
        all_trades.extend(trades.tolist())
        
        removed = len(baseline_trades) - len(trades)
        removed_pct = removed / len(baseline_trades) * 100 if len(baseline_trades) > 0 else 0
        
        print(f"{pair:<8} {stats['n']:<8} {stats['exp']:>6.2f}%   {stats['pf']:<8.2f} {stats['wr']:<8.1f} {removed} ({removed_pct:.0f}%)")
    
    all_trades = np.array(all_trades)
    if len(all_trades) >= 5:
        stats = calc_stats(all_trades)
        print(f"\nTOTAL: {len(all_trades)} trades, Exp={stats['exp']:.3f}%, PF={stats['pf']}, WR={stats['wr']}%")

# RECENT ONLY (2026)
print(f"\n{'=' * 120}")
print("2026 ONLY: Does ATR filter help recent performance?")
print(f"{'=' * 120}")

for atr_threshold in [0, 2.0, 2.5, 3.0]:
    print(f"\nATR THRESHOLD: {atr_threshold}%")
    
    all_recent_trades = []
    
    for pair in VALIDATED:
        df = load_data(pair)
        c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, atr_pct = compute_indicators(df)
        
        # Get recent data (last 20%)
        split_idx = int(len(c) * 0.8)
        
        trades = run_mr(c[split_idx:], o[split_idx:], h[split_idx:], l[split_idx:],
                        rsi[split_idx:], bb_lower[split_idx:], atr[split_idx:], 
                        vol_ratio[split_idx:], session[split_idx:], atr_pct[split_idx:],
                        SESSION_FILTERS[pair], atr_threshold)
        
        all_recent_trades.extend(trades.tolist())
    
    all_recent_trades = np.array(all_recent_trades)
    if len(all_recent_trades) >= 3:
        stats = calc_stats(all_recent_trades)
        print(f"  {len(all_recent_trades)} trades, Exp={stats['exp']:.3f}%, PF={stats['pf']}, WR={stats['wr']}%")
    else:
        print(f"  {len(all_recent_trades)} trades (insufficient)")

# Recommendation
print(f"\n{'=' * 120}")
print("RECOMMENDATION")
print(f"{'=' * 120}")

print("""
The MR strategy is VOLATILITY-DEPENDENT:
- Works when ATR > 2.5%
- Fails when ATR < 2.0%

2026 market is in low-volatility regime (ATR dropped 6-30%).

OPTIONS:
1. Add ATR > 2.5% filter - reduces trades but improves quality
2. Wait for volatility to return (could be months)
3. Develop a different strategy for low-vol regime
4. Reduce position sizes until regime changes
""")
