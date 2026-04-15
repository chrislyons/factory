#!/usr/bin/env python3
"""
Funding Rate Mean Reversion Backtest Strategy
Hypothesis: Extreme funding rates predict short-term mean reversion
"""

import json
import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from itertools import product

# Configuration
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'LINKUSDT']
OUTPUT_PATH = '/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery/funding_rate_mr.json'

# Grid search parameters
ENTRY_THRESHOLDS = [1.5, 2.0, 2.5, 3.0]  # std
EXIT_THRESHOLDS = [0.25, 0.5, 0.75, 1.0]  # std
TIME_EXITS = [8, 16, 24, 48]  # hours
LEVERAGES = [1, 2, 3]

# Friction model
ROUND_TRIP_FEE = 0.0014  # 0.14%
BORROW_FEE_PER_HOUR = 0.0001  # 0.01%/hour

@dataclass
class Trade:
    entry_time: datetime
    exit_time: Optional[datetime]
    direction: str  # 'LONG' or 'SHORT'
    entry_funding_rate: float
    entry_price: float
    exit_price: Optional[float]
    exit_reason: str  # 'normalization' or 'time_exit'
    pnl: Optional[float]
    leverage: int

def fetch_funding_rate_history(symbol: str, limit: int = 1000) -> pd.DataFrame:
    """Fetch funding rate history from Binance"""
    url = 'https://fapi.binance.com/fapi/v1/fundingRate'
    params = {
        'symbol': symbol,
        'limit': limit
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        df = pd.DataFrame(data)
        df['fundingRate'] = df['fundingRate'].astype(float)
        df['fundingTime'] = pd.to_datetime(df['fundingTime'], unit='ms')
        df = df.set_index('fundingTime')
        df = df.sort_index()
        
        return df[['fundingRate']]
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return pd.DataFrame()

def fetch_price_at_time(symbol: str, timestamp_ms: int) -> Optional[float]:
    """Fetch approximate price at a given timestamp using klines"""
    url = 'https://fapi.binance.com/fapi/v1/klines'
    params = {
        'symbol': symbol,
        'interval': '8h',
        'startTime': timestamp_ms,
        'endTime': timestamp_ms + 8 * 60 * 60 * 1000,
        'limit': 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data:
            return float(data[0][4])  # Close price
    except:
        pass
    return None

def calculate_metrics(trades: List[Trade]) -> Dict:
    """Calculate performance metrics"""
    if not trades:
        return {
            'num_trades': 0,
            'win_rate': 0,
            'profit_factor': 0,
            'expectancy': 0,
            'sharpe_ratio': 0,
            'total_pnl': 0,
            'avg_pnl': 0,
            'max_drawdown': 0
        }
    
    pnls = [t.pnl for t in trades if t.pnl is not None]
    
    if not pnls:
        return {
            'num_trades': 0,
            'win_rate': 0,
            'profit_factor': 0,
            'expectancy': 0,
            'sharpe_ratio': 0,
            'total_pnl': 0,
            'avg_pnl': 0,
            'max_drawdown': 0
        }
    
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    total_profit = sum(wins) if wins else 0
    total_loss = abs(sum(losses)) if losses else 0
    
    win_rate = len(wins) / len(pnls) if pnls else 0
    profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
    expectancy = np.mean(pnls)
    
    # Sharpe ratio (annualized approximation, assuming ~1 trade per day)
    sharpe = 0
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe = (np.mean(pnls) / np.std(pnls)) * np.sqrt(365)
    
    # Max drawdown
    cumulative = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = running_max - cumulative
    max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0
    
    return {
        'num_trades': len(pnls),
        'win_rate': round(win_rate, 4),
        'profit_factor': round(profit_factor, 4),
        'expectancy': round(expectancy, 6),
        'sharpe_ratio': round(sharpe, 4),
        'total_pnl': round(sum(pnls), 6),
        'avg_pnl': round(np.mean(pnls), 6),
        'max_drawdown': round(max_drawdown, 6)
    }

def simulate_trade(
    df: pd.DataFrame,
    entry_idx: int,
    entry_threshold: float,
    exit_threshold: float,
    time_exit_hours: int,
    leverage: int,
    rolling_mean: float,
    rolling_std: float
) -> Optional[Trade]:
    """Simulate a single trade"""
    
    entry_row = df.iloc[entry_idx]
    entry_rate = entry_row['fundingRate']
    entry_time = entry_row.name
    
    # Determine direction
    z_score = (entry_rate - rolling_mean) / rolling_std if rolling_std > 0 else 0
    
    if abs(z_score) < entry_threshold:
        return None
    
    direction = 'SHORT' if z_score > 0 else 'LONG'
    
    # Look for exit
    exit_idx = None
    exit_reason = None
    
    # Maximum periods to hold (8h periods per hour)
    max_periods = time_exit_hours // 8
    if time_exit_hours % 8 != 0:
        max_periods += 1
    
    for i in range(entry_idx + 1, min(entry_idx + max_periods + 1, len(df))):
        current_rate = df.iloc[i]['fundingRate']
        current_z = (current_rate - rolling_mean) / rolling_std if rolling_std > 0 else 0
        
        # Check if normalized
        if abs(current_z) <= exit_threshold:
            exit_idx = i
            exit_reason = 'normalization'
            break
        
        # Check time exit
        hours_elapsed = (df.iloc[i].name - entry_time).total_seconds() / 3600
        if hours_elapsed >= time_exit_hours:
            exit_idx = i
            exit_reason = 'time_exit'
            break
    
    if exit_idx is None:
        # Force exit at end of data
        exit_idx = len(df) - 1
        exit_reason = 'data_end'
    
    exit_time = df.iloc[exit_idx].name
    exit_rate = df.iloc[exit_idx]['fundingRate']
    
    # Calculate PnL based on funding rate differential
    # When funding rate is extreme, the position profits as rate mean reverts
    # Simplified model: profit = (entry_rate - exit_rate) for SHORT, opposite for LONG
    
    holding_hours = (exit_time - entry_time).total_seconds() / 3600
    
    # Count how many funding payments we receive/pay
    num_payments = holding_hours / 8  # Binance pays every 8 hours
    
    if direction == 'SHORT':
        # We short when funding is high positive, profit when it decreases
        # Each period we receive funding payment
        gross_pnl = (entry_rate - exit_rate) * num_payments
    else:
        # We long when funding is high negative, profit when it increases
        # Each period we pay funding (negative)
        gross_pnl = (exit_rate - entry_rate) * num_payments
    
    # Apply friction
    total_fee = ROUND_TRIP_FEE + (BORROW_FEE_PER_HOUR * holding_hours)
    net_pnl = (gross_pnl * leverage) - total_fee
    
    return Trade(
        entry_time=entry_time,
        exit_time=exit_time,
        direction=direction,
        entry_funding_rate=entry_rate,
        entry_price=None,
        exit_price=None,
        exit_reason=exit_reason,
        pnl=net_pnl,
        leverage=leverage
    )

def run_backtest(
    symbol: str,
    df: pd.DataFrame,
    entry_threshold: float,
    exit_threshold: float,
    time_exit_hours: int,
    leverage: int
) -> Tuple[List[Trade], Dict]:
    """Run backtest for a single symbol and parameter set"""
    
    # Calculate rolling statistics (30-day = ~90 periods at 8h each)
    window = 90
    df = df.copy()
    df['rolling_mean'] = df['fundingRate'].rolling(window=window, min_periods=30).mean()
    df['rolling_std'] = df['fundingRate'].rolling(window=window, min_periods=30).std()
    
    trades = []
    last_exit_idx = -1
    
    for i in range(window, len(df)):
        # Skip if we're still in a previous trade
        if i <= last_exit_idx:
            continue
        
        rolling_mean = df.iloc[i]['rolling_mean']
        rolling_std = df.iloc[i]['rolling_std']
        
        if pd.isna(rolling_mean) or pd.isna(rolling_std) or rolling_std == 0:
            continue
        
        trade = simulate_trade(
            df, i,
            entry_threshold, exit_threshold,
            time_exit_hours, leverage,
            rolling_mean, rolling_std
        )
        
        if trade:
            trades.append(trade)
            # Find the index of exit
            for j in range(i, len(df)):
                if df.iloc[j].name >= trade.exit_time:
                    last_exit_idx = j
                    break
    
    metrics = calculate_metrics(trades)
    return trades, metrics

def run_grid_search(symbol: str, df: pd.DataFrame) -> List[Dict]:
    """Run grid search over all parameter combinations"""
    
    results = []
    param_combinations = list(product(
        ENTRY_THRESHOLDS,
        EXIT_THRESHOLDS,
        TIME_EXITS,
        LEVERAGES
    ))
    
    print(f"\nRunning grid search for {symbol} ({len(param_combinations)} combinations)...")
    
    for entry_thresh, exit_thresh, time_exit, leverage in param_combinations:
        # Skip invalid combinations (exit threshold should be < entry threshold)
        if exit_thresh >= entry_thresh:
            continue
        
        trades, metrics = run_backtest(
            symbol, df,
            entry_thresh, exit_thresh,
            time_exit, leverage
        )
        
        result = {
            'symbol': symbol,
            'parameters': {
                'entry_threshold': entry_thresh,
                'exit_threshold': exit_thresh,
                'time_exit_hours': time_exit,
                'leverage': leverage
            },
            'metrics': metrics
        }
        results.append(result)
    
    return results

def main():
    print("=" * 70)
    print("FUNDING RATE MEAN REVERSION BACKTEST")
    print("=" * 70)
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Symbols: {SYMBOLS}")
    print(f"Friction: {ROUND_TRIP_FEE*100}% round-trip + {BORROW_FEE_PER_HOUR*100}%/hour")
    
    all_results = []
    symbol_data = {}
    
    # Fetch data for all symbols
    for symbol in SYMBOLS:
        print(f"\nFetching funding rate data for {symbol}...")
        df = fetch_funding_rate_history(symbol, limit=1000)
        
        if df.empty:
            print(f"  WARNING: No data for {symbol}")
            continue
        
        symbol_data[symbol] = df
        print(f"  Fetched {len(df)} records")
        print(f"  Date range: {df.index[0]} to {df.index[-1]}")
        print(f"  Mean rate: {df['fundingRate'].mean():.6f}")
        print(f"  Std rate: {df['fundingRate'].std():.6f}")
        print(f"  Min rate: {df['fundingRate'].min():.6f}")
        print(f"  Max rate: {df['fundingRate'].max():.6f}")
        
        time.sleep(0.5)  # Rate limiting
    
    # Run grid search for each symbol
    for symbol in SYMBOLS:
        if symbol not in symbol_data:
            continue
        
        results = run_grid_search(symbol, symbol_data[symbol])
        all_results.extend(results)
        
        # Find best result for this symbol
        best = max(results, key=lambda x: x['metrics']['profit_factor'] if x['metrics']['num_trades'] > 0 else 0)
        print(f"\n  Best result for {symbol}:")
        print(f"    Parameters: {best['parameters']}")
        print(f"    Profit Factor: {best['metrics']['profit_factor']}")
        print(f"    Win Rate: {best['metrics']['win_rate']*100:.1f}%")
        print(f"    Num Trades: {best['metrics']['num_trades']}")
        print(f"    Sharpe: {best['metrics']['sharpe_ratio']}")
    
    # Aggregate results across symbols
    print("\n" + "=" * 70)
    print("AGGREGATE RESULTS")
    print("=" * 70)
    
    # Group by parameter combination
    param_groups = {}
    for result in all_results:
        key = str(result['parameters'])
        if key not in param_groups:
            param_groups[key] = []
        param_groups[key].append(result)
    
    # Find best aggregate parameter set
    best_agg_pf = 0
    best_agg_params = None
    best_agg_metrics = None
    
    for param_str, group in param_groups.items():
        total_trades = sum(r['metrics']['num_trades'] for r in group)
        
        if total_trades < 10:
            continue
        
        # Calculate aggregate metrics
        all_wins = 0
        all_losses = 0
        total_profit = 0
        total_loss = 0
        all_pnls = []
        
        for r in group:
            trades = r['metrics']['num_trades']
            wr = r['metrics']['win_rate']
            avg_pnl = r['metrics']['avg_pnl']
            
            wins = int(trades * wr)
            losses = trades - wins
            
            if wins > 0 and avg_pnl > 0:
                win_pnl = avg_pnl * trades / wins if wins > 0 else 0
                total_profit += win_pnl * wins
            
            if losses > 0:
                loss_pnl = (avg_pnl * trades - total_profit) / losses if losses > 0 else 0
                total_loss += abs(loss_pnl * losses)
            
            all_wins += wins
            all_losses += losses
        
        total_trades = all_wins + all_losses
        agg_pf = total_profit / total_loss if total_loss > 0 else float('inf')
        agg_wr = all_wins / total_trades if total_trades > 0 else 0
        
        if agg_pf > best_agg_pf and total_trades >= 30:
            best_agg_pf = agg_pf
            best_agg_params = param_str
            best_agg_metrics = {
                'total_trades': total_trades,
                'win_rate': round(agg_wr, 4),
                'profit_factor': round(agg_pf, 4)
            }
    
    # Prepare output
    validated_edge = best_agg_pf > 2.0 and best_agg_metrics and best_agg_metrics['total_trades'] > 30
    
    output = {
        'strategy': 'funding_rate_mean_reversion',
        'timestamp': datetime.now().isoformat(),
        'symbols': SYMBOLS,
        'data_source': 'binance_fapi_fundingRate',
        'friction_model': {
            'round_trip_fee': ROUND_TRIP_FEE,
            'borrow_fee_per_hour': BORROW_FEE_PER_HOUR
        },
        'parameter_grid': {
            'entry_thresholds': ENTRY_THRESHOLDS,
            'exit_thresholds': EXIT_THRESHOLDS,
            'time_exits': TIME_EXITS,
            'leverages': LEVERAGES
        },
        'results_by_symbol': all_results,
        'aggregate_best': {
            'parameters': best_agg_params,
            'metrics': best_agg_metrics
        },
        'validation': {
            'validated_edge': validated_edge,
            'threshold': 'PF > 2.0 with n > 30 trades',
            'result': 'VALIDATED EDGE' if validated_edge else 'NOT VALIDATED'
        }
    }
    
    # Save results
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nResults saved to: {OUTPUT_PATH}")
    
    # Final summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    
    if validated_edge:
        print("STATUS: VALIDATED EDGE")
        print(f"Best parameters: {best_agg_params}")
        print(f"Aggregate profit factor: {best_agg_pf:.4f}")
        print(f"Total trades: {best_agg_metrics['total_trades']}")
        print(f"Win rate: {best_agg_metrics['win_rate']*100:.1f}%")
    else:
        print("STATUS: NOT VALIDATED")
        if best_agg_metrics:
            print(f"Best profit factor achieved: {best_agg_pf:.4f}")
            print(f"Total trades: {best_agg_metrics['total_trades']}")
            print(f"Win rate: {best_agg_metrics['win_rate']*100:.1f}%")
        else:
            print("Insufficient data to validate edge")
        
        print("\nRECOMMENDATION:")
        print("The funding rate mean reversion edge was not validated.")
        print("Possible reasons:")
        print("  1. Funding rates may already be priced in")
        print("  2. Mean reversion may take longer than tested timeframes")
        print("  3. Friction costs may exceed the edge in this model")
        print("\nSuggested next steps:")
        print("  - Test with longer lookback windows")
        print("  - Include cross-exchange funding rate arbitrage")
        print("  - Consider the actual price impact, not just funding differential")

if __name__ == '__main__':
    main()