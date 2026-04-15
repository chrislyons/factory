#!/usr/bin/env python3
"""
Walk-Forward Validation of Top Candidates
==========================================
Validates strategies out-of-sample.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
from src.quant.backtest_framework import Backtester, Strategy, Position
import subprocess
import json
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/systematic')


def fetch_binance(symbol, interval='4h', limit=1500):
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


# Strategy implementations
class MomentumRSI(Strategy):
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
        self.upper_arr = np.full(n, np.nan)
        self.lower_arr = np.full(n, np.nan)
        
        for i in range(self.period - 1, n):
            std = np.std(closes[i - self.period + 1:i + 1])
            self.upper_arr[i] = self.sma_arr[i] + self.num_std * std
            self.lower_arr[i] = self.sma_arr[i] - self.num_std * std
    
    def should_enter(self, i, data):
        if np.isnan(self.lower_arr[i]):
            return None
        if data['low'][i] < self.lower_arr[i]:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.upper_arr[i]) or np.isnan(self.sma_arr[i]):
            return None
        if data['high'][i] > self.upper_arr[i]:
            return 'UPPER_BAND'
        if data['close'][i] > self.sma_arr[i]:
            return 'SMA_MEAN'
        return None


class VolumeWeightedMomentum(Strategy):
    def __init__(self, lookback=20, vol_mult=1.5, leverage=1):
        super().__init__()
        self.lookback = lookback
        self.vol_mult = vol_mult
        self.leverage = leverage
        self.vol_ma = None
        self.mom = None
    
    def init_indicators(self, data):
        self.vol_ma = self.sma(data['volume'], self.lookback)
        n = len(data['close'])
        self.mom = np.full(n, np.nan)
        for i in range(self.lookback, n):
            self.mom[i] = (data['close'][i] / data['close'][i - self.lookback] - 1)
    
    def should_enter(self, i, data):
        if np.isnan(self.vol_ma[i]) or np.isnan(self.mom[i]):
            return None
        if data['volume'][i] > self.vol_ma[i] * self.vol_mult and self.mom[i] > 0.02:
            return Position(data['close'][i], i, 1000, self.leverage)
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.mom[i]):
            return None
        if self.mom[i] < -0.01:
            return 'MOM_NEGATIVE'
        if i - position.entry_bar >= 10:
            return 'TIME_EXIT'
        return None


# Top candidates to validate
CANDIDATES = [
    {'name': 'MeanRev_BB_20_2', 'class': MeanReversionBollinger, 'params': {'period': 20, 'num_std': 2}, 
     'pair': 'UNIUSDT', 'tf': '4h'},
    {'name': 'MeanRev_BB_20_2', 'class': MeanReversionBollinger, 'params': {'period': 20, 'num_std': 2}, 
     'pair': 'SOLUSDT', 'tf': '4h'},
    {'name': 'MomentumRSI_7_35_65', 'class': MomentumRSI, 'params': {'rsi_period': 7, 'rsi_buy': 35, 'rsi_sell': 65}, 
     'pair': 'AVAXUSDT', 'tf': '4h'},
    {'name': 'MomentumRSI_7_35_65', 'class': MomentumRSI, 'params': {'rsi_period': 7, 'rsi_buy': 35, 'rsi_sell': 65}, 
     'pair': 'SOLUSDT', 'tf': '1h'},
    {'name': 'MomentumRSI_7_35_65', 'class': MomentumRSI, 'params': {'rsi_period': 7, 'rsi_buy': 35, 'rsi_sell': 65}, 
     'pair': 'ETHUSDT', 'tf': '1h'},
    {'name': 'VolMom_20_1.5', 'class': VolumeWeightedMomentum, 'params': {'lookback': 20, 'vol_mult': 1.5}, 
     'pair': 'INJUSDT', 'tf': '1h'},
    {'name': 'VolMom_10_2.0', 'class': VolumeWeightedMomentum, 'params': {'lookback': 10, 'vol_mult': 2.0}, 
     'pair': 'ETHUSDT', 'tf': '1h'},
]


def walk_forward_test(candidate, n_splits=3):
    """Run walk-forward test."""
    pair = candidate['pair']
    tf = candidate['tf']
    limit = 1000 if tf != '1d' else 500
    
    data = fetch_binance(pair, tf, limit)
    if not data:
        return None
    
    n = len(data['close'])
    window_size = n // 2
    
    results = []
    
    for split in range(n_splits):
        train_start = split * (n - window_size) // max(n_splits - 1, 1)
        train_end = train_start + window_size
        test_start = train_end
        test_end = min(test_start + window_size, n)
        
        if test_end - test_start < 100:
            break
        
        test_data = {k: v[test_start:test_end] for k, v in data.items()}
        
        strategy = candidate['class'](**candidate['params'])
        bt = Backtester()
        result = bt.run(strategy, test_data)
        
        results.append({
            'split': split,
            'test_bars': test_end - test_start,
            'trades': result.num_trades,
            'pnl': result.total_pnl_pct,
            'pf': min(result.profit_factor, 999),
            'wr': result.win_rate,
            'max_dd': result.max_drawdown,
        })
    
    return results


def run_validation():
    """Validate all candidates."""
    print("=" * 80)
    print("WALK-FORWARD VALIDATION")
    print("=" * 80)
    
    validated = []
    
    for cand in CANDIDATES:
        print(f"\n{cand['name']} | {cand['pair']} | {cand['tf']}")
        
        results = walk_forward_test(cand)
        
        if not results:
            print("  Could not fetch data")
            continue
        
        for r in results:
            status = "PASS" if r['pnl'] > 0 and r['trades'] >= 3 else "FAIL"
            print(f"  Split {r['split']}: trades={r['trades']} | PnL={r['pnl']:+.1f}% | PF={r['pf']:.2f} | WR={r['wr']:.0%} | {status}")
        
        # Aggregate
        total_trades = sum(r['trades'] for r in results)
        profitable_splits = sum(1 for r in results if r['pnl'] > 0)
        avg_pnl = np.mean([r['pnl'] for r in results])
        avg_pf = np.mean([r['pf'] for r in results if r['pf'] < 999])
        
        print(f"  Summary: {profitable_splits}/{len(results)} splits profitable, {total_trades} trades, avg PnL={avg_pnl:+.1f}%")
        
        # Criteria for validation
        if (profitable_splits >= len(results) * 0.6 and 
            total_trades >= 10 and 
            avg_pnl > 0):
            print(f"  *** VALIDATED ***")
            validated.append({
                'candidate': cand['name'],
                'pair': cand['pair'],
                'tf': cand['tf'],
                'total_trades': total_trades,
                'profitable_splits': profitable_splits,
                'avg_pnl': avg_pnl,
                'avg_pf': avg_pf,
            })
    
    # Summary
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    
    if validated:
        print(f"\n{len(validated)} strategies validated:")
        for v in validated:
            print(f"  {v['candidate']} | {v['pair']} | {v['tf']} | trades={v['total_trades']} | PnL={v['avg_pnl']:+.1f}% | PF={v['avg_pf']:.2f}")
    else:
        print("\nNO STRATEGIES VALIDATED")
        print("This means in-sample results did not hold out-of-sample.")
    
    # Save
    with open(DATA_DIR / 'validation_results.json', 'w') as f:
        json.dump({'validated': validated}, f, indent=2)
    
    return validated


if __name__ == '__main__':
    run_validation()
