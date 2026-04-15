"""
Session Filtering: Does time-of-day affect MR edge?
====================================================
Tests if London/NY sessions produce better MR entries.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PAIRS = ['SUI', 'ARB', 'AAVE', 'AVAX', 'LINK', 'INJ', 'POL', 'SOL', 'NEAR', 'ATOM', 'UNI', 'OP']

# Session times in UTC
# London: 08:00-16:00 UTC
# New York: 13:00-21:00 UTC
# Asia: 00:00-08:00 UTC
# Overlap (London+NY): 13:00-16:00 UTC

def get_session(hour):
    """Return session based on hour (0-23 UTC)."""
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
    # Add session column based on index (assuming UTC timestamps)
    if isinstance(df.index, pd.DatetimeIndex):
        df['session'] = df.index.hour.map(get_session)
    else:
        # Try to extract from timestamp column
        df = df.reset_index()
        if 'timestamp' in df.columns:
            df['session'] = pd.to_datetime(df['timestamp'], unit='s').dt.hour.map(get_session)
        elif 'datetime' in df.columns:
            df['session'] = pd.to_datetime(df['datetime']).dt.hour.map(get_session)
        else:
            # Use index as hours (4h candles)
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
    
    session = df['session'].values if 'session' in df.columns else np.zeros(len(df))
    
    return c, o, h, l, rsi, bb_lower, atr, vol_ratio, session


def run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, friction, session_filter=None):
    """Run MR backtest with optional session filter."""
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        
        # Session filter
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
    if len(t) < 5:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


print("=" * 120)
print("SESSION FILTERING TEST: Does time-of-day affect MR edge?")
print("=" * 120)

sessions = {
    'ALL': None,
    'ASIA': ['ASIA'],
    'LONDON': ['LONDON'],
    'NY': ['NY'],
    'LONDON_NY': ['LONDON_NY'],
    'LONDON+NY': ['LONDON', 'NY', 'LONDON_NY'],
    'ASIA+LONDON': ['ASIA', 'LONDON', 'LONDON_NY'],
}

# Collect all trades per session
session_trades = {s: [] for s in sessions}

for pair in PAIRS:
    try:
        df = load_data(pair)
    except:
        continue
    
    c, o, h, l, rsi, bb_lower, atr, vol_ratio, session = compute_indicators(df)
    
    print(f"\n{pair}:")
    
    for session_name, session_filter in sessions.items():
        trades = run_mr_backtest(c, o, h, l, rsi, bb_lower, atr, vol_ratio, session, FRICTION, session_filter)
        
        if len(trades) > 0:
            stats = calc_stats(trades)
            session_trades[session_name].extend(trades.tolist())
            print(f"  {session_name:<12} N={stats['n']:<4} Exp={stats['exp']:>6.2f}%  PF={stats['pf']:<5.2f} WR={stats['wr']:.0f}%")
        else:
            print(f"  {session_name:<12} N=0")

# Summary
print(f"\n{'=' * 120}")
print("SESSION SUMMARY (all pairs combined)")
print(f"{'=' * 120}")

print(f"\n{'Session':<15} {'N':<8} {'Exp%':<10} {'PF':<8} {'WR%':<8} {'vs ALL'}")
print("-" * 60)

all_trades = np.array(session_trades['ALL']) if session_trades['ALL'] else np.array([])
all_exp = all_trades.mean() * 100 if len(all_trades) > 0 else 0

for session_name in sessions:
    trades = np.array(session_trades[session_name])
    if len(trades) >= 5:
        stats = calc_stats(trades)
        vs_all = ((stats['exp'] - all_exp) / abs(all_exp) * 100) if all_exp != 0 else 0
        print(f"{session_name:<15} {stats['n']:<8} {stats['exp']:>7.3f}%  {stats['pf']:<8.2f} {stats['wr']:<8.1f} {vs_all:>+.1f}%")

# Best session analysis
print(f"\n{'=' * 120}")
print("BEST SESSION RECOMMENDATION")
print(f"{'=' * 120}")

best_session = None
best_exp = -999

for session_name in ['ASIA', 'LONDON', 'NY', 'LONDON_NY', 'LONDON+NY']:
    trades = np.array(session_trades[session_name])
    if len(trades) >= 10:
        exp = trades.mean() * 100
        if exp > best_exp:
            best_exp = exp
            best_session = session_name

if best_session:
    trades = np.array(session_trades[best_session])
    stats = calc_stats(trades)
    print(f"\nBest session: {best_session}")
    print(f"  Trades: {stats['n']}")
    print(f"  Expectancy: {stats['exp']:.3f}%")
    print(f"  PF: {stats['pf']}")
    print(f"  WR: {stats['wr']}%")
    print(f"  Improvement over ALL: {(stats['exp'] - all_exp):.3f}%")
