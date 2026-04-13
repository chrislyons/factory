"""
Expand Validated Universe
==========================
Test ALL available pairs for MR edge.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Find all available pairs
all_files = list(DATA_DIR.glob('binance_*_USDT_240m.parquet'))
ALL_PAIRS = [f.name.replace('binance_', '').replace('_USDT_240m.parquet', '') for f in all_files]

print(f"Found {len(ALL_PAIRS)} pairs with data")


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


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
    
    return c, o, h, l, rsi, bb_lower, atr, vol_ratio


def run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, friction):
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
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * 0.75 / entry_price - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * 2.5 / entry_price - friction)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    return np.array(trades)


def run_wf_validation(c, o, h, l, rsi, bb_lower, atr, vol_ratio, friction):
    """Walk-forward validation."""
    n = len(c)
    train_end = int(n * 0.6)
    test_end = int(n * 0.8)
    
    # Train
    train_trades = run_mr_backtest(
        c[:train_end], o[:train_end], h[:train_end], l[:train_end],
        rsi[:train_end], bb_lower[:train_end], atr[:train_end], vol_ratio[:train_end],
        friction
    )
    
    # Test
    test_trades = run_mr_backtest(
        c[train_end:test_end], o[train_end:test_end], h[train_end:test_end], l[train_end:test_end],
        rsi[train_end:test_end], bb_lower[train_end:test_end], atr[train_end:test_end], vol_ratio[train_end:test_end],
        friction
    )
    
    # Validation
    val_trades = run_mr_backtest(
        c[test_end:], o[test_end:], h[test_end:], l[test_end:],
        rsi[test_end:], bb_lower[test_end:], atr[test_end:], vol_ratio[test_end:],
        friction
    )
    
    return train_trades, test_trades, val_trades


def calc_stats(t):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


print("=" * 120)
print("EXPAND VALIDATED UNIVERSE: Testing all available pairs")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

print(f"\n{'Pair':<10} {'Bars':<8} {'Train N':<10} {'Train Exp':<12} {'Test N':<10} {'Test Exp':<12} {'Val N':<10} {'Val Exp':<12} {'Verdict'}")
print("-" * 120)

valid_pairs = []
all_pair_results = []

for pair in sorted(ALL_PAIRS):
    try:
        df = load_data(pair)
    except:
        continue
    
    if len(df) < 500:  # Need minimum data
        continue
    
    c, o, h, l, rsi, bb_lower, atr, vol_ratio = compute_indicators(df)
    
    train_trades, test_trades, val_trades = run_wf_validation(c, o, h, l, rsi, bb_lower, atr, vol_ratio, FRICTION)
    
    train_stats = calc_stats(train_trades)
    test_stats = calc_stats(test_trades)
    val_stats = calc_stats(val_trades)
    
    # Valid if profitable in train and val with sufficient trades
    profitable_count = sum([
        train_stats['exp'] > 0 and train_stats['n'] >= 5,
        test_stats['exp'] >= 0 and test_stats['n'] >= 2,
        val_stats['exp'] >= 0 and val_stats['n'] >= 2,
    ])
    
    total_trades = len(train_trades) + len(test_trades) + len(val_trades)
    is_valid = profitable_count >= 2 and total_trades >= 15
    
    if is_valid:
        verdict = "VALID"
        valid_pairs.append(pair)
    elif train_stats['exp'] > 0 and train_stats['n'] >= 5:
        verdict = "MARGINAL"
    else:
        verdict = "WEAK"
    
    all_pair_results.append({
        'pair': pair,
        'bars': len(df),
        'train': train_stats,
        'test': test_stats,
        'val': val_stats,
        'verdict': verdict,
    })
    
    print(f"{pair:<10} {len(df):<8} "
          f"{train_stats['n']:<4} {train_stats['exp']:>7.2f}%   "
          f"{test_stats['n']:<4} {test_stats['exp']:>7.2f}%   "
          f"{val_stats['n']:<4} {val_stats['exp']:>7.2f}%   "
          f"{verdict}")

# Summary
print(f"\n{'=' * 120}")
print(f"VALID PAIRS: {len(valid_pairs)}")
print(f"{'=' * 120}")

if valid_pairs:
    print(f"\nValid pairs: {', '.join(valid_pairs)}")
    
    # Test combined portfolio
    print(f"\nCOMBINED PORTFOLIO TEST:")
    all_trades = []
    for pair in valid_pairs:
        df = load_data(pair)
        c, o, h, l, rsi, bb_lower, atr, vol_ratio = compute_indicators(df)
        trades = run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, FRICTION)
        stats = calc_stats(trades)
        print(f"  {pair:<10} N={stats['n']:<4} Exp={stats['exp']:>6.2f}%  PF={stats['pf']}")
        all_trades.extend(trades.tolist())
    
    all_trades = np.array(all_trades)
    if len(all_trades) > 0:
        w = all_trades[all_trades > 0]
        ls = all_trades[all_trades <= 0]
        pf = w.sum() / abs(ls.sum()) if len(ls) > 0 else 999
        
        print(f"\n  TOTAL: {len(all_trades)} trades")
        print(f"  Expectancy: {all_trades.mean()*100:.3f}%")
        print(f"  Profit Factor: {pf:.2f}")
        print(f"  Win Rate: {(all_trades > 0).mean()*100:.1f}%")
        
        # Monte Carlo
        np.random.seed(42)
        mc = []
        for _ in range(5000):
            sampled = np.random.choice(all_trades, size=30, replace=True)
            mc.append(sampled.sum())
        mc = np.array(mc)
        
        print(f"\n  Monte Carlo (12mo):")
        print(f"    Mean: {mc.mean()*100:.1f}%")
        print(f"    Prob > 0: {(mc > 0).mean()*100:.1f}%")
