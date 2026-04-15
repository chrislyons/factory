#!/usr/bin/env python3
"""
Statistical Validation
=======================
Monte Carlo permutation tests to verify significance.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
from src.quant.backtest_framework import Backtester, Strategy, Position
import subprocess
import json
from pathlib import Path

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


# Strategy implementations
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


class MomentumRSI(Strategy):
    def __init__(self, rsi_period=7, rsi_buy=35, rsi_sell=65, leverage=1):
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


def extract_trade_pnls(result):
    """Extract individual trade PnLs."""
    return [t.pnl_pct for t in result.trades]


def permutation_test(strategy, data, n_perm=1000):
    """
    Test if strategy performance is better than random.
    
    Method: Shuffle trade timing, keep returns.
    """
    bt = Backtester()
    real_result = bt.run(strategy, data)
    
    if real_result.num_trades < 5:
        return {'real_pnl': real_result.total_pnl_pct, 'p_value': 1.0, 'n_trades': real_result.num_trades}
    
    real_pnl = real_result.total_pnl_pct
    
    # Get price returns
    returns = np.diff(data['close']) / data['close'][:-1]
    
    # Generate random trades
    better_count = 0
    random_pnls = []
    
    n_bars = len(data['close'])
    trade_bars = [t.entry_bar for t in real_result.trades]
    
    for _ in range(n_perm):
        # Random entry bars (uniformly distributed)
        random_entries = sorted(np.random.choice(range(200, n_bars - 20), len(trade_bars), replace=False))
        
        # Compute random PnL (same number of trades, random timing)
        random_pnl = 0
        for entry in random_entries:
            # Random hold period (similar to real)
            hold = np.random.randint(1, 30)
            exit_bar = min(entry + hold, n_bars - 1)
            trade_return = (data['close'][exit_bar] / data['close'][entry] - 1) * 100
            random_pnl += trade_return
        
        random_pnls.append(random_pnl)
        
        if random_pnl >= real_pnl:
            better_count += 1
    
    p_value = better_count / n_perm
    
    return {
        'real_pnl': real_pnl,
        'real_trades': real_result.num_trades,
        'p_value': p_value,
        'random_mean_pnl': np.mean(random_pnls),
        'random_std_pnl': np.std(random_pnls),
        'z_score': (real_pnl - np.mean(random_pnls)) / (np.std(random_pnls) + 1e-10),
    }


def bootstrap_confidence(result, n_boot=5000, confidence=0.95):
    """
    Bootstrap confidence interval for mean trade PnL.
    """
    pnls = [t.pnl_pct for t in result.trades]
    
    if len(pnls) < 5:
        return None
    
    boot_means = []
    for _ in range(n_boot):
        sample = np.random.choice(pnls, len(pnls), replace=True)
        boot_means.append(np.mean(sample))
    
    alpha = (1 - confidence) / 2
    lower = np.percentile(boot_means, alpha * 100)
    upper = np.percentile(boot_means, (1 - alpha) * 100)
    
    return {
        'mean': np.mean(pnls),
        'std': np.std(pnls),
        'ci_lower': lower,
        'ci_upper': upper,
        'confidence': confidence,
        'n_trades': len(pnls),
    }


def run_tests():
    """Run statistical tests on validated strategies."""
    print("=" * 80)
    print("STATISTICAL VALIDATION")
    print("=" * 80)
    
    strategies = [
        ('MeanRev_BB_20_2 | SOLUSDT', MeanReversionBollinger, {'period': 20, 'num_std': 2}, 'SOLUSDT', '4h'),
        ('MomentumRSI_7_35_65 | AVAXUSDT', MomentumRSI, {'rsi_period': 7, 'rsi_buy': 35, 'rsi_sell': 65}, 'AVAXUSDT', '4h'),
    ]
    
    all_results = []
    
    for name, strat_class, params, pair, tf in strategies:
        print(f"\n{name}")
        print("-" * 40)
        
        data = fetch_binance(pair, tf, 1000)
        if not data:
            print("  No data")
            continue
        
        strategy = strat_class(**params)
        bt = Backtester()
        result = bt.run(strategy, data)
        
        print(f"  Trades: {result.num_trades}")
        print(f"  Total PnL: {result.total_pnl_pct:+.1f}%")
        print(f"  Win Rate: {result.win_rate:.0%}")
        print(f"  Profit Factor: {min(result.profit_factor, 999):.2f}")
        print(f"  Max Drawdown: {result.max_drawdown:.1f}%")
        
        # Permutation test
        print(f"\n  Permutation test (1000 iterations)...")
        perm = permutation_test(strategy, data, n_perm=1000)
        print(f"    Real PnL: {perm['real_pnl']:+.1f}%")
        print(f"    Random mean PnL: {perm['random_mean_pnl']:+.1f}%")
        print(f"    Z-score: {perm['z_score']:.2f}")
        print(f"    P-value: {perm['p_value']:.3f}")
        
        if perm['p_value'] < 0.05:
            print(f"    *** SIGNIFICANT (p < 0.05) ***")
        else:
            print(f"    Not significant (p >= 0.05)")
        
        # Bootstrap confidence interval
        print(f"\n  Bootstrap confidence interval...")
        boot = bootstrap_confidence(result, n_boot=5000)
        if boot:
            print(f"    Mean trade PnL: {boot['mean']:+.2f}%")
            print(f"    95% CI: [{boot['ci_lower']:+.2f}%, {boot['ci_upper']:+.2f}%]")
            
            if boot['ci_lower'] > 0:
                print(f"    *** CI DOESN'T CONTAIN ZERO - SIGNIFICANT ***")
            else:
                print(f"    CI contains zero - not robust")
        
        all_results.append({
            'name': name,
            'trades': result.num_trades,
            'pnl': result.total_pnl_pct,
            'p_value': perm['p_value'],
            'z_score': perm['z_score'],
            'ci_contains_zero': boot['ci_lower'] <= 0 if boot else None,
        })
    
    # Summary
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    
    for r in all_results:
        sig_perm = "PASS" if r['p_value'] < 0.05 else "FAIL"
        sig_boot = "PASS" if r['ci_contains_zero'] == False else "FAIL"
        print(f"\n{r['name']}:")
        print(f"  Trades: {r['trades']} | PnL: {r['pnl']:+.1f}%")
        print(f"  Permutation test: {sig_perm} (p={r['p_value']:.3f})")
        print(f"  Bootstrap CI: {sig_boot}")
    
    return all_results


if __name__ == '__main__':
    run_tests()
