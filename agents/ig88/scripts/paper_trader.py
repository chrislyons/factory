#!/usr/bin/env python3
"""
IG-88 Paper Trading Framework
===============================
Monitors 15 pairs for MR signals, executes virtual trades,
tracks P&L, logs everything for assessment.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import time
import os

# Paths
BASE_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88')
DATA_DIR = BASE_DIR / 'data'
STATE_DIR = BASE_DIR / 'state' / 'paper_trading'
LOG_DIR = STATE_DIR / 'logs'
TRADE_LOG = STATE_DIR / 'trades.jsonl'
PORTFOLIO_STATE = STATE_DIR / 'portfolio.json'

# Ensure directories exist
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Friction assumption for paper trading (Kraken limit orders)
FRICTION = 0.01  # 1%

# Portfolio configuration - 15 pairs
PORTFOLIO = {
    # STRONG (2.5% size)
    'ARB':   {'rsi': 18, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 2.5, 'tier': 'STRONG'},
    'SUI':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25, 'size': 2.5, 'tier': 'STRONG'},
    'AVAX':  {'rsi': 20, 'bb': 0.15, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 2.5, 'tier': 'STRONG'},
    'MATIC': {'rsi': 25, 'bb': 0.15, 'vol': 1.8, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 2.5, 'tier': 'STRONG'},
    'UNI':   {'rsi': 22, 'bb': 0.10, 'vol': 1.8, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 2.0, 'tier': 'STRONG'},
    # MEDIUM (1.5% size)
    'DOT':   {'rsi': 20, 'bb': 0.10, 'vol': 1.0, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.5, 'tier': 'MEDIUM'},
    'ALGO':  {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 1.5, 'tier': 'MEDIUM'},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25, 'size': 1.5, 'tier': 'MEDIUM'},
    'FIL':   {'rsi': 20, 'bb': 0.10, 'vol': 1.0, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.5, 'tier': 'MEDIUM'},
    # WEAK (1.0% size)
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'LINK':  {'rsi': 18, 'bb': 0.05, 'vol': 1.8, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'AAVE':  {'rsi': 22, 'bb': 0.15, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 1.0, 'tier': 'WEAK'},
    'SNX':   {'rsi': 22, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
}


class PaperTrader:
    def __init__(self):
        self.positions = {}  # Current open positions
        self.trades = []     # Completed trades
        self.scan_count = 0
        self.start_time = datetime.now(timezone.utc)
        self.load_state()
    
    def load_state(self):
        """Load existing state if available."""
        if PORTFOLIO_STATE.exists():
            with open(PORTFOLIO_STATE) as f:
                state = json.load(f)
                self.positions = state.get('positions', {})
                self.trades = state.get('completed_trades', [])
                self.scan_count = state.get('scan_count', 0)
                print(f"Loaded state: {len(self.positions)} positions, {len(self.trades)} completed trades")
    
    def save_state(self):
        """Save current state."""
        state = {
            'positions': self.positions,
            'completed_trades': self.trades[-100:],  # Keep last 100
            'scan_count': self.scan_count,
            'last_update': datetime.now(timezone.utc).isoformat(),
            'stats': self.get_stats()
        }
        with open(PORTFOLIO_STATE, 'w') as f:
            json.dump(state, f, indent=2)
    
    def log_trade(self, trade):
        """Append trade to log file."""
        with open(TRADE_LOG, 'a') as f:
            f.write(json.dumps(trade) + '\n')
    
    def load_data(self, pair):
        """Load 4H data for a pair."""
        # Try Binance format first
        for suffix in ['binance_{pair}_USDT_240m.parquet', 'binance_{pair}USDT_240m.parquet']:
            path = DATA_DIR / suffix.format(pair=pair)
            if path.exists():
                return pd.read_parquet(path)
        return None
    
    def compute_indicators(self, df):
        """Compute RSI, BB%, ATR, Volume ratio."""
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        
        # RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
        rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
        
        # Bollinger Bands
        sma20 = df['close'].rolling(20).mean().values
        std20 = df['close'].rolling(20).std().values
        bb_lower = sma20 - std20 * 2
        bb_upper = sma20 + std20 * 2
        bb_pct = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
        
        # ATR
        tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
        atr = pd.Series(tr).rolling(14).mean().values
        
        # Volume ratio
        vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
        vol_ratio = df['volume'].values / vol_sma
        
        return c, h, l, rsi, bb_pct, atr, vol_ratio
    
    def check_entry_signal(self, pair, cfg):
        """Check if entry conditions are met."""
        df = self.load_data(pair)
        if df is None or len(df) < 100:
            return None
        
        c, h, l, rsi, bb_pct, atr, vol_ratio = self.compute_indicators(df)
        
        # Check most recent bar (index -2, since -1 is incomplete)
        i = -2
        
        if rsi[i] < cfg['rsi'] and bb_pct[i] < cfg['bb'] and vol_ratio[i] > cfg['vol']:
            return {
                'pair': pair,
                'price': c[i],
                'rsi': float(rsi[i]),
                'bb_pct': float(bb_pct[i]),
                'vol_ratio': float(vol_ratio[i]),
                'atr': float(atr[i]),
                'timestamp': df.index[i].isoformat() if hasattr(df.index[i], 'isoformat') else str(df.index[i])
            }
        return None
    
    def check_exit_conditions(self, pair, position, current_bar):
        """Check if stop-loss or take-profit hit."""
        c, h, l = current_bar['close'], current_bar['high'], current_bar['low']
        
        stop_price = position['entry_price'] - position['atr'] * position['stop_mult']
        target_price = position['entry_price'] + position['atr'] * position['target_mult']
        
        # Check stop (intraday low hit stop)
        if l <= stop_price:
            return 'STOP', stop_price
        
        # Check target (intraday high hit target)
        if h >= target_price:
            return 'TARGET', target_price
        
        # Check time exit (bars held >= max bars)
        bars_held = position.get('bars_held', 0) + 1
        if bars_held >= position['max_bars']:
            return 'TIME', c
        
        return None, None
    
    def open_position(self, signal, cfg):
        """Open a new paper position."""
        pair = signal['pair']
        
        position = {
            'pair': pair,
            'entry_price': signal['price'],
            'entry_time': signal['timestamp'],
            'atr': signal['atr'],
            'stop_mult': cfg['stop'],
            'target_mult': cfg['target'],
            'max_bars': cfg['bars'],
            'size_pct': cfg['size'],
            'tier': cfg['tier'],
            'bars_held': 0,
            'stop_price': signal['price'] - signal['atr'] * cfg['stop'],
            'target_price': signal['price'] + signal['atr'] * cfg['target'],
        }
        
        self.positions[pair] = position
        
        trade_log = {
            'action': 'OPEN',
            'pair': pair,
            'price': signal['price'],
            'time': signal['timestamp'],
            'tier': cfg['tier'],
            'size_pct': cfg['size'],
            'rsi': signal['rsi'],
            'bb_pct': signal['bb_pct'],
        }
        self.log_trade(trade_log)
        
        return position
    
    def close_position(self, pair, exit_price, exit_reason, exit_time):
        """Close a paper position and record trade."""
        position = self.positions.pop(pair, None)
        if not position:
            return None
        
        # Calculate P&L
        gross_return = (exit_price - position['entry_price']) / position['entry_price']
        net_return = gross_return - FRICTION  # Subtract friction
        pnl_pct = net_return * 100
        pnl_weighted = net_return * position['size_pct']  # Weighted by position size
        
        trade = {
            'action': 'CLOSE',
            'pair': pair,
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'entry_time': position['entry_time'],
            'exit_time': exit_time,
            'exit_reason': exit_reason,
            'pnl_pct': round(pnl_pct, 3),
            'pnl_weighted': round(pnl_weighted, 3),
            'size_pct': position['size_pct'],
            'tier': position['tier'],
            'bars_held': position.get('bars_held', 0),
        }
        
        self.trades.append(trade)
        self.log_trade(trade)
        
        return trade
    
    def get_stats(self):
        """Calculate performance statistics."""
        if not self.trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'profit_factor': 0,
            }
        
        pnls = [t['pnl_weighted'] for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        total_pnl = sum(pnls)
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 0
        
        return {
            'total_trades': len(self.trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': round(len(wins) / len(self.trades) * 100, 1) if self.trades else 0,
            'total_pnl': round(total_pnl, 3),
            'avg_pnl': round(total_pnl / len(self.trades), 3),
            'profit_factor': round(gross_profit / gross_loss, 2) if gross_loss > 0 else 9.99,
            'largest_win': round(max(pnls), 3) if pnls else 0,
            'largest_loss': round(min(pnls), 3) if pnls else 0,
        }
    
    def scan(self):
        """Run one scan cycle."""
        self.scan_count += 1
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        
        print(f"\n{'=' * 70}")
        print(f"SCAN #{self.scan_count} | {timestamp}")
        print(f"{'=' * 70}")
        
        # Update existing positions
        positions_to_check = list(self.positions.items())
        for pair, position in positions_to_check:
            df = self.load_data(pair)
            if df is None:
                continue
            
            c, h, l, rsi, bb_pct, atr, vol_ratio = self.compute_indicators(df)
            
            current_bar = {
                'close': c[-2],  # Use completed bar
                'high': h[-2],
                'low': l[-2]
            }
            
            # Update bars held
            position['bars_held'] = position.get('bars_held', 0) + 1
            
            exit_reason, exit_price = self.check_exit_conditions(pair, position, current_bar)
            
            if exit_reason:
                trade = self.close_position(pair, exit_price, exit_reason, df.index[-2].isoformat())
                if trade:
                    pnl_str = f"\033[92m+{trade['pnl_pct']:.2f}%\033[0m" if trade['pnl_pct'] > 0 else f"\033[91m{trade['pnl_pct']:.2f}%\033[0m"
                    print(f"  CLOSE {pair}: {exit_reason} @ {exit_price:.4f} | PnL: {pnl_str}")
        
        # Check for new entries
        open_pairs = set(self.positions.keys())
        max_positions = 7
        
        for pair, cfg in PORTFOLIO.items():
            if pair in open_pairs:
                continue
            if len(self.positions) >= max_positions:
                break
            
            signal = self.check_entry_signal(pair, cfg)
            if signal:
                position = self.open_position(signal, cfg)
                print(f"  OPEN  {pair}: @ {signal['price']:.4f} | RSI={signal['rsi']:.0f} BB={signal['bb_pct']:.2f} Vol={signal['vol_ratio']:.1f}x")
        
        # Print status
        stats = self.get_stats()
        print(f"\nPositions: {len(self.positions)}/{max_positions}")
        print(f"Trades: {stats['total_trades']} | WR: {stats['win_rate']}% | PnL: {stats['total_pnl']:.2f}% | PF: {stats['profit_factor']:.2f}")
        
        self.save_state()
        
        return stats


def main():
    """Main paper trading loop."""
    print("IG-88 PAPER TRADER v1.0")
    print("=" * 70)
    print(f"Pairs: {len(PORTFOLIO)}")
    print(f"Friction: {FRICTION*100:.0f}%")
    print(f"State dir: {STATE_DIR}")
    print()
    
    trader = PaperTrader()
    
    # Run continuous scan
    while True:
        try:
            trader.scan()
            
            # Wait for next 4H candle
            # 4H candles close at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
            # Check every 5 minutes
            print(f"\nNext scan in 5 minutes... (Ctrl+C to stop)")
            time.sleep(300)
            
        except KeyboardInterrupt:
            print("\n\nPaper trader stopped.")
            trader.save_state()
            print(f"State saved to {PORTFOLIO_STATE}")
            break


if __name__ == '__main__':
    main()
