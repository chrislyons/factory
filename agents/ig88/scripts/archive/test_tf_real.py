#!/usr/bin/env python3
"""
Test TF Strategy with Validated Framework
==========================================
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
from src.quant.backtest_framework import Backtester, Strategy, Position, Indicators
import subprocess
import json


def fetch_binance(symbol, interval='4h', limit=500):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(result.stdout)
        return {
            'open': np.array([float(d[1]) for d in data]),
            'high': np.array([float(d[2]) for d in data]),
            'low': np.array([float(d[3]) for d in data]),
            'close': np.array([float(d[4]) for d in data]),
            'volume': np.array([float(d[5]) for d in data]),
        }
    except:
        return None


class TrendFollowingStrategy(Strategy):
    """EMA-based trend following strategy."""
    
    def __init__(self, ema_fast=9, ema_slow=21, ema_trend=55, 
                 adx_threshold=20, stop_loss=0.96, trailing=0.96,
                 rsi_exit=70, leverage=1):
        super().__init__()
        self.ema_fast_period = ema_fast
        self.ema_slow_period = ema_slow
        self.ema_trend_period = ema_trend
        self.adx_threshold = adx_threshold
        self.stop_loss = stop_loss
        self.trailing = trailing
        self.rsi_exit = rsi_exit
        self.leverage = leverage
        
        self.ema_fast_arr = None
        self.ema_slow_arr = None
        self.ema_trend_arr = None
        self.adx_arr = None
        self.rsi_arr = None
    
    def init_indicators(self, data):
        self.ema_fast_arr = self.ema(data['close'], self.ema_fast_period)
        self.ema_slow_arr = self.ema(data['close'], self.ema_slow_period)
        self.ema_trend_arr = self.ema(data['close'], self.ema_trend_period)
        self.adx_arr = self.adx(data['high'], data['low'], data['close'], 14)
        self.rsi_arr = self.rsi(data['close'], 14)
    
    def should_enter(self, i, data):
        # Check all indicators valid
        if any(np.isnan(arr[i]) for arr in [self.ema_fast_arr, self.ema_slow_arr, 
                                             self.ema_trend_arr, self.adx_arr]):
            return None
        if any(np.isnan(arr[i-1]) for arr in [self.ema_fast_arr, self.ema_slow_arr]):
            return None
        
        # Trending regime
        if self.adx_arr[i] < self.adx_threshold:
            return None
        
        # EMA alignment (bullish)
        ema_bull = (self.ema_fast_arr[i] > self.ema_slow_arr[i] > 
                    self.ema_trend_arr[i])
        if not ema_bull:
            return None
        
        # EMA crossover up
        if self.ema_fast_arr[i-1] <= self.ema_slow_arr[i-1]:
            return Position(
                entry_price=data['close'][i],
                entry_bar=i,
                size=1000,
                leverage=self.leverage,
                stop_loss=data['close'][i] * self.stop_loss,
                trailing_pct=self.trailing,
            )
        
        return None
    
    def should_exit(self, i, data, position):
        if any(np.isnan(arr[i]) for arr in [self.ema_fast_arr, self.ema_slow_arr, self.rsi_arr]):
            return None
        
        # Update trailing stop
        if position.trailing_pct:
            new_trailing = data['high'][i] * position.trailing_pct
            if position.trailing_stop is None:
                position.trailing_stop = new_trailing
            else:
                position.trailing_stop = max(position.trailing_stop, new_trailing)
        
        # Stop loss
        if position.stop_loss and data['low'][i] <= position.stop_loss:
            return 'STOP_LOSS'
        
        # Trailing stop
        if position.trailing_stop and data['low'][i] <= position.trailing_stop:
            return 'TRAILING_STOP'
        
        # EMA cross down
        if self.ema_fast_arr[i] < self.ema_slow_arr[i]:
            return 'EMA_CROSS'
        
        # RSI overbought
        if self.rsi_arr[i] > self.rsi_exit:
            return 'RSI_EXIT'
        
        return None


def test_strategies():
    """Test TF strategy on multiple pairs with validated framework."""
    print("=" * 70)
    print("TREND FOLLOWING - REAL TEST (No Look-ahead Bias)")
    print("=" * 70)
    
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'UNIUSDT', 'AVAXUSDT']
    
    # Test with default parameters first
    param_sets = [
        {'name': 'Default', 'ema_fast': 9, 'ema_slow': 21, 'ema_trend': 55, 'adx_threshold': 20},
        {'name': 'Optimized', 'ema_fast': 9, 'ema_slow': 34, 'ema_trend': 89, 'adx_threshold': 20},
    ]
    
    all_results = []
    
    for params in param_sets:
        print(f"\n{params['name']} Parameters:")
        print(f"  EMA: {params['ema_fast']}/{params['ema_slow']}/{params['ema_trend']}, ADX>{params['adx_threshold']}")
        print(f"  {'Pair':10} {'Trades':6} {'WR':6} {'PF':6} {'PnL':8} {'MaxDD':6}")
        print("  " + "-" * 50)
        
        for pair in pairs:
            data = fetch_binance(pair, '4h', 500)
            if not data:
                continue
            
            # Filter out non-strategy params
            strat_params = {k: v for k, v in params.items() if k != 'name'}
            strategy = TrendFollowingStrategy(**strat_params)
            bt = Backtester()
            result = bt.run(strategy, data)
            
            pf = min(result.profit_factor, 999)  # Cap for display
            
            print(f"  {pair:10} {result.num_trades:6} {result.win_rate:5.0%} {pf:6.2f} {result.total_pnl_pct:+7.1f}% {result.max_drawdown:5.1f}%")
            
            all_results.append({
                'pair': pair,
                'params': params['name'],
                'trades': result.num_trades,
                'win_rate': result.win_rate,
                'profit_factor': result.profit_factor,
                'pnl': result.total_pnl_pct,
                'max_dd': result.max_drawdown,
            })
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    for param_name in ['Default', 'Optimized']:
        subset = [r for r in all_results if r['params'] == param_name]
        if not subset:
            continue
        
        total_trades = sum(r['trades'] for r in subset)
        profitable = sum(1 for r in subset if r['pnl'] > 0)
        avg_pnl = np.mean([r['pnl'] for r in subset])
        
        print(f"\n{param_name}:")
        print(f"  Total trades: {total_trades}")
        print(f"  Profitable pairs: {profitable}/{len(subset)}")
        print(f"  Avg PnL: {avg_pnl:+.1f}%")
        
        if total_trades < 10:
            print("  INSUFFICIENT SAMPLE SIZE - no reliable edge")
    
    return all_results


if __name__ == '__main__':
    test_strategies()
