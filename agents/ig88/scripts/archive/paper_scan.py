#!/usr/bin/env python3
"""
IG-88 Paper Trading Scanner (One-Shot)
=======================================
Single scan cycle for cron/timer integration.
Returns status summary for reporting.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import sys

# Paths
BASE_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88')
DATA_DIR = BASE_DIR / 'data'
STATE_DIR = BASE_DIR / 'state' / 'paper_trading'
PORTFOLIO_STATE = STATE_DIR / 'portfolio.json'
TRADE_LOG = STATE_DIR / 'trades.jsonl'

# Ensure directories exist
STATE_DIR.mkdir(parents=True, exist_ok=True)

FRICTION = 0.01  # 1%

PORTFOLIO = {
    # STRONG (2-2.5% size) - Optimized R:R 2026-04-13
    'ARB':   {'rsi': 18, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 25, 'size': 2.5, 'tier': 'STRONG'},
    'SUI':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 25, 'size': 2.5, 'tier': 'STRONG'},
    'AVAX':  {'rsi': 20, 'bb': 0.15, 'vol': 1.2, 'stop': 1.25, 'target': 2.00, 'bars': 25, 'size': 2.5, 'tier': 'STRONG'},
    'MATIC': {'rsi': 25, 'bb': 0.15, 'vol': 1.8, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 2.5, 'tier': 'STRONG'},
    'UNI':   {'rsi': 22, 'bb': 0.10, 'vol': 1.8, 'stop': 0.75, 'target': 2.00, 'bars': 20, 'size': 2.0, 'tier': 'STRONG'},
    # MEDIUM (1.5% size) - Optimized R:R 2026-04-13
    # DOT dropped (no edge), FIL dropped (no edge), SNX dropped (no edge)
    'ALGO':  {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 1.50, 'target': 2.00, 'bars': 20, 'size': 1.5, 'tier': 'MEDIUM'},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 0.75, 'target': 1.50, 'bars': 15, 'size': 1.5, 'tier': 'MEDIUM'},
    # WEAK (1% size) - Optimized R:R 2026-04-13
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.50, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.50, 'target': 1.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'LINK':  {'rsi': 18, 'bb': 0.05, 'vol': 1.8, 'stop': 1.00, 'target': 4.00, 'bars': 25, 'size': 1.0, 'tier': 'WEAK'},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.50, 'target': 2.50, 'bars': 20, 'size': 1.0, 'tier': 'WEAK'},
    'AAVE':  {'rsi': 22, 'bb': 0.15, 'vol': 1.5, 'stop': 1.25, 'target': 4.00, 'bars': 15, 'size': 1.0, 'tier': 'WEAK'},
}


def load_state():
    if PORTFOLIO_STATE.exists():
        with open(PORTFOLIO_STATE) as f:
            return json.load(f)
    return {'positions': {}, 'completed_trades': [], 'scan_count': 0}


def save_state(state):
    state['last_update'] = datetime.now(timezone.utc).isoformat()
    with open(PORTFOLIO_STATE, 'w') as f:
        json.dump(state, f, indent=2)


def log_trade(trade):
    with open(TRADE_LOG, 'a') as f:
        f.write(json.dumps(trade) + '\n')


def load_data(pair):
    for suffix in ['binance_{pair}_USDT_240m.parquet', 'binance_{pair}USDT_240m.parquet']:
        path = DATA_DIR / suffix.format(pair=pair)
        if path.exists():
            return pd.read_parquet(path)
    return None


def get_freshness():
    """Return dict mapping pair to age in hours of most recent bar."""
    freshness = {}
    for pair in PORTFOLIO.keys():
        df = load_data(pair)
        if df is None:
            freshness[pair] = None
            continue
        # Get last timestamp
        if df.index.name == 'open_time':
            last_ts = df.index[-1]
        elif 'open_time' in df.columns:
            last_ts = df['open_time'].iloc[-1]
        else:
            last_ts = df.index[-1]
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_hours = (now - last_ts).total_seconds() / 3600
        freshness[pair] = age_hours
    return freshness


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_upper = sma20 + std20 * 2
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio


def run_scan():
    """Execute one scan cycle."""
    state = load_state()
    positions = state.get('positions', {})
    trades = state.get('completed_trades', [])
    scan_count = state.get('scan_count', 0) + 1
    
    events = []
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    # Data freshness check
    freshness = get_freshness()
    stale_pairs = []
    for pair, age in freshness.items():
        if age is None:
            events.append(f"⚠️  DATA MISSING: {pair} parquet file not found")
        elif age > 4:
            stale_pairs.append(pair)
            events.append(f"⚠️  DATA STALE: {pair} last bar {age:.1f}h ago")
    if stale_pairs:
        events.append(f"⚠️  {len(stale_pairs)} pairs have stale data (>4h)")
    
    # Check exits for existing positions
    for pair, pos in list(positions.items()):
        df = load_data(pair)
        if df is None:
            continue
        
        c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
        
        stop_price = pos['entry_price'] - pos['atr'] * pos['stop_mult']
        target_price = pos['entry_price'] + pos['atr'] * pos['target_mult']
        
        current_close = c[-2]
        current_high = h[-2]
        current_low = l[-2]
        
        # Update bars held
        pos['bars_held'] = pos.get('bars_held', 0) + 1
        
        exit_reason = None
        exit_price = None
        
        if current_low <= stop_price:
            exit_reason = 'STOP'
            exit_price = stop_price
        elif current_high >= target_price:
            exit_reason = 'TARGET'
            exit_price = target_price
        elif pos['bars_held'] >= pos['max_bars']:
            exit_reason = 'TIME'
            exit_price = current_close
        
        if exit_reason:
            # Calculate P&L
            gross_return = (exit_price - pos['entry_price']) / pos['entry_price']
            net_return = gross_return - FRICTION
            pnl_pct = net_return * 100
            pnl_weighted = net_return * pos['size_pct']
            
            trade = {
                'pair': pair,
                'entry_price': pos['entry_price'],
                'exit_price': exit_price,
                'exit_reason': exit_reason,
                'pnl_pct': round(pnl_pct, 3),
                'pnl_weighted': round(pnl_weighted, 3),
                'size_pct': pos['size_pct'],
                'tier': pos['tier'],
                'bars_held': pos['bars_held'],
                'time': timestamp
            }
            
            trades.append(trade)
            log_trade({'action': 'CLOSE', **trade})
            del positions[pair]
            
            pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
            events.append(f"{pnl_emoji} CLOSE {pair}: {exit_reason} @ {exit_price:.4f} | PnL: {pnl_pct:+.2f}%")
    
    # Check for new entries (if room)
    max_positions = 7
    open_pairs = set(positions.keys())
    
    for pair, cfg in PORTFOLIO.items():
        if pair in open_pairs:
            continue
        if len(positions) >= max_positions:
            break
        
        df = load_data(pair)
        if df is None:
            continue
        
        c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
        
        i = -2  # Last completed bar
        
        if rsi[i] < cfg['rsi'] and bb_pct[i] < cfg['bb'] and vol_ratio[i] > cfg['vol']:
            position = {
                'pair': pair,
                'entry_price': float(c[i]),
                'atr': float(atr[i]),
                'stop_mult': cfg['stop'],
                'target_mult': cfg['target'],
                'max_bars': cfg['bars'],
                'size_pct': cfg['size'],
                'tier': cfg['tier'],
                'bars_held': 0,
                'entry_time': timestamp
            }
            positions[pair] = position
            log_trade({'action': 'OPEN', **position, 'rsi': float(rsi[i]), 'bb_pct': float(bb_pct[i])})
            
            events.append(f"🟢 OPEN {pair}: @ {c[i]:.4f} | RSI={rsi[i]:.0f} BB={bb_pct[i]:.2f} | {cfg['tier']} {cfg['size']}%")
    
    # Calculate stats
    pnls = [t['pnl_weighted'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_pnl = sum(pnls) if pnls else 0
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    
    # Freshness summary
    max_age = max([a for a in freshness.values() if a is not None], default=0)
    stale_count = sum(1 for a in freshness.values() if a is not None and a > 4)
    
    stats = {
        'scan_count': scan_count,
        'timestamp': timestamp,
        'positions': len(positions),
        'total_trades': len(trades),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': round(len(wins) / len(trades) * 100, 1) if trades else 0,
        'total_pnl': round(total_pnl, 3),
        'profit_factor': round(gross_profit / gross_loss, 2) if gross_loss > 0 else (9.99 if gross_profit > 0 else 0),
        'max_age_hours': round(max_age, 2),
        'stale_pairs_count': stale_count,
    }
    
    # Save state
    state['positions'] = positions
    state['completed_trades'] = trades[-100:]  # Keep last 100
    state['scan_count'] = scan_count
    state['stats'] = stats
    save_state(state)
    
    return stats, events


def print_status():
    """Print current status."""
    state = load_state()
    stats = state.get('stats', {})
    positions = state.get('positions', {})
    
    print("\n" + "=" * 60)
    print("IG-88 PAPER TRADER STATUS")
    print("=" * 60)
    
    print(f"\n📊 Performance Summary:")
    print(f"   Scans: {stats.get('scan_count', 0)}")
    print(f"   Trades: {stats.get('total_trades', 0)} ({stats.get('winning_trades', 0)}W / {stats.get('losing_trades', 0)}L)")
    print(f"   Win Rate: {stats.get('win_rate', 0):.1f}%")
    print(f"   Total PnL: {stats.get('total_pnl', 0):+.3f}%")
    print(f"   Profit Factor: {stats.get('profit_factor', 0):.2f}")
    
    print(f"\n📈 Open Positions ({len(positions)}):")
    if positions:
        for pair, pos in positions.items():
            entry = pos['entry_price']
            stop = entry - pos['atr'] * pos['stop_mult']
            target = entry + pos['atr'] * pos['target_mult']
            print(f"   {pair:<8} Entry: {entry:.4f} | Stop: {stop:.4f} | Target: {target:.4f} | {pos['tier']} {pos['size_pct']}%")
    else:
        print("   No open positions")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'status':
        print_status()
    else:
        stats, events = run_scan()
        
        for event in events:
            print(event)
        
        if not events:
            print("No signals this cycle.")
        
        print(f"\nPositions: {stats.get('positions', 0)}/7 | Trades: {stats.get('total_trades', 0)} | PnL: {stats.get('total_pnl', 0):+.3f}% | PF: {stats.get('profit_factor', 0):.2f}")
