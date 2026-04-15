#!/usr/bin/env python3
"""
DEEP SCAN - Extended Strategy Search
=====================================
Test more strategies, more parameters, more timeframes.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
from src.quant.backtest_framework import Backtester, Strategy, Position
import subprocess
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List
from itertools import product

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/systematic')


def fetch_binance(symbol, interval='4h', limit=1000):
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


# ============================================================================
# MORE STRATEGIES
# ============================================================================

class DoubleMA(Strategy):
    """Double moving average crossover (simpler than EMA)."""
    
    def __init__(self, fast=10, slow=30, leverage=1):
        super().__init__()
        self.fast = fast
        self.slow = slow
        self.leverage = leverage
        self.sma_fast = None
        self.sma_slow = None
    
    def init_indicators(self, data):
        self.sma_fast = self.sma(data['close'], self.fast)
        self.sma_slow = self.sma(data['close'], self.slow)
    
    def should_enter(self, i, data):
        if np.isnan(self.sma_fast[i]) or np.isnan(self.sma_slow[i]):
            return None
        if np.isnan(self.sma_fast[i-1]) or np.isnan(self.sma_slow[i-1]):
            return None
        if self.sma_fast[i-1] <= self.sma_slow[i-1] and self.sma_fast[i] > self.sma_slow[i]:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.sma_fast[i]) or np.isnan(self.sma_slow[i]):
            return None
        if self.sma_fast[i] < self.sma_slow[i]:
            return 'CROSS_DOWN'
        return None


class DonchianBreakout(Strategy):
    """Donchian channel breakout."""
    
    def __init__(self, period=20, hold=10, leverage=1):
        super().__init__()
        self.period = period
        self.hold = hold
        self.leverage = leverage
        self.upper = None
        self.lower = None
    
    def init_indicators(self, data):
        n = len(data['close'])
        self.upper = np.full(n, np.nan)
        self.lower = np.full(n, np.nan)
        for i in range(self.period - 1, n):
            self.upper[i] = np.max(data['high'][i - self.period + 1:i + 1])
            self.lower[i] = np.min(data['low'][i - self.period + 1:i + 1])
    
    def should_enter(self, i, data):
        if np.isnan(self.upper[i]):
            return None
        if data['close'][i] > self.upper[i-1]:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.lower[i]):
            return None
        if data['close'][i] < self.lower[i]:
            return 'CHANNEL_BREAK'
        if i - position.entry_bar >= self.hold:
            return 'TIME_EXIT'
        return None


class RSIMeanRev(Strategy):
    """RSI mean reversion with tighter thresholds."""
    
    def __init__(self, period=14, oversold=25, overbought=75, leverage=1):
        super().__init__()
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.leverage = leverage
        self.rsi_arr = None
    
    def init_indicators(self, data):
        self.rsi_arr = self.rsi(data['close'], self.period)
    
    def should_enter(self, i, data):
        if np.isnan(self.rsi_arr[i]) or np.isnan(self.rsi_arr[i-1]):
            return None
        if self.rsi_arr[i-1] > self.oversold and self.rsi_arr[i] <= self.oversold:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.rsi_arr[i]):
            return None
        if self.rsi_arr[i] >= self.overbought:
            return 'OVERBOUGHT'
        if i - position.entry_bar >= 20:
            return 'TIME_EXIT'
        return None


class VWAPBounce(Strategy):
    """VWAP bounce strategy."""
    
    def __init__(self, leverage=1):
        super().__init__()
        self.leverage = leverage
        self.vwap = None
    
    def init_indicators(self, data):
        # Session VWAP (approximate with rolling)
        n = len(data['close'])
        self.vwap = np.full(n, np.nan)
        cumulative_tp_vol = 0
        cumulative_vol = 0
        for i in range(n):
            tp = (data['high'][i] + data['low'][i] + data['close'][i]) / 3
            cumulative_tp_vol += tp * data['volume'][i]
            cumulative_vol += data['volume'][i]
            if cumulative_vol > 0:
                self.vwap[i] = cumulative_tp_vol / cumulative_vol
    
    def should_enter(self, i, data):
        if np.isnan(self.vwap[i]) or i < 1:
            return None
        # Price bounced off VWAP
        if data['low'][i] <= self.vwap[i] and data['close'][i] > self.vwap[i]:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.vwap[i]):
            return None
        if data['close'][i] < self.vwap[i]:
            return 'VWAP_BREAK'
        if i - position.entry_bar >= 10:
            return 'TIME_EXIT'
        return None


class ATRChannel(Strategy):
    """ATR channel breakout."""
    
    def __init__(self, atr_period=14, channel_mult=2, leverage=1):
        super().__init__()
        self.atr_period = atr_period
        self.channel_mult = channel_mult
        self.leverage = leverage
        self.atr_arr = None
        self.upper = None
        self.lower = None
    
    def init_indicators(self, data):
        self.atr_arr = self.atr(data['high'], data['low'], data['close'], self.atr_period)
        n = len(data['close'])
        # 20-period median
        median = self.sma(data['close'], 20)
        self.upper = median + self.atr_arr * self.channel_mult
        self.lower = median - self.atr_arr * self.channel_mult
    
    def should_enter(self, i, data):
        if np.isnan(self.upper[i]):
            return None
        if data['close'][i] > self.upper[i]:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.lower[i]) or np.isnan(self.atr_arr[i]):
            return None
        if data['close'][i] < self.lower[i]:
            return 'CHANNEL_BREAK'
        # Trailing stop
        stop = data['close'][position.entry_bar] - self.atr_arr[i] * 2
        if data['low'][i] < stop:
            return 'ATR_STOP'
        return None


# ============================================================================
# SCAN CONFIGURATION
# ============================================================================

STRATEGY_CONFIGS = [
    # Double MA
    ('DoubleMA_5_15', DoubleMA, {'fast': 5, 'slow': 15}),
    ('DoubleMA_10_30', DoubleMA, {'fast': 10, 'slow': 30}),
    ('DoubleMA_20_50', DoubleMA, {'fast': 20, 'slow': 50}),
    
    # Donchian
    ('Donchian_10', DonchianBreakout, {'period': 10, 'hold': 10}),
    ('Donchian_20', DonchianBreakout, {'period': 20, 'hold': 10}),
    ('Donchian_40', DonchianBreakout, {'period': 40, 'hold': 10}),
    
    # RSI Mean Reversion
    ('RSI_MR_14_20_80', RSIMeanRev, {'period': 14, 'oversold': 20, 'overbought': 80}),
    ('RSI_MR_14_25_75', RSIMeanRev, {'period': 14, 'oversold': 25, 'overbought': 75}),
    ('RSI_MR_7_30_70', RSIMeanRev, {'period': 7, 'oversold': 30, 'overbought': 70}),
    
    # VWAP
    ('VWAP_Bounce', VWAPBounce, {}),
    
    # ATR Channel
    ('ATR_Channel_1.5', ATRChannel, {'atr_period': 14, 'channel_mult': 1.5}),
    ('ATR_Channel_2.0', ATRChannel, {'atr_period': 14, 'channel_mult': 2.0}),
    ('ATR_Channel_3.0', ATRChannel, {'atr_period': 14, 'channel_mult': 3.0}),
]

PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'LINKUSDT', 'UNIUSDT', 'NEARUSDT', 'INJUSDT', 'AAVEUSDT']

TIMEFRAMES = [('1h', 1000), ('4h', 1000), ('1d', 500)]


def run_deep_scan():
    """Deep scan with more strategies."""
    print("=" * 80)
    print("DEEP STRATEGY SCAN")
    print("=" * 80)
    
    all_results = []
    tested = 0
    passed_filters = 0
    
    for tf_name, tf_limit in TIMEFRAMES:
        print(f"\n{'=' * 50}")
        print(f"TIMEFRAME: {tf_name}")
        print(f"{'=' * 50}")
        
        for pair in PAIRS:
            data = fetch_binance(pair, tf_name, tf_limit)
            if not data or len(data['close']) < 300:
                continue
            
            for strat_name, strat_class, strat_params in STRATEGY_CONFIGS:
                tested += 1
                
                strategy = strat_class(**strat_params)
                bt = Backtester()
                result = bt.run(strategy, data)
                
                # Filters
                if result.num_trades < 15:  # Need sample size
                    continue
                if result.total_pnl_pct <= 0:
                    continue
                if result.profit_factor < 1.1:
                    continue
                if result.win_rate < 0.45:
                    continue
                
                passed_filters += 1
                
                entry = {
                    'strategy': strat_name,
                    'pair': pair,
                    'tf': tf_name,
                    'trades': result.num_trades,
                    'pnl': result.total_pnl_pct,
                    'pf': min(result.profit_factor, 999),
                    'wr': result.win_rate,
                    'dd': result.max_drawdown,
                    'avg_win': result.avg_win,
                    'avg_loss': result.avg_loss,
                    'sharpe': result.sharpe_ratio,
                }
                all_results.append(entry)
                
                print(f"  {strat_name:20} | {pair:10} | trades={result.num_trades:3} | "
                      f"WR={result.win_rate:.0%} | PF={min(result.profit_factor, 999):.2f} | "
                      f"PnL={result.total_pnl_pct:+.1f}%")
    
    # Summary
    print("\n" + "=" * 80)
    print(f"DEEP SCAN COMPLETE: {tested} tests, {passed_filters} passed filters")
    print("=" * 80)
    
    if all_results:
        # Sort by Sharpe
        all_results.sort(key=lambda x: -x.get('sharpe', 0))
        
        print("\nTOP 15 BY SHARPE RATIO:")
        for i, r in enumerate(all_results[:15]):
            print(f"  {i+1}. {r['strategy']:20} | {r['pair']:10} | {r['tf']} | "
                  f"trades={r['trades']:3} | Sharpe={r['sharpe']:.2f} | "
                  f"PnL={r['pnl']:+.1f}% | PF={r['pf']:.2f}")
        
        # Save
        with open(DATA_DIR / 'deep_scan_results.json', 'w') as f:
            json.dump({'tested': tested, 'passed': passed_filters, 'results': all_results}, f, indent=2)
    
    return all_results


if __name__ == '__main__':
    run_deep_scan()
