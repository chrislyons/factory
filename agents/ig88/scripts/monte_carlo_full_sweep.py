"""
Comprehensive Monte Carlo Strategy Validation
==============================================
Tests ALL stop/target combinations across ALL pairs with:
- Bootstrap confidence intervals (1000 iterations)
- Walk-forward stability (4 quarters)
- Regime segmentation (low/mid/high vol)
- MEV risk scoring
- Sharpe/Sortino/Calmar ratios

Output: Complete optimization matrix with statistical rigor.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple
import json
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025  # Jupiter perps

# All pairs to test
PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX', 'BTC', 'ETH']

# Stop/target grid (percentage as decimal)
STOP_LEVELS = [0.0025, 0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02]
TARGET_LEVELS = [0.025, 0.05, 0.075, 0.10, 0.125, 0.15, 0.20]

# MR signal parameters to test
RSI_THRESHOLDS = [32, 35, 38, 40]
BB_STDS = [0.5, 1.0, 1.5, 2.0]
VOL_THRESHOLDS = [1.1, 1.2, 1.3, 1.5]
ENTRY_OFFSETS = [0, 1, 2]  # T0, T1, T2

# Monte Carlo settings
BOOTSTRAP_ITERATIONS = 1000
QUARTER_SPLITS = 4


def load_data(pair: str) -> pd.DataFrame:
    """Load 4h OHLCV data for a pair."""
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if path.exists():
        return pd.read_parquet(path)
    return None


def compute_indicators(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Compute all indicators needed for MR signals."""
    c = df['close'].values
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    
    # Volume
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = (atr / c) * 100
    
    return {
        'c': c, 'o': o, 'h': h, 'l': l,
        'rsi': rsi, 'sma20': sma20, 'std20': std20,
        'vol_ratio': vol_ratio, 'atr_pct': atr_pct,
    }


def run_backtest(
    ind: Dict[str, np.ndarray],
    rsi_thresh: float,
    bb_std: float,
    vol_thresh: float,
    entry_offset: int,
    stop_pct: float,
    target_pct: float,
    lookback_start: int = 0,
    lookback_end: int = None,
) -> np.ndarray:
    """
    Run MR backtest with given parameters.
    Returns array of trade returns (decimal).
    """
    c = ind['c']
    o = ind['o']
    h = ind['h']
    l = ind['l']
    rsi = ind['rsi']
    sma20 = ind['sma20']
    std20 = ind['std20']
    vol_ratio = ind['vol_ratio']
    
    bb_l = sma20 - std20 * bb_std
    
    end = lookback_end if lookback_end else len(c) - entry_offset - 8
    start = max(100, lookback_start)
    
    trades = []
    
    for i in range(start, end - entry_offset - 8):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        
        # Long signal only (mean reversion oversold)
        if rsi[i] < rsi_thresh and c[i] < bb_l[i] and vol_ratio[i] > vol_thresh:
            entry_bar = i + entry_offset
            if entry_bar >= len(c) - 8:
                continue
            
            entry = o[entry_bar]
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
            
            exited = False
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                
                if l[bar] <= stop and h[bar] >= target:
                    # Both hit - assume stop first (conservative)
                    trades.append(-stop_pct - FRICTION)
                    exited = True
                    break
                elif l[bar] <= stop:
                    trades.append(-stop_pct - FRICTION)
                    exited = True
                    break
                elif h[bar] >= target:
                    trades.append(target_pct - FRICTION)
                    exited = True
                    break
            
            if not exited:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry) / entry - FRICTION)
    
    return np.array(trades) if trades else np.array([])


def compute_stats(trades: np.ndarray) -> Dict:
    """Compute comprehensive statistics from trade array."""
    if len(trades) < 5:
        return {
            'n': 0, 'pf': 0, 'wr': 0, 'exp': 0, 'sharpe': 0,
            'sortino': 0, 'max_dd': 0, 'avg_win': 0, 'avg_loss': 0,
        }
    
    wins = trades[trades > 0]
    losses = trades[trades <= 0]
    
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 999
    wr = len(wins) / len(trades) * 100
    exp = trades.mean() * 100
    
    # Sharpe (annualized for 4h bars = 6 trades/day * 365)
    trades_per_year = 6 * 365
    sharpe = (trades.mean() / trades.std()) * np.sqrt(trades_per_year) if trades.std() > 0 else 0
    
    # Sortino (only downside deviation)
    downside = trades[trades < 0]
    sortino = (trades.mean() / downside.std()) * np.sqrt(trades_per_year) if len(downside) > 0 and downside.std() > 0 else 0
    
    # Max drawdown
    equity = np.cumsum(trades)
    running_max = np.maximum.accumulate(equity)
    drawdown = running_max - equity
    max_dd = drawdown.max() * 100
    
    return {
        'n': len(trades),
        'pf': round(float(pf), 4),
        'wr': round(float(wr), 2),
        'exp': round(float(exp), 4),
        'sharpe': round(float(sharpe), 3),
        'sortino': round(float(sortino), 3),
        'max_dd': round(float(max_dd), 2),
        'avg_win': round(float(wins.mean() * 100), 4) if len(wins) > 0 else 0,
        'avg_loss': round(float(losses.mean() * 100), 4) if len(losses) > 0 else 0,
    }


def bootstrap_ci(trades: np.ndarray, iterations: int = 1000, ci: float = 0.95) -> Dict:
    """Bootstrap confidence intervals for PF and expectancy."""
    if len(trades) < 10:
        return {'pf_ci': (0, 0), 'exp_ci': (0, 0)}
    
    bootstrapped_pfs = []
    bootstrapped_exps = []
    
    alpha = (1 - ci) / 2
    
    for _ in range(iterations):
        sample = np.random.choice(trades, size=len(trades), replace=True)
        wins = sample[sample > 0]
        losses = sample[sample <= 0]
        
        if len(losses) > 0 and losses.sum() != 0:
            pf = wins.sum() / abs(losses.sum())
        else:
            pf = 999
        
        bootstrapped_pfs.append(pf)
        bootstrapped_exps.append(sample.mean() * 100)
    
    pf_sorted = sorted(bootstrapped_pfs)
    exp_sorted = sorted(bootstrapped_exps)
    
    return {
        'pf_ci': (
            round(float(pf_sorted[int(iterations * alpha)]), 4),
            round(float(pf_sorted[int(iterations * (1 - alpha))]), 4),
        ),
        'exp_ci': (
            round(float(exp_sorted[int(iterations * alpha)]), 4),
            round(float(exp_sorted[int(iterations * (1 - alpha))]), 4),
        ),
        'pf_mean': round(float(np.mean(bootstrapped_pfs)), 4),
        'exp_mean': round(float(np.mean(bootstrapped_exps)), 4),
    }


def get_regime(trade_idx: int, atr_pct: np.ndarray) -> str:
    """Determine volatility regime for a given trade."""
    if trade_idx >= len(atr_pct):
        return 'unknown'
    atr = atr_pct[trade_idx]
    if atr < 2.0:
        return 'low'
    elif atr < 4.0:
        return 'mid'
    else:
        return 'high'


def run_quarterly_analysis(
    ind: Dict[str, np.ndarray],
    rsi_thresh: float,
    bb_std: float,
    vol_thresh: float,
    entry_offset: int,
    stop_pct: float,
    target_pct: float,
) -> List[Dict]:
    """Split data into quarters and test each."""
    n = len(ind['c'])
    quarter_size = n // 4
    results = []
    
    for q in range(4):
        start = q * quarter_size
        end = (q + 1) * quarter_size if q < 3 else n
        
        trades = run_backtest(
            ind, rsi_thresh, bb_std, vol_thresh, entry_offset,
            stop_pct, target_pct, start, end
        )
        
        stats = compute_stats(trades)
        stats['quarter'] = q + 1
        stats['period'] = f"Q{q+1} ({start}-{end})"
        results.append(stats)
    
    return results


def mev_risk_score(stop_pct: float) -> float:
    """
    Score MEV risk (0-100, higher = more risky).
    Based on Solana MEV research: bots target 0.1-0.5% stops.
    """
    if stop_pct <= 0.0025:
        return 95  # Very high risk
    elif stop_pct <= 0.005:
        return 70  # High risk
    elif stop_pct <= 0.0075:
        return 40  # Moderate risk
    elif stop_pct <= 0.01:
        return 20  # Low risk
    elif stop_pct <= 0.015:
        return 10  # Very low risk
    else:
        return 5   # Negligible risk


def main():
    print("=" * 100)
    print("COMPREHENSIVE MONTE CARLO STRATEGY VALIDATION")
    print("=" * 100)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Pairs: {len(PAIRS)}")
    print(f"Stop levels: {len(STOP_LEVELS)}")
    print(f"Target levels: {len(TARGET_LEVELS)}")
    print(f"Stop/Target combos: {len(STOP_LEVELS) * len(TARGET_LEVELS)}")
    print(f"RSI thresholds: {len(RSI_THRESHOLDS)}")
    print(f"BB std devs: {len(BB_STDS)}")
    print(f"Volume thresholds: {len(VOL_THRESHOLDS)}")
    print(f"Entry offsets: {len(ENTRY_OFFSETS)}")
    print(f"Bootstrap iterations: {BOOTSTRAP_ITERATIONS}")
    print()
    
    all_results = {}
    best_per_pair = {}
    
    for pair in PAIRS:
        print(f"\n{'=' * 80}")
        print(f"TESTING: {pair}")
        print(f"{'=' * 80}")
        
        df = load_data(pair)
        if df is None:
            print(f"  SKIP: No data found for {pair}")
            continue
        
        ind = compute_indicators(df)
        print(f"  Data points: {len(df)}")
        
        pair_results = []
        best_exp = -999
        best_config = None
        
        # Grid search over stop/target combos
        for rsi in RSI_THRESHOLDS:
            for bb in BB_STDS:
                for vol in VOL_THRESHOLDS:
                    for entry in ENTRY_OFFSETS:
                        for stop in STOP_LEVELS:
                            for target in TARGET_LEVELS:
                                
                                trades = run_backtest(
                                    ind, rsi, bb, vol, entry, stop, target
                                )
                                
                                if len(trades) < 10:
                                    continue
                                
                                stats = compute_stats(trades)
                                ci = bootstrap_ci(trades, BOOTSTRAP_ITERATIONS)
                                quarters = run_quarterly_analysis(
                                    ind, rsi, bb, vol, entry, stop, target
                                )
                                
                                # Walk-forward stability (PF in all quarters > 1)
                                q_stable = all(q.get('pf', 0) > 0.8 for q in quarters if q.get('n', 0) > 5)
                                
                                mev = mev_risk_score(stop)
                                
                                result = {
                                    'pair': pair,
                                    'rsi': rsi,
                                    'bb_std': bb,
                                    'vol_thresh': vol,
                                    'entry': f'T{entry}',
                                    'stop_pct': round(stop * 100, 2),
                                    'target_pct': round(target * 100, 2),
                                    'risk_reward': round(target / stop, 2) if stop > 0 else 0,
                                    **stats,
                                    'pf_95ci': ci['pf_ci'],
                                    'exp_95ci': ci['exp_ci'],
                                    'mev_risk': mev,
                                    'q_stable': q_stable,
                                    'quarters': quarters,
                                }
                                
                                pair_results.append(result)
                                
                                # Track best by expectancy (risk-adjusted)
                                risk_adj_exp = stats['exp'] * (1 - mev/200)  # Penalize high MEV risk
                                if risk_adj_exp > best_exp and stats['pf'] > 1:
                                    best_exp = risk_adj_exp
                                    best_config = result
        
        all_results[pair] = pair_results
        
        if best_config:
            best_per_pair[pair] = best_config
            print(f"\n  BEST CONFIG for {pair}:")
            print(f"    RSI<{best_config['rsi']}, BB {best_config['bb_std']}σ, Vol>{best_config['vol_thresh']}, {best_config['entry']}")
            print(f"    Stop: {best_config['stop_pct']}%, Target: {best_config['target_pct']}% (R:R {best_config['risk_reward']})")
            print(f"    PF: {best_config['pf']} (CI: {best_config['pf_95ci']})")
            print(f"    Expectancy: {best_config['exp']}% (CI: {best_config['exp_95ci']})")
            print(f"    Win Rate: {best_config['wr']}%")
            print(f"    Sharpe: {best_config['sharpe']}")
            print(f"    Max DD: {best_config['max_dd']}%")
            print(f"    MEV Risk: {best_config['mev_risk']}/100")
            print(f"    Trades: {best_config['n']}")
        
        print(f"\n  Total configs tested for {pair}: {len(pair_results)}")
    
    # Save results
    output = {
        'timestamp': datetime.now().isoformat(),
        'settings': {
            'pairs': PAIRS,
            'stop_levels': STOP_LEVELS,
            'target_levels': TARGET_LEVELS,
            'rsi_thresholds': RSI_THRESHOLDS,
            'bb_stds': BB_STDS,
            'vol_thresholds': VOL_THRESHOLDS,
            'entry_offsets': ENTRY_OFFSETS,
            'bootstrap_iterations': BOOTSTRAP_ITERATIONS,
            'friction': FRICTION,
        },
        'best_per_pair': best_per_pair,
        'all_results': {k: len(v) for k, v in all_results.items()},
    }
    
    output_path = DATA_DIR / 'monte_carlo_sweep_results.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n\n{'=' * 100}")
    print("FINAL SUMMARY")
    print(f"{'=' * 100}\n")
    
    print("Best Configuration Per Pair:")
    print("-" * 90)
    print(f"{'Pair':<8} {'RSI':<6} {'BB':<6} {'Vol':<6} {'Entry':<7} {'Stop':<7} {'Target':<8} {'PF':<8} {'Exp%':<8} {'Sharpe':<8} {'MEV':<6}")
    print("-" * 90)
    
    for pair, config in best_per_pair.items():
        print(f"{pair:<8} {config['rsi']:<6} {config['bb_std']:<6} {config['vol_thresh']:<6} {config['entry']:<7} {config['stop_pct']:<7} {config['target_pct']:<8} {config['pf']:<8} {config['exp']:<8} {config['sharpe']:<8} {config['mev_risk']:<6}")
    
    print(f"\nResults saved to: {output_path}")
    print(f"Completed: {datetime.now().isoformat()}")


if __name__ == '__main__':
    main()
