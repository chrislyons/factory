#!/usr/bin/env python3
"""
Polymarket Paper Trader
========================
Track paper positions on Polymarket correlated arb.
"""
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/paper_trades')
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / 'polymarket_state.json'


def api_get(url):
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
    try:
        return json.loads(result.stdout)
    except:
        return None


def get_market_price(slug):
    """Get current market price for a slug."""
    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    data = api_get(url)
    if data and len(data) > 0:
        prices_str = data[0].get('outcomePrices', '[]')
        try:
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            return float(prices[0]) if prices else None
        except:
            return None
    return None


# Our paper trades
PAPER_TRADES = [
    {
        'id': 'POLY_001',
        'question': 'Jesus Christ returns before GTA VI',
        'slug': 'will-jesus-christ-return-before-gta-vi-665',
        'direction': 'BUY_NO',
        'entry_yes_price': 0.485,
        'base_rate': 0.01,
        'position_usd': 100,
    },
    {
        'id': 'POLY_002',
        'question': 'Rihanna album before GTA VI',
        'slug': 'new-rhianna-album-before-gta-vi-926',
        'direction': 'BUY_NO',
        'entry_yes_price': 0.585,
        'base_rate': 0.15,
        'position_usd': 100,
    },
    {
        'id': 'POLY_003',
        'question': 'Trump out as President before GTA VI',
        'slug': 'trump-out-as-president-before-gta-vi-846',
        'direction': 'BUY_NO',
        'entry_yes_price': 0.520,
        'base_rate': 0.15,
        'position_usd': 75,
    },
]


def run_paper_tracker():
    """Track paper positions."""
    print("=" * 60)
    print("POLYMARKET PAPER TRACKER")
    print("=" * 60)
    
    # Load or init state
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
    else:
        state = {
            'positions': {},
            'started': datetime.now(timezone.utc).isoformat(),
            'trades': [],
        }
    
    total_position = 0
    total_current = 0
    
    for trade in PAPER_TRADES:
        slug = trade['slug']
        
        # Get current price
        current_yes = get_market_price(slug)
        
        if current_yes is None:
            print(f"\n{trade['question'][:50]}...")
            print(f"  Could not fetch price")
            continue
        
        # Calculate PnL
        # If we bought NO at entry_yes_price, our NO cost was (1 - entry_yes_price)
        # Current NO value is (1 - current_yes)
        entry_no_price = 1 - trade['entry_yes_price']
        current_no_price = 1 - current_yes
        
        if trade['direction'] == 'BUY_NO':
            # PnL = (current_no - entry_no) / entry_no * position
            pnl_pct = (current_no_price / entry_no_price - 1) * 100 if entry_no_price > 0 else 0
            pnl_usd = trade['position_usd'] * (pnl_pct / 100)
        
        # Track
        state['positions'][trade['id']] = {
            'question': trade['question'],
            'direction': trade['direction'],
            'entry_yes': trade['entry_yes_price'],
            'current_yes': current_yes,
            'entry_no': entry_no_price,
            'current_no': current_no_price,
            'pnl_pct': pnl_pct,
            'pnl_usd': pnl_usd,
            'position_usd': trade['position_usd'],
        }
        
        total_position += trade['position_usd']
        total_current += trade['position_usd'] + pnl_usd
        
        # Display
        print(f"\n{trade['question'][:50]}...")
        print(f"  Direction: {trade['direction']}")
        print(f"  Entry YES: {trade['entry_yes_price']:.1%} | Current YES: {current_yes:.1%}")
        print(f"  Entry NO: {entry_no_price:.1%} | Current NO: {current_no_price:.1%}")
        print(f"  PnL: {pnl_pct:+.1f}% (${pnl_usd:+.2f})")
        print(f"  Position: ${trade['position_usd']}")
    
    # Summary
    total_pnl = total_current - total_position
    print(f"\n{'=' * 60}")
    print(f"TOTAL PORTFOLIO:")
    print(f"  Total Position: ${total_position}")
    print(f"  Current Value: ${total_current:.2f}")
    if total_position > 0:
        print(f"  Total PnL: ${total_pnl:+.2f} ({total_pnl/total_position*100:+.1f}%)")
    else:
        print(f"  Total PnL: $0.00 (0.0%)")
    
    # Save state
    state['last_update'] = datetime.now(timezone.utc).isoformat()
    state['total_position'] = total_position
    state['total_current'] = total_current
    state['total_pnl'] = total_pnl
    
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    
    print(f"\nState saved to {STATE_FILE}")


if __name__ == '__main__':
    run_paper_tracker()
