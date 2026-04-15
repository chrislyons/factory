#!/usr/bin/env python3
"""Fast position monitor - checks stops/targets on open paper positions.

This script runs frequently (every 15 min) to catch stop/target hits
between 4h signal scans. Also checks volatility regime for circuit breakers.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
PAPER_TRADES_PATH = DATA_DIR / 'paper_trades.jsonl'
LOG_PATH = DATA_DIR / 'paper_trading_log_20260413.md'
REGIME_STATE_PATH = DATA_DIR / 'current_regime.json'

# Import volatility monitor
from volatility_monitor import get_regime, get_stop_adjustment, should_close_all, should_tighten_stops, THRESHOLDS

def load_open_positions():
    """Load open positions from trades log."""
    positions = []
    if not PAPER_TRADES_PATH.exists():
        return positions
    
    with open(PAPER_TRADES_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            trade = json.loads(line)
            if trade.get('outcome') == 'open':
                positions.append(trade)
    return positions

def get_current_prices(pairs):
    """Fetch current prices from Binance."""
    prices = {}
    for pair in pairs:
        # Extract base symbol (e.g., SOL-PERP -> SOLUSDT)
        base = pair.replace('-PERP', '')
        symbol = f"{base}USDT"
        
        try:
            import urllib.request
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                prices[pair] = float(data['price'])
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
    
    return prices

def check_and_close(position, current_price):
    """Check if stop or target hit, return exit info or None."""
    entry = position['entry_price']
    side = position['side']
    stop = position.get('stop_level')
    target = position.get('target_level')
    
    if not stop or not target:
        return None
    
    if side == 'short':
        # Short: stop is above entry, target below
        if current_price >= stop:
            return {'exit_price': stop, 'reason': 'stop'}
        elif current_price <= target:
            return {'exit_price': target, 'reason': 'target'}
    else:
        # Long: stop below entry, target above
        if current_price <= stop:
            return {'exit_price': stop, 'reason': 'stop'}
        elif current_price >= target:
            return {'exit_price': target, 'reason': 'target'}
    
    return None

def close_position(trade_id, exit_price, reason):
    """Update the trade record with exit info."""
    trades = []
    with open(PAPER_TRADES_PATH) as f:
        for line in f:
            if line.strip():
                trades.append(json.loads(line))
    
    # Update the matching trade
    for trade in trades:
        if trade['trade_id'] == trade_id:
            entry = trade['entry_price']
            side = trade['side']
            size = trade['position_size_usd']
            leverage = trade.get('leverage', 1.0)
            friction = 0.0042
            
            # Calculate P&L
            if side == 'short':
                raw_pnl_pct = (entry - exit_price) / entry
            else:
                raw_pnl_pct = (exit_price - entry) / entry
            
            pnl_pct = raw_pnl_pct - friction
            pnl_usd = pnl_pct * size * leverage
            
            trade['exit_timestamp'] = datetime.now(timezone.utc).isoformat()
            trade['exit_price'] = exit_price
            trade['exit_reason'] = reason
            trade['outcome'] = 'win' if pnl_usd > 0 else 'loss'
            trade['pnl_usd'] = round(pnl_usd, 2)
            trade['pnl_pct'] = round(pnl_pct * 100, 3)
            break
    
    # Write back
    with open(PAPER_TRADES_PATH, 'w') as f:
        for trade in trades:
            f.write(json.dumps(trade) + '\n')
    
    return trade

def close_all_positions(positions, prices, reason):
    """Emergency close all positions."""
    closed = []
    for pos in positions:
        pair = pos['pair']
        price = prices.get(pair)
        if price is None:
            continue
        trade = close_position(pos['trade_id'], price, reason)
        closed.append(trade)
        print(f"  CLOSED: {pair} {pos['side']} @ ${price:.4f} | P&L: ${trade['pnl_usd']:+.2f}")
    return closed

def adjust_stops_for_volatility(positions, regime):
    """Tighten stops based on volatility regime."""
    adjustment = get_stop_adjustment(regime)
    
    if adjustment >= 1.0:
        return  # No adjustment needed
    
    print(f"  Volatility adjustment: tightening stops to {adjustment*100:.0f}%")
    
    for pos in positions:
        if pos.get('stop_level') and pos.get('target_level'):
            entry = pos['entry_price']
            stop = pos['stop_level']
            target = pos['target_level']
            
            # Tighten stop (move closer to entry)
            if pos['side'] == 'short':
                # Short stop is above entry - move it down
                new_stop = entry + (stop - entry) * adjustment
            else:
                # Long stop is below entry - move it up
                new_stop = entry - (entry - stop) * adjustment
            
            pos['stop_level'] = new_stop
            print(f"    {pos['pair']}: Stop ${stop:.4f} -> ${new_stop:.4f}")

def main():
    print(f"=== Position Check {datetime.now(timezone.utc).strftime('%H:%M UTC')} ===")
    
    # Check volatility regime first
    regime = get_regime()
    if regime:
        print(f"  Regime: {regime['state']} - {regime['message']}")
    
    positions = load_open_positions()
    if not positions:
        print("  No open positions")
        return
    
    print(f"  Open positions: {len(positions)}")
    
    # Get unique pairs
    pairs = list(set(p['pair'] for p in positions))
    prices = get_current_prices(pairs)
    
    # CIRCUIT BREAKER: Close all positions in crash
    if regime and should_close_all(regime):
        print("\n  ⚠️  CIRCUIT BREAKER TRIGGERED")
        print(f"  {regime['message']}")
        closed = close_all_positions(positions, prices, 'circuit_breaker')
        print(f"  Emergency closed {len(closed)} positions")
        return
    
    # Tighten stops if volatility elevated
    if regime and should_tighten_stops(regime):
        adjust_stops_for_volatility(positions, regime)
    
    # Normal position checking
    for pos in positions:
        pair = pos['pair']
        price = prices.get(pair)
        
        if price is None:
            print(f"  {pair}: No price data")
            continue
        
        result = check_and_close(pos, price)
        
        if result:
            trade = close_position(pos['trade_id'], result['exit_price'], result['reason'])
            print(f"  CLOSED: {pair} {pos['side']} | {result['reason'].upper()} | P&L: ${trade['pnl_usd']:+.2f}")
        else:
            # Calculate unrealized P&L
            entry = pos['entry_price']
            if pos['side'] == 'short':
                upnl = (entry - price) / entry
            else:
                upnl = (price - entry) / entry
            
            leverage = pos.get('leverage', 1.0)
            upnl_usd = upnl * pos['position_size_usd'] * leverage
            
            # Show adjusted stop if volatility is high
            stop_note = ""
            if regime and should_tighten_stops(regime) and pos.get('stop_level'):
                stop_note = f" | Stop: ${pos['stop_level']:.4f}"
            
            print(f"  {pair} {pos['side']}: ${price:.4f} | Unrealized: ${upnl_usd:+.2f}{stop_note}")
    
    print("  Done.")

if __name__ == '__main__':
    main()
