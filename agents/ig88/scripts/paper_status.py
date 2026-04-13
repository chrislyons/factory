#!/usr/bin/env python3
"""Quick status check for paper trading."""
import json
from pathlib import Path
from datetime import datetime, timezone

STATE_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/state/paper_trading')
PORTFOLIO_STATE = STATE_DIR / 'portfolio.json'

def main():
    if not PORTFOLIO_STATE.exists():
        print("No paper trading state found. Run paper_scan.py first.")
        return
    
    with open(PORTFOLIO_STATE) as f:
        state = json.load(f)
    
    stats = state.get('stats', {})
    positions = state.get('positions', {})
    last_update = state.get('last_update', 'Never')
    
    print("=" * 55)
    print("IG-88 PAPER TRADER STATUS")
    print("=" * 55)
    
    print(f"\nLast update: {last_update}")
    print(f"Total scans: {stats.get('scan_count', 0)}")
    
    print(f"\n📊 PERFORMANCE:")
    print(f"  Trades: {stats.get('total_trades', 0)} ({stats.get('winning_trades', 0)}W / {stats.get('losing_trades', 0)}L)")
    print(f"  Win Rate: {stats.get('win_rate', 0):.1f}%")
    
    pnl = stats.get('total_pnl', 0)
    pnl_str = f"+{pnl:.3f}%" if pnl >= 0 else f"{pnl:.3f}%"
    print(f"  Total PnL: {pnl_str}")
    print(f"  Profit Factor: {stats.get('profit_factor', 0):.2f}")
    
    print(f"\n📈 OPEN POSITIONS ({len(positions)}/7):")
    if positions:
        for pair, pos in positions.items():
            entry = pos['entry_price']
            atr = pos.get('atr', 0)
            stop = entry - atr * pos.get('stop_mult', 1)
            target = entry + atr * pos.get('target_mult', 2)
            bars = pos.get('bars_held', 0)
            max_bars = pos.get('max_bars', 20)
            print(f"  {pair:<8} Entry: {entry:.4f} | Stop: {stop:.4f} | Target: {target:.4f}")
            print(f"           {pos.get('tier', '?')} {pos.get('size_pct', 0)}% | Bars: {bars}/{max_bars}")
    else:
        print("  No open positions")
    
    print("\n" + "=" * 55)

if __name__ == '__main__':
    main()
