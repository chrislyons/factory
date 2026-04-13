"""
Position Manager
================
Tracks open positions, checks stops/targets, manages exits.
Maintains state in JSON file for persistence across sessions.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
STATE_FILE = DATA_DIR / 'active_positions.json'
TRADE_LOG = DATA_DIR / 'trade_log.jsonl'

# Friction constant
FRICTION = 0.0025


def load_pair_data(pair):
    """Load current OHLCV data."""
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    return pd.read_parquet(path)


def load_positions():
    """Load active positions from disk."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'positions': [], 'last_updated': None}


def save_positions(state):
    """Save positions to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state['last_updated'] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def log_trade(trade):
    """Append trade to log file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    trade['timestamp'] = datetime.now(timezone.utc).isoformat()
    with open(TRADE_LOG, 'a') as f:
        f.write(json.dumps(trade) + '\n')


def open_position(pair, strategy, entry_price, stop_pct, target_pct, size_pct, exit_bars=None):
    """Open a new position."""
    state = load_positions()
    
    # Check if already have position in this pair
    for pos in state['positions']:
        if pos['pair'] == pair and pos['status'] == 'OPEN':
            return None  # Already have position
    
    position = {
        'id': f"{pair}_{strategy}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        'pair': pair,
        'strategy': strategy,
        'entry_price': entry_price,
        'entry_time': datetime.now(timezone.utc).isoformat(),
        'stop_price': entry_price * (1 - stop_pct),
        'target_price': entry_price * (1 + target_pct),
        'stop_pct': stop_pct,
        'target_pct': target_pct,
        'size_pct': size_pct,
        'exit_bars': exit_bars,
        'entry_bar_index': None,  # Set when we know the bar index
        'bars_held': 0,
        'status': 'OPEN',
        'exit_price': None,
        'exit_reason': None,
        'pnl_pct': None,
    }
    
    state['positions'].append(position)
    save_positions(state)
    
    log_trade({
        'action': 'OPEN',
        'position': position,
    })
    
    return position


def close_position(position_id, exit_price, reason):
    """Close a position."""
    state = load_positions()
    
    for pos in state['positions']:
        if pos['id'] == position_id and pos['status'] == 'OPEN':
            pnl_pct = (exit_price - pos['entry_price']) / pos['entry_price'] - FRICTION
            
            pos['status'] = 'CLOSED'
            pos['exit_price'] = exit_price
            pos['exit_reason'] = reason
            pos['exit_time'] = datetime.now(timezone.utc).isoformat()
            pos['pnl_pct'] = float(pnl_pct)
            
            save_positions(state)
            
            log_trade({
                'action': 'CLOSE',
                'position': pos,
            })
            
            return pos
    
    return None


def check_positions():
    """
    Check all open positions for stops, targets, and time-based exits.
    Returns list of closed positions.
    """
    state = load_positions()
    closed = []
    
    for pos in state['positions']:
        if pos['status'] != 'OPEN':
            continue
        
        pair = pos['pair']
        try:
            df = load_pair_data(pair)
        except:
            continue
        
        # Get current price (last closed bar)
        current_price = df['close'].iloc[-2]  # Second-to-last (most recent closed)
        high = df['high'].iloc[-2]
        low = df['low'].iloc[-2]
        
        # Update bars held
        pos['bars_held'] = pos.get('bars_held', 0) + 1
        
        # Check stop loss
        if low <= pos['stop_price']:
            closed_pos = close_position(pos['id'], pos['stop_price'], 'STOP')
            if closed_pos:
                closed.append(closed_pos)
            continue
        
        # Check take profit
        if high >= pos['target_price']:
            closed_pos = close_position(pos['id'], pos['target_price'], 'TARGET')
            if closed_pos:
                closed.append(closed_pos)
            continue
        
        # Check time-based exit
        if pos.get('exit_bars') and pos['bars_held'] >= pos['exit_bars']:
            closed_pos = close_position(pos['id'], current_price, 'TIME')
            if closed_pos:
                closed.append(closed_pos)
            continue
    
    return closed


def get_portfolio_state():
    """Get current portfolio state summary."""
    state = load_positions()
    
    open_positions = [p for p in state['positions'] if p['status'] == 'OPEN']
    closed_positions = [p for p in state['positions'] if p['status'] == 'CLOSED']
    
    total_exposure = sum(p['size_pct'] for p in open_positions)
    
    # Calculate open P&L
    open_pnl = 0
    for pos in open_positions:
        try:
            df = load_pair_data(pos['pair'])
            current_price = df['close'].iloc[-2]
            pnl = (current_price - pos['entry_price']) / pos['entry_price'] - FRICTION
            open_pnl += pnl * pos['size_pct'] / 100
        except:
            pass
    
    # Calculate closed P&L
    closed_pnl = sum(p.get('pnl_pct', 0) * p['size_pct'] / 100 for p in closed_positions)
    
    return {
        'open_count': len(open_positions),
        'closed_count': len(closed_positions),
        'total_exposure': total_exposure,
        'open_positions': open_positions,
        'open_pnl_pct': open_pnl * 100,
        'closed_pnl_pct': closed_pnl * 100,
        'total_pnl_pct': (open_pnl + closed_pnl) * 100,
    }


def format_position(pos):
    """Format position for display."""
    status_icon = "🟢" if pos['status'] == 'OPEN' else "🔴"
    return (f"{status_icon} {pos['pair']:5} {pos['strategy']:5} "
            f"Entry=${pos['entry_price']:.4f} Stop=${pos['stop_price']:.4f} "
            f"Target=${pos['target_price']:.4f} Size={pos['size_pct']:.1f}% "
            f"P&L={pos.get('pnl_pct', 'N/A')}")


if __name__ == '__main__':
    state = load_positions()
    portfolio = get_portfolio_state()
    
    print("=" * 70)
    print("POSITION MANAGER")
    print("=" * 70)
    
    print(f"\nOpen Positions: {portfolio['open_count']}")
    print(f"Closed Positions: {portfolio['closed_count']}")
    print(f"Total Exposure: {portfolio['total_exposure']:.1f}%")
    print(f"Open P&L: {portfolio['open_pnl_pct']:.2f}%")
    print(f"Closed P&L: {portfolio['closed_pnl_pct']:.2f}%")
    print(f"Total P&L: {portfolio['total_pnl_pct']:.2f}%")
    
    if portfolio['open_positions']:
        print("\nOpen Positions:")
        print("-" * 70)
        for pos in portfolio['open_positions']:
            print(format_position(pos))
    
    # Check for exits
    closed = check_positions()
    if closed:
        print(f"\n{len(closed)} positions closed:")
        for pos in closed:
            print(f"  {format_position(pos)}")
