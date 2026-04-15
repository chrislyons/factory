"""
Paper Trading Pass
===================
Single pass of the paper trading system:
1. Get current regime
2. Scan for signals
3. Open/close positions (simulated)
4. Track friction vs expected
5. Log everything
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import datetime, timezone
from src.trading.regime import get_current_regime, save_state
from src.trading.scanner import scan_all_pairs
from src.trading.position_manager import (
    load_positions, open_position, check_positions,
    get_portfolio_state, save_positions
)
from src.trading.friction_tracker import estimate_pair_friction

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
PAPER_LOG = DATA_DIR / 'paper_trading_log.jsonl'

# Realistic friction estimate from OHLCV analysis
ACTUAL_FRICTION_ESTIMATE = 1.332  # Portfolio average from friction tracker


def log_paper_trade(event_type, data):
    """Log paper trading event."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'event': event_type,
        **data,
    }
    with open(PAPER_LOG, 'a') as f:
        f.write(json.dumps(entry) + '\n')


def run_paper_trade_pass():
    """Execute one paper trading pass."""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    
    # 1. Get regime
    regime = get_current_regime()
    save_state(regime)
    
    # 2. Check existing positions for exits
    closed = check_positions()
    for pos in closed:
        log_paper_trade('CLOSE', {
            'position': pos,
            'regime': regime['regime'],
        })
    
    # 3. Get portfolio state
    portfolio = get_portfolio_state()
    
    # 4. Scan for signals
    signals = []
    if regime['weights']['mr'] > 0 or regime['weights']['h3'] > 0:
        signals = scan_all_pairs(
            mr_weight=regime['weights']['mr'],
            h3_weight=regime['weights']['h3']
        )
    
    # 5. Process signals with REALISTIC friction adjustment
    trades_opened = []
    for signal in signals:
        pair = signal['pair']
        strategy = signal['strategy']
        confidence = signal.get('confidence', 0)
        
        # Get existing exposure
        pair_exposure = sum(p['size_pct'] for p in portfolio['open_positions']
                          if p['pair'] == pair and p['status'] == 'OPEN')
        
        # Calculate adjusted size based on REAL friction
        # If friction is higher than backtest, reduce size proportionally
        backtest_friction = 0.0025  # What we backtested with
        friction_ratio = ACTUAL_FRICTION_ESTIMATE / 100 / backtest_friction
        
        base_size = 8.0  # Base position size
        adjusted_size = base_size / friction_ratio  # Reduce if friction is higher
        
        # Check capacity
        if pair_exposure > 0 or adjusted_size < 1.0:
            continue
        
        # Check confidence
        if confidence < 0.6:
            continue
        
        # Open position
        if signal['strategy'] == 'MR':
            pos = open_position(
                pair=pair,
                strategy=strategy,
                entry_price=signal['entry_price_est'],
                stop_pct=signal['stop_pct'],
                target_pct=signal['target_pct'],
                size_pct=adjusted_size,
            )
        else:
            pos = open_position(
                pair=pair,
                strategy=strategy,
                entry_price=signal['entry_price_est'],
                stop_pct=0.005,
                target_pct=0.10,
                size_pct=adjusted_size,
                exit_bars=signal.get('exit_bars', 10),
            )
        
        if pos:
            trades_opened.append(pos)
            log_paper_trade('OPEN', {
                'position': pos,
                'regime': regime['regime'],
                'friction_adjusted_size': adjusted_size,
                'friction_ratio': friction_ratio,
            })
    
    # 6. Get updated portfolio state
    portfolio = get_portfolio_state()
    
    # 7. Get friction reading
    friction_data = {}
    try:
        # Sample a few pairs for friction
        for pair in ['SOL', 'AVAX', 'SUI']:
            fr = estimate_pair_friction(pair)
            friction_data[pair] = fr['estimated_total_friction']
    except:
        pass
    
    # 8. Log summary
    summary = {
        'timestamp': timestamp,
        'regime': regime['regime'],
        'mr_weight': regime['weights']['mr'],
        'h3_weight': regime['weights']['h3'],
        'open_positions': portfolio['open_count'],
        'total_exposure': portfolio['total_exposure'],
        'open_pnl': portfolio['open_pnl_pct'],
        'closed_pnl': portfolio['closed_pnl_pct'],
        'total_pnl': portfolio['total_pnl_pct'],
        'signals_detected': len(signals),
        'trades_opened': len(trades_opened),
        'trades_closed': len(closed),
        'friction_estimate': ACTUAL_FRICTION_ESTIMATE,
        'friction_by_pair': friction_data,
    }
    
    log_paper_trade('SCAN_SUMMARY', summary)
    
    return summary


if __name__ == '__main__':
    summary = run_paper_trade_pass()
    
    print("=" * 70)
    print(f"PAPER TRADE PASS - {summary['timestamp']}")
    print("=" * 70)
    print(f"Regime: {summary['regime']}")
    print(f"Weights: MR={summary['mr_weight']*100:.0f}%, H3={summary['h3_weight']*100:.0f}%")
    print(f"Signals: {summary['signals_detected']}")
    print(f"Opened: {summary['trades_opened']}, Closed: {summary['trades_closed']}")
    print(f"Positions: {summary['open_positions']}, Exposure: {summary['total_exposure']:.1f}%")
    print(f"P&L: Open={summary['open_pnl']:.2f}%, Closed={summary['closed_pnl']:.2f}%, Total={summary['total_pnl']:.2f}%")
    print(f"Friction (est): {summary['friction_estimate']:.3f}%")
    
    if summary['friction_by_pair']:
        print(f"\nFriction by pair:")
        for pair, fr in summary['friction_by_pair'].items():
            print(f"  {pair}: {fr:.3f}%")
