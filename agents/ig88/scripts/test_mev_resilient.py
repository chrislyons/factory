"""
MEV-Resilient Strategy Validation
===================================
Focus: Find stop/target combos that are:
1. Profitable (PF > 1.3)
2. MEV-safe (stop > 0.5%)
3. Statistically robust (CI doesn't include 0)
4. Stable across regimes (works in low/mid/high vol)

Then test portfolio construction with these params.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX']  # Focus on tradeable pairs
# BTC/ETH: market leaders only, 0% allocation

# MEV-safe stop levels (0.5% minimum to avoid sniper bots)
SAFE_STOPS = [0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02]

# Wide targets to maintain risk-reward
TARGETS = [0.05, 0.075, 0.10, 0.125, 0.15, 0.20]

# Optimal params from previous testing (starting point)
OPTIMAL_PARAMS = {
    'SOL':  {'rsi': 40, 'bb': 1.5, 'vol': 1.5, 'entry': 1},
    'NEAR': {'rsi': 40, 'bb': 1.0, 'vol': 1.5, 'entry': 1},
    'LINK': {'rsi': 38, 'bb': 0.5, 'vol': 1.1, 'entry': 0},
    'AVAX': {'rsi': 32, 'bb': 0.5, 'vol': 1.3, 'entry': 0},
}


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
    
    h, l = df['high'].values, df['low'].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'sma20': sma20, 'std20': std20,
        'vol_ratio': vol_ratio, 'atr': atr, 'atr_pct': (atr / c) * 100,
    }


def run_backtest(ind, params, stop_pct, target_pct):
    """Run backtest with given parameters."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20 = ind['rsi'], ind['sma20'], ind['std20']
    vol_ratio = ind['vol_ratio']
    
    bb_l = sma20 - std20 * params['bb']
    entry_offset = params['entry']
    
    trades = []
    regimes = {'low': [], 'mid': [], 'high': []}
    
    for i in range(100, len(c) - entry_offset - 8):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + entry_offset
            if entry_bar >= len(c) - 8:
                continue
            
            entry = o[entry_bar]
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
            
            # Determine regime
            atr_pct = ind['atr_pct'][i] if not np.isnan(ind['atr_pct'][i]) else 3.0
            regime = 'low' if atr_pct < 2.0 else ('high' if atr_pct >= 4.0 else 'mid')
            
            exited = False
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                
                if l[bar] <= stop:
                    ret = -stop_pct - FRICTION
                    trades.append(ret)
                    regimes[regime].append(ret)
                    exited = True
                    break
                elif h[bar] >= target:
                    ret = target_pct - FRICTION
                    trades.append(ret)
                    regimes[regime].append(ret)
                    exited = True
                    break
            
            if not exited:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                ret = (exit_price - entry) / entry - FRICTION
                trades.append(ret)
                regimes[regime].append(ret)
    
    return trades, regimes


def calc_stats(trades):
    """Calculate statistics."""
    if len(trades) < 10:
        return None
    
    t = np.array(trades)
    w = t[t > 0]
    ls = t[t <= 0]
    
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    wr = len(w) / len(t) * 100
    exp = t.mean() * 100
    
    # Sharpe (annualized for 4h bars)
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    
    # Max drawdown
    equity = np.cumsum(t)
    running_max = np.maximum.accumulate(equity)
    max_dd = (running_max - equity).max() * 100
    
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'wr': round(float(wr), 1),
        'exp': round(float(exp), 3),
        'sharpe': round(float(sharpe), 2),
        'max_dd': round(float(max_dd), 1),
    }


def bootstrap_ci(trades, iterations=500):
    """Bootstrap confidence intervals."""
    t = np.array(trades)
    if len(t) < 10:
        return {'pf_ci': (0, 0), 'exp_ci': (0, 0)}
    
    pfs = []
    exps = []
    
    for _ in range(iterations):
        sample = np.random.choice(t, size=len(t), replace=True)
        w = sample[sample > 0]
        ls = sample[sample <= 0]
        
        if len(ls) > 0 and ls.sum() != 0:
            pfs.append(w.sum() / abs(ls.sum()))
        exps.append(sample.mean() * 100)
    
    return {
        'pf_ci': (round(float(np.percentile(pfs, 2.5)), 3), round(float(np.percentile(pfs, 97.5)), 3)),
        'exp_ci': (round(float(np.percentile(exps, 2.5)), 3), round(float(np.percentile(exps, 97.5)), 3)),
    }


def mev_risk_score(stop_pct):
    """MEV risk score (0-100)."""
    if stop_pct <= 0.0025: return 95
    elif stop_pct <= 0.005: return 70
    elif stop_pct <= 0.0075: return 40
    elif stop_pct <= 0.01: return 20
    elif stop_pct <= 0.015: return 10
    else: return 5


print("=" * 100)
print("MEV-RESILIENT STRATEGY VALIDATION")
print("=" * 100)
print(f"Testing {len(PAIRS)} pairs × {len(SAFE_STOPS)} stops × {len(TARGETS)} targets = {len(PAIRS) * len(SAFE_STOPS) * len(TARGETS)} configs")
print()

results = {}
best_per_pair = {}

for pair in PAIRS:
    print(f"\n{'=' * 80}")
    print(f"{pair}")
    print(f"{'=' * 80}")
    
    df = load_data(pair)
    if df is None:
        continue
    
    ind = compute_indicators(df)
    params = OPTIMAL_PARAMS[pair]
    
    print(f"Params: RSI<{params['rsi']}, BB {params['bb']}σ, Vol>{params['vol']}, {params['entry']}")
    print()
    
    pair_results = []
    best_score = -999
    
    for stop in SAFE_STOPS:
        for target in TARGETS:
            if target <= stop * 2:  # Minimum 2:1 R:R
                continue
            
            trades, regimes = run_backtest(ind, params, stop, target)
            stats = calc_stats(trades)
            
            if stats is None or stats['pf'] < 1.0:
                continue
            
            ci = bootstrap_ci(trades)
            mev = mev_risk_score(stop)
            
            # Check regime stability
            regime_stats = {}
            regime_stable = True
            for reg in ['low', 'mid', 'high']:
                if len(regimes[reg]) >= 5:
                    rs = calc_stats(regimes[reg])
                    regime_stats[reg] = rs
                    if rs and rs['pf'] < 0.8:
                        regime_stable = False
            
            # Score: PF × Exp × Regime stability, penalize MEV risk
            score = stats['pf'] * stats['exp'] * (1 if regime_stable else 0.5) * (1 - mev/200)
            
            result = {
                'pair': pair,
                'stop': round(stop * 100, 2),
                'target': round(target * 100, 2),
                'rr': round(target / stop, 1),
                'mev_risk': mev,
                **stats,
                'pf_ci': ci['pf_ci'],
                'exp_ci': ci['exp_ci'],
                'regime_stable': regime_stable,
                'regime_stats': regime_stats,
                'score': round(score, 4),
            }
            
            pair_results.append(result)
            
            if score > best_score:
                best_score = score
                best_per_pair[pair] = result
    
    results[pair] = pair_results
    
    if pair in best_per_pair:
        b = best_per_pair[pair]
        print(f"  BEST: Stop {b['stop']}%, Target {b['target']}% (R:R {b['rr']})")
        print(f"    PF: {b['pf']} (CI: {b['pf_ci']})")
        print(f"    Exp: {b['exp']}% (CI: {b['exp_ci']})")
        print(f"    WR: {b['wr']}% | Sharpe: {b['sharpe']} | MaxDD: {b['max_dd']}%")
        print(f"    MEV Risk: {b['mev_risk']}/100")
        print(f"    Regime Stable: {b['regime_stable']}")
        print(f"    Trades: {b['n']}")
    
    print(f"  Configs tested: {len(pair_results)}")
    print(f"  Profitable configs (PF>1): {sum(1 for r in pair_results if r['pf'] > 1)}")

# Save results
output = {
    'timestamp': pd.Timestamp.now().isoformat(),
    'best_per_pair': best_per_pair,
    'config_counts': {k: len(v) for k, v in results.items()},
}
with open(DATA_DIR / 'mev_resilient_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n\n{'=' * 100}")
print("PORTFOLIO CONSTRUCTION")
print(f"{'=' * 100}\n")

# Test portfolio with best configs
print("Recommended MEV-Resilient Portfolio:")
print("-" * 80)
print(f"{'Pair':<8} {'Weight':<8} {'Stop':<8} {'Target':<8} {'R:R':<8} {'PF':<8} {'Exp%':<8} {'MEV Risk':<10}")
print("-" * 80)

weights = {'SOL': 0.40, 'NEAR': 0.25, 'LINK': 0.15, 'AVAX': 0.15}
total_exp = 0
total_pf_weighted = 0

for pair in PAIRS:
    if pair in best_per_pair:
        b = best_per_pair[pair]
        w = weights.get(pair, 0)
        weighted_exp = b['exp'] * w
        total_exp += weighted_exp
        total_pf_weighted += b['pf'] * w
        
        print(f"{pair:<8} {w*100:>5.0f}%   {b['stop']:>6}%  {b['target']:>6}%  {b['rr']:>6}   {b['pf']:>6.3f} {b['exp']:>6.3f}%  {b['mev_risk']:>6}/100")

print("-" * 80)
print(f"Portfolio Weighted PF: {total_pf_weighted:.3f}")
print(f"Portfolio Weighted Exp: {total_exp:.3f}% per trade")
print()

# Monthly estimate
trades_per_month = 20  # Rough estimate across 4 pairs
monthly_exp = ((1 + total_exp/100) ** trades_per_month - 1) * 100
print(f"Est. Monthly Return: ~{monthly_exp:.1f}%")
print(f"Est. Annual Return: ~{((1 + total_exp/100) ** (trades_per_month * 12) - 1) * 100:.0f}%")

print(f"\nResults saved to: {DATA_DIR / 'mev_resilient_results.json'}")
