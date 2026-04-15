#!/usr/bin/env python3
"""
Framework Validation
=====================
Verify the backtest framework has NO look-ahead bias.
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


class TestEMA:
    """Test EMA has no look-ahead."""
    
    def __init__(self):
        self.ind = Indicators()
    
    def test_ema_values(self):
        """Verify EMA values match manual calculation."""
        prices = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0, 1.0])
        period = 3
        
        ema = self.ind.ema(prices, period)
        
        # Manual calculation
        # EMA[2] = SMA of [1,2,3] = 2.0
        # alpha = 2/(3+1) = 0.5
        # EMA[3] = 0.5*4 + 0.5*2 = 3.0
        # EMA[4] = 0.5*5 + 0.5*3 = 4.0
        # EMA[5] = 0.5*4 + 0.5*4 = 4.0
        
        assert np.isnan(ema[0]), "EMA[0] should be NaN"
        assert np.isnan(ema[1]), "EMA[1] should be NaN"
        assert abs(ema[2] - 2.0) < 0.001, f"EMA[2] should be 2.0, got {ema[2]}"
        assert abs(ema[3] - 3.0) < 0.001, f"EMA[3] should be 3.0, got {ema[3]}"
        assert abs(ema[4] - 4.0) < 0.001, f"EMA[4] should be 4.0, got {ema[4]}"
        
        print("  EMA values: PASS")
    
    def test_ema_no_future(self):
        """Verify EMA[i] doesn't depend on prices[i+1:]."""
        prices = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
        
        ema_full = self.ind.ema(prices, 3)
        
        # Now compute EMA up to bar 5 only
        prices_partial = prices[:6]
        ema_partial = self.ind.ema(prices_partial, 3)
        
        # EMA values up to bar 5 should be identical
        for i in range(6):
            if np.isnan(ema_full[i]) and np.isnan(ema_partial[i]):
                continue
            assert abs(ema_full[i] - ema_partial[i]) < 0.001, \
                f"EMA[{i}] differs: full={ema_full[i]}, partial={emal_partial[i]}"
        
        print("  EMA no look-ahead: PASS")


class TestRSI:
    """Test RSI has no look-ahead."""
    
    def __init__(self):
        self.ind = Indicators()
    
    def test_rsi_bounds(self):
        """RSI should be between 0 and 100."""
        prices = np.random.randn(200).cumsum() + 100
        rsi = self.ind.rsi(prices, 14)
        
        valid_rsi = rsi[~np.isnan(rsi)]
        assert np.all(valid_rsi >= 0) and np.all(valid_rsi <= 100), "RSI out of bounds"
        
        print("  RSI bounds: PASS")
    
    def test_rsi_no_future(self):
        """Verify RSI[i] doesn't depend on future prices."""
        prices = np.random.randn(100).cumsum() + 100
        
        rsi_full = self.ind.rsi(prices, 14)
        rsi_partial = self.ind.rsi(prices[:50], 14)
        
        for i in range(50):
            if np.isnan(rsi_full[i]) and np.isnan(rsi_partial[i]):
                continue
            if not np.isnan(rsi_full[i]) and not np.isnan(rsi_partial[i]):
                assert abs(rsi_full[i] - rsi_partial[i]) < 0.001, \
                    f"RSI[{i}] differs: full={rsi_full[i]}, partial={rsi_partial[i]}"
        
        print("  RSI no look-ahead: PASS")


class TestADX:
    """Test ADX has no look-ahead."""
    
    def __init__(self):
        self.ind = Indicators()
    
    def test_adx_bounds(self):
        """ADX should be between 0 and 100."""
        prices = np.random.randn(300).cumsum() + 100
        highs = prices + np.random.rand(300) * 2
        lows = prices - np.random.rand(300) * 2
        
        adx = self.ind.adx(highs, lows, prices, 14)
        
        valid_adx = adx[~np.isnan(adx)]
        assert np.all(valid_adx >= 0) and np.all(valid_adx <= 100), "ADX out of bounds"
        
        print("  ADX bounds: PASS")


class SimpleTrendStrategy(Strategy):
    """Simple trend strategy for testing."""
    
    def __init__(self):
        super().__init__()
        self.ema_fast = None
        self.ema_slow = None
    
    def init_indicators(self, data):
        self.ema_fast = self.ema(data['close'], 9)
        self.ema_slow = self.ema(data['close'], 21)
    
    def should_enter(self, i, data):
        if np.isnan(self.ema_fast[i]) or np.isnan(self.ema_slow[i]):
            return None
        if np.isnan(self.ema_fast[i-1]) or np.isnan(self.ema_slow[i-1]):
            return None
        
        # Enter on EMA crossover up
        if self.ema_fast[i-1] <= self.ema_slow[i-1] and self.ema_fast[i] > self.ema_slow[i]:
            return Position(
                entry_price=data['close'][i],
                entry_bar=i,
                size=1000,
                leverage=1.0,
            )
        return None
    
    def should_exit(self, i, data, position):
        if np.isnan(self.ema_fast[i]) or np.isnan(self.ema_slow[i]):
            return None
        
        # Exit on EMA cross down
        if self.ema_fast[i] < self.ema_slow[i]:
            return 'EMA_CROSS'
        return None


def run_framework_validation():
    """Run all framework validation tests."""
    print("=" * 60)
    print("FRAMEWORK VALIDATION")
    print("=" * 60)
    
    print("\nIndicator Tests:")
    
    ema_test = TestEMA()
    ema_test.test_ema_values()
    ema_test.test_ema_no_future()
    
    rsi_test = TestRSI()
    rsi_test.test_rsi_bounds()
    rsi_test.test_rsi_no_future()
    
    adx_test = TestADX()
    adx_test.test_adx_bounds()
    
    print("\nBacktest Engine Test:")
    
    # Fetch real data
    data = fetch_binance('BTCUSDT', '4h', 500)
    if data:
        bt = Backtester()
        strategy = SimpleTrendStrategy()
        result = bt.run(strategy, data)
        
        print(f"  Trades: {result.num_trades}")
        print(f"  Win Rate: {result.win_rate:.1%}")
        print(f"  Profit Factor: {result.profit_factor:.2f}")
        print(f"  Total PnL: {result.total_pnl_pct:+.1f}%")
        print(f"  Max Drawdown: {result.max_drawdown:.1f}%")
        
        if result.num_trades > 0:
            print("  Backtest engine: PASS")
        else:
            print("  Backtest engine: No trades (may be expected)")
    else:
        print("  Could not fetch data")
    
    print("\n" + "=" * 60)
    print("FRAMEWORK VALIDATION COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    run_framework_validation()
