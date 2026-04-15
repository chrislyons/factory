"""
Session Filtering: Validated Pairs Only
=========================================
Tests session edge on ARB, ATOM, AVAX, AAVE, SUI.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Validated pairs
VALIDATED = ['ARB', 'ATOM', 'AVAX', 'AAVE', 'SUI']


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
        if 'timestamp' in df.columns:
            df['session'] = pd.to_datetime(df['timestamp'], unit='s').dt.hour.map(get_session)
        else:
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


def run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, session_filter=None):
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        if session_filter and session[i] not in session_filter:
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
                    trades.append(-atr[entry_bar] * 0.75 / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * 2.5 / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    return np.array(trades)


def calc_stats(t):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


print("=" * 120)
print("SESSION FILTERING: Validated Pairs (ARB, ATOM, AVAX, AAVE, SUI)")
print("=" * 120)

sessions = {
    'ALL': None,
    'ASIA': ['ASIA'],
    'LONDON': ['LONDON'],
    'NY': ['NY'],
    'LONDON+NY': ['LONDON', 'NY', 'LONDON_NY'],
    'ASIA+LONDON': ['ASIA', 'LONDON', 'LONDON_NY'],
    'ASIA+NY': ['ASIA', 'NY'],
}

all_results = {}

for session_name, session_filter in sessions.items():
    all_trades = []
    
    for pair in VALIDATED:
        df = load_data(pair)
        c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
        trades = run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, session_filter)
        all_trades.extend(trades.tolist())
    
    all_trades = np.array(all_trades)
    if len(all_trades) >= 5:
        stats = calc_stats(all_trades)
        all_results[session_name] = stats
        
        # Monte Carlo
        np.random.seed(42)
        mc_results = []
        for _ in range(5000):
            sampled = np.random.choice(all_trades, size=30, replace=True)
            mc_results.append(sampled.sum())
        mc_results = np.array(mc_results)
        
        print(f"\n{session_name}:")
        print(f"  Trades: {stats['n']}")
        print(f"  Expectancy: {stats['exp']:.3f}%")
        print(f"  PF: {stats['pf']}")
        print(f"  WR: {stats['wr']}%")
        print(f"  Monte Carlo (12mo): Mean={mc_results.mean()*100:.1f}%, Prob>0={(mc_results>0).mean()*100:.1f}%")

# Comparison
print(f"\n{'=' * 120}")
print("SESSION COMPARISON")
print(f"{'=' * 120}")

print(f"\n{'Session':<15} {'N':<8} {'Exp%':<10} {'PF':<8} {'WR%':<8} {'vs ALL'}")
print("-" * 60)

base_exp = all_results['ALL']['exp'] if 'ALL' in all_results else 0

for session_name, stats in all_results.items():
    vs_base = stats['exp'] - base_exp
    print(f"{session_name:<15} {stats['n']:<8} {stats['exp']:>7.3f}%  {stats['pf']:<8.2f} {stats['wr']:<8.1f} {vs_base:>+.3f}%")

# Walk-forward on best session
print(f"\n{'=' * 120}")
print("WALK-FORWARD: Best Session Filter")
print(f"{'=' * 120}")

# Find best session
best_session = max(all_results.items(), key=lambda x: x[1]['exp'] if x[1]['n'] >= 30 else -999)[0]
print(f"\nBest session filter: {best_session}")
print(f"Running walk-forward validation...")

wf_results = []
for pair in VALIDATED:
    df = load_data(pair)
    n = len(df)
    train_end = int(n * 0.6)
    test_end = int(n * 0.8)
    
    c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
    
    filter_val = sessions[best_session]
    
    train_trades = run_mr_backtest(
        c[:train_end], o[:train_end], h[:train_end], l[:train_end],
        rsi[:train_end], bb_lower[:train_end], atr[:train_end], 
        vol_ratio[:train_end], session[:train_end], filter_val
    )
    
    test_trades = run_mr_backtest(
        c[train_end:test_end], o[train_end:test_end], h[train_end:test_end], l[train_end:test_end],
        rsi[train_end:test_end], bb_lower[train_end:test_end], atr[train_end:test_end],
        vol_ratio[train_end:test_end], session[train_end:test_end], filter_val
    )
    
    val_trades = run_mr_backtest(
        c[test_end:], o[test_end:], h[test_end:], l[test_end:],
        rsi[test_end:], bb_lower[test_end:], atr[test_end:],
        vol_ratio[test_end:], session[test_end:], filter_val
    )
    
    train_stats = calc_stats(train_trades)
    test_stats = calc_stats(test_trades)
    val_stats = calc_stats(val_trades)
    
    wf_results.append({
        'pair': pair,
        'train': train_stats,
        'test': test_stats,
        'val': val_stats,
    })

print(f"\n{'Pair':<8} {'Train':<20} {'Test':<20} {'Val':<20}")
print("-" * 70)

for r in wf_results:
    print(f"{r['pair']:<8} "
          f"N={r['train']['n']:<3} {r['train']['exp']:>5.2f}%   "
          f"N={r['test']['n']:<3} {r['test']['exp']:>5.2f}%   "
          f"N={r['val']['n']:<3} {r['val']['exp']:>5.2f}%")
