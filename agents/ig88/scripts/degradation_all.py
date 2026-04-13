"""
Check Degradation Across All Validated Pairs
==============================================
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
    
    return c, o, h, l, rsi, bb_lower, atr, vol_ratio, session


def run_mr_with_indices(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, filter_session=None):
    """Return trades with their bar indices."""
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
                    trades.append({'idx': i, 'pnl': -atr[entry_bar] * 0.75 / entry_price - FRICTION})
                    break
                if h[bar] >= target_price:
                    trades.append({'idx': i, 'pnl': atr[entry_bar] * 2.5 / entry_price - FRICTION})
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append({'idx': i, 'pnl': (exit_price - entry_price) / entry_price - FRICTION})
    return trades


print("=" * 120)
print("DEGRADATION ANALYSIS: All Validated Pairs")
print("=" * 120)

print(f"\n{'Pair':<8} {'Early N':<10} {'Early Exp':<12} {'Early PF':<10} {'Recent N':<10} {'Recent Exp':<12} {'Recent PF':<10} {'Trend'}")
print("-" * 90)

for pair in VALIDATED:
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
    
    trades = run_mr_with_indices(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, SESSION_FILTERS[pair])
    
    if not trades:
        print(f"{pair:<8} No trades found")
        continue
    
    # Split at 80% mark (recent = last 20%)
    split_idx = int(len(c) * 0.8)
    
    early_trades = [t for t in trades if t['idx'] < split_idx]
    recent_trades = [t for t in trades if t['idx'] >= split_idx]
    
    # Early stats
    if len(early_trades) >= 3:
        early_pnls = np.array([t['pnl'] for t in early_trades])
        early_w = early_pnls[early_pnls > 0]
        early_ls = early_pnls[early_pnls <= 0]
        early_pf = early_w.sum() / abs(early_ls.sum()) if len(early_ls) > 0 else 999
        early_exp = early_pnls.mean() * 100
    else:
        early_exp = 0
        early_pf = 0
    
    # Recent stats
    if len(recent_trades) >= 2:
        recent_pnls = np.array([t['pnl'] for t in recent_trades])
        recent_w = recent_pnls[recent_pnls > 0]
        recent_ls = recent_pnls[recent_pnls <= 0]
        recent_pf = recent_w.sum() / abs(recent_ls.sum()) if len(recent_ls) > 0 else 999
        recent_exp = recent_pnls.mean() * 100
    else:
        recent_exp = 0
        recent_pf = 0
    
    # Trend
    if early_exp > 0 and recent_exp > 0:
        ratio = recent_exp / early_exp
        if ratio > 0.8:
            trend = "STABLE"
        elif ratio > 0.5:
            trend = "MILD DEGR"
        else:
            trend = "DEGRADING"
    elif early_exp > 0 and recent_exp <= 0:
        trend = "FAILED"
    else:
        trend = "UNCLEAR"
    
    print(f"{pair:<8} {len(early_trades):<10} {early_exp:>8.2f}%    {early_pf:<10.2f} {len(recent_trades):<10} {recent_exp:>8.2f}%    {recent_pf:<10.2f} {trend}")

# Volatility trend
print(f"\n{'=' * 120}")
print("VOLATILITY TREND (ATR%)")
print(f"{'=' * 120}")

print(f"\n{'Pair':<8} {'Early ATR%':<12} {'Recent ATR%':<12} {'Change'}")
print("-" * 50)

for pair in VALIDATED:
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
    
    split_idx = int(len(c) * 0.8)
    
    early_atr = atr[500:split_idx].mean() / c[500:split_idx].mean() * 100
    recent_atr = atr[split_idx:].mean() / c[split_idx:].mean() * 100
    
    change = (recent_atr / early_atr - 1) * 100
    
    print(f"{pair:<8} {early_atr:>8.2f}%     {recent_atr:>8.2f}%     {change:>+.1f}%")

# Summary
print(f"\n{'=' * 120}")
print("PORTFOLIO ADJUSTMENT RECOMMENDATION")
print(f"{'=' * 120}")

print("""
If pairs show degradation, consider:
1. Reducing position size for degraded pairs
2. Adding newer pairs with fresher edges
3. Tightening entry criteria (e.g., RSI < 15 instead of < 20)
""")
