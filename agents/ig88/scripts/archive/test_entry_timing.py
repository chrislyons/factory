"""
Entry Timing Analysis
====================
Test: Does signal quality vary by time-of-candle?

Hypothesis: If many bots act at candle close (:00), early-candle signals
might be "cleaner" (less noise from other bots) or "noisier" (more whipsaw).

We test by simulating entry at different points within the 4h candle:
- 0.0 = enter at candle open (first bar)
- 0.25 = enter at 25% through candle (1 hour in)
- 0.5 = enter at midpoint (2 hours in)
- 0.75 = enter at 75% (3 hours in)
- 1.0 = enter at candle close (last bar = "normal" behavior)
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0042

def load_data(pair='SOL'):
    """Load 4h data with multiple naming convention support."""
    # Try multiple naming conventions
    for p in [f'{pair}_USDT', f'{pair}USDT', pair]:
        path = DATA_DIR / f'binance_{p}_240m.parquet'
        if path.exists():
            df = pd.read_parquet(path)
            print(f"  Loaded {pair}: {len(df)} bars")
            return df
    print(f"  No data found for {pair}")
    return None

def compute_indicators(df):
    """Compute RSI, BB, ATR."""
    df = df.copy()
    c = df['close'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    df['rsi'] = (100 - (100 / (1 + gain / loss)))
    
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_lower'] = df['sma20'] - df['std20']
    df['bb_upper'] = df['sma20'] + df['std20']
    
    # ATR
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['atr_pct'] = (df['atr'] / df['close']) * 100
    
    return df

def get_stop_target(atr_pct):
    """Adaptive stop/target."""
    if atr_pct < 2.0:
        return 0.015, 0.03
    elif atr_pct < 4.0:
        return 0.01, 0.075
    else:
        return 0.005, 0.075

def test_entry_timing(df, entry_offset_pct, lookahead_bars=8):
    """
    Test entering at different points.
    
    entry_offset_pct: fraction through the signal bar (0=immediate, 1=wait full bar)
    
    Since we only have 4h data, "entry offset" means:
    - 0.0 = enter at signal bar's open (optimistic)
    - 0.5 = enter halfway through signal bar
    - 1.0 = enter at next bar open (realistic T2)
    - 1.5 = wait 1 extra bar before entering
    - 2.0 = wait 2 extra bars before entering
    
    This tests: does waiting for the signal to "settle" improve results?
    """
    trades = []
    c = df['close'].values
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    rsi = df['rsi'].values
    bb_l = df['bb_lower'].values
    bb_h = df['bb_upper'].values
    atr_pct = df['atr_pct'].values
    
    for i in range(100, len(c) - lookahead_bars - 5):
        if pd.isna(rsi[i]) or pd.isna(bb_l[i]):
            continue
        
        atr_val = atr_pct[i] if not pd.isna(atr_pct[i]) else 3.0
        stop_pct, target_pct = get_stop_target(atr_val)
        
        # LONG signal
        if rsi[i] < 35 and c[i] < bb_l[i] and c[i+1] > c[i]:
            # Entry point based on offset
            if entry_offset_pct <= 1.0:
                # Enter during signal bar or next bar open
                entry_frac = entry_offset_pct
                entry = o[i] + (c[i] - o[i]) * entry_frac if entry_frac <= 1.0 else o[i+1]
            else:
                # Wait N extra bars
                extra_bars = int(entry_offset_pct - 1.0)
                entry_bar = i + 1 + extra_bars
                if entry_bar >= len(c):
                    continue
                entry = o[entry_bar]
            
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
            
            # Check subsequent bars for exit
            for j in range(1, lookahead_bars + 1):
                check_bar = i + j
                if check_bar >= len(c):
                    break
                
                bar_h = h[check_bar]
                bar_l = l[check_bar]
                
                if bar_l <= stop and bar_h >= target:
                    # Both hit - conservative: assume stop hit first for longs
                    ret = -stop_pct - FRICTION
                    trades.append(ret)
                    break
                elif bar_l <= stop:
                    ret = -stop_pct - FRICTION
                    trades.append(ret)
                    break
                elif bar_h >= target:
                    ret = target_pct - FRICTION
                    trades.append(ret)
                    break
                elif j == lookahead_bars:
                    # Time exit
                    ret = (c[check_bar] - entry) / entry - FRICTION
                    trades.append(ret)
        
        # SHORT signal
        elif rsi[i] > 65 and c[i] > bb_h[i] and c[i+1] < c[i]:
            if entry_offset_pct <= 1.0:
                entry_frac = entry_offset_pct
                entry = o[i] + (c[i] - o[i]) * entry_frac if entry_frac <= 1.0 else o[i+1]
            else:
                extra_bars = int(entry_offset_pct - 1.0)
                entry_bar = i + 1 + extra_bars
                if entry_bar >= len(c):
                    continue
                entry = o[entry_bar]
            
            stop = entry * (1 + stop_pct)
            target = entry * (1 - target_pct)
            
            for j in range(1, lookahead_bars + 1):
                check_bar = i + j
                if check_bar >= len(c):
                    break
                
                bar_h = h[check_bar]
                bar_l = l[check_bar]
                
                if bar_h >= stop and bar_l <= target:
                    ret = -stop_pct - FRICTION
                    trades.append(ret)
                    break
                elif bar_h >= stop:
                    ret = -stop_pct - FRICTION
                    trades.append(ret)
                    break
                elif bar_l <= target:
                    ret = target_pct - FRICTION
                    trades.append(ret)
                    break
                elif j == lookahead_bars:
                    ret = (entry - c[check_bar]) / entry - FRICTION
                    trades.append(ret)
    
    return trades

def compute_stats(trades):
    """Compute statistics."""
    if len(trades) < 10:
        return {'n': 0, 'pf': 0, 'wr': 0, 'avg': 0, 'sharpe': 0}
    
    t = np.array(trades)
    w = t[t > 0]
    ls = t[t <= 0]
    
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    wr = len(w) / len(t) * 100
    avg = t.mean() * 100
    sharpe = t.mean() / t.std() if t.std() > 0 else 0
    
    return {
        'n': len(t),
        'pf': round(pf, 2),
        'wr': round(wr, 1),
        'avg': round(avg, 3),
        'sharpe': round(sharpe, 2),
    }

print("="*80)
print("ENTRY TIMING / SIGNAL SETTLING ANALYSIS")
print("="*80)
print("\nHypothesis: Waiting for signal to 'settle' improves quality.")
print("Testing: Enter at 0, 0.5, 1, 1.5, 2 bars after signal forms.\n")

pairs = ['SOL', 'AVAX', 'ETH', 'NEAR', 'LINK', 'BTC']

# Test different entry offsets
offsets = [0.0, 0.5, 1.0, 1.5, 2.0]
offset_labels = ['T0 (same bar)', 'T0.5 (mid-bar)', 'T1 (next bar)', 'T1.5 (1.5 bars)', 'T2 (2 bars)']

all_results = {}

for pair in pairs:
    df = load_data(pair)
    if df is None:
        print(f"  {pair}: No data")
        continue
    
    df = compute_indicators(df)
    
    print(f"\n{pair}:")
    print(f"{'Offset':>15} {'n':>5} {'PF':>6} {'WR':>6} {'Exp%':>7} {'Sharpe':>7}")
    print("-" * 55)
    
    pair_results = []
    for offset, label in zip(offsets, offset_labels):
        trades = test_entry_timing(df, offset)
        stats = compute_stats(trades)
        pair_results.append((offset, stats))
        
        if stats['n'] > 0:
            print(f"{label:>15} {stats['n']:5} {stats['pf']:6.2f} {stats['wr']:5.1f}% {stats['avg']:6.3f}% {stats['sharpe']:7.2f}")
        else:
            print(f"{label:>15} {'<10':>5}")
    
    all_results[pair] = pair_results

# Aggregate analysis
print("\n" + "="*80)
print("AGGREGATE ANALYSIS BY OFFSET")
print("="*80)

print(f"\n{'Offset':>15} {'Total Trades':>12} {'Avg PF':>8} {'Avg WR':>8} {'Avg Exp':>8} {'Avg Sharpe':>11}")
print("-" * 70)

for offset, label in zip(offsets, offset_labels):
    all_trades = []
    total_pf = []
    total_wr = []
    total_exp = []
    total_sharpe = []
    
    for pair, results in all_results.items():
        for off, stats in results:
            if off == offset and stats['n'] > 0:
                total_pf.append(stats['pf'])
                total_wr.append(stats['wr'])
                total_exp.append(stats['avg'])
                total_sharpe.append(stats['sharpe'])
    
    if total_pf:
        print(f"{label:>15} {len(total_pf):>12} {np.mean(total_pf):8.2f} {np.mean(total_wr):7.1f}% {np.mean(total_exp):7.3f}% {np.mean(total_sharpe):10.2f}")

print("\n" + "="*80)
print("CONCLUSION")
print("="*80)
