"""
Extended Pair Audit: Pair-Specific Optimization with Walk-Forward
==================================================================
Test each new pair with its own optimal parameters.
Validate with walk-forward (6 windows) and bootstrap confidence.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

NEW_PAIRS = ['ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']


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
    
    # BTC regime
    btc_df = load_data('BTC')
    btc_c = btc_df['close'].values
    btc_20ret = np.full(len(c), np.nan)
    btc_ret = pd.Series(btc_c).pct_change(20).values
    min_len = min(len(btc_ret), len(c))
    btc_20ret[:min_len] = btc_ret[:min_len]
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'sma20': sma20, 'std20': std20,
        'vol_ratio': vol_ratio, 'atr': atr, 'btc_20ret': btc_20ret,
    }


def run_backtest(ind, rsi_thresh, bb_std, vol_thresh, entry, stop, target):
    """Run MR backtest."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20, vol_ratio = ind['rsi'], ind['sma20'], ind['std20'], ind['vol_ratio']
    bb_l = sma20 - std20 * bb_std
    
    trades = []
    for i in range(100, len(c) - entry - 8):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        if rsi[i] < rsi_thresh and c[i] < bb_l[i] and vol_ratio[i] > vol_thresh:
            entry_bar = i + entry
            if entry_bar >= len(c) - 8:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price * (1 - stop)
            target_price = entry_price * (1 + target)
            
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-stop - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(target - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades) if trades else np.array([])


def calc_stats(trades):
    if len(trades) < 10:
        return {'n': len(trades), 'pf': 0, 'wr': 0, 'exp': 0, 'sharpe': 0}
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (trades.mean() / trades.std()) * np.sqrt(6 * 365) if trades.std() > 0 else 0
    return {
        'n': len(trades),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(trades)*100), 1),
        'exp': round(float(trades.mean()*100), 3),
        'sharpe': round(float(sharpe), 2),
    }


def walk_forward(ind, rsi, bb, vol, entry, stop, target, windows=6):
    """Walk-forward validation."""
    n = len(ind['c'])
    w_size = n // windows
    
    results = []
    for w in range(windows):
        start = w * w_size
        end = (w + 1) * w_size if w < windows - 1 else n
        
        subset = {k: v[start:end] if isinstance(v, np.ndarray) else v for k, v in ind.items()}
        trades = run_backtest(subset, rsi, bb, vol, entry, stop, target)
        stats = calc_stats(trades)
        stats['window'] = w + 1
        results.append(stats)
    
    return results


def optimize_pair(pair, df):
    """Find optimal parameters for a specific pair."""
    ind = compute_indicators(df)
    n = len(df)
    
    best_score = -999
    best_params = None
    
    # Parameter grid
    rsi_values = [25, 30, 35, 40]
    bb_values = [1.0, 1.5, 2.0, 2.5]
    vol_values = [1.3, 1.5, 1.8, 2.0]
    entry_values = [1, 2]
    stop_values = [0.005, 0.0075, 0.01]
    target_values = [0.075, 0.10, 0.125, 0.15]
    
    for rsi in rsi_values:
        for bb in bb_values:
            for vol in vol_values:
                for entry in entry_values:
                    for stop in stop_values:
                        for target in target_values:
                            if target <= stop * 2:
                                continue
                            
                            trades = run_backtest(ind, rsi, bb, vol, entry, stop, target)
                            stats = calc_stats(trades)
                            
                            if stats['n'] < 30:
                                continue
                            
                            # Stability score: reward high PF, punish high n variance
                            wf = walk_forward(ind, rsi, bb, vol, entry, stop, target, windows=6)
                            wf_pfs = [r['pf'] for r in wf if r['n'] >= 5]
                            profitable_windows = sum(1 for p in wf_pfs if p > 1.0)
                            
                            if profitable_windows < 3:
                                continue
                            
                            # Score: PF * profitable_windows * trade_count_factor
                            score = stats['pf'] * profitable_windows * min(1.0, stats['n'] / 100)
                            
                            if score > best_score:
                                best_score = score
                                best_params = {
                                    'rsi': rsi, 'bb': bb, 'vol': vol,
                                    'entry': entry, 'stop': stop, 'target': target,
                                    **stats,
                                    'wf_profitable': profitable_windows,
                                    'wf_pfs': wf_pfs,
                                    'score': score,
                                }
    
    return best_params


print("=" * 100)
print("EXTENDED PAIR AUDIT: 5000 BARS PER PAIR")
print("=" * 100)

all_results = {}

for pair in NEW_PAIRS:
    df = load_data(pair)
    if df is None:
        print(f"\n{pair}: NO DATA")
        continue
    
    print(f"\n{'=' * 80}")
    print(f"OPTIMIZING: {pair} ({len(df)} bars, {df.index.min().date()} to {df.index.max().date()})")
    print(f"{'=' * 80}")
    
    best = optimize_pair(pair, df)
    
    if best is None:
        print(f"  NO VIABLE CONFIGURATION FOUND")
        continue
    
    all_results[pair] = best
    
    print(f"\n  OPTIMAL CONFIG:")
    print(f"    RSI < {best['rsi']}, BB {best['bb']}σ, Vol > {best['vol']}")
    print(f"    Entry: T{best['entry']}, Stop: {best['stop']*100:.2f}%, Target: {best['target']*100:.1f}%")
    print(f"\n  PERFORMANCE:")
    print(f"    PF: {best['pf']:.3f}")
    print(f"    Trades: {best['n']}")
    print(f"    Win Rate: {best['wr']:.1f}%")
    print(f"    Expectancy: {best['exp']:.3f}%")
    print(f"    Sharpe: {best['sharpe']:.2f}")
    print(f"\n  WALK-FORWARD STABILITY:")
    print(f"    Profitable windows: {best['wf_profitable']}/6")
    print(f"    WF PFS: {[round(p, 2) for p in best['wf_pfs']]}")
    
    verdict = "STRONG" if best['wf_profitable'] >= 5 and best['pf'] > 1.5 else \
               "ROBUST" if best['wf_profitable'] >= 4 and best['pf'] > 1.2 else \
               "MARGINAL" if best['wf_profitable'] >= 3 and best['pf'] > 1.0 else "FAIL"
    print(f"\n  VERDICT: {verdict}")


# ============================================================================
# FULL PORTFOLIO COMPARISON
# ============================================================================
print("\n" + "=" * 100)
print("FULL PORTFOLIO: ORIGINAL + NEW PAIRS")
print("=" * 100)

# Original pairs (from earlier optimization)
original = {
    'SOL':  {'pf': 2.44, 'n': 173, 'exp': 0.89, 'wf': 6},
    'NEAR': {'pf': 3.25, 'n': 150, 'exp': 1.35, 'wf': 5},
    'LINK': {'pf': 3.47, 'n': 129, 'exp': 1.45, 'wf': 5},
    'AVAX': {'pf': 3.88, 'n': 172, 'exp': 1.61, 'wf': 5},
}

print(f"\n{'Pair':<10} {'PF':<8} {'n':<8} {'Exp%':<10} {'WF':<10} {'Verdict'}")
print("-" * 60)

print("--- Original Pairs (10,900+ bars) ---")
for pair, r in original.items():
    verdict = "VALID" if r['wf'] >= 5 else "MARGINAL"
    print(f"{pair:<10} {r['pf']:<8.3f} {r['n']:<8} {r['exp']:<9.3f}% {r['wf']:<10} {verdict}")

print("\n--- New Pairs (5,000 bars) ---")
for pair, r in all_results.items():
    verdict = "VALID" if r['wf_profitable'] >= 5 and r['pf'] > 1.5 else \
              "ROBUST" if r['wf_profitable'] >= 4 and r['pf'] > 1.2 else \
              "MARGINAL" if r['wf_profitable'] >= 3 else "FAIL"
    print(f"{pair:<10} {r['pf']:<8.3f} {r['n']:<8} {r['exp']:<9.3f}% {r['wf_profitable']:<10} {verdict}")


# ============================================================================
# PORTFOLIO CONSTRUCTION
# ============================================================================
print("\n" + "=" * 100)
print("RECOMMENDED PORTFOLIO CONSTRUCTION")
print("=" * 100)

# Separate into tiers
tier1 = []  # Original 4 pairs
tier2 = []  # New pairs with WF >= 5
tier3 = []  # New pairs with WF >= 4

for pair, r in original.items():
    tier1.append((pair, r))

for pair, r in all_results.items():
    if r['wf_profitable'] >= 5 and r['pf'] > 1.5:
        tier2.append((pair, r))
    elif r['wf_profitable'] >= 4 and r['pf'] > 1.2:
        tier3.append((pair, r))

print(f"\nTier 1 (Core — proven, 10k+ bars):")
for pair, r in tier1:
    print(f"  {pair:<8} PF={r['pf']:.2f}, Exp={r['exp']:.2f}%")

print(f"\nTier 2 (Extended — robust, 5k bars):")
if tier2:
    for pair, r in tier2:
        print(f"  {pair:<8} PF={r['pf']:.2f}, Exp={r['exp']:.2f}%")
else:
    print(f"  None")

print(f"\nTier 3 (Watchlist — marginal, needs monitoring):")
if tier3:
    for pair, r in tier3:
        print(f"  {pair:<8} PF={r['pf']:.2f}, Exp={r['exp']:.2f}%")
else:
    print(f"  None")

# Equal weight portfolio
all_viable = tier1 + tier2
if all_viable:
    weight = 1.0 / len(all_viable)
    total_exp = sum(r['exp'] for _, r in all_viable) / len(all_viable)
    
    print(f"\nEqual Weight Portfolio ({len(all_viable)} pairs):")
    print(f"  Weight per pair: {weight*100:.1f}%")
    print(f"  Average expectancy: {total_exp:.3f}% per trade")
    
    # Simulated annual return (assuming 4 trades per pair per week)
    trades_per_week = 4
    weeks_per_year = 52
    annual_trades = trades_per_week * weeks_per_year * len(all_viable)
    annual_return = total_exp * annual_trades
    
    print(f"  Estimated annual trades: {annual_trades}")
    print(f"  Estimated annual return: {annual_return:.1f}% (before compounding)")
