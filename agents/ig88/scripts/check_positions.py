#!/usr/bin/env python3
"""Fast position check — check stops/targets on open paper positions, no signal detection."""

import json
import re
from pathlib import Path
from datetime import datetime, timezone

import requests

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
TRADES_PATH = DATA_DIR / 'paper_trades.jsonl'

# Load trades
trades = []
with open(TRADES_PATH) as f:
    for line in f:
        if line.strip():
            trades.append(json.loads(line))

# Open trades have outcome=None
open_trades = [(i, t) for i, t in enumerate(trades) if t.get('outcome') is None]

if not open_trades:
    print("[POSITION CHECK] No open positions.")
    exit(0)

print(f"[POSITION CHECK] {len(open_trades)} open positions found.")
print(f"[POSITION CHECK] Timestamp: {datetime.now(timezone.utc).isoformat()}")
print("=" * 70)

# Get unique pairs
pairs_needed = set()
for _, t in open_trades:
    pair = t['pair'].replace('-PERP', '').replace('/', '')
    if not pair.endswith('USDT'):
        pair = pair + 'USDT'
    pairs_needed.add(pair)

# Fetch current prices from Binance
prices = {}
for pair in sorted(pairs_needed):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval=4h&limit=2"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Use the most recent completed candle's close
        current_price = float(data[-1][4])
        prices[pair] = current_price
        print(f"  Price {pair}: ${current_price:.4f}")
    except Exception as e:
        print(f"  ERROR fetching {pair}: {e}")

print()

# Check each open position
closed_count = 0
now = datetime.now(timezone.utc)

for idx, t in open_trades:
    pair_key = t['pair'].replace('-PERP', '').replace('/', '')
    if not pair_key.endswith('USDT'):
        pair_key = pair_key + 'USDT'
    
    current_price = prices.get(pair_key)
    if current_price is None:
        print(f"  SKIP {t['pair']}: no price data")
        continue
    
    entry = t['entry_price']
    side = t['side']
    leverage = t.get('leverage', 1.0)
    position_size = t.get('position_size_usd', 500)
    
    # Parse stop/target from notes or fields
    notes = t.get('notes', '')
    stop_pct = None
    target_pct = None
    
    # Check direct fields first
    if t.get('stop_price') and t.get('target_price'):
        stop_price = t['stop_price']
        target_price = t['target_price']
    else:
        # Parse from notes
        if 'Stop=' in notes:
            stop_match = re.search(r'Stop=([\d.]+)%', notes)
            target_match = re.search(r'Target=([\d.]+)%', notes)
            if stop_match:
                stop_pct = float(stop_match.group(1))
            if target_match:
                target_pct = float(target_match.group(1))
        
        if stop_pct is None:
            stop_pct = 2.0
        if target_pct is None:
            target_pct = 3.0
        
        if side == 'short':
            stop_price = entry * (1 + stop_pct / 100)
            target_price = entry * (1 - target_pct / 100)
        else:  # long
            stop_price = entry * (1 - stop_pct / 100)
            target_price = entry * (1 + target_pct / 100)
    
    # Check if hit
    if side == 'short':
        raw_pct = ((current_price - entry) / entry) * 100
        hit_stop = current_price >= stop_price
        hit_target = current_price <= target_price
    else:
        raw_pct = ((current_price - entry) / entry) * 100
        hit_stop = current_price <= stop_price
        hit_target = current_price >= target_price
    
    leveraged_pct = raw_pct * (-1 if side == 'short' else 1) * leverage
    unrealized_pnl = position_size * (raw_pct / 100) * (-1 if side == 'short' else 1) * leverage
    
    if hit_stop or hit_target:
        exit_reason = 'target' if hit_target else 'stop'
        pnl_pct = raw_pct * (-1 if side == 'short' else 1) * leverage
        pnl_usd = position_size * (pnl_pct / 100)
        outcome = 'win' if pnl_pct > 0 else 'loss'
        
        entry_ts = t.get('entry_timestamp', '')
        try:
            entry_dt = datetime.fromisoformat(entry_ts)
            hold_hours = (now - entry_dt).total_seconds() / 3600
        except:
            hold_hours = 0
        
        trades[idx]['exit_timestamp'] = now.isoformat()
        trades[idx]['exit_price'] = current_price
        trades[idx]['outcome'] = outcome
        trades[idx]['exit_reason'] = exit_reason
        trades[idx]['pnl_usd'] = round(pnl_usd, 2)
        trades[idx]['pnl_pct'] = round(pnl_pct, 2)
        trades[idx]['hold_duration_hours'] = round(hold_hours, 1)
        
        closed_count += 1
        action = "STOP HIT" if hit_stop else "TARGET HIT"
        print(f"  *** {action} *** {t['pair']} {side.upper()}")
        print(f"      Entry: ${entry:.4f} -> Exit: ${current_price:.4f}")
        print(f"      P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f}) | Hold: {hold_hours:.1f}h")
    else:
        dist_to_stop = abs(stop_price - current_price)
        dist_to_target = abs(target_price - current_price)
        print(f"  [OPEN] {t['pair']} {side.upper()} @ ${entry:.4f}, now=${current_price:.4f}")
        print(f"      Unrealized: {leveraged_pct:+.2f}% (${unrealized_pnl:+.2f})")
        print(f"      Stop: ${stop_price:.4f} (dist: ${dist_to_stop:.4f}) | Target: ${target_price:.4f} (dist: ${dist_to_target:.4f})")

# Write updated trades back
if closed_count > 0:
    with open(TRADES_PATH, 'w') as f:
        for t in trades:
            f.write(json.dumps(t, default=str) + '\n')
    print(f"\n[CLOSED] {closed_count} position(s) closed and saved.")
else:
    print(f"\n[STATUS] All positions remain open. No stops/targets hit.")

# Summary
still_open = sum(1 for t in trades if t.get('outcome') is None)
total_closed = sum(1 for t in trades if t.get('outcome') is not None)
wins = sum(1 for t in trades if t.get('outcome') in ('win', 'target'))
realized_pnl = sum(t.get('pnl_usd', 0) for t in trades if t.get('outcome') is not None)
print(f"\n[SUMMARY] Open: {still_open} | Closed: {total_closed} | Win rate: {wins}/{total_closed} | Realized P&L: ${realized_pnl:+.2f}")
