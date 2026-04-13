"""
Test: T1 Entry Timing + Validated MR Signal Combination
=========================================================
Combine the T1 edge with our validated MR signal:
- RSI < 35
- BB 1σ lower
- Volume > 1.2x SMA20

Does T1 entry IMPROVE our already-validated PF 3.21 strategy?
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0042

def load_data(pair='SOL', timeframe='240m'):
    for p in [f'{pair}_USDT', f'{pair}USDT', pair]:
        path = DATA_DIR / f'binance_{p}_{timeframe}.parquet'
        if path.exists():
            return pd.read_parquet(path)
    return None

def run_mr_test(df, entry_offset, friction=0.0042, atr_stops=True):
    """
    Run MR strategy with specific entry timing.
    
    MR Signal (validated):
    - RSI < 35
    - Close < BB 1σ lower
    - Volume > 1.2x SMA20
    
    Entry timing:
    - T0 = enter at signal bar close
    - T1 = enter at next bar open
    - T2 = enter 2 bars later
    """
    c = df['close'].values
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    v = df['volume'].values
    
    # Compute RSI
    close_series = df['close']
    delta = close_series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    
    # Compute BB 1σ
    sma20 = close_series.rolling(20).mean().values
    std20 = close_series.rolling(20).std().values
    bb_l = sma20 - std20  # 1σ lower
    bb_h = sma20 + std20  # 1σ upper
    
    # Compute Volume ratio
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    # Compute ATR
    tr1 = h - l
    tr2 = np.abs(h - np.roll(c, 1))
    tr3 = np.abs(l - np.roll(c, 1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = (atr / c) * 100
    
    trades = []
    
    for i in range(100, len(c) - entry_offset - 10):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]) or np.isnan(atr_pct[i]):
            continue
        
        # MR Signal (long only for now - validated direction)
        long_signal = (
            rsi[i] < 35 and
            c[i] < bb_l[i] and
            vol_ratio[i] > 1.2
        )
        
        if not long_signal:
            continue
        
        # Entry bar
        entry_bar = i + entry_offset
        if entry_bar >= len(c) - 8:
            continue
        
        # Check if signal still valid at entry
        if c[entry_bar] > bb_l[entry_bar]:
            continue  # Price recovered
        
        if rsi[entry_bar] > 40:
            continue  # RSI recovered
        
        # Entry price
        entry = o[entry_bar]
        
        # Stop/target
        if atr_stops:
            atr_val = atr_pct[entry_bar]
            if atr_val < 2.0:
                stop_pct, target_pct = 0.015, 0.03
            elif atr_val < 4.0:
                stop_pct, target_pct = 0.01, 0.075
            else:
                stop_pct, target_pct = 0.005, 0.075
        else:
            stop_pct, target_pct = 0.01, 0.075  # Fixed 1%/7.5%
        
        stop = entry * (1 - stop_pct)
        target = entry * (1 + target_pct)
        
        # Check exits (8 bars = 32h for 4h candles)
        exited = False
        for j in range(1, 9):
            check_bar = entry_bar + j
            if check_bar >= len(c):
                break
            
            if l[check_bar] <= stop and h[check_bar] >= target:
                ret = -stop_pct - friction
                trades.append(ret)
                exited = True
                break
            elif l[check_bar] <= stop:
                ret = -stop_pct - friction
                trades.append(ret)
                exited = True
                break
            elif h[check_bar] >= target:
                ret = target_pct - friction
                trades.append(ret)
                exited = True
                break
        
        if not exited:
            exit_price = c[min(entry_bar + 8, len(c) - 1)]
            ret = (exit_price - entry) / entry - friction
            trades.append(ret)
    
    return np.array(trades) if trades else np.array([])

def compute_stats(trades):
    if len(trades) < 5:
        return {'n': len(trades), 'pf': np.nan, 'wr': np.nan, 'exp': np.nan}
    
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    wr = len(w) / len(trades) * 100
    exp = trades.mean() * 100
    
    return {'n': len(trades), 'pf': round(pf, 3), 'wr': round(wr, 1), 'exp': round(exp, 3)}

print("="*80)
print("MR SIGNAL + T1 ENTRY TIMING COMBINATION")
print("="*80)
print("\nMR Signal: RSI < 35, BB 1σ lower, Vol > 1.2x")
print("Testing: Does T1 entry improve the validated strategy?\n")

pairs = ['SOL', 'BTC', 'ETH', 'NEAR', 'LINK', 'AVAX']
offsets = [0, 1, 2]
offset_labels = ['T0 (immediate)', 'T1 (1 bar wait)', 'T2 (2 bar wait)']

print(f"{'Pair':>6}", end='')
for label in offset_labels:
    print(f" {label:>18}", end='')
print()
print("-" * 70)

all_t0 = []
all_t1 = []
all_t2 = []

for pair in pairs:
    df = load_data(pair, '240m')
    if df is None:
        continue
    
    results = []
    for offset, label in zip(offsets, offset_labels):
        trades = run_mr_test(df, offset)
        s = compute_stats(trades)
        results.append(s)
        
        if offset == 0:
            all_t0.extend(trades)
        elif offset == 1:
            all_t1.extend(trades)
        else:
            all_t2.extend(trades)
    
    print(f"{pair:>6}", end='')
    for s in results:
        if np.isnan(s['pf']):
            print(f" {'N/A':>18}", end='')
        else:
            print(f" PF={s['pf']:.2f} n={s['n']:>4}", end='')
    print()

print("\n" + "-" * 70)
print("AGGREGATE:")
for label, trades in [('T0', all_t0), ('T1', all_t1), ('T2', all_t2)]:
    s = compute_stats(np.array(trades))
    print(f"  {label}: n={s['n']}, PF={s['pf']:.3f}, WR={s['wr']:.1f}%, Exp={s['exp']:.3f}%")

# ===============================
# Statistical significance test
# ===============================
print("\n" + "="*80)
print("STATISTICAL SIGNIFICANCE (T1 vs T0 on MR signal)")
print("="*80)

all_t0 = np.array(all_t0)
all_t1 = np.array(all_t1)

if len(all_t0) > 50 and len(all_t1) > 50:
    # Bootstrap
    diffs = []
    for _ in range(2000):
        s0 = np.random.choice(all_t0, size=len(all_t0), replace=True)
        s1 = np.random.choice(all_t1, size=len(all_t1), replace=True)
        
        pf0 = s0[s0 > 0].sum() / abs(s0[s0 <= 0].sum()) if s0[s0 <= 0].sum() != 0 else 1.0
        pf1 = s1[s1 > 0].sum() / abs(s1[s1 <= 0].sum()) if s1[s1 <= 0].sum() != 0 else 1.0
        
        if pf0 < 50 and pf1 < 50:
            diffs.append(pf1 - pf0)
    
    diffs = np.array(diffs)
    p_value = (diffs <= 0).mean()
    
    print(f"\nT1 - T0 Performance Difference (MR signal):")
    print(f"  Mean: {diffs.mean():.3f}")
    print(f"  95% CI: [{np.percentile(diffs, 2.5):.3f}, {np.percentile(diffs, 97.5):.3f}]")
    print(f"  P(T1 <= T0): {p_value:.4f}")
    print(f"  {'SIGNIFICANT' if p_value < 0.05 else 'NOT SIGNIFICANT'} at α=0.05")

# ===============================
# Per-pair breakdown
# ===============================
print("\n" + "="*80)
print("PER-PAIR T1 vs T0 COMPARISON")
print("="*80)

for pair in pairs:
    df = load_data(pair, '240m')
    if df is None:
        continue
    
    t0 = run_mr_test(df, 0)
    t1 = run_mr_test(df, 1)
    
    s0 = compute_stats(t0)
    s1 = compute_stats(t1)
    
    delta = s1['pf'] - s0['pf'] if not (np.isnan(s0['pf']) or np.isnan(s1['pf'])) else np.nan
    better = 'T1' if s1['pf'] > s0['pf'] else 'T0'
    
    print(f"{pair:>6}: T0={s0['pf']:.3f} (n={s0['n']}), T1={s1['pf']:.3f} (n={s1['n']}), Δ={delta:+.3f}, Winner={better}")

print("\n" + "="*80)
print("CONCLUSION")
print("="*80)
