"""
H3-B Volume Ignition Parameter Optimization

Systematic grid search for H3-B Volume Ignition strategy parameters:
- Volume spike threshold: [1.3, 1.5, 1.8, 2.0]
- Momentum lookback: [1, 2, 3]
- RSI bounds: [(30, 70), (35, 65), (40, 60)]
- Entry timing: T1 (immediate), T2 (confirmation bar)

Data: 240m Binance parquet files
Friction: Jupiter 0.0025 (25 bps)
"""

from __future__ import annotations
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from itertools import product
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[2]))

import src.quant.indicators as ind
from src.quant.backtest_engine import BacktestEngine, Trade, TradeOutcome, ExitReason
from src.quant.regime import RegimeState


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class H3BParams:
    """H3-B Volume Ignition strategy parameters."""
    volume_threshold: float     # Volume spike: current_vol / avg_vol > threshold
    momentum_lookback: int      # Bars to look back for momentum
    rsi_lower: float            # RSI must be > lower
    rsi_upper: float            # RSI must be < upper
    entry_timing: str           # T1 or T2
    rsi_period: int = 14        # RSI calculation period
    vol_avg_period: int = 20    # Volume average period
    atr_period: int = 14        # ATR period for stops
    atr_stop_mult: float = 2.0  # ATR stop loss multiplier
    atr_target_mult: float = 3.0  # ATR take profit multiplier
    max_hold_bars: int = 20     # Maximum hold period (in bars)


# Jupiter friction model
JUPITER_FRICTION = 0.0025  # 25 bps


def apply_jupiter_friction(price: float, side: str) -> float:
    """Apply Jupiter swap friction."""
    if side == "buy":
        return price * (1.0 + JUPITER_FRICTION)
    else:
        return price * (1.0 - JUPITER_FRICTION)


# ============================================================================
# Data Loading
# ============================================================================

def load_parquet_data(filepath: Path) -> Optional[pd.DataFrame]:
    """Load and validate parquet data."""
    try:
        df = pd.read_parquet(filepath)
        # Standardize column names
        if 'datetime' in df.columns:
            df = df.set_index('datetime')
        elif 'time' in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            df['datetime'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df = df.set_index('datetime')
        
        # Ensure required columns exist
        required = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required):
            print(f"    [SKIP] Missing columns in {filepath.name}")
            return None
        
        return df.sort_index()
    except Exception as e:
        print(f"    [ERROR] Loading {filepath.name}: {e}")
        return None


def discover_pairs(data_dir: Path) -> list[tuple[str, Path]]:
    """Discover all 240m parquet files."""
    pairs = []
    pattern = "binance_*_240m.parquet"
    
    for f in sorted(data_dir.glob(pattern)):
        # Extract pair name from filename
        name = f.stem  # e.g., "binance_BTC_USDT_240m"
        parts = name.split("_")
        # Handle both "binance_BTC_USDT_240m" and "binance_AVAX_USDT_240m"
        if len(parts) >= 4:
            pair = f"{parts[1]}/{parts[2]}"  # e.g., "BTC/USDT"
            pairs.append((pair, f))
    
    return pairs


# ============================================================================
# H3-B Signal Generation
# ============================================================================

def generate_h3b_signals(
    df: pd.DataFrame,
    params: H3BParams
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Generate H3-B Volume Ignition signals.
    
    Entry conditions:
    1. Volume spike: current_volume > avg_volume * threshold
    2. Momentum confirmation: price change over lookback > 0
    3. RSI filter: RSI within bounds (not overbought/oversold)
    
    Returns:
        long_signal: bool array for long entries
        stop_levels: ATR-based stop loss levels
        target_levels: ATR-based take profit levels
    """
    c = df['close'].values.astype(float)
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    v = df['volume'].values.astype(float)
    n = len(c)
    
    # Volume spike detection
    vol_sma = ind.sma(v, params.vol_avg_period)
    vol_spike = v / np.where(vol_sma > 0, vol_sma, 1.0)
    vol_condition = vol_spike > params.volume_threshold
    
    # Momentum confirmation
    momentum = np.zeros(n)
    for i in range(params.momentum_lookback, n):
        momentum[i] = (c[i] - c[i - params.momentum_lookback]) / c[i - params.momentum_lookback]
    momentum_condition = momentum > 0
    
    # RSI filter
    rsi_vals = ind.rsi(c, params.rsi_period)
    rsi_condition = (rsi_vals > params.rsi_lower) & (rsi_vals < params.rsi_upper)
    
    # Combine signals for T1 (immediate entry)
    long_signal = vol_condition & momentum_condition & rsi_condition
    
    # T2: Add confirmation - previous bar must also have shown momentum
    if params.entry_timing == "T2":
        momentum_prev = np.roll(momentum, 1)
        momentum_prev[0] = 0
        long_signal = long_signal & (momentum_prev > 0)
    
    # ATR for stops/targets
    atr_vals = ind.atr(h, l, c, params.atr_period)
    stop_levels = c - (atr_vals * params.atr_stop_mult)
    target_levels = c + (atr_vals * params.atr_target_mult)
    
    return long_signal, stop_levels, target_levels


# ============================================================================
# Backtest Execution
# ============================================================================

def run_h3b_backtest(
    df: pd.DataFrame,
    pair: str,
    params: H3BParams,
    initial_capital: float = 10000.0
) -> dict:
    """
    Run H3-B backtest on a single pair.
    
    Returns dict with performance metrics.
    """
    c = df['close'].values.astype(float)
    ts = df.index
    n = len(c)
    
    # Generate signals
    long_signal, stop_levels, target_levels = generate_h3b_signals(df, params)
    
    # Track trades
    trades = []
    position = None
    equity = initial_capital
    equity_curve = [initial_capital]
    
    # Warmup period
    warmup = max(params.vol_avg_period, params.rsi_period, params.atr_period) + params.momentum_lookback
    
    for i in range(warmup, n):
        current_price = c[i]
        current_time = ts[i]
        
        # Check exit conditions first
        if position is not None:
            entry_idx = position['entry_idx']
            bars_held = i - entry_idx
            
            # Check stops/targets
            exit_price = None
            exit_reason = None
            
            # Use high/low for stop/target detection
            if params.entry_timing == "T1" or (params.entry_timing == "T2" and bars_held > 0):
                # Check if stop hit
                if df['low'].iloc[i] <= position['stop']:
                    exit_price = apply_jupiter_friction(position['stop'], "sell")
                    exit_reason = ExitReason.STOP_HIT
                # Check if target hit
                elif df['high'].iloc[i] >= position['target']:
                    exit_price = apply_jupiter_friction(position['target'], "sell")
                    exit_reason = ExitReason.TARGET_HIT
                # Check time stop
                elif bars_held >= params.max_hold_bars:
                    exit_price = apply_jupiter_friction(current_price, "sell")
                    exit_reason = ExitReason.TIME_STOP
            
            # Execute exit
            if exit_price is not None:
                pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                pnl_usd = pnl_pct * position['size_usd']
                
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current_time,
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'pnl_usd': pnl_usd,
                    'exit_reason': exit_reason.value if exit_reason else 'unknown',
                    'bars_held': bars_held,
                })
                
                equity += pnl_usd
                position = None
        
        # Check for new entry
        if position is None and long_signal[i]:
            entry_price = apply_jupiter_friction(current_price, "buy")
            
            # Position sizing: 2% of equity (conservative)
            size_usd = equity * 0.02
            
            position = {
                'entry_time': current_time,
                'entry_price': entry_price,
                'size_usd': size_usd,
                'stop': stop_levels[i],
                'target': target_levels[i],
                'entry_idx': i,
            }
        
        equity_curve.append(equity)
    
    # Close any open position at end
    if position is not None:
        exit_price = apply_jupiter_friction(c[-1], "sell")
        pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
        pnl_usd = pnl_pct * position['size_usd']
        trades.append({
            'entry_time': position['entry_time'],
            'exit_time': ts[-1],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'pnl_pct': pnl_pct,
            'pnl_usd': pnl_usd,
            'exit_reason': 'end_of_data',
            'bars_held': n - 1 - position['entry_idx'],
        })
        equity += pnl_usd
    
    # Compute statistics
    return compute_stats(trades, equity_curve, pair, params)


def compute_stats(trades: list[dict], equity_curve: list[float], pair: str, params: H3BParams) -> dict:
    """Compute performance statistics."""
    n_trades = len(trades)
    
    if n_trades == 0:
        return {
            'pair': pair,
            'params': asdict(params),
            'n_trades': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'sharpe_ratio': 0.0,
            'max_drawdown_pct': 0.0,
            'total_pnl_pct': 0.0,
            'total_pnl_usd': 0.0,
            'avg_win_pct': 0.0,
            'avg_loss_pct': 0.0,
            'expectancy': 0.0,
        }
    
    # Win/loss separation
    wins = [t for t in trades if t['pnl_usd'] > 0]
    losses = [t for t in trades if t['pnl_usd'] <= 0]
    
    win_rate = len(wins) / n_trades if n_trades > 0 else 0
    
    # Profit factor
    gross_wins = sum(t['pnl_usd'] for t in wins)
    gross_losses = abs(sum(t['pnl_usd'] for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
    
    # Average win/loss
    avg_win_pct = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss_pct = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
    
    # Expectancy
    expectancy = (win_rate * avg_win_pct) - ((1 - win_rate) * abs(avg_loss_pct))
    
    # Sharpe ratio (annualized, 240m bars = ~6.5 per day => 2372 per year)
    returns = np.array([t['pnl_pct'] for t in trades])
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(2372)
    else:
        sharpe = 0.0
    
    # Max drawdown from equity curve
    equity = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity)
    drawdowns = (running_max - equity) / running_max
    max_dd = np.max(drawdowns) if len(drawdowns) > 0 else 0
    
    # Total PnL
    total_pnl_usd = equity[-1] - equity[0]
    total_pnl_pct = (equity[-1] / equity[0] - 1) * 100 if equity[0] > 0 else 0
    
    return {
        'pair': pair,
        'params': asdict(params),
        'n_trades': n_trades,
        'n_wins': len(wins),
        'n_losses': len(losses),
        'win_rate': round(win_rate, 4),
        'profit_factor': round(profit_factor, 4),
        'sharpe_ratio': round(sharpe, 4),
        'max_drawdown_pct': round(max_dd, 4),
        'total_pnl_pct': round(total_pnl_pct, 2),
        'total_pnl_usd': round(total_pnl_usd, 2),
        'avg_win_pct': round(avg_win_pct, 4),
        'avg_loss_pct': round(avg_loss_pct, 4),
        'expectancy': round(expectancy, 4),
    }


# ============================================================================
# Grid Search
# ============================================================================

def run_optimization(data_dir: Path, output_path: Path):
    """Run full parameter grid search."""
    print("\n" + "=" * 80)
    print("H3-B VOLUME IGNITION PARAMETER OPTIMIZATION")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)
    
    # Parameter grid
    volume_thresholds = [1.3, 1.5, 1.8, 2.0]
    momentum_lookbacks = [1, 2, 3]
    rsi_bounds = [(30, 70), (35, 65), (40, 60)]
    entry_timings = ["T1", "T2"]
    
    # Generate all parameter combinations
    param_combos = list(product(
        volume_thresholds,
        momentum_lookbacks,
        rsi_bounds,
        entry_timings
    ))
    
    print(f"\nParameter grid: {len(param_combos)} combinations")
    print(f"  Volume thresholds: {volume_thresholds}")
    print(f"  Momentum lookbacks: {momentum_lookbacks}")
    print(f"  RSI bounds: {rsi_bounds}")
    print(f"  Entry timings: {entry_timings}")
    
    # Discover pairs
    pairs = discover_pairs(data_dir)
    print(f"\nDiscovered {len(pairs)} pairs with 240m data:")
    for pair, path in pairs:
        print(f"  - {pair}: {path.name}")
    
    # Results storage
    all_results = {}
    pair_results = {pair: [] for pair, _ in pairs}
    
    total_runs = len(param_combos) * len(pairs)
    run_count = 0
    
    print(f"\nTotal optimization runs: {total_runs}")
    print("-" * 80)
    
    for vol_thresh, mom_lookback, rsi_bound, entry_timing in param_combos:
        params = H3BParams(
            volume_threshold=vol_thresh,
            momentum_lookback=mom_lookback,
            rsi_lower=rsi_bound[0],
            rsi_upper=rsi_bound[1],
            entry_timing=entry_timing,
        )
        
        param_key = f"VT{vol_thresh}_ML{mom_lookback}_RSI{rsi_bound[0]}-{rsi_bound[1]}_{entry_timing}"
        
        for pair, filepath in pairs:
            run_count += 1
            
            # Load data
            df = load_parquet_data(filepath)
            if df is None or len(df) < 100:
                continue
            
            # Run backtest
            result = run_h3b_backtest(df, pair, params)
            
            # Store results
            pair_results[pair].append(result)
            
            # Progress indicator
            if run_count % 50 == 0 or run_count == total_runs:
                print(f"  Progress: {run_count}/{total_runs} ({100*run_count/total_runs:.1f}%)")
    
    print("-" * 80)
    
    # Find best parameters per pair
    print("\n" + "=" * 80)
    print("OPTIMIZATION RESULTS - Best Parameters Per Pair")
    print("=" * 80)
    
    best_per_pair = {}
    aggregate_results = {
        'total_trades': 0,
        'total_wins': 0,
        'total_losses': 0,
        'weighted_pf': 0.0,
        'weighted_wr': 0.0,
    }
    
    print(f"\n{'Pair':<15} {'Best Params':<55} {'Trades':>6} {'WR':>6} {'PF':>7} {'PnL%':>8} {'Sharpe':>7}")
    print("-" * 105)
    
    for pair, results in pair_results.items():
        if not results:
            continue
        
        # Sort by profit factor (descending), filter for minimum trades
        valid_results = [r for r in results if r['n_trades'] >= 5]
        
        if not valid_results:
            print(f"{pair:<15} {'No valid results (<5 trades)':<55}")
            continue
        
        best = max(valid_results, key=lambda x: x['profit_factor'])
        best_per_pair[pair] = best
        
        # Aggregate
        aggregate_results['total_trades'] += best['n_trades']
        aggregate_results['total_wins'] += best.get('n_wins', 0)
        aggregate_results['total_losses'] += best.get('n_losses', 0)
        
        # Compact param summary
        p = best['params']
        param_summary = f"VT={p['volume_threshold']} ML={p['momentum_lookback']} RSI={p['rsi_lower']}-{p['rsi_upper']} {p['entry_timing']}"
        
        print(f"{pair:<15} {param_summary:<55} {best['n_trades']:>6} {best['win_rate']:>6.1%} {best['profit_factor']:>7.3f} {best['total_pnl_pct']:>+7.2f}% {best['sharpe_ratio']:>7.2f}")
    
    # Compute aggregate metrics
    if aggregate_results['total_trades'] > 0:
        aggregate_results['weighted_wr'] = aggregate_results['total_wins'] / aggregate_results['total_trades']
    
    # Save results
    output = {
        'run_at': datetime.now(timezone.utc).isoformat(),
        'strategy': 'H3-B Volume Ignition',
        'friction_model': 'Jupiter 0.0025 (25 bps)',
        'parameter_grid': {
            'volume_thresholds': volume_thresholds,
            'momentum_lookbacks': momentum_lookbacks,
            'rsi_bounds': rsi_bounds,
            'entry_timings': entry_timings,
        },
        'pairs_tested': len(pairs),
        'total_combinations': len(param_combos),
        'best_params_per_pair': best_per_pair,
        'aggregate': aggregate_results,
        'all_results_by_pair': pair_results,
    }
    
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nResults saved to: {output_path}")
    
    # Final summary
    print("\n" + "=" * 80)
    print("AGGREGATE SUMMARY")
    print("=" * 80)
    print(f"Total pairs with edge: {len(best_per_pair)}")
    print(f"Aggregate trades: {aggregate_results['total_trades']}")
    print(f"Aggregate win rate: {aggregate_results['weighted_wr']:.1%}")
    
    profitable_pairs = [p for p, r in best_per_pair.items() if r['profit_factor'] > 1.0]
    print(f"Profitable pairs (PF>1): {len(profitable_pairs)}/{len(best_per_pair)}")
    
    return output


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    data_dir = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
    output_path = Path("/Users/nesbitt/dev/factory/agents/ig88/data/h3b_optimization_results.json")
    
    start_time = time.time()
    results = run_optimization(data_dir, output_path)
    elapsed = time.time() - start_time
    
    print(f"\nOptimization completed in {elapsed:.1f} seconds")
