#!/usr/bin/env python3
"""
Final Statistical Test
=======================
Proper significance tests on strategies with sufficient sample size.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
from src.quant.backtest_framework import Backtester, Strategy, Position
import subprocess
import json
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/systematic')


def fetch_binance_full(symbol, interval='1h'):
    """Fetch max data."""
    all_data = []
    end_time = None
    
    for _ in range(10):
        if end_time:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000&endTime={end_time}"
        else:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000"
        
        result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
        try:
            data = json.loads(result.stdout)
            if not data:
                break
            all_data = data + all_data
            end_time = data[0][0] - 1
        except:
            break
        
        if len(data) < 1000:
            break
    
    if not all_data:
        return None
    
    return {
        'open': np.array([float(d[1]) for d in all_data]),
        'high': np.array([float(d[2]) for d in all_data]),
        'low': np.array([float(d[3]) for d in all_data]),
        'close': np.array([float(d[4]) for d in all_data]),
        'volume': np.array([float(d[5]) for d in all_data]),
    }


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


def bootstrap_ci(pnls, n_boot=10000, confidence=0.95):
    """Bootstrap confidence interval."""
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
    }


def walk_forward_test(strat_class, params, data, n_splits=5):
    """Walk-forward with multiple splits."""
    n = len(data['close'])
    window = n // (n_splits + 1)
    
    results = []
    for split in range(n_splits):
        test_start = (split + 1) * window
        test_end = min(test_start + window, n)
        
        if test_end - test_start < 500:
            continue
        
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


def run_final_tests():
    """Run comprehensive tests on best candidates."""
    print("=" * 80)
    print("FINAL STATISTICAL VALIDATION")
    print("=" * 80)
    
    candidates = [
        ('Donchian_20', 'AVAXUSDT', DonchianBreakout, {'period': 20, 'hold': 10}),
        ('Donchian_20', 'LINKUSDT', DonchianBreakout, {'period': 20, 'hold': 10}),
        ('Donchian_20', 'NEARUSDT', DonchianBreakout, {'period': 20, 'hold': 10}),
        ('Donchian_20', 'ETHUSDT', DonchianBreakout, {'period': 20, 'hold': 10}),
    ]
    
    validated = []
    
    for name, pair, strat_class, params in candidates:
        print(f"\n{'=' * 60}")
        print(f"{name} | {pair}")
        print(f"{'=' * 60}")
        
        data = fetch_binance_full(pair, '1h')
        if not data:
            continue
        
        print(f"Bars: {len(data['close'])}")
        
        # Full period test
        strategy = strat_class(**params)
        bt = Backtester()
        result = bt.run(strategy, data)
        
        print(f"\nFull Period:")
        print(f"  Trades: {result.num_trades}")
        print(f"  PnL: {result.total_pnl_pct:+.1f}%")
        print(f"  PF: {min(result.profit_factor, 999):.2f}")
        print(f"  Win Rate: {result.win_rate:.1%}")
        print(f"  Max DD: {result.max_drawdown:.1f}%")
        
        # Extract trade PnLs for statistical tests
        trade_pnls = [t.pnl_pct for t in result.trades]
        
        # Bootstrap CI
        print(f"\nBootstrap CI (10000 iterations):")
        boot = bootstrap_ci(trade_pnls)
        print(f"  Mean trade PnL: {boot['mean']:+.2f}%")
        print(f"  95% CI: [{boot['ci_lower']:+.2f}%, {boot['ci_upper']:+.2f}%]")
        
        ci_excludes_zero = boot['ci_lower'] > 0
        
        # Walk-forward
        print(f"\nWalk-Forward (5 splits):")
        wf = walk_forward_test(strat_class, params, data, n_splits=5)
        
        for r in wf:
            print(f"  Split {r['split']}: trades={r['trades']}, PnL={r['pnl']:+.1f}%, PF={min(r['pf'], 999):.2f}")
        
        profitable_splits = sum(1 for r in wf if r['pnl'] > 0)
        total_wf_trades = sum(r['trades'] for r in wf)
        avg_wf_pnl = np.mean([r['pnl'] for r in wf])
        
        print(f"\n  Summary: {profitable_splits}/{len(wf)} splits profitable")
        print(f"  WF trades: {total_wf_trades}")
        print(f"  Avg WF PnL: {avg_wf_pnl:+.1f}%")
        
        # T-test: is mean PnL significantly > 0?
        from scipy import stats
        t_stat, p_value = stats.ttest_1samp(trade_pnls, 0)
        print(f"\nOne-sample t-test (H0: mean PnL = 0):")
        print(f"  t-statistic: {t_stat:.2f}")
        print(f"  p-value: {p_value:.4f}")
        
        # Validation criteria
        passes = [
            ('Sample size', result.num_trades >= 50),
            ('Positive PnL', result.total_pnl_pct > 0),
            ('CI excludes zero', ci_excludes_zero),
            ('WF profitable', profitable_splits >= 3),
            ('T-test significant', p_value < 0.05),
        ]
        
        print(f"\nValidation Criteria:")
        for criterion, passed in passes:
            print(f"  {'PASS' if passed else 'FAIL'}: {criterion}")
        
        all_pass = all(p[1] for p in passes)
        
        if all_pass:
            print(f"\n*** VALIDATED ***")
            validated.append({
                'name': name,
                'pair': pair,
                'trades': result.num_trades,
                'pnl': result.total_pnl_pct,
                'pf': result.profit_factor,
                'wr': result.win_rate,
                'p_value': p_value,
                'ci': [boot['ci_lower'], boot['ci_upper']],
            })
    
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    
    if validated:
        print(f"\n{len(validated)} strategies validated:")
        for v in validated:
            print(f"\n{v['name']} | {v['pair']}:")
            print(f"  {v['trades']} trades, PnL={v['pnl']:+.1f}%, PF={v['pf']:.2f}, WR={v['wr']:.0%}")
            print(f"  p-value={v['p_value']:.4f}, 95% CI=[{v['ci'][0]:+.2f}%, {v['ci'][1]:+.2f}%]")
    else:
        print("\nNo strategies passed all validation criteria.")
        print("This is a valid finding - consistent edge is extremely rare.")
    
    with open(DATA_DIR / 'final_validation.json', 'w') as f:
        json.dump({'validated': validated}, f, indent=2)
    
    return validated


if __name__ == '__main__':
    run_final_tests()
