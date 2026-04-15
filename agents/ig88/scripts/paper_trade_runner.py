#!/usr/bin/env python3
"""
Paper Trade Runner
==================
Execute paper trades on best candidates.
Track actual PnL, not backtest PnL.
"""
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
import subprocess
import json
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/paper_trades')
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / 'current_state.json'


def fetch_binance(symbol, interval='1h', limit=100):
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


def sma(prices, period):
    n = len(prices)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        result[i] = np.mean(prices[i - period + 1:i + 1])
    return result


def donchian_channels(highs, lows, period):
    n = len(highs)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(period - 1, n):
        upper[i] = np.max(highs[i - period + 1:i + 1])
        lower[i] = np.min(lows[i - period + 1:i + 1])
    return upper, lower


class PaperTrader:
    """Simple paper trader for Donchian breakout."""
    
    def __init__(self, pair, period=20, hold=10, position_size=100):
        self.pair = pair
        self.period = period
        self.hold = hold
        self.position_size = position_size
        self.position = None
        self.trades = []
        self.equity = [1000]  # Start with $1000
    
    def update(self, data):
        """Process new bar, return signal if any."""
        n = len(data['close'])
        if n < self.period + 1:
            return None
        
        upper, lower = donchian_channels(data['high'], data['low'], self.period)
        
        i = n - 1  # Latest bar
        signal = None
        
        # Check exit first
        if self.position is not None:
            bars_held = i - self.position['entry_bar']
            
            exit_price = None
            exit_reason = None
            
            # Stop: price breaks below lower channel
            if data['close'][i] < lower[i]:
                exit_price = data['close'][i]
                exit_reason = 'CHANNEL_BREAK'
            
            # Time exit
            elif bars_held >= self.hold:
                exit_price = data['close'][i]
                exit_reason = 'TIME_EXIT'
            
            if exit_price:
                pnl = (exit_price / self.position['entry_price'] - 1) * self.position_size
                self.trades.append({
                    'entry_time': self.position['entry_time'],
                    'exit_time': datetime.now(timezone.utc).isoformat(),
                    'entry_price': self.position['entry_price'],
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'exit_reason': exit_reason,
                })
                self.equity.append(self.equity[-1] + pnl)
                self.position = None
                signal = {'action': 'EXIT', 'price': exit_price, 'pnl': pnl, 'reason': exit_reason}
        
        # Check entry
        if self.position is None:
            # Enter if price breaks above upper channel
            if i > 0 and data['close'][i] > upper[i-1]:
                self.position = {
                    'entry_price': data['close'][i],
                    'entry_bar': i,
                    'entry_time': datetime.now(timezone.utc).isoformat(),
                }
                signal = {'action': 'ENTER', 'price': data['close'][i]}
        
        return signal
    
    def get_stats(self):
        """Get trading statistics."""
        if not self.trades:
            return {'trades': 0, 'pnl': 0, 'win_rate': 0, 'pf': 0}
        
        pnls = [t['pnl'] for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        return {
            'trades': len(self.trades),
            'pnl': sum(pnls),
            'win_rate': len(wins) / len(pnls) if pnls else 0,
            'pf': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else np.inf,
            'avg_win': np.mean(wins) if wins else 0,
            'avg_loss': np.mean(losses) if losses else 0,
            'equity': self.equity[-1],
        }


def run_paper_trader():
    """Run paper trader on live data."""
    print("=" * 60)
    print("PAPER TRADING - Donchian Breakout")
    print("=" * 60)
    
    # Load state or create new
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
    else:
        state = {
            'traders': {},
            'started': datetime.now(timezone.utc).isoformat(),
        }
    
    # Pairs to trade
    pairs = ['AVAXUSDT', 'NEARUSDT', 'LINKUSDT', 'ETHUSDT']
    
    for pair in pairs:
        print(f"\n{pair}:")
        
        # Create trader if not exists
        if pair not in state['traders']:
            state['traders'][pair] = {
                'position': None,
                'trades': [],
                'equity': [1000],
            }
        
        # Fetch latest data
        data = fetch_binance(pair, '1h', 100)
        if not data:
            print("  No data")
            continue
        
        # Recreate trader from state
        trader = PaperTrader(pair, period=20, hold=10)
        trader.position = state['traders'][pair]['position']
        trader.trades = state['traders'][pair]['trades']
        trader.equity = state['traders'][pair]['equity']
        
        # Process latest bar
        signal = trader.update(data)
        
        if signal:
            print(f"  SIGNAL: {signal['action']} @ ${signal['price']:.2f}")
            if signal['action'] == 'EXIT':
                print(f"    PnL: ${signal['pnl']:+.2f} | Reason: {signal['reason']}")
        else:
            if trader.position:
                print(f"  HOLDING: entry=${trader.position['entry_price']:.2f}, "
                      f"bars_held={len(data['close']) - trader.position['entry_bar']}")
            else:
                print(f"  WAITING for entry signal")
        
        # Show stats
        stats = trader.get_stats()
        if stats['trades'] > 0:
            print(f"  Stats: {stats['trades']} trades, PnL=${stats['pnl']:+.2f}, "
                  f"WR={stats['win_rate']:.0%}, PF={min(stats['pf'], 999):.2f}")
        
        # Update state
        state['traders'][pair] = {
            'position': trader.position,
            'trades': trader.trades,
            'equity': trader.equity,
        }
    
    # Save state
    state['last_update'] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    
    print(f"\nState saved to {STATE_FILE}")


if __name__ == '__main__':
    run_paper_trader()
