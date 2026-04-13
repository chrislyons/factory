"""
Entry Timing Validation: T0 vs T1 vs T2
=========================================
Test whether entering immediately (T0), 1 bar later (T1), or 2 bars later (T2)
produces better results across all 12 pairs.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

PAIRS = {
    'SOL':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'stop': 0.005, 'target': 0.10},
    'NEAR': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'stop': 0.005, 'target': 0.125},
    'LINK': {'rsi': 30, 'bb': 2.0, 'vol': 1.8, 'stop': 0.005, 'target': 0.15},
    'AVAX': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'stop': 0.005, 'target': 0.125},
    'ATOM': {'rsi': 30, 'bb': 1.5, 'vol': 1.5, 'stop': 0.005, 'target': 0.125},
    'UNI':  {'rsi': 40, 'bb': 1.5, 'vol': 2.0, 'stop': 0.005, 'target': 0.15},
    'AAVE': {'rsi': 35, 'bb': 1.5, 'vol': 1.5, 'stop': 0.005, 'target': 0.15},
    'ARB':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'stop': 0.005, 'target': 0.15},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3, 'stop': 0.005, 'target': 0.15},
    'INJ':  {'rsi': 30, 'bb': 1.0, 'vol': 1.5, 'stop': 0.005, 'target': 0.075},
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8, 'stop': 0.005, 'target': 0.15},
    'POL':  {'rsi': 35, 'bb': 1.0, 'vol': 1.3, 'stop': 0.005, 'target': 0.10},
}

ENTRY_DELAYS = [0, 1, 2]  # T0, T1, T2


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
    return {
        'c': c, 'o': df['open'].values, 'h': df['high'].values, 'l': df['low'].values,
        'rsi': rsi, 'sma20': sma20, 'std20': std20, 'vol_ratio': vol_ratio,
    }


def run_backtest(ind, params, entry_delay, max_holding=15):
    """Run MR backtest with specified entry delay."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20, vol_ratio = ind['rsi'], ind['sma20'], ind['std20'], ind['vol_ratio']
    bb_l = sma20 - std20 * params['bb']
    
    trades = []
    entry_prices = []  # Track actual entry prices for analysis
    
    for i in range(100, len(c) - entry_delay - max_holding):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        
        # Check signal on bar i
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            # Enter at entry_delay bars later
            entry_bar = i + entry_delay
            if entry_bar >= len(c) - max_holding:
                continue
            
            entry_price = o[entry_bar]  # Enter at open of entry bar
            stop_price = entry_price * (1 - params['stop'])
            target_price = entry_price * (1 + params['target'])
            
            # Check price action after entry
            for j in range(1, max_holding + 1):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-params['stop'] - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(params['target'] - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + max_holding, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades) if trades else np.array([])


def calc_stats(trades):
    if len(trades) < 10:
        return {'n': len(trades), 'pf': 0, 'wr': 0, 'exp': 0, 'sharpe': 0, 'total': 0}
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
        'total': round(float(t.sum() * 100), 2),
    }


print("=" * 100)
print("ENTRY TIMING VALIDATION: T0 vs T1 vs T2")
print("=" * 100)
print(f"\nTesting {len(PAIRS)} pairs x 3 entry delays")
print()

results = {}

for pair, params in PAIRS.items():
    df = load_data(pair)
    ind = compute_indicators(df)
    
    results[pair] = {}
    
    print(f"\n{'─' * 70}")
    print(f"{pair}")
    print(f"{'─' * 70}")
    print(f"{'Entry':<8} {'N':<6} {'PF':<8} {'WR':<8} {'Exp%':<10} {'Sharpe':<8} {'Total%':<10}")
    print("─" * 60)
    
    for delay in ENTRY_DELAYS:
        trades = run_backtest(ind, params, delay)
        stats = calc_stats(trades)
        results[pair][f'T{delay}'] = stats
        
        label = f"T{delay}"
        best_marker = ""
        print(f"{label:<8} {stats['n']:<6} {stats['pf']:<8.3f} {stats['wr']:<7.1f}% {stats['exp']:<9.3f}% {stats['sharpe']:<7.2f} {stats['total']:<9.2f}%")


# ============================================================================
# WINNER ANALYSIS
# ============================================================================
print("\n" + "=" * 100)
print("ENTRY TIMING WINNER BY PAIR")
print("=" * 100)

print(f"\n{'Pair':<10} {'T0 Exp%':<12} {'T1 Exp%':<12} {'T2 Exp%':<12} {'Winner':<8} {'T0→T1 Δ':<10}")
print("-" * 70)

t0_wins = 0
t1_wins = 0
t2_wins = 0

for pair in PAIRS:
    t0_exp = results[pair]['T0']['exp']
    t1_exp = results[pair]['T1']['exp']
    t2_exp = results[pair]['T2']['exp']
    
    best = max([('T0', t0_exp), ('T1', t1_exp), ('T2', t2_exp)], key=lambda x: x[1])
    winner = best[0]
    
    if winner == 'T0':
        t0_wins += 1
    elif winner == 'T1':
        t1_wins += 1
    else:
        t2_wins += 1
    
    delta = t1_exp - t0_exp
    delta_str = f"{delta:+.3f}%"
    
    print(f"{pair:<10} {t0_exp:>8.3f}%    {t1_exp:>8.3f}%    {t2_exp:>8.3f}%    {winner:<8} {delta_str}")

print(f"\nSummary: T0 wins {t0_wins}x, T1 wins {t1_wins}x, T2 wins {t2_wins}x")


# ============================================================================
# PORTFOLIO LEVEL
# ============================================================================
print("\n" + "=" * 100)
print("PORTFOLIO LEVEL COMPARISON")
print("=" * 100)

print(f"\n{'Metric':<20} {'T0':<15} {'T1':<15} {'T2':<15}")
print("-" * 65)

# Total trades
for metric, key in [('Total Trades', 'n'), ('Avg Exp%', 'exp'), ('Avg Sharpe', 'sharpe')]:
    t0_vals = [results[p]['T0'][key] for p in PAIRS]
    t1_vals = [results[p]['T1'][key] for p in PAIRS]
    t2_vals = [results[p]['T2'][key] for p in PAIRS]
    
    if key == 'n':
        print(f"{metric:<20} {sum(t0_vals):<15} {sum(t1_vals):<15} {sum(t2_vals):<15}")
    else:
        print(f"{metric:<20} {np.mean(t0_vals):>8.3f}%      {np.mean(t1_vals):>8.3f}%      {np.mean(t2_vals):>8.3f}%")


# ============================================================================
# RECOMMENDATIONS
# ============================================================================
print("\n" + "=" * 100)
print("RECOMMENDATIONS")
print("=" * 100)

winner_pct = {'T0': t0_wins/len(PAIRS)*100, 'T1': t1_wins/len(PAIRS)*100, 'T2': t2_wins/len(PAIRS)*100}
best_entry = max(winner_pct, key=winner_pct.get)

print(f"""
1. WINNER: {best_entry} ({winner_pct[best_entry]:.0f}% of pairs)

2. KEY INSIGHT:
   - Immediate entry (T0) captures the full bounce
   - Delayed entry (T1/T2) means chasing price
   - But T0 has more exposure to sudden reversals

3. PRACTICAL RECOMMENDATION:
   - Use {best_entry} for all pairs
   - Exception: If spread > 0.3%, use T1 to avoid slippage on entry
   
4. EXECUTION STRATEGY:
   - Place limit order at open of entry bar
   - If not filled within 1 bar, cancel and skip
   - Never chase more than 0.5% from signal price
""")
