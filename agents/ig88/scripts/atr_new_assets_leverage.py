#!/usr/bin/env python3
"""
ATR Breakout Backtest with Leverage - Walk-Forward Validation on New Assets
Tests Donchian(20) breakout with ATR(10) stop across RNDR, WLD, SUI, FIL at 1x/2x/3x leverage.
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# Configuration
DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h')
OUTPUT_FILE = Path('/Users/nesbitt/dev/factory/agents/ig88/data/atr_new_assets_leverage.json')

SYMBOLS = ['RNDR', 'WLD', 'SUI', 'FIL']
LEVERAGE_LEVELS = [1, 2, 3]
SPLIT_PCTS = [0.5, 0.6, 0.7, 0.8]
FRICTION_PCT = 0.0014  # 0.14% round-trip

# Strategy params
DONCHIAN_PERIOD = 20
ATR_PERIOD = 10
ATR_MULT = 2.0
TRAIL_PCT = 0.02
MAX_HOLD_HOURS = 96
DIRECTION = 'LNG'  # Long only


def load_data(symbol: str) -> pd.DataFrame:
    """Load and prepare OHLCV data for a symbol."""
    filepath = DATA_DIR / f'binance_{symbol}USDT_60m.parquet'
    if not filepath.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")
    
    df = pd.read_parquet(filepath)
    
    # Convert time from seconds to datetime
    df = df.copy()
    df['dt'] = pd.to_datetime(df['time'], unit='s')
    df = df.sort_values('dt').reset_index(drop=True)
    return df


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Donchian channels and ATR."""
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    
    # Donchian channels - use rolling max/min of high/low
    upper = pd.Series(high).rolling(DONCHIAN_PERIOD).max().values
    lower = pd.Series(low).rolling(DONCHIAN_PERIOD).min().values
    
    # ATR calculation (TRUE RANGE, not simple H-L)
    tr = np.zeros(len(df))
    tr[0] = high[0] - low[0]
    for i in range(1, len(df)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i-1]),
            abs(low[i] - close[i-1])
        )
    atr = pd.Series(tr).rolling(ATR_PERIOD).mean().values
    
    df = df.copy()
    df['upper'] = upper
    df['lower'] = lower
    df['atr'] = atr
    return df


def run_backtest(df: pd.DataFrame, leverage: int) -> list:
    """Run ATR breakout backtest on a dataframe slice."""
    close = df['close'].values
    upper = df['upper'].values
    atr = df['atr'].values
    datetimes = df['dt'].values
    
    # Need at least DONCHIAN_PERIOD + 1 bars before we can trade
    min_start = max(DONCHIAN_PERIOD, ATR_PERIOD) + 1
    
    trades = []
    in_trade = False
    entry_price = 0.0
    entry_idx = 0
    stop_price = 0.0
    
    for i in range(min_start, len(df)):
        if np.isnan(upper[i]) or np.isnan(atr[i]) or np.isnan(upper[i-1]):
            continue
        
        current_close = close[i]
        current_atr = atr[i]
        
        if not in_trade:
            # Entry: close > upper[i-1] (previous bar's Donchian high)
            if current_close > upper[i-1]:
                entry_price = current_close
                # Initial stop: entry - ATR_MULT * ATR
                stop_price = entry_price - (ATR_MULT * current_atr)
                entry_idx = i
                in_trade = True
        else:
            bars_held = i - entry_idx
            exit_trade = False
            exit_reason = ''
            
            # Update trailing stop: 2% below current close
            new_trail_stop = current_close * (1 - TRAIL_PCT)
            stop_price = max(stop_price, new_trail_stop)
            
            # Check exit conditions
            if current_close <= stop_price:
                exit_trade = True
                exit_reason = 'stop'
            elif bars_held >= MAX_HOLD_HOURS:
                exit_trade = True
                exit_reason = 'time'
            
            if exit_trade:
                exit_price = stop_price if exit_reason == 'stop' else current_close
                
                # Calculate raw PnL percentage
                raw_pnl_pct = (exit_price - entry_price) / entry_price
                
                # Apply leverage
                leveraged_pnl = raw_pnl_pct * leverage
                
                # Subtract friction (applied once per round-trip regardless of leverage)
                net_pnl = leveraged_pnl - FRICTION_PCT
                
                trades.append({
                    'entry_time': str(datetimes[entry_idx]),
                    'exit_time': str(datetimes[i]),
                    'entry_price': float(entry_price),
                    'exit_price': float(exit_price),
                    'raw_pnl_pct': float(raw_pnl_pct),
                    'leveraged_pnl': float(leveraged_pnl),
                    'net_pnl': float(net_pnl),
                    'leverage': leverage,
                    'bars_held': bars_held,
                    'exit_reason': exit_reason
                })
                
                in_trade = False
    
    return trades


def calculate_metrics(trades: list) -> dict:
    """Calculate performance metrics from trade list."""
    if not trades:
        return {
            'profit_factor': 0.0,
            'annualized_return': 0.0,
            'max_drawdown': 0.0,
            'win_rate': 0.0,
            'trade_count': 0,
            'total_return': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'sharpe_ratio': 0.0
        }
    
    pnls = [t['net_pnl'] for t in trades]
    winning = [p for p in pnls if p > 0]
    losing = [p for p in pnls if p <= 0]
    
    total_return = sum(pnls)
    win_rate = len(winning) / len(pnls)
    
    gross_profit = sum(winning) if winning else 0
    gross_loss = abs(sum(losing)) if losing else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
        float('inf') if gross_profit > 0 else 0
    )
    
    avg_win = float(np.mean(winning)) if winning else 0
    avg_loss = float(np.mean(losing)) if losing else 0
    
    # Max drawdown from cumulative PnL
    cumulative = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = running_max - cumulative
    max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0
    
    # Annualized return calculation
    if len(trades) >= 2:
        first_time = pd.to_datetime(trades[0]['entry_time'])
        last_time = pd.to_datetime(trades[-1]['exit_time'])
        years = (last_time - first_time).total_seconds() / (365.25 * 24 * 3600)
        if years > 0:
            # Compound annualized return
            if total_return > -1:
                annualized = (1 + total_return) ** (1 / years) - 1
            else:
                annualized = -1.0
        else:
            annualized = total_return
    else:
        annualized = total_return
    
    # Simplified Sharpe ratio
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)))
    else:
        sharpe = 0.0
    
    return {
        'profit_factor': float(profit_factor) if profit_factor != float('inf') else 999.99,
        'annualized_return': float(annualized),
        'max_drawdown': float(max_drawdown),
        'win_rate': float(win_rate),
        'trade_count': len(trades),
        'total_return': float(total_return),
        'avg_win': float(avg_win),
        'avg_loss': float(avg_loss),
        'sharpe_ratio': float(sharpe)
    }


def main():
    print("=" * 80)
    print("ATR BREAKOUT BACKTEST - NEW ASSETS LEVERAGE STRESS TEST")
    print("=" * 80)
    print(f"Strategy: Donchian({DONCHIAN_PERIOD}) breakout, ATR({ATR_PERIOD}) stop")
    print(f"Initial stop: entry - {ATR_MULT}*ATR, Trail: {TRAIL_PCT*100}%, Max hold: {MAX_HOLD_HOURS}h")
    print(f"Friction: {FRICTION_PCT*100}% round-trip")
    print(f"Leverage levels: {LEVERAGE_LEVELS}x")
    print(f"Walk-forward splits: {[f'{int(s*100)}/{int((1-s)*100)}' for s in SPLIT_PCTS]}")
    print(f"Assets: {SYMBOLS}")
    print("=" * 80)
    
    all_results = {}
    
    for symbol in SYMBOLS:
        print(f"\n{'='*60}")
        print(f"Processing {symbol}...")
        print(f"{'='*60}")
        
        try:
            df = load_data(symbol)
            print(f"  Loaded {len(df)} bars from {df['dt'].iloc[0]} to {df['dt'].iloc[-1]}")
            
            df = calculate_indicators(df)
            
            symbol_results = {}
            
            for leverage in LEVERAGE_LEVELS:
                print(f"\n  Leverage {leverage}x:")
                leverage_results = {}
                
                for split_pct in SPLIT_PCTS:
                    split_idx = int(len(df) * split_pct)
                    train_df = df.iloc[:split_idx]
                    test_df = df.iloc[split_idx:]
                    
                    # Run backtest on test (out-of-sample) period
                    trades = run_backtest(test_df, leverage)
                    metrics = calculate_metrics(trades)
                    
                    split_name = f"{int(split_pct*100)}_{int((1-split_pct)*100)}"
                    leverage_results[split_name] = metrics
                    
                    print(f"    Split {split_name}: PF={metrics['profit_factor']:.2f}, "
                          f"AnnRet={metrics['annualized_return']*100:.1f}%, "
                          f"MaxDD={metrics['max_drawdown']*100:.1f}%, "
                          f"WR={metrics['win_rate']*100:.1f}%, "
                          f"Trades={metrics['trade_count']}")
                
                symbol_results[f'{leverage}x'] = leverage_results
            
            all_results[symbol] = symbol_results
            
        except Exception as e:
            print(f"  ERROR: {e}")
            all_results[symbol] = {'error': str(e)}
    
    # Compile summary table
    print("\n" + "=" * 120)
    print("COMPREHENSIVE RESULTS SUMMARY")
    print("=" * 120)
    
    header = f"{'Asset':<8} {'Leverage':<9} {'Split':<10} {'PF':>8} {'AnnRet%':>9} {'MaxDD%':>9} {'WinRate%':>9} {'Trades':>7}"
    print(header)
    print("-" * 120)
    
    for symbol in SYMBOLS:
        if 'error' in all_results.get(symbol, {}):
            print(f"{symbol:<8} ERROR: {all_results[symbol]['error']}")
            continue
        
        for leverage in LEVERAGE_LEVELS:
            lev_key = f'{leverage}x'
            for split_pct in SPLIT_PCTS:
                split_name = f"{int(split_pct*100)}_{int((1-split_pct)*100)}"
                m = all_results[symbol][lev_key][split_name]
                
                print(f"{symbol:<8} {lev_key:<9} {split_name:<10} "
                      f"{m['profit_factor']:>8.2f} "
                      f"{m['annualized_return']*100:>8.1f}% "
                      f"{m['max_drawdown']*100:>8.1f}% "
                      f"{m['win_rate']*100:>8.1f}% "
                      f"{m['trade_count']:>7}")
    
    # Save results
    output = {
        'metadata': {
            'strategy': f'Donchian({DONCHIAN_PERIOD}) ATR({ATR_PERIOD}) Breakout',
            'direction': DIRECTION,
            'initial_stop': f'entry - {ATR_MULT}*ATR',
            'trailing_stop': f'{TRAIL_PCT*100}%',
            'max_hold_hours': MAX_HOLD_HOURS,
            'friction_pct': FRICTION_PCT,
            'leverage_levels': LEVERAGE_LEVELS,
            'split_percentages': SPLIT_PCTS,
            'symbols': SYMBOLS,
            'timestamp': datetime.now().isoformat()
        },
        'results': all_results
    }
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nResults saved to: {OUTPUT_FILE}")
    print("=" * 80)


if __name__ == '__main__':
    main()
