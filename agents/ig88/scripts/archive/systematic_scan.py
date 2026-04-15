#!/usr/bin/env python3
"""
SYSTEMATIC STRATEGY SCAN
=========================
Tests all strategy/timeframe/pair combinations.
Reports only statistically valid results.
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

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/systematic')
DATA_DIR.mkdir(parents=True, exist_ok=True)


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
# STRATEGY DEFINITIONS
# ============================================================================

class MomentumRSI(Strategy):
    """RSI momentum: buy when RSI crosses above threshold."""
    
    def __init__(self, rsi_period=14, rsi_buy=30, rsi_sell=70, leverage=1):
        super().__init__()
        self.rsi_period = rsi_period
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell
        self.leverage = leverage
        self.rsi_arr = None
    
    def init_indicators(self, data):
        self.rsi_arr = self.rsi(data['close'], self.rsi_period)
    
    def should_enter(self, i, data):
        if np.isnan(self.rsi_arr[i]) or np.isnan(self.rsi_arr[i-1]):
            return None
        # Crosses above buy threshold
        if self.rsi_arr[i-1] < self.rsi_buy and self.rsi_arr[i] >= self.rsi_buy:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.rsi_arr[i]):
            return None
        if self.rsi_arr[i] > self.rsi_sell:
            return 'RSI_SELL'
        return None


class MeanReversionBollinger(Strategy):
    """Bollinger Band mean reversion."""
    
    def __init__(self, period=20, num_std=2, leverage=1):
        super().__init__()
        self.period = period
        self.num_std = num_std
        self.leverage = leverage
        self.sma_arr = None
        self.upper_arr = None
        self.lower_arr = None
    
    def init_indicators(self, data):
        closes = data['close']
        n = len(closes)
        self.sma_arr = self.sma(closes, self.period)
        
        # Bollinger bands
        self.upper_arr = np.full(n, np.nan)
        self.lower_arr = np.full(n, np.nan)
        
        for i in range(self.period - 1, n):
            std = np.std(closes[i - self.period + 1:i + 1])
            self.upper_arr[i] = self.sma_arr[i] + self.num_std * std
            self.lower_arr[i] = self.sma_arr[i] - self.num_std * std
    
    def should_enter(self, i, data):
        if np.isnan(self.lower_arr[i]):
            return None
        # Price below lower band - buy the dip
        if data['low'][i] < self.lower_arr[i]:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.upper_arr[i]) or np.isnan(self.sma_arr[i]):
            return None
        # Exit at upper band or SMA (whichever first)
        if data['high'][i] > self.upper_arr[i]:
            return 'UPPER_BAND'
        if data['close'][i] > self.sma_arr[i]:
            return 'SMA_MEAN'
        return None


class TrendEMACross(Strategy):
    """EMA crossover trend following."""
    
    def __init__(self, fast=9, slow=21, adx_period=14, adx_threshold=20, leverage=1):
        super().__init__()
        self.fast = fast
        self.slow = slow
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.leverage = leverage
        self.ema_fast = None
        self.ema_slow = None
        self.adx_arr = None
    
    def init_indicators(self, data):
        self.ema_fast = self.ema(data['close'], self.fast)
        self.ema_slow = self.ema(data['close'], self.slow)
        self.adx_arr = self.adx(data['high'], data['low'], data['close'], self.adx_period)
    
    def should_enter(self, i, data):
        if any(np.isnan(arr[i]) for arr in [self.ema_fast, self.ema_slow, self.adx_arr]):
            return None
        if any(np.isnan(arr[i-1]) for arr in [self.ema_fast, self.ema_slow]):
            return None
        
        # Only trade in trending regime
        if self.adx_arr[i] < self.adx_threshold:
            return None
        
        # EMA cross up
        if self.ema_fast[i-1] <= self.ema_slow[i-1] and self.ema_fast[i] > self.ema_slow[i]:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.ema_fast[i]) or np.isnan(self.ema_slow[i]):
            return None
        if self.ema_fast[i] < self.ema_slow[i]:
            return 'EMA_CROSS'
        return None


class BreakoutATR(Strategy):
    """ATR-based breakout strategy."""
    
    def __init__(self, atr_period=14, atr_mult=1.5, hold_bars=10, leverage=1):
        super().__init__()
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.hold_bars = hold_bars
        self.leverage = leverage
        self.atr_arr = None
        self.high_lookback = None
    
    def init_indicators(self, data):
        self.atr_arr = self.atr(data['high'], data['low'], data['close'], self.atr_period)
        # 20-bar high
        n = len(data['close'])
        self.high_lookback = np.full(n, np.nan)
        for i in range(20, n):
            self.high_lookback[i] = np.max(data['high'][i-20:i])
    
    def should_enter(self, i, data):
        if np.isnan(self.atr_arr[i]) or np.isnan(self.high_lookback[i]):
            return None
        
        # Breakout above 20-bar high by ATR threshold
        if data['close'][i] > self.high_lookback[i] + self.atr_arr[i] * self.atr_mult:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        # Time-based exit
        if i - position.entry_bar >= self.hold_bars:
            return 'TIME_EXIT'
        # Trailing stop based on ATR
        if np.isnan(self.atr_arr[i]):
            return None
        stop = position.entry_price - self.atr_arr[i] * 2
        if data['low'][i] < stop:
            return 'ATR_STOP'
        return None


class VolumeWeightedMomentum(Strategy):
    """Volume-weighted momentum."""
    
    def __init__(self, lookback=20, vol_mult=1.5, leverage=1):
        super().__init__()
        self.lookback = lookback
        self.vol_mult = vol_mult
        self.leverage = leverage
        self.vol_ma = None
        self.mom = None
    
    def init_indicators(self, data):
        self.vol_ma = self.sma(data['volume'], self.lookback)
        # Momentum = return over lookback
        n = len(data['close'])
        self.mom = np.full(n, np.nan)
        for i in range(self.lookback, n):
            self.mom[i] = (data['close'][i] / data['close'][i - self.lookback] - 1)
    
    def should_enter(self, i, data):
        if np.isnan(self.vol_ma[i]) or np.isnan(self.mom[i]):
            return None
        
        # High volume + positive momentum
        if (data['volume'][i] > self.vol_ma[i] * self.vol_mult and 
            self.mom[i] > 0.02):  # 2% momentum threshold
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.mom[i]):
            return None
        # Exit when momentum turns negative
        if self.mom[i] < -0.01:
            return 'MOM_NEGATIVE'
        # Time exit
        if i - position.entry_bar >= 10:
            return 'TIME_EXIT'
        return None


# ============================================================================
# SCAN ENGINE
# ============================================================================

@dataclass
class StrategyConfig:
    name: str
    strategy_class: type
    params: Dict
    min_trades: int = 10


STRATEGIES = [
    StrategyConfig('MomentumRSI_14_30_70', MomentumRSI, {'rsi_period': 14, 'rsi_buy': 30, 'rsi_sell': 70}),
    StrategyConfig('MomentumRSI_14_25_75', MomentumRSI, {'rsi_period': 14, 'rsi_buy': 25, 'rsi_sell': 75}),
    StrategyConfig('MomentumRSI_7_35_65', MomentumRSI, {'rsi_period': 7, 'rsi_buy': 35, 'rsi_sell': 65}),
    StrategyConfig('MeanRev_BB_20_2', MeanReversionBollinger, {'period': 20, 'num_std': 2}),
    StrategyConfig('MeanRev_BB_10_1.5', MeanReversionBollinger, {'period': 10, 'num_std': 1.5}),
    StrategyConfig('TrendEMA_9_21', TrendEMACross, {'fast': 9, 'slow': 21, 'adx_threshold': 20}),
    StrategyConfig('TrendEMA_12_26', TrendEMACross, {'fast': 12, 'slow': 26, 'adx_threshold': 20}),
    StrategyConfig('TrendEMA_5_13', TrendEMACross, {'fast': 5, 'slow': 13, 'adx_threshold': 25}),
    StrategyConfig('Breakout_ATR_1.5', BreakoutATR, {'atr_mult': 1.5, 'hold_bars': 10}),
    StrategyConfig('Breakout_ATR_2.0', BreakoutATR, {'atr_mult': 2.0, 'hold_bars': 10}),
    StrategyConfig('VolMom_20_1.5', VolumeWeightedMomentum, {'lookback': 20, 'vol_mult': 1.5}),
    StrategyConfig('VolMom_10_2.0', VolumeWeightedMomentum, {'lookback': 10, 'vol_mult': 2.0}),
]

PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'LINKUSDT', 'UNIUSDT', 'NEARUSDT', 'INJUSDT']

TIMEFRAMES = [
    ('1h', 1000),
    ('4h', 1000),
    ('1d', 500),
]


def run_scan():
    """Run systematic scan of all combinations."""
    print("=" * 80)
    print("SYSTEMATIC STRATEGY SCAN")
    print("=" * 80)
    
    results = []
    tested = 0
    passed = 0
    
    for tf_name, tf_limit in TIMEFRAMES:
        print(f"\n{'=' * 40}")
        print(f"TIMEFRAME: {tf_name}")
        print(f"{'=' * 40}")
        
        for pair in PAIRS:
            print(f"\n  {pair}:", end=' ')
            
            data = fetch_binance(pair, tf_name, tf_limit)
            if not data or len(data['close']) < 300:
                print("NO DATA")
                continue
            
            for strat_config in STRATEGIES:
                tested += 1
                
                strategy = strat_config.strategy_class(**strat_config.params)
                bt = Backtester()
                result = bt.run(strategy, data)
                
                # Filter: need minimum trades
                if result.num_trades < strat_config.min_trades:
                    continue
                
                # Filter: need positive PnL
                if result.total_pnl_pct <= 0:
                    continue
                
                # Filter: need profit factor > 1.2
                if result.profit_factor < 1.2:
                    continue
                
                # Filter: need reasonable win rate > 40%
                if result.win_rate < 0.40:
                    continue
                
                passed += 1
                
                entry = {
                    'strategy': strat_config.name,
                    'pair': pair,
                    'timeframe': tf_name,
                    'trades': result.num_trades,
                    'win_rate': result.win_rate,
                    'profit_factor': min(result.profit_factor, 999),
                    'pnl': result.total_pnl_pct,
                    'max_dd': result.max_drawdown,
                    'sharpe': result.sharpe_ratio,
                }
                results.append(entry)
                
                print(f"\n      PASS: {strat_config.name} | trades={result.num_trades} | "
                      f"WR={result.win_rate:.0%} | PF={min(result.profit_factor, 999):.2f} | "
                      f"PnL={result.total_pnl_pct:+.1f}% | DD={result.max_drawdown:.1f}%")
            
            print()  # newline after pair
    
    # Summary
    print("\n" + "=" * 80)
    print(f"SCAN COMPLETE: {tested} tests, {passed} passed filters")
    print("=" * 80)
    
    if results:
        # Sort by PnL
        results.sort(key=lambda x: -x['pnl'])
        
        print(f"\nTOP RESULTS:")
        for i, r in enumerate(results[:20]):
            print(f"  {i+1}. {r['strategy']} | {r['pair']} | {r['timeframe']}")
            print(f"      trades={r['trades']} | WR={r['win_rate']:.0%} | PF={r['profit_factor']:.2f} | PnL={r['pnl']:+.1f}%")
    else:
        print("\nNO STRATEGIES PASSED ALL FILTERS")
        print("This is a valid finding - edge is hard to find.")
    
    # Save results
    with open(DATA_DIR / f'scan_{tf_name}.json', 'w') as f:
        json.dump({
            'tested': tested,
            'passed': passed,
            'results': results,
        }, f, indent=2)
    
    return results


if __name__ == '__main__':
    run_scan()
