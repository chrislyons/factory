"""
Multi-Timeframe Validation: SUI + OP
======================================
Test SUI and OP on 1h and 2h timeframes.
4h is validated; checking if other TFs add edge.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0133

# Timeframes to test
TIMEFRAMES = ['60m', '120m', '240m']

# Pair configs
PAIRS = {
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8, 'entry': 2, 'target': 0.15, 'stop': 'fixed_0.75'},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3, 'entry': 2, 'target': 0.15, 'stop': 'fixed_0.5'},
}


def load_data(pair, tf):
    path = DATA_DIR / f'binance_{pair}_USDT_{tf}.parquet'
    if not path.exists():
        return None
    return pd.read_parquet(path)


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


def run_backtest(pair, params, df):
    c, o, h, l, rsi, bb_l, vol_ratio, atr = compute_indicators(df)
    trades = []
    for i in range(100, len(c) - 17):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]) or np.isnan(atr[i]):
            continue
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['entry']
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
        return {'n': len(t), 'pf': 0, 'wr': 0, 'exp': 0, 'sharpe': 0, 'max_dd': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    cumsum = np.cumsum(t)
    max_dd = np.max(np.maximum.accumulate(cumsum) - cumsum)
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(t)*100), 1),
        'exp': round(float(t.mean()*100), 3),
        'sharpe': round(float(sharpe), 2),
        'max_dd': round(float(max_dd * 100), 2),
    }


print("=" * 90)
print("MULTI-TIMEFRAME VALIDATION: SUI + OP")
print("=" * 90)

results = {}

for pair, params in PAIRS.items():
    print(f"\n{'─' * 90}")
    print(f"{pair}")
    print(f"{'─' * 90}")
    print(f"{'TF':<8} {'N':<8} {'PF':<10} {'WR':<10} {'Exp%':<12} {'Sharpe':<10} {'MaxDD':<10} {'Verdict'}")
    print("-" * 80)
    
    results[pair] = {}
    
    for tf in TIMEFRAMES:
        df = load_data(pair, tf)
        if df is None:
            print(f"{tf:<8} {'NO DATA':<60}")
            continue
        
        trades = run_backtest(pair, params, df)
        stats = calc_stats(trades)
        results[pair][tf] = stats
        
        verdict = "PROD" if stats['pf'] > 1.5 and stats['exp'] > 0.5 and stats['n'] >= 50 else "TEST" if stats['exp'] > 0 else "FAIL"
        print(f"{tf:<8} {stats['n']:<8} {stats['pf']:<10.3f} {stats['wr']:<9.1f}% {stats['exp']:<11.3f}% {stats['sharpe']:<9.2f} {stats['max_dd']:<9.2f}% {verdict}")

print(f"\n{'=' * 90}")
print("TIMEFRAME COMPARISON SUMMARY")
print(f"{'=' * 90}")

for pair in PAIRS:
    print(f"\n{pair}:")
    best_tf = None
    best_exp = -999
    for tf in TIMEFRAMES:
        if tf in results[pair]:
            exp = results[pair][tf]['exp']
            pf = results[pair][tf]['pf']
            print(f"  {tf}: Exp={exp:.3f}%, PF={pf:.3f}")
            if exp > best_exp and pf > 1.0:
                best_exp = exp
                best_tf = tf
    if best_tf:
        print(f"  -> Best timeframe: {best_tf}")
