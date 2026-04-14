#!/usr/bin/env python3
"""
Max Data Test
==============
Test strategies with maximum historical data.
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
    """Fetch maximum available data."""
    all_data = []
    end_time = None
    
    for _ in range(10):  # Max 10 pages = 10000 bars
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
            end_time = data[0][0] - 1  # Go backwards
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


def run_max_test():
    """Test with max data."""
    print("=" * 80)
    print("MAXIMUM DATA TEST")
    print("=" * 80)
    
    # Test Donchian on multiple pairs with max data
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'NEARUSDT', 'LINKUSDT', 'UNIUSDT', 'INJUSDT']
    
    results = []
    
    for pair in pairs:
        print(f"\n{pair}:")
        data = fetch_binance_full(pair, '1h')
        
        if not data:
            print("  No data")
            continue
        
        print(f"  Bars: {len(data['close'])}")
        
        # Test Donchian 20
        strategy = DonchianBreakout(period=20, hold=10)
        bt = Backtester()
        result = bt.run(strategy, data)
        
        print(f"  Donchian_20: trades={result.num_trades}, PnL={result.total_pnl_pct:+.1f}%, "
              f"PF={min(result.profit_factor, 999):.2f}, WR={result.win_rate:.0%}, "
              f"DD={result.max_drawdown:.1f}%")
        
        if result.num_trades >= 20 and result.total_pnl_pct > 0:
            results.append({
                'pair': pair,
                'strategy': 'Donchian_20',
                'bars': len(data['close']),
                'trades': result.num_trades,
                'pnl': result.total_pnl_pct,
                'pf': min(result.profit_factor, 999),
                'wr': result.win_rate,
                'dd': result.max_drawdown,
            })
    
    # Also test on 1D for more history
    print("\n" + "=" * 40)
    print("DAILY TIMEFRAME (longer history)")
    print("=" * 40)
    
    for pair in pairs:
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval=1d&limit=1000"
        result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
        try:
            data_raw = json.loads(result.stdout)
            data = {
                'open': np.array([float(d[1]) for d in data_raw]),
                'high': np.array([float(d[2]) for d in data_raw]),
                'low': np.array([float(d[3]) for d in data_raw]),
                'close': np.array([float(d[4]) for d in data_raw]),
                'volume': np.array([float(d[5]) for d in data_raw]),
            }
        except:
            continue
        
        print(f"\n{pair}: {len(data['close'])} bars")
        
        strategy = DonchianBreakout(period=20, hold=10)
        bt = Backtester()
        result = bt.run(strategy, data)
        
        print(f"  Donchian_20: trades={result.num_trades}, PnL={result.total_pnl_pct:+.1f}%, "
              f"PF={min(result.profit_factor, 999):.2f}, WR={result.win_rate:.0%}")
        
        if result.num_trades >= 15 and result.total_pnl_pct > 0:
            results.append({
                'pair': pair,
                'strategy': 'Donchian_20_1d',
                'bars': len(data['close']),
                'trades': result.num_trades,
                'pnl': result.total_pnl_pct,
                'pf': min(result.profit_factor, 999),
                'wr': result.win_rate,
                'dd': result.max_drawdown,
            })
    
    # Summary
    print("\n" + "=" * 80)
    print("RESULTS WITH SUFFICIENT SAMPLE SIZE (>=20 trades 1h, >=15 trades 1d)")
    print("=" * 80)
    
    if results:
        results.sort(key=lambda x: -x['pnl'])
        for r in results:
            print(f"  {r['strategy']:15} | {r['pair']:10} | bars={r['bars']:5} | "
                  f"trades={r['trades']:3} | PnL={r['pnl']:+.1f}% | PF={r['pf']:.2f} | WR={r['wr']:.0%}")
    else:
        print("  No strategies passed sample size threshold with positive PnL")
    
    with open(DATA_DIR / 'max_data_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return results


if __name__ == '__main__':
    run_max_test()
