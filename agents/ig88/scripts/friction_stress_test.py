"""
Friction Stress Test: Finding the Breakdown Point
===================================================
Test ALL 12 pairs across 0.5%, 1.0%, 1.5%, 2.0% round-trip friction.
Determine exactly where each pair becomes unprofitable.

Crypto spreads can be brutal — we need to know where this falls apart.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# All 12 validated pairs with their optimal MR parameters
PAIRS = {
    'SOL':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.10},
    'NEAR': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
    'LINK': {'rsi': 30, 'bb': 2.0, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.15},
    'AVAX': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
    'ATOM': {'rsi': 30, 'bb': 1.5, 'vol': 1.5, 'entry': 1, 'stop': 0.005, 'target': 0.125},
    'UNI':  {'rsi': 40, 'bb': 1.5, 'vol': 2.0, 'entry': 2, 'stop': 0.005, 'target': 0.15},
    'AAVE': {'rsi': 35, 'bb': 1.5, 'vol': 1.5, 'entry': 1, 'stop': 0.005, 'target': 0.15},
    'ARB':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.15},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3, 'entry': 1, 'stop': 0.005, 'target': 0.15},
    'INJ':  {'rsi': 30, 'bb': 1.0, 'vol': 1.5, 'entry': 2, 'stop': 0.005, 'target': 0.075},
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.15},
    'POL':  {'rsi': 35, 'bb': 1.0, 'vol': 1.3, 'entry': 2, 'stop': 0.005, 'target': 0.10},
}

# Friction levels to test (in decimal)
FRICTION_LEVELS = [0.0025, 0.005, 0.01, 0.015, 0.02]
FRICTION_LABELS = ['0.25%', '0.50%', '1.00%', '1.50%', '2.00%']

# H3 strategies (SOL, AVAX only)
H3A_PAIRS = ['SOL']
H3B_PAIRS = ['SOL', 'AVAX']


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
    
    # Ichimoku for H3
    tenkan = (pd.Series(h).rolling(9).max() + pd.Series(l).rolling(9).min()) / 2
    kijun = (pd.Series(h).rolling(26).max() + pd.Series(l).rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((pd.Series(h).rolling(52).max() + pd.Series(l).rolling(52).min()) / 2).shift(26)
    
    # BTC regime
    btc_df = load_data('BTC')
    btc_c = btc_df['close'].values
    btc_20ret = np.full(len(c), np.nan)
    btc_ret = pd.Series(btc_c).pct_change(20).values
    min_len = min(len(btc_ret), len(c))
    btc_20ret[:min_len] = btc_ret[:min_len]
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'sma20': sma20, 'std20': std20, 'vol_ratio': vol_ratio,
        'tenkan': tenkan.values, 'kijun': kijun.values,
        'senkou_a': senkou_a.values, 'senkou_b': senkou_b.values,
        'btc_20ret': btc_20ret,
    }


def run_mr_backtest(ind, params, friction):
    """Run MR backtest with specified friction."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20, vol_ratio = ind['rsi'], ind['sma20'], ind['std20'], ind['vol_ratio']
    bb_l = sma20 - std20 * params['bb']
    
    trades = []
    for i in range(100, len(c) - params['entry'] - 8):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['entry']
            if entry_bar >= len(c) - 8:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price * (1 - params['stop'])
            target_price = entry_price * (1 + params['target'])
            
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-params['stop'] - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(params['target'] - friction)
                    break
            else:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades) if trades else np.array([])


def run_h3a_backtest(ind, friction):
    """Run H3-A backtest with specified friction."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    tenkan, kijun = ind['tenkan'], ind['kijun']
    senkou_a, senkou_b = ind['senkou_a'], ind['senkou_b']
    rsi = ind['rsi']
    btc_20ret = ind['btc_20ret']
    
    trades = []
    for i in range(100, len(c) - 11):
        if np.isnan(rsi[i]) or np.isnan(tenkan[i]) or np.isnan(kijun[i]):
            continue
        if np.isnan(senkou_a[i]) or np.isnan(senkou_b[i]):
            continue
        if not np.isnan(btc_20ret[i]) and btc_20ret[i] < 0:
            continue
        
        tk_cross = tenkan[i] > kijun[i]
        cloud_top = np.nanmax([senkou_a[i], senkou_b[i]])
        above_cloud = c[i] > cloud_top
        rsi_ok = rsi[i] > 40
        
        if not (tk_cross and above_cloud and rsi_ok):
            continue
        
        entry_bar = i + 1
        entry_price = o[entry_bar]
        
        for j in range(1, 11):
            bar = entry_bar + j
            if bar >= len(c):
                break
            if c[bar] < c[entry_bar] * 0.98:  # 2% stop
                trades.append(-0.02 - friction)
                break
            if c[bar] > c[entry_bar] * 1.05:  # 5% target
                trades.append(0.05 - friction)
                break
        else:
            exit_price = c[min(entry_bar + 10, len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades) if trades else np.array([])


def run_h3b_backtest(ind, friction):
    """Run H3-B backtest with specified friction."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    vol_ratio = ind['vol_ratio']
    rsi = ind['rsi']
    btc_20ret = ind['btc_20ret']
    
    trades = []
    for i in range(100, len(c) - 11):
        if np.isnan(vol_ratio[i]) or np.isnan(rsi[i]):
            continue
        if i < 1:
            continue
        if not np.isnan(btc_20ret[i]) and btc_20ret[i] < 0:
            continue
        
        vol_spike = vol_ratio[i] > 1.5
        price_gain = (c[i] - c[i-1]) / c[i-1] > 0.005
        rsi_cross = rsi[i] > 50 and rsi[i-1] <= 50
        
        if not (vol_spike and price_gain and rsi_cross):
            continue
        
        entry_bar = i + 1
        entry_price = o[entry_bar]
        
        for j in range(1, 11):
            bar = entry_bar + j
            if bar >= len(c):
                break
            if c[bar] < c[entry_bar] * 0.98:
                trades.append(-0.02 - friction)
                break
            if c[bar] > c[entry_bar] * 1.08:
                trades.append(0.08 - friction)
                break
        else:
            exit_price = c[min(entry_bar + 10, len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades) if trades else np.array([])


def calc_stats(trades):
    if len(trades) < 5:
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
print("FRICTION STRESS TEST: FINDING THE BREAKDOWN POINT")
print("=" * 100)
print(f"\nTesting {len(PAIRS)} pairs x {len(FRICTION_LEVELS)} friction levels")
print(f"Friction levels: {', '.join(FRICTION_LABELS)}")
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
print()

# ============================================================================
# MR STRATEGY STRESS TEST
# ============================================================================
print("=" * 100)
print("MR STRATEGY: ALL PAIRS ACROSS FRICTION LEVELS")
print("=" * 100)

mr_results = {}

for pair, params in PAIRS.items():
    print(f"\n{'─' * 80}")
    print(f"{pair}")
    print(f"{'─' * 80}")
    
    df = load_data(pair)
    ind = compute_indicators(df)
    
    mr_results[pair] = {}
    
    print(f"{'Friction':<12} {'N':<6} {'PF':<8} {'WR':<8} {'Exp%':<10} {'Sharpe':<8} {'Total%':<10} {'Status'}")
    print("─" * 75)
    
    for friction, label in zip(FRICTION_LEVELS, FRICTION_LABELS):
        trades = run_mr_backtest(ind, params, friction)
        stats = calc_stats(trades)
        mr_results[pair][label] = stats
        
        if stats['n'] < 10:
            status = "INSUFFICIENT"
        elif stats['pf'] < 1.0:
            status = "UNPROFITABLE ✗"
        elif stats['exp'] <= 0:
            status = "BREAKEVEN ~"
        else:
            status = "PROFITABLE ✓"
        
        print(f"{label:<12} {stats['n']:<6} {stats['pf']:<8.3f} {stats['wr']:<7.1f}% {stats['exp']:<9.3f}% {stats['sharpe']:<7.2f} {stats['total']:<9.2f}% {status}")


# ============================================================================
# H3 STRATEGY STRESS TEST (SOL, AVAX)
# ============================================================================
print("\n" + "=" * 100)
print("H3 STRATEGY: SOL + AVAX ACROSS FRICTION LEVELS")
print("=" * 100)

h3_results = {'H3-A': {}, 'H3-B': {}}

for pair in ['SOL', 'AVAX']:
    print(f"\n{'─' * 80}")
    print(f"{pair}")
    print(f"{'─' * 80}")
    
    df = load_data(pair)
    ind = compute_indicators(df)
    
    if pair in H3A_PAIRS:
        print(f"\n  H3-A (Ichimoku):")
        print(f"  {'Friction':<12} {'N':<6} {'PF':<8} {'WR':<8} {'Exp%':<10} {'Status'}")
        print("  " + "─" * 60)
        
        h3_results['H3-A'][pair] = {}
        for friction, label in zip(FRICTION_LEVELS, FRICTION_LABELS):
            trades = run_h3a_backtest(ind, friction)
            stats = calc_stats(trades)
            h3_results['H3-A'][pair][label] = stats
            
            if stats['n'] < 10:
                status = "INSUFFICIENT"
            elif stats['pf'] < 1.0:
                status = "UNPROFITABLE ✗"
            elif stats['exp'] <= 0:
                status = "BREAKEVEN ~"
            else:
                status = "PROFITABLE ✓"
            
            print(f"  {label:<12} {stats['n']:<6} {stats['pf']:<8.3f} {stats['wr']:<7.1f}% {stats['exp']:<9.3f}% {status}")
    
    if pair in H3B_PAIRS:
        print(f"\n  H3-B (Volume Ignition):")
        print(f"  {'Friction':<12} {'N':<6} {'PF':<8} {'WR':<8} {'Exp%':<10} {'Status'}")
        print("  " + "─" * 60)
        
        h3_results['H3-B'][pair] = {}
        for friction, label in zip(FRICTION_LEVELS, FRICTION_LABELS):
            trades = run_h3b_backtest(ind, friction)
            stats = calc_stats(trades)
            h3_results['H3-B'][pair][label] = stats
            
            if stats['n'] < 10:
                status = "INSUFFICIENT"
            elif stats['pf'] < 1.0:
                status = "UNPROFITABLE ✗"
            elif stats['exp'] <= 0:
                status = "BREAKEVEN ~"
            else:
                status = "PROFITABLE ✓"
            
            print(f"  {label:<12} {stats['n']:<6} {stats['pf']:<8.3f} {stats['wr']:<7.1f}% {stats['exp']:<9.3f}% {status}")


# ============================================================================
# BREAKDOWN SUMMARY
# ============================================================================
print("\n" + "=" * 100)
print("BREAKDOWN SUMMARY: WHERE DOES EACH PAIR FAIL?")
print("=" * 100)

print("\nMR Strategy — Maximum Profitable Friction:")
print("─" * 60)
print(f"{'Pair':<10} {'0.25%':<10} {'0.50%':<10} {'1.00%':<10} {'1.50%':<10} {'2.00%':<10} {'Max Friction'}")
print("─" * 60)

for pair in PAIRS:
    row = f"{pair:<10}"
    max_friction = "0.25%"  # Default
    
    for label in FRICTION_LABELS:
        stats = mr_results[pair][label]
        if stats['exp'] > 0:
            row += f"{'✓':<10}"
            max_friction = label
        else:
            row += f"{'✗':<10}"
    
    row += f"  {max_friction}"
    print(row)


print("\nH3 Strategy — Maximum Profitable Friction:")
print("─" * 60)

for strategy in ['H3-A', 'H3-B']:
    for pair in ['SOL', 'AVAX']:
        if pair not in h3_results[strategy]:
            continue
        
        row = f"{strategy} {pair:<6}"
        max_friction = "0.25%"
        
        for label in FRICTION_LABELS:
            stats = h3_results[strategy][pair][label]
            if stats['exp'] > 0:
                row += f"{'✓':<10}"
                max_friction = label
            else:
                row += f"{'✗':<10}"
        
        row += f"  {max_friction}"
        print(row)


# ============================================================================
# PORTFOLIO EXPECTANCY AT EACH FRICTION LEVEL
# ============================================================================
print("\n" + "=" * 100)
print("PORTFOLIO EXPECTANCY AT EACH FRICTION LEVEL")
print("=" * 100)

print(f"\n{'Friction':<12} {'Avg Exp%':<12} {'Min Exp%':<12} {'Max Exp%':<12} {'Pairs Profitable'}")
print("─" * 70)

for label in FRICTION_LABELS:
    exps = []
    profitable = 0
    
    for pair in PAIRS:
        exp = mr_results[pair][label]['exp']
        exps.append(exp)
        if exp > 0:
            profitable += 1
    
    avg_exp = np.mean(exps)
    min_exp = np.min(exps)
    max_exp = np.max(exps)
    
    print(f"{label:<12} {avg_exp:>8.3f}%    {min_exp:>8.3f}%    {max_exp:>8.3f}%    {profitable}/{len(PAIRS)}")


# ============================================================================
# RECOMMENDATIONS
# ============================================================================
print("\n" + "=" * 100)
print("RECOMMENDATIONS")
print("=" * 100)

print("""
Based on the stress test:

1. POSITION SIZING: Reduce position size proportionally as friction increases.
   If friction doubles, halve position size to maintain risk-adjusted returns.

2. PAIR SELECTION: At higher friction (>1%), prioritize pairs with higher
   expectancy and wider targets (LINK, AVAX, SUI, OP).

3. EXECUTION: Use limit orders wherever possible to minimize slippage.
   Market orders during high-vol periods can easily add 0.5%+ slippage.

4. VENUE SELECTION: If Jupiter Perps fees exceed 1.5%, consider:
   - Switching to spot (if spread is tighter)
   - Using DEX aggregator for better routing
   - Waiting for lower-vol periods to execute

5. STOP ADJUSTMENT: At higher friction, consider widening stops slightly
   to avoid getting stopped out by noise + friction combined.
""")
