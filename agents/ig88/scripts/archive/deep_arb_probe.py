"""
Deep ARB Probe: Why is ARB 2-3x stronger than other pairs?
===========================================================
Hypotheses to test:
1. ARB has different bounce mechanics (higher mean reversion)
2. ARB's oversold conditions are "more extreme"
3. Data quality issue (stale prices, gaps, etc)
4. Specific time period dominating results
5. ARB has different volume/microstructure
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PAIRS = ['ARB', 'AVAX', 'AAVE', 'SUI', 'ATOM']


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_full_indicators(df):
    """Compute all possible indicators for comparison."""
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_width = (sma20 + std20 * 2 - bb_lower) / sma20 * 100
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Volume
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    # Returns
    returns = df['close'].pct_change().values
    
    # Intraday range
    intraday_range = (h - l) / c * 100
    
    return {
        'close': c, 'open': o, 'high': h, 'low': l,
        'rsi': rsi, 'bb_lower': bb_lower, 'bb_width': bb_width,
        'atr': atr, 'atr_pct': atr / c * 100,
        'vol_ratio': vol_ratio, 'volume': df['volume'].values,
        'returns': returns, 'intraday_range': intraday_range,
    }


print("=" * 120)
print("DEEP ARB PROBE: Why is ARB stronger?")
print("=" * 120)

# 1. BASIC STATISTICS COMPARISON
print(f"\n{'=' * 120}")
print("TEST 1: BASIC MARKET STRUCTURE")
print(f"{'=' * 120}")

print(f"\n{'Pair':<8} {'Vol%':<10} {'ATR%':<10} {'BB Width':<12} {'Avg Range':<12} {'Skew':<10} {'Kurtosis'}")
print("-" * 80)

for pair in PAIRS:
    df = load_data(pair)
    ind = compute_full_indicators(df)
    
    returns = pd.Series(ind['returns']).dropna()
    
    print(f"{pair:<8} "
          f"{returns.std()*100:>7.2f}%  "
          f"{ind['atr_pct'][500:].mean():>7.2f}%  "
          f"{ind['bb_width'][500:].mean():>9.2f}%  "
          f"{ind['intraday_range'][500:].mean():>9.2f}%  "
          f"{returns.skew():>7.2f}    "
          f"{returns.kurtosis():>7.2f}")

# 2. OVERSOLD BOUNCE COMPARISON
print(f"\n{'=' * 120}")
print("TEST 2: OVERSOLD BOUNCE MECHANICS")
print(f"{'=' * 120}")

for pair in PAIRS:
    df = load_data(pair)
    ind = compute_full_indicators(df)
    
    c = ind['close']
    h = ind['high']
    low = ind['low']
    rsi = ind['rsi']
    bb_lower = ind['bb_lower']
    
    # Find all oversold events (RSI < 30 for broader sample)
    oversold_mask = (rsi < 30) & (c < bb_lower)
    oversold_indices = np.where(oversold_mask)[0]
    
    if len(oversold_indices) < 5:
        print(f"\n{pair}: Only {len(oversold_indices)} oversold events")
        continue
    
    # Measure bounce characteristics
    bounces_1bar = []
    bounces_3bar = []
    bounces_5bar = []
    bounces_10bar = []
    max_drawdown_after = []
    
    for idx in oversold_indices:
        if idx + 10 >= len(c):
            continue
        
        entry = c[idx + 1]  # Enter next bar
        if np.isnan(entry) or entry == 0:
            continue
        
        # Bounces
        bounces_1bar.append((c[idx + 1] / c[idx] - 1) * 100)
        bounces_3bar.append((c[idx + 3] / c[idx] - 1) * 100)
        bounces_5bar.append((c[idx + 5] / c[idx] - 1) * 100)
        bounces_10bar.append((c[idx + 10] / c[idx] - 1) * 100)
        
        # Max drawdown after signal
        future_lows = low[idx+1:min(idx+11, len(low))]
        if len(future_lows) > 0:
            max_dd = (future_lows.min() / c[idx] - 1) * 100
            max_drawdown_after.append(max_dd)
    
    b1 = np.array(bounces_1bar) if bounces_1bar else np.array([0])
    b3 = np.array(bounces_3bar) if bounces_3bar else np.array([0])
    b5 = np.array(bounces_5bar) if bounces_5bar else np.array([0])
    b10 = np.array(bounces_10bar) if bounces_10bar else np.array([0])
    dd = np.array(max_drawdown_after) if max_drawdown_after else np.array([0])
    
    print(f"\n{pair} ({len(oversold_indices)} oversold events):")
    print(f"  1-bar bounce:  {b1.mean():>6.2f}% (median: {np.median(b1):.2f}%)")
    print(f"  3-bar bounce:  {b3.mean():>6.2f}% (median: {np.median(b3):.2f}%)")
    print(f"  5-bar bounce:  {b5.mean():>6.2f}% (median: {np.median(b5):.2f}%)")
    print(f"  10-bar bounce: {b10.mean():>6.2f}% (median: {np.median(b10):.2f}%)")
    print(f"  Max DD after:  {dd.mean():>6.2f}% (worst: {dd.min():.2f}%)")
    print(f"  Bounce > 0%:   {(b5 > 0).mean()*100:.0f}%")
    print(f"  Bounce > 3%:   {(b5 > 3).mean()*100:.0f}%")

# 3. TRADE-BY-TRADE COMPARISON
print(f"\n{'=' * 120}")
print("TEST 3: TRADE-BY-TRADE DEEP DIVE")
print(f"{'=' * 120}")


def run_mr_detailed(c, o, h, l, rsi, bb_lower, atr, vol_ratio):
    """Return detailed trade info."""
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
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
                        'exit': 'stop',
                        'pnl': -atr[entry_bar] * 0.75 / entry_price - FRICTION,
                        'rsi': rsi[i],
                        'bb_dist': (c[i] - bb_lower[i]) / c[i] * 100,
                        'atr_pct': atr[entry_bar] / entry_price * 100,
                        'bars_held': j,
                    })
                    break
                if h[bar] >= target_price:
                    trades.append({
                        'exit': 'target',
                        'pnl': atr[entry_bar] * 2.5 / entry_price - FRICTION,
                        'rsi': rsi[i],
                        'bb_dist': (c[i] - bb_lower[i]) / c[i] * 100,
                        'atr_pct': atr[entry_bar] / entry_price * 100,
                        'bars_held': j,
                    })
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append({
                    'exit': 'time',
                    'pnl': (exit_price - entry_price) / entry_price - FRICTION,
                    'rsi': rsi[i],
                    'bb_dist': (c[i] - bb_lower[i]) / c[i] * 100,
                    'atr_pct': atr[entry_bar] / entry_price * 100,
                    'bars_held': 15,
                })
    return trades


print(f"\n{'Pair':<8} {'N':<6} {'Exp%':<10} {'PF':<8} {'WR%':<8} {'Avg RSI':<10} {'Avg BB Dist':<12} {'Avg ATR%'}")
print("-" * 80)

for pair in PAIRS:
    df = load_data(pair)
    ind = compute_full_indicators(df)
    
    trades = run_mr_detailed(ind['close'], ind['open'], ind['high'], ind['low'],
                             ind['rsi'], ind['bb_lower'], ind['atr'], ind['vol_ratio'])
    
    if len(trades) < 3:
        print(f"{pair:<8} {len(trades):<6} (insufficient)")
        continue
    
    pnls = np.array([t['pnl'] for t in trades])
    w = pnls[pnls > 0]
    ls = pnls[pnls <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    
    avg_rsi = np.mean([t['rsi'] for t in trades])
    avg_bb_dist = np.mean([t['bb_dist'] for t in trades])
    avg_atr = np.mean([t['atr_pct'] for t in trades])
    
    print(f"{pair:<8} {len(trades):<6} {pnls.mean()*100:>6.2f}%   {pf:<8.2f} {(pnls > 0).mean()*100:>5.0f}%    {avg_rsi:<10.1f} {avg_bb_dist:<12.2f} {avg_atr:.2f}%")

# 4. EXIT TYPE ANALYSIS
print(f"\n{'=' * 120}")
print("TEST 4: EXIT TYPE DISTRIBUTION")
print(f"{'=' * 120}")

print(f"\n{'Pair':<8} {'Stop':<12} {'Target':<12} {'Time':<12} {'Target Rate'}")
print("-" * 60)

for pair in PAIRS:
    df = load_data(pair)
    ind = compute_full_indicators(df)
    
    trades = run_mr_detailed(ind['close'], ind['open'], ind['high'], ind['low'],
                             ind['rsi'], ind['bb_lower'], ind['atr'], ind['vol_ratio'])
    
    if len(trades) < 3:
        continue
    
    exits = {}
    for t in trades:
        exits[t['exit']] = exits.get(t['exit'], 0) + 1
    
    total = len(trades)
    stop_pct = exits.get('stop', 0) / total * 100
    target_pct = exits.get('target', 0) / total * 100
    time_pct = exits.get('time', 0) / total * 100
    
    print(f"{pair:<8} {exits.get('stop', 0):>3} ({stop_pct:.0f}%)  {exits.get('target', 0):>3} ({target_pct:.0f}%)  {exits.get('time', 0):>3} ({time_pct:.0f}%)  {target_pct:.0f}%")

# 5. CHECK DATA GAPS/STALES
print(f"\n{'=' * 120}")
print("TEST 5: DATA QUALITY CHECK")
print(f"{'=' * 120}")

for pair in PAIRS:
    df = load_data(pair)
    
    # Check for gaps
    if 'timestamp' in df.columns:
        ts = pd.to_datetime(df['timestamp'], unit='s')
    elif isinstance(df.index, pd.DatetimeIndex):
        ts = df.index
    else:
        ts = None
    
    # Check for zero/near-zero prices
    zero_prices = (df['close'] <= 0).sum()
    tiny_prices = (df['close'] < 0.01).sum()
    
    # Check for gaps > 8 hours
    if ts is not None:
        gaps = ts.diff().dropna()
        big_gaps = (gaps > pd.Timedelta(hours=8)).sum()
    else:
        big_gaps = "N/A"
    
    # Check for identical consecutive prices (stale)
    stale = (df['close'].diff() == 0).sum()
    
    print(f"\n{pair}:")
    print(f"  Zero prices: {zero_prices}")
    print(f"  Tiny prices (<$0.01): {tiny_prices}")
    print(f"  Gaps > 8h: {big_gaps}")
    print(f"  Stale bars (no change): {stale} ({stale/len(df)*100:.1f}%)")
    print(f"  Price range: ${df['close'].min():.4f} - ${df['close'].max():.4f}")

# 6. CONCENTRATION TEST
print(f"\n{'=' * 120}")
print("TEST 6: TRADE CONCENTRATION (Are ARB's wins from a few lucky trades?)")
print(f"{'=' * 120}")

for pair in PAIRS:
    df = load_data(pair)
    ind = compute_full_indicators(df)
    
    trades = run_mr_detailed(ind['close'], ind['open'], ind['high'], ind['low'],
                             ind['rsi'], ind['bb_lower'], ind['atr'], ind['vol_ratio'])
    
    if len(trades) < 5:
        continue
    
    pnls = np.array([t['pnl'] for t in trades])
    sorted_pnls = np.sort(pnls)[::-1]  # Best to worst
    
    top3_contribution = sorted_pnls[:3].sum() / pnls.sum() * 100 if pnls.sum() != 0 else 999
    bottom3_contribution = sorted_pnls[-3:].sum() / pnls.sum() * 100 if pnls.sum() != 0 else 999
    
    print(f"\n{pair} (total PnL: {pnls.sum()*100:.2f}%):")
    print(f"  Top 3 trades: {sorted_pnls[:3].sum()*100:.2f}% ({top3_contribution:.0f}% of total)")
    print(f"  Bottom 3 trades: {sorted_pnls[-3:].sum()*100:.2f}%")
    print(f"  Top trade: {sorted_pnls[0]*100:.2f}%")
    print(f"  Worst trade: {sorted_pnls[-1]*100:.2f}%")
