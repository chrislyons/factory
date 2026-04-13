"""
Debug H3-A Discrepancy
======================
Why is H3-A failing now when it was validated at PF 5.5?
Possible causes:
1. Different parameters in original validation
2. Regime filter was mandatory (not optional)
3. Exit mechanism different (ATR trailing vs fixed)
4. Data has changed
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025


def load_data(pair='SOL'):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    
    # Ichimoku
    tenkan = (pd.Series(h).rolling(9).max() + pd.Series(l).rolling(9).min()) / 2
    kijun = (pd.Series(h).rolling(26).max() + pd.Series(l).rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((pd.Series(h).rolling(52).max() + pd.Series(l).rolling(52).min()) / 2).shift(26)
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # BTC returns for regime
    btc_df = load_data('BTC')
    btc_c = btc_df['close'].values
    btc_20ret = pd.Series(btc_c).pct_change(20).values
    
    # Align BTC returns to SOL length
    btc_aligned = np.full(len(c), np.nan)
    min_len = min(len(btc_20ret), len(c))
    btc_aligned[:min_len] = btc_20ret[:min_len]
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'tenkan': tenkan.values, 'kijun': kijun.values,
        'senkou_a': senkou_a.values, 'senkou_b': senkou_b.values,
        'rsi': rsi, 'atr': atr, 'btc_20ret': btc_aligned,
    }


def test_h3a_variants(ind):
    """Test different H3-A parameter combinations to find what works."""
    
    results = []
    
    # Test different parameter combos
    params_list = [
        # (rsi_thresh, require_tk_cross, require_above_cloud, require_score, regime_filter, exit_type)
        (55, True, True, 3, None, "atr_trail"),  # Original from IG88024
        (55, True, True, 3, -0.05, "atr_trail"),  # With BTC regime -5%
        (55, True, True, 3, 0.0, "atr_trail"),    # With BTC regime 0%
        (50, True, True, 3, None, "atr_trail"),   # Lower RSI threshold
        (50, True, True, 3, 0.0, "atr_trail"),    # Lower RSI + regime
        (45, True, True, 2, 0.0, "atr_trail"),    # Relaxed score
        (55, False, True, 2, 0.0, "atr_trail"),   # No TK cross required
        (55, True, False, 2, 0.0, "atr_trail"),   # No above cloud
        (40, True, True, 3, 0.0, "time5"),        # Time exit 5 bars
        (40, True, True, 3, 0.0, "time10"),       # Time exit 10 bars
    ]
    
    c = ind['c']
    o = ind['o']
    h = ind['h']
    l = ind['l']
    tenkan = ind['tenkan']
    kijun = ind['kijun']
    senkou_a = ind['senkou_a']
    senkou_b = ind['senkou_b']
    rsi = ind['rsi']
    atr = ind['atr']
    btc_20ret = ind['btc_20ret']
    
    for params in params_list:
        rsi_thresh, require_tk, require_cloud, min_score, regime_thresh, exit_type = params
        
        trades = []
        
        for i in range(100, len(c) - 15):
            if np.isnan(rsi[i]) or np.isnan(tenkan[i]) or np.isnan(kijun[i]):
                continue
            if np.isnan(senkou_a[i]) or np.isnan(senkou_b[i]) or np.isnan(atr[i]):
                continue
            
            # Check regime filter
            if regime_thresh is not None and not np.isnan(btc_20ret[i]):
                if btc_20ret[i] < regime_thresh:
                    continue
            
            # Check conditions
            tk_cross = tenkan[i] > kijun[i]
            cloud_top = np.nanmax([senkou_a[i], senkou_b[i]])
            above_cloud = c[i] > cloud_top
            rsi_ok = rsi[i] > rsi_thresh
            
            # Count score
            score = 0
            if tk_cross: score += 1
            if above_cloud: score += 1
            if rsi_ok: score += 1
            
            # Apply filters
            if require_tk and not tk_cross:
                continue
            if require_cloud and not above_cloud:
                continue
            if score < min_score:
                continue
            
            # Entry at T1
            entry_bar = i + 1
            if entry_bar >= len(c) - 10:
                continue
            
            entry = o[entry_bar]
            atr_val = atr[entry_bar]
            
            if atr_val <= 0 or np.isnan(atr_val):
                continue
            
            # Exit logic
            if exit_type == "atr_trail":
                # ATR trailing stop (2x ATR initial, trail)
                stop = entry - atr_val * 2
                target = entry + atr_val * 10  # Cap at 10x ATR
                
                trail_stop = stop
                exited = False
                
                for j in range(1, 9):
                    bar = entry_bar + j
                    if bar >= len(c):
                        break
                    
                    # Update trail
                    new_trail = c[bar] - atr[bar] * 2
                    trail_stop = max(trail_stop, new_trail)
                    
                    if l[bar] <= trail_stop:
                        ret = (trail_stop - entry) / entry - FRICTION
                        trades.append(ret)
                        exited = True
                        break
                    
                    if h[bar] >= target:
                        ret = (target - entry) / entry - FRICTION
                        trades.append(ret)
                        exited = True
                        break
                
                if not exited:
                    exit_price = c[min(entry_bar + 8, len(c) - 1)]
                    trades.append((exit_price - entry) / entry - FRICTION)
            
            elif exit_type == "time5":
                exit_price = c[min(entry_bar + 5, len(c) - 1)]
                trades.append((exit_price - entry) / entry - FRICTION)
            
            elif exit_type == "time10":
                exit_price = c[min(entry_bar + 10, len(c) - 1)]
                trades.append((exit_price - entry) / entry - FRICTION)
        
        trades = np.array(trades) if trades else np.array([])
        
        if len(trades) >= 10:
            w = trades[trades > 0]
            ls = trades[trades <= 0]
            pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
            wr = len(w) / len(trades) * 100
            exp = trades.mean() * 100
            
            results.append({
                'params': f"RSI>{rsi_thresh}, TK={require_tk}, Cloud={require_cloud}, Score>={min_score}, Regime={regime_thresh}, Exit={exit_type}",
                'n': len(trades),
                'pf': round(pf, 3),
                'wr': round(wr, 1),
                'exp': round(exp, 3),
            })
    
    return results


print("=" * 100)
print("H3-A DEBUG: FINDING THE VALIDATED PARAMETERS")
print("=" * 100)

df = load_data('SOL')
print(f"Data: {len(df)} bars")
ind = compute_indicators(df)

results = test_h3a_variants(ind)

print(f"\n{'#':<4} {'Params':<70} {'N':<6} {'PF':<8} {'WR':<8} {'Exp%':<8}")
print("-" * 105)

for i, r in enumerate(results):
    marker = " <-- VIABLE" if r['pf'] > 1.5 else ""
    print(f"{i+1:<4} {r['params'][:68]:<70} {r['n']:<6} {r['pf']:<8.3f} {r['wr']:<7.1f}% {r['exp']:<7.3f}%{marker}")

print("\n" + "=" * 100)
print("CONCLUSION")
print("=" * 100)
