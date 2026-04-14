#!/usr/bin/env python3
"""
Validate Deep Scan Results
============================
Walk-forward + permutation tests on top candidates.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
from src.quant.backtest_framework import Backtester, Strategy, Position
import subprocess
import json
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/systematic')


def fetch_binance(symbol, interval='1h', limit=1500):
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


# Strategies
class DonchianBreakout(Strategy):
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


class DoubleMA(Strategy):
    def __init__(self, fast=5, slow=15, leverage=1):
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


class VWAPBounce(Strategy):
    def __init__(self, leverage=1):
        super().__init__()
        self.leverage = leverage
        self.vwap = None
    
    def init_indicators(self, data):
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


# Top candidates
CANDIDATES = [
    ('Donchian_20', DonchianBreakout, {'period': 20, 'hold': 10}, 'NEARUSDT', '1h'),
    ('Donchian_10', DonchianBreakout, {'period': 10, 'hold': 10}, 'ETHUSDT', '1h'),
    ('VWAP_Bounce', VWAPBounce, {}, 'ETHUSDT', '1h'),
    ('DoubleMA_5_15', DoubleMA, {'fast': 5, 'slow': 15}, 'AVAXUSDT', '1h'),
    ('DoubleMA_5_15', DoubleMA, {'fast': 5, 'slow': 15}, 'ETHUSDT', '1h'),
]


def walk_forward(strat_class, params, data, n_splits=4):
    """Walk-forward validation."""
    n = len(data['close'])
    window = n // n_splits
    
    results = []
    for split in range(n_splits):
        test_start = (split + 1) * window
        test_end = min(test_start + window, n)
        
        if test_end - test_start < 200:
            break
        
        test_data = {k: v[test_start:test_end] for k, v in data.items()}
        
        strat = strat_class(**params)
        bt = Backtester()
        result = bt.run(strat, test_data)
        
        results.append({
            'split': split,
            'trades': result.num_trades,
            'pnl': result.total_pnl_pct,
            'pf': result.profit_factor,
            'wr': result.win_rate,
        })
    
    return results


def permutation_test(strategy, data, n_perm=500):
    """Permutation test."""
    bt = Backtester()
    real = bt.run(strategy, data)
    
    if real.num_trades < 5:
        return {'p_value': 1.0, 'trades': real.num_trades}
    
    real_pnl = real.total_pnl_pct
    n_bars = len(data['close'])
    entry_bars = [t.entry_bar for t in real.trades]
    
    count_better = 0
    for _ in range(n_perm):
        # Random entries
        random_bars = sorted(np.random.choice(range(100, n_bars - 50), len(entry_bars), replace=False))
        random_pnl = 0
        for bar in random_bars:
            hold = np.random.randint(1, 20)
            exit_bar = min(bar + hold, n_bars - 1)
            ret = (data['close'][exit_bar] / data['close'][bar] - 1) * 100
            random_pnl += ret
        
        if random_pnl >= real_pnl:
            count_better += 1
    
    return {
        'p_value': count_better / n_perm,
        'trades': real.num_trades,
        'real_pnl': real_pnl,
    }


def validate_all():
    """Validate all candidates."""
    print("=" * 80)
    print("DEEP SCAN VALIDATION")
    print("=" * 80)
    
    validated = []
    
    for name, strat_class, params, pair, tf in CANDIDATES:
        print(f"\n{name} | {pair} | {tf}")
        print("-" * 40)
        
        data = fetch_binance(pair, tf, 1500)
        if not data:
            print("  No data")
            continue
        
        strategy = strat_class(**params)
        bt = Backtester()
        full_result = bt.run(strategy, data)
        
        print(f"  Full period: {full_result.num_trades} trades, PnL={full_result.total_pnl_pct:+.1f}%, PF={min(full_result.profit_factor, 999):.2f}")
        
        # Walk-forward
        wf_results = walk_forward(strat_class, params, data, n_splits=4)
        profitable = sum(1 for r in wf_results if r['pnl'] > 0)
        total_wf_trades = sum(r['trades'] for r in wf_results)
        avg_wf_pnl = np.mean([r['pnl'] for r in wf_results])
        
        print(f"  Walk-forward: {profitable}/{len(wf_results)} profitable, {total_wf_trades} trades, avg PnL={avg_wf_pnl:+.1f}%")
        
        for r in wf_results:
            print(f"    Split {r['split']}: trades={r['trades']}, PnL={r['pnl']:+.1f}%")
        
        # Permutation test
        perm = permutation_test(strat_class(**params), data, n_perm=500)
        print(f"  Permutation test: p={perm['p_value']:.3f}")
        
        # Criteria
        wf_pass = profitable >= len(wf_results) * 0.75 and avg_wf_pnl > 0
        perm_pass = perm['p_value'] < 0.10  # Relaxed threshold due to small samples
        
        if wf_pass and perm_pass:
            print(f"  *** POTENTIALLY VALIDATED ***")
            validated.append({
                'name': name,
                'pair': pair,
                'tf': tf,
                'trades': full_result.num_trades,
                'pnl': full_result.total_pnl_pct,
                'pf': min(full_result.profit_factor, 999),
                'wf_profitable': profitable,
                'wf_splits': len(wf_results),
                'perm_p': perm['p_value'],
            })
    
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    
    if validated:
        for v in validated:
            print(f"\n{v['name']} | {v['pair']} | {v['tf']}:")
            print(f"  {v['trades']} trades, PnL={v['pnl']:+.1f}%, PF={v['pf']:.2f}")
            print(f"  WF: {v['wf_profitable']}/{v['wf_splits']} profitable")
            print(f"  Permutation p={v['perm_p']:.3f}")
    else:
        print("\nNo strategies passed all validation tests.")
        print("This is expected - edges are rare and require large samples.")
    
    return validated


if __name__ == '__main__':
    validate_all()
