"""
Allocator Scan Loop
===================
Main execution loop for the regime-conditional allocator.
1. Determine current regime
2. Scan for signals
3. Execute trades (paper or live based on config)
4. Check existing positions
5. Log and report
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.trading.regime import get_current_regime, save_state, check_regime_transition, load_state
from src.trading.scanner import scan_all_pairs
from src.trading.position_manager import (
    load_positions, open_position, check_positions, 
    get_portfolio_state, format_position
)
import json
from datetime import datetime, timezone

# Configuration
MIN_CONFIDENCE = 0.6  # Minimum signal confidence to execute
MAX_TOTAL_EXPOSURE = 50.0  # Maximum total portfolio exposure
MAX_PER_PAIR = 20.0  # Maximum exposure per pair
PAPER_TRADING = True  # Set to False for live execution


def calculate_position_size(portfolio_state, pair_exposure, strategy_exp):
    """
    Calculate position size using Half-Kelly.
    
    Returns size as percentage of portfolio.
    """
    # Base Half-Kelly (strategy-specific)
    half_kelly = strategy_exp * 0.5  # Simplified
    
    # Cap at maximum
    max_size = min(half_kelly, 10.0)  # Max 10% per trade
    
    # Reduce if high exposure
    remaining_capacity = MAX_TOTAL_EXPOSURE - portfolio_state['total_exposure']
    if remaining_capacity < max_size:
        max_size = max(0, remaining_capacity)
    
    # Reduce if already have position in pair
    if pair_exposure > 0:
        max_size = min(max_size, MAX_PER_PAIR - pair_exposure)
    
    return max(0, max_size)


def run_scan(paper_mode=True):
    """Run one scan cycle."""
    print("=" * 70)
    print(f"ALLOCATOR SCAN - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)
    
    # 1. Determine regime
    regime = get_current_regime()
    old_state = load_state()
    
    # Check for regime transition
    is_transition, old_regime, new_regime = check_regime_transition(old_state, regime)
    save_state(regime)
    
    print(f"\nRegime: {regime['regime']}")
    print(f"  BTC 20-bar: {regime['metadata']['btc_20bar_return']*100:.2f}%")
    print(f"  BTC > 200-SMA: {regime['metadata']['price_above_200sma']}")
    print(f"  30d Vol: {regime['metadata']['realized_vol_30d']*100:.1f}%")
    print(f"\nWeights: MR={regime['weights']['mr']*100:.0f}%, H3={regime['weights']['h3']*100:.0f}%, Cash={regime['weights']['cash']*100:.0f}%")
    
    if is_transition:
        print(f"\n⚠️  REGIME TRANSITION: {old_regime} → {new_regime}")
    
    # 2. Check existing positions
    closed = check_positions()
    if closed:
        print(f"\n📋 {len(closed)} position(s) closed:")
        for pos in closed:
            print(f"  {format_position(pos)}")
    
    # 3. Get portfolio state
    portfolio = get_portfolio_state()
    print(f"\nPortfolio: {portfolio['open_count']} open, "
          f"Exposure={portfolio['total_exposure']:.1f}%, "
          f"P&L={portfolio['total_pnl_pct']:.2f}%")
    
    # 4. Scan for signals
    if regime['weights']['mr'] > 0 or regime['weights']['h3'] > 0:
        signals = scan_all_pairs(
            mr_weight=regime['weights']['mr'],
            h3_weight=regime['weights']['h3']
        )
    else:
        signals = []
    
    if not signals:
        print("\nNo signals detected.")
        return
    
    print(f"\n{len(signals)} signal(s) detected:")
    
    # 5. Execute signals
    for signal in signals:
        pair = signal['pair']
        strategy = signal['strategy']
        confidence = signal.get('confidence', 0)
        
        # Get existing exposure for this pair
        pair_exposure = sum(p['size_pct'] for p in portfolio['open_positions'] 
                          if p['pair'] == pair and p['status'] == 'OPEN')
        
        # Expected expectancy per strategy
        strat_exp = {
            'MR': 1.35,   # Portfolio average
            'H3-A': 2.07,
            'H3-B': 2.95,
        }.get(strategy, 1.0)
        
        # Calculate position size
        size = calculate_position_size(portfolio, pair_exposure, strat_exp)
        
        # Check confidence threshold
        if confidence < MIN_CONFIDENCE:
            print(f"  ⏭️  {strategy:5} {pair:5} - Confidence {confidence:.2f} < {MIN_CONFIDENCE} threshold")
            continue
        
        # Check if we have capacity
        if size < 1.0:
            print(f"  ⏭️  {strategy:5} {pair:5} - Insufficient capacity (size={size:.1f}%)")
            continue
        
        # Execute trade
        if signal['strategy'] == 'MR':
            pos = open_position(
                pair=pair,
                strategy=strategy,
                entry_price=signal['entry_price_est'],
                stop_pct=signal['stop_pct'],
                target_pct=signal['target_pct'],
                size_pct=size,
            )
        else:  # H3
            pos = open_position(
                pair=pair,
                strategy=strategy,
                entry_price=signal['entry_price_est'],
                stop_pct=0.005,
                target_pct=0.10,
                size_pct=size,
                exit_bars=signal.get('exit_bars', 10),
            )
        
        if pos:
            mode = "📄 PAPER" if paper_mode else "💰 LIVE"
            print(f"  {mode} {strategy:5} {pair:5} @ ${pos['entry_price']:.4f} "
                  f"Stop=${pos['stop_price']:.4f} Target=${pos['target_price']:.4f} "
                  f"Size={size:.1f}%")
        else:
            print(f"  ❌ {strategy:5} {pair:5} - Failed to open position")
    
    print("\n" + "=" * 70)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Allocator Scan')
    parser.add_argument('--live', action='store_true', help='Execute live trades')
    args = parser.parse_args()
    
    run_scan(paper_mode=not args.live)
