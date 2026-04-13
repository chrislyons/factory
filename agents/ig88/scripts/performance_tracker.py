"""
Paper Trading Performance Tracker
===================================
Monitors paper trading results and compares to backtest expectations.
Detects:
- Performance degradation (real < backtest)
- Friction divergence (actual > estimated)
- Regime-specific performance
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
PAPER_LOG = DATA_DIR / 'paper_trading_log.jsonl'
PERF_STATE = DATA_DIR / 'performance_state.json'

# Backtest expectations (from validation)
BACKTEST_EXPECTATIONS = {
    'SOL':  {'exp_pct': 0.80, 'pf': 2.27, 'wr': 16.2},
    'NEAR': {'exp_pct': 1.30, 'pf': 3.11, 'wr': 18.0},
    'LINK': {'exp_pct': 1.21, 'pf': 2.96, 'wr': 17.8},
    'AVAX': {'exp_pct': 1.61, 'pf': 3.79, 'wr': 23.3},
    'ATOM': {'exp_pct': 1.07, 'pf': 2.78, 'wr': 20.2},
    'UNI':  {'exp_pct': 0.96, 'pf': 2.50, 'wr': 14.4},
    'AAVE': {'exp_pct': 0.75, 'pf': 2.19, 'wr': 16.2},
    'ARB':  {'exp_pct': 1.22, 'pf': 2.92, 'wr': 14.9},
    'OP':   {'exp_pct': 1.87, 'pf': 4.07, 'wr': 18.7},
    'INJ':  {'exp_pct': 1.31, 'pf': 3.38, 'wr': 26.7},
    'SUI':  {'exp_pct': 2.34, 'pf': 5.23, 'wr': 26.1},
    'POL':  {'exp_pct': 0.66, 'pf': 2.05, 'wr': 15.7},
}

# Friction expectation
BACKTEST_FRICTION = 0.0025  # 0.25%
LIVE_FRICTION_ESTIMATE = 0.0133  # 1.33% from OHLCV analysis


def load_paper_log():
    """Load all paper trading logs."""
    entries = []
    if PAPER_LOG.exists():
        with open(PAPER_LOG) as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except:
                        pass
    return entries


def load_performance_state():
    """Load current performance state."""
    if PERF_STATE.exists():
        with open(PERF_STATE) as f:
            return json.load(f)
    return {
        'trades': [],
        'daily_pnl': {},
        'regime_performance': {},
        'pair_performance': {},
        'last_update': None,
    }


def save_performance_state(state):
    """Save performance state."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state['last_update'] = datetime.now(timezone.utc).isoformat()
    with open(PERF_STATE, 'w') as f:
        json.dump(state, f, indent=2)


def update_performance():
    """Update performance metrics from paper trading log."""
    entries = load_paper_log()
    state = load_performance_state()
    
    # Process all trade events
    for entry in entries:
        event = entry.get('event')
        ts = entry.get('timestamp', '')
        
        if event == 'OPEN':
            pos = entry.get('position', {})
            pair = pos.get('pair')
            strategy = pos.get('strategy')
            
            state['trades'].append({
                'id': pos.get('id'),
                'pair': pair,
                'strategy': strategy,
                'entry_price': pos.get('entry_price'),
                'entry_time': pos.get('entry_time'),
                'size_pct': pos.get('size_pct'),
                'stop_pct': pos.get('stop_pct'),
                'target_pct': pos.get('target_pct'),
                'status': 'OPEN',
            })
        
        elif event == 'CLOSE':
            pos = entry.get('position', {})
            pnl_pct = pos.get('pnl_pct', 0)
            pair = pos.get('pair')
            exit_reason = pos.get('exit_reason')
            regime = entry.get('regime', 'UNKNOWN')
            
            # Update pair performance
            if pair not in state['pair_performance']:
                state['pair_performance'][pair] = {
                    'trades': 0, 'wins': 0, 'losses': 0,
                    'total_pnl': 0, 'pnl_history': [],
                }
            
            pp = state['pair_performance'][pair]
            pp['trades'] += 1
            pp['total_pnl'] += pnl_pct
            pp['pnl_history'].append(pnl_pct)
            if pnl_pct > 0:
                pp['wins'] += 1
            else:
                pp['losses'] += 1
            
            # Update regime performance
            if regime not in state['regime_performance']:
                state['regime_performance'][regime] = {
                    'trades': 0, 'wins': 0, 'losses': 0,
                    'total_pnl': 0,
                }
            
            rp = state['regime_performance'][regime]
            rp['trades'] += 1
            rp['total_pnl'] += pnl_pct
            if pnl_pct > 0:
                rp['wins'] += 1
            else:
                rp['losses'] += 1
            
            # Mark trade as closed
            for t in state['trades']:
                if t['id'] == pos.get('id'):
                    t['status'] = 'CLOSED'
                    t['exit_price'] = pos.get('exit_price')
                    t['exit_reason'] = exit_reason
                    t['pnl_pct'] = pnl_pct
                    break
    
    save_performance_state(state)
    return state


def print_performance_report(state):
    """Print performance report."""
    print("=" * 80)
    print("PAPER TRADING PERFORMANCE REPORT")
    print("=" * 80)
    print(f"Last Update: {state.get('last_update', 'N/A')}")
    
    # Overall stats
    trades = state.get('trades', [])
    closed = [t for t in trades if t['status'] == 'CLOSED']
    open_trades = [t for t in trades if t['status'] == 'OPEN']
    
    if closed:
        pnls = [t.get('pnl_pct', 0) for t in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        total_pnl = sum(pnls)
        win_rate = len(wins) / len(closed) * 100 if closed else 0
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0
        
        print(f"\nOverall:")
        print(f"  Total Trades: {len(closed)}")
        print(f"  Win Rate: {win_rate:.1f}%")
        print(f"  Total P&L: {total_pnl:.2f}%")
        print(f"  Avg Win: {avg_win:.3f}%")
        print(f"  Avg Loss: {avg_loss:.3f}%")
        print(f"  Profit Factor: {pf:.2f}")
    
    # Pair performance
    pp = state.get('pair_performance', {})
    if pp:
        print(f"\nPair Performance:")
        print(f"{'Pair':<10} {'Trades':<8} {'Win%':<8} {'Total P&L':<12} {'Exp Backtest'}")
        print("-" * 60)
        
        for pair in sorted(pp.keys()):
            data = pp[pair]
            wr = data['wins'] / data['trades'] * 100 if data['trades'] > 0 else 0
            backtest_exp = BACKTEST_EXPECTATIONS.get(pair, {}).get('exp_pct', 0)
            print(f"{pair:<10} {data['trades']:<8} {wr:<7.1f}% {data['total_pnl']:>8.2f}%    {backtest_exp:.2f}%")
    
    # Regime performance
    rp = state.get('regime_performance', {})
    if rp:
        print(f"\nRegime Performance:")
        print(f"{'Regime':<25} {'Trades':<8} {'Win%':<8} {'Total P&L'}")
        print("-" * 50)
        
        for regime in sorted(rp.keys()):
            data = rp[regime]
            wr = data['wins'] / data['trades'] * 100 if data['trades'] > 0 else 0
            print(f"{regime:<25} {data['trades']:<8} {wr:<7.1f}% {data['total_pnl']:>8.2f}%")
    
    # Friction analysis
    print(f"\nFriction Analysis:")
    print(f"  Backtest friction: {BACKTEST_FRICTION*100:.2f}%")
    print(f"  Live estimate:     {LIVE_FRICTION_ESTIMATE*100:.2f}%")
    print(f"  Friction delta:    {(LIVE_FRICTION_ESTIMATE - BACKTEST_FRICTION)*100:.2f}%")
    
    if closed and len(closed) >= 10:
        # Compare actual vs expected per trade
        actual_avg = np.mean([t.get('pnl_pct', 0) for t in closed])
        expected_avg = np.mean([BACKTEST_EXPECTATIONS.get(t['pair'], {}).get('exp_pct', 0) for t in closed])
        
        print(f"  Expected avg P&L:  {expected_avg:.3f}% (backtest)")
        print(f"  Actual avg P&L:    {actual_avg:.3f}% (paper)")
        print(f"  Performance gap:   {actual_avg - expected_avg:.3f}%")
        
        if actual_avg < expected_avg * 0.5:
            print(f"  ⚠️  WARNING: Actual performance significantly below backtest")


if __name__ == '__main__':
    state = update_performance()
    print_performance_report(state)
