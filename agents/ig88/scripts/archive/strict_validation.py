"""
Strict Validation: Tighter Criteria for MR Edge
================================================
Only pairs that are PROFITABLE in ALL three periods.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

ALL_PAIRS = ['AAVE', 'ARB', 'ATOM', 'AVAX', 'BTC', 'ETH', 'INJ', 'LINK', 'NEAR', 'OP', 'POL', 'SOL', 'SUI', 'UNI']


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


def calc_stats(t):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


print("=" * 120)
print("STRICT VALIDATION: Must be profitable in ALL periods")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

print(f"\n{'Pair':<10} {'Train':<20} {'Test':<20} {'Val':<20} {'All+':<8} {'Verdict'}")
print("-" * 100)

strict_valid = []

for pair in ALL_PAIRS:
    try:
        df = load_data(pair)
    except:
        continue
    
    n = len(df)
    train_end = int(n * 0.6)
    test_end = int(n * 0.8)
    
    c, o, h, l, rsi, bb_lower, atr, vol_ratio = compute_indicators(df)
    
    train_trades = run_mr_backtest(c[:train_end], o[:train_end], h[:train_end], l[:train_end],
                                    rsi[:train_end], bb_lower[:train_end], atr[:train_end], vol_ratio[:train_end], FRICTION)
    test_trades = run_mr_backtest(c[train_end:test_end], o[train_end:test_end], h[train_end:test_end], l[train_end:test_end],
                                   rsi[train_end:test_end], bb_lower[train_end:test_end], atr[train_end:test_end], vol_ratio[train_end:test_end], FRICTION)
    val_trades = run_mr_backtest(c[test_end:], o[test_end:], h[test_end:], l[test_end:],
                                  rsi[test_end:], bb_lower[test_end:], atr[test_end:], vol_ratio[test_end:], FRICTION)
    
    train_s = calc_stats(train_trades)
    test_s = calc_stats(test_trades)
    val_s = calc_stats(val_trades)
    
    # STRICT: ALL three periods must be profitable with sufficient trades
    all_profitable = (train_s['exp'] > 0 and train_s['n'] >= 5 and
                      test_s['exp'] > 0 and test_s['n'] >= 3 and
                      val_s['exp'] > 0 and val_s['n'] >= 3)
    
    total_trades = train_s['n'] + test_s['n'] + val_s['n']
    
    train_str = f"N={train_s['n']:<2} {train_s['exp']:>5.2f}%"
    test_str = f"N={test_s['n']:<2} {test_s['exp']:>5.2f}%"
    val_str = f"N={val_s['n']:<2} {val_s['exp']:>5.2f}%"
    
    if all_profitable and total_trades >= 20:
        verdict = "STRICT VALID"
        strict_valid.append(pair)
    elif train_s['exp'] > 0 and train_s['n'] >= 5:
        verdict = "MARGINAL"
    else:
        verdict = "WEAK"
    
    print(f"{pair:<10} {train_str:<20} {test_str:<20} {val_str:<20} {total_trades:<8} {verdict}")

# Summary
print(f"\n{'=' * 120}")
print(f"STRICT VALID PAIRS: {len(strict_valid)}")
print(f"{'=' * 120}")

if strict_valid:
    all_trades = []
    
    print(f"\n{'Pair':<10} {'Full N':<10} {'Full Exp':<12} {'PF':<8} {'WR%'}")
    print("-" * 50)
    
    for pair in strict_valid:
        df = load_data(pair)
        c, o, h, l, rsi, bb_lower, atr, vol_ratio = compute_indicators(df)
        trades = run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, FRICTION)
        stats = calc_stats(trades)
        all_trades.extend(trades.tolist())
        print(f"{pair:<10} {stats['n']:<10} {stats['exp']:>7.3f}%  {stats['pf']:<8.2f} {stats['wr']}")
    
    all_trades = np.array(all_trades)
    w = all_trades[all_trades > 0]
    ls = all_trades[all_trades <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 else 999
    
    print(f"\n{'=' * 120}")
    print("COMBINED PORTFOLIO")
    print(f"{'=' * 120}")
    print(f"Trades: {len(all_trades)}")
    print(f"Expectancy: {all_trades.mean()*100:.3f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Win Rate: {(all_trades > 0).mean()*100:.1f}%")
    print(f"Avg Win: {w.mean()*100:.2f}%")
    print(f"Avg Loss: {abs(ls.mean())*100:.2f}%")
    
    # Monte Carlo
    np.random.seed(42)
    mc = []
    for _ in range(10000):
        sampled = np.random.choice(all_trades, size=30, replace=True)
        mc.append(sampled.sum())
    mc = np.array(mc)
    
    print(f"\nMonte Carlo (12mo, ~{len(all_trades)/12:.1f} trades/month):")
    print(f"  Mean: {mc.mean()*100:.1f}%")
    print(f"  5th pctl: {np.percentile(mc, 5)*100:.1f}%")
    print(f"  Prob > 0: {(mc > 0).mean()*100:.1f}%")
    print(f"  Prob > 50%: {(mc > 0.5).mean()*100:.1f}%")
