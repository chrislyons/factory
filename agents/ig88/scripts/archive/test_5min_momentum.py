#!/usr/bin/env python3
"""
5-Minute BTC Microstructure Test
==================================
Apply Stacy's insights to crypto trading:
1. Test 5-minute timeframe
2. Add volatility filter (12-candle realized vol)
3. Test candle-age based entries
4. Implement Kelly position sizing
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
import subprocess
import json
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime

# Fetch 5-minute data
def fetch_binance(symbol, interval='5m', limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    return {
        'timestamp': np.array([d[0] for d in data]),
        'open': np.array([float(d[1]) for d in data]),
        'high': np.array([float(d[2]) for d in data]),
        'low': np.array([float(d[3]) for d in data]),
        'close': np.array([float(d[4]) for d in data]),
        'volume': np.array([float(d[5]) for d in data]),
    }


def realized_vol(closes, period=12):
    """Realized volatility over N candles."""
    returns = np.diff(np.log(closes))
    if len(returns) < period:
        return np.full(len(closes), np.nan)
    
    rv = np.full(len(closes), np.nan)
    for i in range(period, len(returns) + 1):
        rv[i] = np.std(returns[i-period:i]) * np.sqrt(252 * 288)  # Annualized (5m candles)
    return rv


def candle_age_pattern(data, lookback=100):
    """
    Analyze: does price behavior within a candle follow patterns?
    Returns average return by position within candle (open, 25%, 50%, 75%, close)
    """
    # For 5m candles, look at intra-candle movement
    body = data['close'] - data['open']
    range_pct = (data['high'] - data['low']) / data['open'] * 100
    
    # Direction accuracy
    up_candles = body > 0
    down_candles = body < 0
    
    # After an up candle, what happens next?
    next_returns = np.diff(data['close']) / data['close'][:-1] * 100
    
    # Statistics
    after_up = next_returns[up_candles[:-1]]
    after_down = next_returns[down_candles[:-1]]
    
    return {
        'avg_up_candle': np.mean(body[up_candles]),
        'avg_down_candle': np.mean(body[down_candles]),
        'avg_range': np.mean(range_pct),
        'return_after_up': np.mean(after_up) if len(after_up) > 0 else 0,
        'return_after_down': np.mean(after_down) if len(after_down) > 0 else 0,
        'up_continuation': np.mean(after_up > 0) if len(after_up) > 0 else 0.5,
        'down_reversal': np.mean(after_down > 0) if len(after_down) > 0 else 0.5,
    }


def kelly_fraction(win_rate, avg_win, avg_loss):
    """Calculate Kelly fraction."""
    if avg_loss == 0:
        return 0
    b = avg_win / abs(avg_loss)
    f = (win_rate * b - (1 - win_rate)) / b
    return max(0, f)


@dataclass
class Trade:
    entry_price: float
    entry_time: int
    exit_price: float = 0
    exit_time: int = 0
    pnl: float = 0
    reason: str = ''


class Momentum5mStrategy:
    """
    5-minute momentum strategy with volatility filter.
    
    Based on Stacy's insights:
    - Volatility filter (12-candle RV)
    - Kelly position sizing
    """
    
    def __init__(self, vol_period=12, vol_threshold=0.5, min_body_pct=0.1):
        self.vol_period = vol_period
        self.vol_threshold = vol_threshold  # Annualized vol must be > threshold
        self.min_body_pct = min_body_pct  # Minimum candle body size
        self.position = None
        self.trades: List[Trade] = []
    
    def calculate_signals(self, data):
        """Calculate all indicators."""
        n = len(data['close'])
        
        # Realized volatility
        rv = realized_vol(data['close'], self.vol_period)
        
        # Candle properties
        body = data['close'] - data['open']
        body_pct = body / data['open'] * 100
        candle_range = (data['high'] - data['low']) / data['open'] * 100
        
        # Short-term momentum (5 candles)
        momentum = np.full(n, np.nan)
        for i in range(5, n):
            momentum[i] = (data['close'][i] / data['close'][i-5] - 1) * 100
        
        # Volume spike
        vol_ma = np.full(n, np.nan)
        for i in range(20, n):
            vol_ma[i] = np.mean(data['volume'][i-20:i])
        vol_spike = data['volume'] / (vol_ma + 1e-10)
        
        return {
            'rv': rv,
            'body': body,
            'body_pct': body_pct,
            'candle_range': candle_range,
            'momentum': momentum,
            'vol_spike': vol_spike,
        }
    
    def should_enter_long(self, i, data, signals):
        """
        Enter long when:
        1. Volatility is above threshold (not range-bound)
        2. Strong bullish candle (body > min_body_pct)
        3. Volume spike
        4. Positive momentum
        """
        if np.isnan(signals['rv'][i]) or np.isnan(signals['momentum'][i]):
            return False
        
        conditions = [
            signals['rv'][i] > self.vol_threshold,  # Volatility filter
            signals['body_pct'][i] > self.min_body_pct,  # Bullish candle
            signals['vol_spike'][i] > 1.2,  # Volume confirmation
            signals['momentum'][i] > 0,  # Positive momentum
        ]
        
        return all(conditions)
    
    def should_enter_short(self, i, data, signals):
        """Mirror for short."""
        if np.isnan(signals['rv'][i]) or np.isnan(signals['momentum'][i]):
            return False
        
        conditions = [
            signals['rv'][i] > self.vol_threshold,
            signals['body_pct'][i] < -self.min_body_pct,
            signals['vol_spike'][i] > 1.2,
            signals['momentum'][i] < 0,
        ]
        
        return all(conditions)
    
    def run_backtest(self, data):
        """Run backtest."""
        signals = self.calculate_signals(data)
        n = len(data['close'])
        
        in_position = False
        entry_price = 0
        entry_idx = 0
        
        for i in range(50, n - 1):
            if not in_position:
                # Check for entry
                if self.should_enter_long(i, data, signals):
                    in_position = True
                    entry_price = data['close'][i]
                    entry_idx = i
                elif self.should_enter_short(i, data, signals):
                    in_position = True
                    entry_price = data['close'][i]
                    entry_idx = i
                    # Track as negative for shorts
            else:
                # Check for exit (after 3 candles or 0.3% move)
                hold_candles = i - entry_idx
                current_return = (data['close'][i] / entry_price - 1) * 100
                
                exit_condition = (
                    hold_candles >= 3 or  # Time stop
                    abs(current_return) > 0.3  # Profit/loss target
                )
                
                if exit_condition:
                    pnl = current_return
                    trade = Trade(
                        entry_price=entry_price,
                        entry_time=data['timestamp'][entry_idx],
                        exit_price=data['close'][i],
                        exit_time=data['timestamp'][i],
                        pnl=pnl,
                        reason='time' if hold_candles >= 3 else 'target'
                    )
                    self.trades.append(trade)
                    in_position = False
        
        return self.trades
    
    def get_stats(self):
        """Calculate statistics."""
        if not self.trades:
            return {'trades': 0}
        
        pnls = [t.pnl for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        return {
            'trades': len(pnls),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(pnls) if pnls else 0,
            'total_pnl': sum(pnls),
            'avg_win': np.mean(wins) if wins else 0,
            'avg_loss': np.mean(losses) if losses else 0,
            'pf': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else np.inf,
            'kelly': kelly_fraction(len(wins) / len(pnls), np.mean(wins) if wins else 0, abs(np.mean(losses)) if losses else 0),
        }


def run_tests():
    """Run 5-minute tests."""
    print("=" * 70)
    print("5-MINUTE BTC MOMENTUM TEST")
    print("=" * 70)
    
    # Fetch data
    data = fetch_binance('BTCUSDT', '5m', 1000)
    print(f"\nData: {len(data['close'])} candles")
    print(f"Period: {datetime.fromtimestamp(data['timestamp'][0]/1000)} to {datetime.fromtimestamp(data['timestamp'][-1]/1000)}")
    
    # Analyze candle patterns
    print("\n" + "-" * 40)
    print("CANDLE PATTERN ANALYSIS")
    print("-" * 40)
    
    patterns = candle_age_pattern(data, lookback=500)
    print(f"Avg up candle body: {patterns['avg_up_candle']:.2f}")
    print(f"Avg down candle body: {patterns['avg_down_candle']:.2f}")
    print(f"Avg candle range: {patterns['avg_range']:.2f}%")
    print(f"Return after up candle: {patterns['return_after_up']:.4f}%")
    print(f"Return after down candle: {patterns['return_after_down']:.4f}%")
    print(f"Up continuation rate: {patterns['up_continuation']:.1%}")
    print(f"Down reversal rate: {patterns['down_reversal']:.1%}")
    
    # Test with volatility filter ON
    print("\n" + "-" * 40)
    print("STRATEGY: Momentum + Volatility Filter")
    print("-" * 40)
    
    strategy = Momentum5mStrategy(vol_threshold=0.5)
    trades = strategy.run_backtest(data)
    stats = strategy.get_stats()
    
    print(f"Trades: {stats.get('trades', 0)}")
    if stats.get('trades', 0) > 0:
        print(f"Win Rate: {stats['win_rate']:.1%}")
        print(f"Total PnL: {stats['total_pnl']:.2f}%")
        print(f"Avg Win: {stats['avg_win']:.3f}%")
        print(f"Avg Loss: {stats['avg_loss']:.3f}%")
        print(f"Profit Factor: {min(stats['pf'], 999):.2f}")
        print(f"Kelly Fraction: {stats['kelly']:.1%}")
    
    # Test with volatility filter OFF
    print("\n" + "-" * 40)
    print("STRATEGY: Momentum Only (No Vol Filter)")
    print("-" * 40)
    
    strategy_no_vol = Momentum5mStrategy(vol_threshold=0)  # No filter
    trades_no_vol = strategy_no_vol.run_backtest(data)
    stats_no_vol = strategy_no_vol.get_stats()
    
    print(f"Trades: {stats_no_vol.get('trades', 0)}")
    if stats_no_vol.get('trades', 0) > 0:
        print(f"Win Rate: {stats_no_vol['win_rate']:.1%}")
        print(f"Total PnL: {stats_no_vol['total_pnl']:.2f}%")
        print(f"Profit Factor: {min(stats_no_vol['pf'], 999):.2f}")
    
    # Comparison
    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    
    if stats.get('trades', 0) > 0 and stats_no_vol.get('trades', 0) > 0:
        print(f"{'Metric':<20} {'With Vol Filter':>15} {'No Filter':>15}")
        print("-" * 50)
        print(f"{'Trades':<20} {stats['trades']:>15} {stats_no_vol['trades']:>15}")
        print(f"{'Win Rate':<20} {stats['win_rate']:>14.1%} {stats_no_vol['win_rate']:>14.1%}")
        print(f"{'Total PnL':<20} {stats['total_pnl']:>14.2f}% {stats_no_vol['total_pnl']:>14.2f}%")
        print(f"{'Profit Factor':<20} {min(stats['pf'], 999):>14.2f} {min(stats_no_vol['pf'], 999):>14.2f}")
        
        # Conclusion
        print("\n" + "-" * 40)
        if stats['pf'] > stats_no_vol['pf']:
            print("CONCLUSION: Volatility filter improves results (as Stacy predicted)")
        else:
            print("CONCLUSION: Volatility filter did not help in this test")


if __name__ == '__main__':
    run_tests()
