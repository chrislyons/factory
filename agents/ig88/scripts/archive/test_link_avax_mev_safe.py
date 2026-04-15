"""
LINK & AVAX Deep Dive: Finding MEV-Safe Edge
=============================================
Test different signal parameter combinations to find edge
that works with MEV-safe stops (0.5%+) on LINK and AVAX.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    h, l = df['high'].values, df['low'].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'sma20': sma20, 'std20': std20,
        'vol_ratio': vol_ratio, 'atr': atr, 'atr_pct': (atr / c) * 100,
    }


def run_backtest(ind, rsi_thresh, bb_std, vol_thresh, entry_offset, stop_pct, target_pct):
    """Run MR backtest."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20 = ind['rsi'], ind['sma20'], ind['std20']
    vol_ratio = ind['vol_ratio']
    bb_l = sma20 - std20 * bb_std
    
    trades = []
    for i in range(100, len(c) - entry_offset - 8):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        
        if rsi[i] < rsi_thresh and c[i] < bb_l[i] and vol_ratio[i] > vol_thresh:
            entry_bar = i + entry_offset
            if entry_bar >= len(c) - 8:
                continue
            
            entry = o[entry_bar]
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
            
            exited = False
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop:
                    trades.append(-stop_pct - FRICTION)
                    exited = True
                    break
                elif h[bar] >= target:
                    trades.append(target_pct - FRICTION)
                    exited = True
                    break
            
            if not exited:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry) / entry - FRICTION)
    
    return np.array(trades) if trades else np.array([])


def calc_stats(trades):
    if len(trades) < 10:
        return None
    t = trades
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(t)*100), 1),
        'exp': round(float(t.mean()*100), 3),
        'sharpe': round(float(sharpe), 2),
    }


print("=" * 100)
print("LINK & AVAX: FINDING MEV-SAFE EDGE")
print("=" * 100)

# Test multiple signal parameter combos with MEV-safe stops
RSI_RANGE = [25, 28, 30, 32, 35, 38, 40]
BB_RANGE = [0.5, 1.0, 1.5, 2.0]
VOL_RANGE = [1.0, 1.1, 1.2, 1.3, 1.5]
ENTRY_RANGE = [0, 1, 2]

# MEV-safe stops to test
SAFE_STOPS = [0.005, 0.006, 0.0075, 0.01]
TARGETS = [0.075, 0.10, 0.125, 0.15]

for pair in ['LINK', 'AVAX']:
    print(f"\n{'=' * 90}")
    print(f"PAIR: {pair}")
    print(f"{'=' * 90}")
    
    df = load_data(pair)
    ind = compute_indicators(df)
    print(f"Data points: {len(df)}")
    print(f"ATR% range: {ind['atr_pct'][~np.isnan(ind['atr_pct'])].min():.2f}% - {ind['atr_pct'][~np.isnan(ind['atr_pct'])].max():.2f}%")
    print(f"ATR% median: {np.nanmedian(ind['atr_pct']):.2f}%")
    
    best_results = []
    
    # Grid search over signal params
    for rsi in RSI_RANGE:
        for bb in BB_RANGE:
            for vol in VOL_RANGE:
                for entry in ENTRY_RANGE:
                    for stop in SAFE_STOPS:
                        for target in TARGETS:
                            if target <= stop * 2:
                                continue
                            
                            trades = run_backtest(ind, rsi, bb, vol, entry, stop, target)
                            stats = calc_stats(trades)
                            
                            if stats and stats['pf'] > 1.2 and stats['n'] >= 20:
                                mev = 70 if stop <= 0.005 else 40 if stop <= 0.0075 else 20
                                best_results.append({
                                    'rsi': rsi, 'bb': bb, 'vol': vol, 'entry': f'T{entry}',
                                    'stop': round(stop*100, 2), 'target': round(target*100, 1),
                                    'mev': mev,
                                    **stats,
                                })
    
    # Sort by PF
    best_results.sort(key=lambda x: x['pf'], reverse=True)
    
    print(f"\nTop 15 Configs (PF > 1.2, MEV-safe stops):\n")
    print(f"{'RSI':<6} {'BB':<5} {'Vol':<5} {'Entry':<7} {'Stop':<7} {'Target':<8} {'N':<6} {'PF':<8} {'WR':<8} {'Exp%':<8} {'MEV':<6}")
    print("-" * 85)
    
    for r in best_results[:15]:
        print(f"{r['rsi']:<6} {r['bb']:<5} {r['vol']:<5} {r['entry']:<7} {r['stop']:<6}% {r['target']:<7}% {r['n']:<6} {r['pf']:<8} {r['wr']:<7}% {r['exp']:<7}% {r['mev']:<5}/100")
    
    if best_results:
        best = best_results[0]
        print(f"\n  BEST CONFIG: RSI<{best['rsi']}, BB {best['bb']}σ, Vol>{best['vol']}, {best['entry']}")
        print(f"    Stop: {best['stop']}%, Target: {best['target']}%")
        print(f"    PF: {best['pf']} | WR: {best['wr']}% | Exp: {best['exp']}% | Sharpe: {best['sharpe']}")
    else:
        print("\n  NO PROFITABLE MEV-SAFE CONFIGS FOUND")
        print("  Testing with even wider parameter space...")

print(f"\n\n{'=' * 90}")
print("EXPANDED TEST: TRYING WIDER RANGES")
print(f"{'=' * 90}")

# Now test with even more relaxed constraints
for pair in ['LINK', 'AVAX', 'BTC', 'ETH']:
    print(f"\n--- {pair} ---")
    
    df = load_data(pair)
    ind = compute_indicators(df)
    
    # Try multiple aggressive combos
    test_configs = [
        # (rsi, bb, vol, entry, stop, target)
        (30, 2.0, 1.0, 0, 0.005, 0.10),
        (35, 2.0, 1.0, 0, 0.005, 0.10),
        (30, 1.5, 1.0, 0, 0.005, 0.10),
        (25, 2.0, 1.0, 0, 0.005, 0.10),
        (30, 2.0, 1.2, 1, 0.005, 0.10),
        (35, 2.0, 1.2, 1, 0.005, 0.10),
        (30, 1.5, 1.2, 1, 0.005, 0.10),
        (35, 1.5, 1.2, 1, 0.005, 0.10),
        (40, 1.5, 1.2, 1, 0.005, 0.10),
        (35, 2.0, 1.5, 2, 0.005, 0.10),
        (40, 2.0, 1.5, 2, 0.005, 0.10),
        (30, 2.5, 1.0, 0, 0.006, 0.10),
        (35, 2.5, 1.0, 0, 0.006, 0.10),
        (30, 2.5, 1.2, 1, 0.006, 0.10),
        (35, 2.5, 1.2, 1, 0.006, 0.10),
    ]
    
    found = False
    for rsi, bb, vol, entry, stop, target in test_configs:
        trades = run_backtest(ind, rsi, bb, vol, entry, stop, target)
        stats = calc_stats(trades)
        if stats and stats['pf'] > 1.0 and stats['n'] >= 15:
            found = True
            print(f"  RSI<{rsi}, BB {bb}σ, Vol>{vol}, T{entry}, Stop {stop*100:.2f}%, Target {target*100:.0f}%: PF={stats['pf']}, n={stats['n']}, Exp={stats['exp']}%")
    
    if not found:
        print("  No profitable configs found with 0.5%+ stops")
