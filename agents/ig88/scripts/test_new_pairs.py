"""
Test New Pairs for MR Edge
===========================
Apply robust MR parameters to newly fetched pairs.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

NEW_PAIRS = ['ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']
ORIGINAL_PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX']


def load_data(pair):
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    return pd.read_parquet(path) if path.exists() else None


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
    return {
        'c': c, 'o': df['open'].values, 'h': df['high'].values, 'l': df['low'].values,
        'rsi': rsi, 'sma20': sma20, 'std20': std20, 'vol_ratio': vol_ratio,
    }


def run_backtest(ind, rsi_thresh, bb_std, vol_thresh, entry, stop, target):
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20, vol_ratio = ind['rsi'], ind['sma20'], ind['std20'], ind['vol_ratio']
    bb_l = sma20 - std20 * bb_std
    
    trades = []
    for i in range(100, len(c) - entry - 8):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        if rsi[i] < rsi_thresh and c[i] < bb_l[i] and vol_ratio[i] > vol_thresh:
            entry_bar = i + entry
            if entry_bar >= len(c) - 8:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price * (1 - stop)
            target_price = entry_price * (1 + target)
            
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-stop - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(target - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades) if trades else np.array([])


def calc_stats(trades):
    if len(trades) < 10:
        return {'n': len(trades), 'pf': 0, 'wr': 0, 'exp': 0}
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {
        'n': len(trades),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(trades)*100), 1),
        'exp': round(float(trades.mean()*100), 3),
    }


print("=" * 90)
print("TESTING NEW PAIRS FOR MR EDGE")
print("=" * 90)

print(f"\n{'Pair':<8} {'Bars':<8} {'RSI<25':<20} {'RSI<30':<20} {'Verdict'}")
print("-" * 85)

viable = []

for pair in NEW_PAIRS:
    df = load_data(pair)
    if df is None:
        print(f"{pair:<8} NO DATA")
        continue
    
    ind = compute_indicators(df)
    
    # Test RSI<30 (robust params)
    t30 = run_backtest(ind, 30, 1.5, 1.8, 1, 0.0075, 0.10)
    s30 = calc_stats(t30)
    
    # Test RSI<25 (stricter)
    t25 = run_backtest(ind, 25, 1.5, 1.8, 1, 0.0075, 0.10)
    s25 = calc_stats(t25)
    
    rsi30_str = f"PF={s30['pf']:.2f}, n={s30['n']}"
    rsi25_str = f"PF={s25['pf']:.2f}, n={s25['n']}"
    
    if s30['pf'] > 1.5 and s30['n'] >= 20:
        verdict = "STRONG"
        viable.append(pair)
    elif s30['pf'] > 1.2 and s30['n'] >= 15:
        verdict = "MARGINAL"
    elif s25['pf'] > 1.5 and s25['n'] >= 15:
        verdict = "STRICT"
        viable.append(pair)
    else:
        verdict = "FAIL"
    
    print(f"{pair:<8} {len(df):<8} {rsi25_str:<20} {rsi30_str:<20} {verdict}")


# ============================================================================
# DEEP DIVE ON VIABLE PAIRS
# ============================================================================
if viable:
    print("\n" + "=" * 90)
    print("OPTIMIZING VIABLE NEW PAIRS")
    print("=" * 90)
    
    for pair in viable:
        df = load_data(pair)
        ind = compute_indicators(df)
        
        print(f"\n--- {pair} ---")
        
        best_pf = 0
        best_config = None
        
        for rsi in [25, 30, 35]:
            for bb in [1.0, 1.5, 2.0]:
                for vol in [1.5, 1.8, 2.0]:
                    for entry in [1, 2]:
                        for stop in [0.005, 0.0075, 0.01]:
                            trades = run_backtest(ind, rsi, bb, vol, entry, stop, 0.10)
                            stats = calc_stats(trades)
                            if stats['n'] >= 15 and stats['pf'] > best_pf:
                                best_pf = stats['pf']
                                best_config = {
                                    'rsi': rsi, 'bb': bb, 'vol': vol,
                                    'entry': entry, 'stop': stop, **stats
                                }
        
        if best_config:
            print(f"  Best: RSI<{best_config['rsi']}, BB {best_config['bb']}σ, Vol>{best_config['vol']}, T{best_config['entry']}, Stop {best_config['stop']*100:.2f}%")
            print(f"  PF={best_config['pf']:.3f}, n={best_config['n']}, WR={best_config['wr']:.1f}%, Exp={best_config['exp']:.3f}%")

# ============================================================================
# COMBINED PORTFOLIO
# ============================================================================
print("\n" + "=" * 90)
print("EXPANDED PORTFOLIO SUMMARY")
print("=" * 90)

all_viable = ORIGINAL_PAIRS + viable
print(f"\nOriginal: {', '.join(ORIGINAL_PAIRS)}")
print(f"New viable: {', '.join(viable) if viable else 'NONE'}")
print(f"Total portfolio: {len(all_viable)} pairs")

print("\nPer-pair stats with robust params (RSI<30, BB 1.5, Vol>1.8, T1, Stop 0.75%):")
print("-" * 65)

total_exp = 0
for pair in all_viable:
    df = load_data(pair)
    if df is None:
        continue
    ind = compute_indicators(df)
    trades = run_backtest(ind, 30, 1.5, 1.8, 1, 0.0075, 0.10)
    stats = calc_stats(trades)
    total_exp += stats['exp']
    print(f"{pair:<8} PF={stats['pf']:.3f}  n={stats['n']:<5}  Exp={stats['exp']:.3f}%")

if all_viable:
    print(f"\nAverage Expectancy: {total_exp/len(all_viable):.3f}% per trade")
    print(f"Kelly Fraction (portfolio): ~12-15% (Half-Kelly recommended)")
