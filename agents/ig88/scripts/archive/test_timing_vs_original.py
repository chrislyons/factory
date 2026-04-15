"""
Cross-check: Why does my test show PF 0.327 while original validation showed PF 3.21?
Reproduce the exact original test conditions.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

def load_data(pair='SOL', timeframe='240m'):
    for p in [f'{pair}_USDT', f'{pair}USDT', pair]:
        path = DATA_DIR / f'binance_{p}_{timeframe}.parquet'
        if path.exists():
            return pd.read_parquet(path)
    return None

# Load SOL data
df = load_data('SOL', '240m')
print(f"Loaded SOL: {len(df)} bars")

c = df['close'].values
o = df['open'].values
h = df['high'].values
l = df['low'].values
v = df['volume'].values

# Compute indicators exactly as in original
close_series = df['close']
delta = close_series.diff()
gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
rsi = (100 - (100 / (1 + gain / loss))).values

sma20 = close_series.rolling(20).mean().values
std20 = close_series.rolling(20).std().values
bb_l = sma20 - std20
bb_h = sma20 + std20

vol_sma = df['volume'].rolling(20).mean().values
vol_ratio = v / vol_sma

# ATR
tr1 = h - l
tr2 = np.abs(h - np.roll(c, 1))
tr3 = np.abs(l - np.roll(c, 1))
tr = np.maximum(tr1, np.maximum(tr2, tr3))
atr = pd.Series(tr).rolling(14).mean().values

print("\nIndicator Stats:")
print(f"  RSI < 35: {(rsi < 35).sum()} bars ({(rsi < 35).sum()/len(rsi)*100:.1f}%)")
print(f"  RSI < 35 & BB lower: {( (c < bb_l) & (rsi < 35) ).sum()} bars")
print(f"  RSI < 35 & BB lower & Vol > 1.2x: {( (c < bb_l) & (rsi < 35) & (vol_ratio > 1.2) ).sum()} bars")

# Count signals with different conditions
signals = []
for i in range(100, len(c) - 10):
    if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
        continue
    
    # Original MR conditions
    if rsi[i] < 35 and c[i] < bb_l[i] and vol_ratio[i] > 1.2:
        signals.append(i)

print(f"\nTotal MR signals found: {len(signals)}")

# Test different entry methods
print("\n--- Entry Method Comparison ---")

FRICTION = 0.0042

for entry_method in ['T0_same_bar_close', 'T1_next_bar_open', 'T2_two_bars']:
    trades = []
    
    for i in signals:
        if entry_method == 'T0_same_bar_close':
            entry = c[i]  # Close of signal bar
            entry_bar = i
        elif entry_method == 'T1_next_bar_open':
            if i + 1 >= len(o):
                continue
            entry = o[i + 1]  # Open of next bar
            entry_bar = i + 1
        else:  # T2
            if i + 2 >= len(o):
                continue
            entry = o[i + 2]
            entry_bar = i + 2
        
        # Check if price recovered at entry
        if c[entry_bar] > bb_l[entry_bar]:
            continue  # Skip recovered signals
        
        # Adaptive stops (original)
        atr_val = atr[entry_bar] / entry if entry > 0 else 0
        if atr_val < 0.02:
            stop_pct, target_pct = 0.015, 0.03
        elif atr_val < 0.04:
            stop_pct, target_pct = 0.01, 0.075
        else:
            stop_pct, target_pct = 0.005, 0.075
        
        stop = entry * (1 - stop_pct)
        target = entry * (1 + target_pct)
        
        # Check exits over 8 bars
        exited = False
        for j in range(1, 9):
            bar = entry_bar + j
            if bar >= len(l):
                break
            
            if l[bar] <= stop and h[bar] >= target:
                ret = -stop_pct - FRICTION
                trades.append(ret)
                exited = True
                break
            elif l[bar] <= stop:
                ret = -stop_pct - FRICTION
                trades.append(ret)
                exited = True
                break
            elif h[bar] >= target:
                ret = target_pct - FRICTION
                trades.append(ret)
                exited = True
                break
        
        if not exited:
            exit_bar = min(entry_bar + 8, len(c) - 1)
            ret = (c[exit_bar] - entry) / entry - FRICTION
            trades.append(ret)
    
    trades = np.array(trades) if trades else np.array([])
    
    if len(trades) > 0:
        w = trades[trades > 0]
        ls = trades[trades <= 0]
        pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
        wr = len(w) / len(trades) * 100
        exp = trades.mean() * 100
        
        print(f"\n{entry_method}:")
        print(f"  n={len(trades)}, PF={pf:.3f}, WR={wr:.1f}%, Exp={exp:.3f}%")
    else:
        print(f"\n{entry_method}: No trades")

# Check what the original validation might have done differently
print("\n" + "="*80)
print("HYPOTHESIS: Original validation used T1 but filtered differently")
print("="*80)

# Test without price recovery filter
trades_no_filter = []
for i in signals:
    if i + 1 >= len(o):
        continue
    entry = o[i + 1]
    entry_bar = i + 1
    
    # NO recovery filter
    
    atr_val = atr[entry_bar] / entry if entry > 0 else 0
    if atr_val < 0.02:
        stop_pct, target_pct = 0.015, 0.03
    elif atr_val < 0.04:
        stop_pct, target_pct = 0.01, 0.075
    else:
        stop_pct, target_pct = 0.005, 0.075
    
    stop = entry * (1 - stop_pct)
    target = entry * (1 + target_pct)
    
    exited = False
    for j in range(1, 9):
        bar = entry_bar + j
        if bar >= len(l):
            break
        
        if l[bar] <= stop and h[bar] >= target:
            trades_no_filter.append(-stop_pct - FRICTION)
            exited = True
            break
        elif l[bar] <= stop:
            trades_no_filter.append(-stop_pct - FRICTION)
            exited = True
            break
        elif h[bar] >= target:
            trades_no_filter.append(target_pct - FRICTION)
            exited = True
            break
    
    if not exited:
        exit_bar = min(entry_bar + 8, len(c) - 1)
        trades_no_filter.append((c[exit_bar] - entry) / entry - FRICTION)

trades_no_filter = np.array(trades_no_filter) if trades_no_filter else np.array([])
if len(trades_no_filter) > 0:
    w = trades_no_filter[trades_no_filter > 0]
    ls = trades_no_filter[trades_no_filter <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    wr = len(w) / len(trades_no_filter) * 100
    exp = trades_no_filter.mean() * 100
    print(f"\nT1 without recovery filter:")
    print(f"  n={len(trades_no_filter)}, PF={pf:.3f}, WR={wr:.1f}%, Exp={exp:.3f}%")

# Test with different friction
for friction in [0.0042, 0.0025, 0.001, 0.0]:
    trades_nf = []
    for i in signals:
        if i + 1 >= len(o):
            continue
        entry = o[i + 1]
        entry_bar = i + 1
        
        atr_val = atr[entry_bar] / entry if entry > 0 else 0
        if atr_val < 0.02:
            stop_pct, target_pct = 0.015, 0.03
        elif atr_val < 0.04:
            stop_pct, target_pct = 0.01, 0.075
        else:
            stop_pct, target_pct = 0.005, 0.075
        
        stop = entry * (1 - stop_pct)
        target = entry * (1 + target_pct)
        
        exited = False
        for j in range(1, 9):
            bar = entry_bar + j
            if bar >= len(l):
                break
            
            if l[bar] <= stop and h[bar] >= target:
                trades_nf.append(-stop_pct - friction)
                exited = True
                break
            elif l[bar] <= stop:
                trades_nf.append(-stop_pct - friction)
                exited = True
                break
            elif h[bar] >= target:
                trades_nf.append(target_pct - friction)
                exited = True
                break
        
        if not exited:
            exit_bar = min(entry_bar + 8, len(c) - 1)
            trades_nf.append((c[exit_bar] - entry) / entry - friction)
    
    trades_nf = np.array(trades_nf) if trades_nf else np.array([])
    if len(trades_nf) > 0:
        w = trades_nf[trades_nf > 0]
        ls = trades_nf[trades_nf <= 0]
        pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
        wr = len(w) / len(trades_nf) * 100
        print(f"  Friction={friction*100:.2f}%: n={len(trades_nf)}, PF={pf:.3f}, WR={wr:.1f}%")
