"""
Optimal Portfolio: Strict Validation + Session Filter
======================================================
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

ALL_PAIRS = ['AAVE', 'ARB', 'ATOM', 'AVAX', 'BTC', 'ETH', 'INJ', 'LINK', 'NEAR', 'OP', 'POL', 'SOL', 'SUI', 'UNI']


def get_session(hour):
    if 0 <= hour < 8:
        return 'ASIA'
    elif 8 <= hour < 13:
        return 'LONDON'
    elif 13 <= hour < 16:
        return 'LONDON_NY'
    elif 16 <= hour < 21:
        return 'NY'
    else:
        return 'OFF_HOURS'


def load_data(pair):
    df = pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')
    if isinstance(df.index, pd.DatetimeIndex):
        df['session'] = df.index.hour.map(get_session)
    else:
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


def run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, friction, filter_session=False):
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        
        # ASIA session filter
        if filter_session and session[i] != 'ASIA':
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
print("OPTIMAL PORTFOLIO: Strict Validation + ASIA Session Filter")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

print(f"\n{'Pair':<10} {'ALL':<20} {'ASIA':<20} {'Improvement'}")
print("-" * 70)

results = []

for pair in ALL_PAIRS:
    try:
        df = load_data(pair)
    except:
        continue
    
    c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
    
    # Test ALL sessions
    all_trades = run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, FRICTION, False)
    all_stats = calc_stats(all_trades)
    
    # Test ASIA only
    asia_trades = run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, FRICTION, True)
    asia_stats = calc_stats(asia_trades)
    
    improvement = ((asia_stats['exp'] - all_stats['exp']) / abs(all_stats['exp']) * 100) if all_stats['exp'] != 0 else 0
    
    print(f"{pair:<10} N={all_stats['n']:<2} {all_stats['exp']:>5.2f}%  N={asia_stats['n']:<2} {asia_stats['exp']:>5.2f}%  {improvement:>+.0f}%")
    
    results.append({
        'pair': pair,
        'all': all_stats,
        'asia': asia_stats,
    })

# Find strict valid with session filter
print(f"\n{'=' * 120}")
print("STRICT VALID WITH ASIA FILTER")
print(f"{'=' * 120}")

strict_asia_valid = []

for r in results:
    pair = r['pair']
    try:
        df = load_data(pair)
    except:
        continue
    
    n = len(df)
    train_end = int(n * 0.6)
    test_end = int(n * 0.8)
    
    c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
    
    train = run_mr_backtest(c[:train_end], o[:train_end], h[:train_end], l[:train_end],
                            rsi[:train_end], bb_lower[:train_end], atr[:train_end], 
                            vol_ratio[:train_end], session[:train_end], FRICTION, True)
    test = run_mr_backtest(c[train_end:test_end], o[train_end:test_end], h[train_end:test_end], l[train_end:test_end],
                           rsi[train_end:test_end], bb_lower[train_end:test_end], atr[train_end:test_end],
                           vol_ratio[train_end:test_end], session[train_end:test_end], FRICTION, True)
    val = run_mr_backtest(c[test_end:], o[test_end:], h[test_end:], l[test_end:],
                          rsi[test_end:], bb_lower[test_end:], atr[test_end:],
                          vol_ratio[test_end:], session[test_end:], FRICTION, True)
    
    train_s = calc_stats(train)
    test_s = calc_stats(test)
    val_s = calc_stats(val)
    
    total = train_s['n'] + test_s['n'] + val_s['n']
    
    all_pos = (train_s['exp'] > 0 and train_s['n'] >= 3 and
               test_s['exp'] > 0 and test_s['n'] >= 2 and
               val_s['exp'] > 0 and val_s['n'] >= 2)
    
    if all_pos and total >= 10:
        strict_asia_valid.append(pair)
        print(f"{pair:<10} Train: N={train_s['n']} {train_s['exp']:.2f}%  Test: N={test_s['n']} {test_s['exp']:.2f}%  Val: N={val_s['n']} {val_s['exp']:.2f}%  STRICT VALID")
    else:
        print(f"{pair:<10} Train: N={train_s['n']} {train_s['exp']:.2f}%  Test: N={test_s['n']} {test_s['exp']:.2f}%  Val: N={val_s['n']} {val_s['exp']:.2f}%")

# Final portfolio
print(f"\n{'=' * 120}")
print("FINAL OPTIMAL PORTFOLIO (Strict Valid + ASIA Session)")
print(f"{'=' * 120}")

if strict_asia_valid:
    all_trades = []
    
    for pair in strict_asia_valid:
        df = load_data(pair)
        c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
        trades = run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, FRICTION, True)
        stats = calc_stats(trades)
        all_trades.extend(trades.tolist())
        print(f"{pair:<10} N={stats['n']:<4} Exp={stats['exp']:>6.2f}%  PF={stats['pf']:<5.2f} WR={stats['wr']:.0f}%")
    
    all_trades = np.array(all_trades)
    w = all_trades[all_trades > 0]
    ls = all_trades[all_trades <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 else 999
    
    print(f"\nTOTAL: {len(all_trades)} trades")
    print(f"Expectancy: {all_trades.mean()*100:.3f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Win Rate: {(all_trades > 0).mean()*100:.1f}%")
    
    # Monte Carlo
    np.random.seed(42)
    mc = []
    for _ in range(10000):
        size = max(5, int(len(all_trades) * 0.5))
        sampled = np.random.choice(all_trades, size=size, replace=True)
        mc.append(sampled.sum())
    mc = np.array(mc)
    
    print(f"\nMonte Carlo (12mo):")
    print(f"  Mean: {mc.mean()*100:.1f}%")
    print(f"  5th pctl: {np.percentile(mc, 5)*100:.1f}%")
    print(f"  Prob > 0: {(mc > 0).mean()*100:.1f}%")
else:
    print("No pairs pass strict validation with ASIA filter")
