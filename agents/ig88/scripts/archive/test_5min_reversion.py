#!/usr/bin/env python3
"""
5-Minute Mean Reversion Test
==============================
Candle pattern analysis showed DOWN candles have 56.8% reversal rate.
Test: buy after down candles in ranging markets.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
import subprocess
import json
from datetime import datetime


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
    returns = np.diff(np.log(closes))
    rv = np.full(len(closes), np.nan)
    for i in range(period, len(returns) + 1):
        rv[i] = np.std(returns[i-period:i]) * np.sqrt(252 * 288)
    return rv


def kelly_fraction(win_rate, avg_win, avg_loss):
    if avg_loss == 0:
        return 0
    b = avg_win / abs(avg_loss)
    f = (win_rate * b - (1 - win_rate)) / b
    return max(0, f)


class MeanReversion5m:
    """
    Mean reversion on 5-minute BTC.
    
    Entry: After a down candle of certain size, in LOW volatility regime.
    Exit: After X candles or when position reaches target.
    
    Based on insight: DOWN candles have 56.8% reversal rate.
    """
    
    def __init__(self, vol_threshold=0.3, min_body_pct=0.1, hold_candles=3, target_pct=0.15):
        self.vol_threshold = vol_threshold  # LOW vol for reversion
        self.min_body_pct = min_body_pct
        self.hold_candles = hold_candles
        self.target_pct = target_pct
        self.trades = []
    
    def run(self, data):
        n = len(data['close'])
        rv = realized_vol(data['close'], 12)
        
        # Calculate indicators
        body_pct = (data['close'] - data['open']) / data['open'] * 100
        vol_ma = np.full(n, np.nan)
        for i in range(20, n):
            vol_ma[i] = np.mean(data['volume'][i-20:i])
        
        position = None
        
        for i in range(50, n - 1):
            if position is None:
                # LOOK FOR LONG ENTRY: down candle + low vol + volume spike
                if (np.isnan(rv[i]) or np.isnan(body_pct[i])):
                    continue
                
                conditions = [
                    rv[i] < self.vol_threshold,  # LOW volatility (ranging)
                    body_pct[i] < -self.min_body_pct,  # Down candle
                    data['volume'][i] > vol_ma[i] * 1.0,  # At least avg volume
                ]
                
                if all(conditions):
                    position = {
                        'entry_price': data['close'][i],
                        'entry_idx': i,
                        'type': 'LONG',
                    }
            
            else:
                # Check exit
                hold = i - position['entry_idx']
                current_return = (data['close'][i] / position['entry_price'] - 1) * 100
                
                # Exit conditions
                take_profit = current_return >= self.target_pct
                stop_loss = current_return <= -self.target_pct * 1.5
                time_exit = hold >= self.hold_candles
                
                if take_profit or stop_loss or time_exit:
                    self.trades.append({
                        'entry_price': position['entry_price'],
                        'exit_price': data['close'][i],
                        'hold': hold,
                        'pnl': current_return,
                        'exit_reason': 'TP' if take_profit else ('SL' if stop_loss else 'TIME'),
                    })
                    position = None
        
        return self.trades
    
    def stats(self):
        if not self.trades:
            return {'trades': 0}
        
        pnls = [t['pnl'] for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        return {
            'trades': len(pnls),
            'wins': len(wins),
            'win_rate': len(wins) / len(pnls) if pnls else 0,
            'total_pnl': sum(pnls),
            'avg_win': np.mean(wins) if wins else 0,
            'avg_loss': np.mean(losses) if losses else 0,
            'pf': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else np.inf,
            'kelly': kelly_fraction(len(wins) / len(pnls), np.mean(wins) if wins else 0, abs(np.mean(losses)) if losses else 0),
        }


def run_tests():
    print("=" * 70)
    print("5-MINUTE BTC MEAN REVERSION TEST")
    print("=" * 70)
    
    data = fetch_binance('BTCUSDT', '5m', 1000)
    print(f"\nData: {len(data['close'])} candles")
    
    # Test different volatility thresholds
    thresholds = [0.2, 0.3, 0.5, 1.0, 999]
    
    print("\n" + "-" * 60)
    print(f"{'Vol Threshold':<15} {'Trades':>8} {'Win Rate':>10} {'Total PnL':>10} {'PF':>8} {'Kelly':>8}")
    print("-" * 60)
    
    best_pf = 0
    best_thresh = None
    
    for thresh in thresholds:
        strategy = MeanReversion5m(vol_threshold=thresh)
        strategy.run(data)
        s = strategy.stats()
        
        if s['trades'] >= 10:
            print(f"{thresh:<15.2f} {s['trades']:>8} {s['win_rate']:>9.1%} {s['total_pnl']:>9.2f}% {min(s['pf'], 999):>8.2f} {s['kelly']:>7.1%}")
            
            if s['pf'] > best_pf:
                best_pf = s['pf']
                best_thresh = thresh
    
    print("\n" + "=" * 70)
    print(f"BEST VOLATILITY THRESHOLD: {best_thresh} (PF = {best_pf:.2f})")
    print("=" * 70)
    
    # Now test across multiple pairs
    print("\n" + "-" * 60)
    print("CROSS-PAIR VALIDATION (vol_threshold=0.3)")
    print("-" * 60)
    
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'LINKUSDT']
    
    for pair in pairs:
        data = fetch_binance(pair, '5m', 1000)
        strategy = MeanReversion5m(vol_threshold=0.3)
        strategy.run(data)
        s = strategy.stats()
        
        if s['trades'] >= 5:
            print(f"{pair:<12} trades={s['trades']:>3} | WR={s['win_rate']:.0%} | PnL={s['total_pnl']:+.2f}% | PF={min(s['pf'], 999):.2f}")


if __name__ == '__main__':
    run_tests()
