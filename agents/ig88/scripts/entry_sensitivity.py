"""
Entry Sensitivity Test
=======================
How does performance change if entry is delayed?
- T0: Immediate (we know this loses)
- T1: 1 bar delay (current production)
- T2: 2 bar delay (current production)
- T3, T4, T5: Longer delays

Tests whether waiting too long degrades the edge.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0133

PAIRS = {
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8, 'target': 0.15, 'stop': 'fixed_0.75'},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3, 'target': 0.15, 'stop': 'fixed_0.5'},
}

ENTRY_DELAYS = [0, 1, 2, 3, 4, 5]


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_l = sma20 - std20 * 1.5
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    return c, o, h, l, rsi, bb_l, vol_ratio, atr


def get_stop_distance(stop_type, entry_price, atr_value):
    if stop_type == 'fixed_0.5':
        return entry_price * 0.005
    elif stop_type == 'fixed_0.75':
        return entry_price * 0.0075
    return entry_price * 0.005


def run_backtest(pair, params, entry_delay):
    df = load_data(pair)
    c, o, h, l, rsi, bb_l, vol_ratio, atr = compute_indicators(df)
    
    trades = []
    for i in range(100, len(c) - 17):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]) or np.isnan(atr[i]):
            continue
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + entry_delay
            if entry_bar >= len(c) - 15:
                continue
            entry_price = o[entry_bar]
            stop_dist = get_stop_distance(params['stop'], entry_price, atr[entry_bar])
            stop_price = entry_price - stop_dist
            target_price = entry_price * (1 + params['target'])
            for j in range(1, 16):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-stop_dist/entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(params['target'] - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    return np.array(trades)


def calc_stats(t):
    if len(t) < 5:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0, 'sharpe': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'exp': round(float(t.mean() * 100), 3),
        'wr': round(float(len(w) / len(t) * 100), 1),
        'sharpe': round(float(sharpe), 2),
    }


print("=" * 90)
print("ENTRY SENSITIVITY TEST: How much does delay hurt?")
print("=" * 90)

for pair, params in PAIRS.items():
    print(f"\n{'─' * 90}")
    print(f"{pair}")
    print(f"{'─' * 90}")
    print(f"{'Delay':<8} {'N':<8} {'PF':<10} {'Exp%':<12} {'WR':<10} {'Sharpe':<10} {'Change'}")
    print("-" * 70)
    
    base_exp = None
    for delay in ENTRY_DELAYS:
        trades = run_backtest(pair, params, delay)
        stats = calc_stats(trades)
        
        if base_exp is None and stats['exp'] != 0:
            base_exp = stats['exp']
        
        change = ""
        if base_exp and stats['exp'] != 0:
            pct_change = ((stats['exp'] - base_exp) / abs(base_exp)) * 100
            change = f"{pct_change:+.0f}%"
        
        verdict = "PROD" if delay == 2 else ""
        print(f"T{delay:<7} {stats['n']:<8} {stats['pf']:<10.3f} {stats['exp']:<11.3f}% {stats['wr']:<9.1f}% {stats['sharpe']:<9.2f} {change} {verdict}")

print(f"\n{'=' * 90}")
print("CONCLUSION: Optimal entry delay")
print(f"{'=' * 90}")
