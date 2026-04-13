#!/usr/bin/env python3
"""MR Scanner v3: Full cycle with proper position closing and dedup.
1. Load trades, close any that hit stops/targets
2. Scan for fresh signals (last 2 bars, skip open pairs)
3. Update paper_trades.jsonl with all changes
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trading.config import load_config
from src.trading.paper_trader import PaperTrader

# Configuration
PAIRS = ['SOLUSDT', 'AVAXUSDT', 'ETHUSDT', 'NEARUSDT', 'LINKUSDT', 'BTCUSDT']
DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
PAPER_TRADES_PATH = DATA_DIR / 'paper_trades.jsonl'
SIGNAL_LOG_PATH = DATA_DIR / 'mr_signals.jsonl'

RSI_THRESHOLD = 35
BB_MULTIPLIER = 1.0
VOLUME_MULTIPLIER = 1.2
POSITION_SIZE_USD = 500.0
LEVERAGE = 2.0

REGIME_STOPS = {
    'low_vol': {'atr_pct': 2.0, 'stop': 0.015, 'target': 0.03},
    'mid_vol': {'atr_pct': 4.0, 'stop': 0.01, 'target': 0.075},
    'high_vol': {'atr_pct': 999, 'stop': 0.005, 'target': 0.075},
}

SYMBOL_MAP = {
    'SOLUSDT': 'SOL-PERP',
    'AVAXUSDT': 'AVAX-PERP',
    'ETHUSDT': 'ETH-PERP',
    'NEARUSDT': 'NEAR-PERP',
    'LINKUSDT': 'LINK-PERP',
    'BTCUSDT': 'BTC-PERP',
}

# Skip NEAR - consistently stops out
DISABLED_PAIRS = {'NEARUSDT'}

def get_regime_params(atr_pct: float) -> dict:
    if atr_pct < 2.0:
        return REGIME_STOPS['low_vol']
    elif atr_pct < 4.0:
        return REGIME_STOPS['mid_vol']
    else:
        return REGIME_STOPS['high_vol']

def load_trades() -> list:
    if not PAPER_TRADES_PATH.exists():
        return []
    records = []
    with open(PAPER_TRADES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records

def save_trades(trades: list):
    with open(PAPER_TRADES_PATH, 'w') as f:
        for t in trades:
            f.write(json.dumps(t) + '\n')

def get_open_by_pair(trades: list) -> dict:
    """Get unique open position per pair (keep latest)."""
    open_by_pair = {}
    for idx, t in enumerate(trades):
        if t.get('outcome') == 'open':
            pair = t.get('pair', '')
            if pair not in open_by_pair or t.get('entry_timestamp', '') > open_by_pair[pair][1].get('entry_timestamp', ''):
                open_by_pair[pair] = (idx, t)
    return open_by_pair

def parse_stop_target(notes: str) -> tuple:
    """Parse stop and target percentages from notes string."""
    stop_pct = 0.015
    target_pct = 0.03
    if 'Stop=' in notes:
        try:
            stop_pct = float(notes.split('Stop=')[1].split('%')[0]) / 100.0
        except: pass
    if 'Target=' in notes:
        try:
            target_pct = float(notes.split('Target=')[1].split('%')[0]) / 100.0
        except: pass
    return stop_pct, target_pct

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss))
    
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_lower'] = df['sma20'] - BB_MULTIPLIER * df['std20']
    df['bb_upper'] = df['sma20'] + BB_MULTIPLIER * df['std20']
    
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['atr_pct'] = (df['atr'] / df['close']) * 100
    
    return df

def detect_recent_signal(df: pd.DataFrame, pair: str, max_bars_back: int = 2) -> dict | None:
    df = compute_indicators(df)
    start_idx = max(20, len(df) - max_bars_back - 1)
    
    for i in range(start_idx, len(df) - 1):
        row = df.iloc[i]
        
        if row['volume'] < row['vol_sma20'] * VOLUME_MULTIPLIER:
            continue
        
        atr_pct = float(row['atr_pct']) if not pd.isna(row['atr_pct']) else 3.0
        
        # Long signal
        if (row['rsi'] < RSI_THRESHOLD and 
            row['close'] < row['bb_lower'] and
            row['close'] > row['open']):
            
            current_price = float(df.iloc[-1]['close'])
            return {
                'timestamp': df.index[i].isoformat(),
                'pair': pair,
                'side': 'long',
                'entry_price': current_price,
                'rsi': float(row['rsi']),
                'volume_ratio': float(row['volume'] / row['vol_sma20']),
                'atr_pct': atr_pct,
            }
        
        # Short signal
        elif (row['rsi'] > (100 - RSI_THRESHOLD) and
              row['close'] > row['bb_upper'] and
              row['close'] < row['open']):
            
            current_price = float(df.iloc[-1]['close'])
            return {
                'timestamp': df.index[i].isoformat(),
                'pair': pair,
                'side': 'short',
                'entry_price': current_price,
                'rsi': float(row['rsi']),
                'volume_ratio': float(row['volume'] / row['vol_sma20']),
                'atr_pct': atr_pct,
            }
    
    return None

def run_cycle():
    now = datetime.now(timezone.utc)
    print('=' * 60)
    print('=== MR SCANNER v3 FULL CYCLE ===')
    print(f'Time: {now.strftime("%Y-%m-%d %H:%M:%S UTC")}')
    print('=' * 60)
    
    trades = load_trades()
    print(f'\nLoaded {len(trades)} total trade records')
    
    # Fetch live prices
    import urllib.request
    ids_map = {
        'SOLUSDT': 'solana', 'AVAXUSDT': 'avalanche-2', 'ETHUSDT': 'ethereum',
        'NEARUSDT': 'near', 'LINKUSDT': 'chainlink', 'BTCUSDT': 'bitcoin'
    }
    current_prices = {}
    try:
        url = f'https://api.coingecko.com/api/v3/simple/price?ids={",".join(ids_map.values())}&vs_currencies=usd'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        cg_data = json.loads(resp.read())
        reverse_map = {v: k for k, v in ids_map.items()}
        for cg_id, info in cg_data.items():
            sym = reverse_map.get(cg_id)
            if sym:
                current_prices[sym] = info['usd']
        print(f'Live prices: {", ".join(f"{s}=${p:,.2f}" for s, p in current_prices.items())}')
    except Exception as e:
        print(f'Price fetch failed: {e}')
    
    # =========================================================================
    # STEP 1: Close positions that hit stops/targets
    # =========================================================================
    print('\n--- STEP 1: CLOSE EXITS ---')
    
    open_map = get_open_by_pair(trades)
    closed_this_cycle = []
    still_open = set()
    
    for pair, (idx, trade) in open_map.items():
        entry_price = trade['entry_price']
        side = trade['side']
        notes = trade.get('notes', '')
        stop_pct, target_pct = parse_stop_target(notes)
        
        binance_sym = pair.replace('-PERP', 'USDT')
        current_price = current_prices.get(binance_sym)
        if current_price is None:
            still_open.add(pair)
            continue
        
        if side == 'long':
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            gross_pct = (current_price - entry_price) / entry_price * LEVERAGE
            hit_stop = current_price <= stop_price
            hit_target = current_price >= target_price
        else:
            stop_price = entry_price * (1 + stop_pct)
            target_price = entry_price * (1 - target_pct)
            gross_pct = (entry_price - current_price) / entry_price * LEVERAGE
            hit_stop = current_price >= stop_price
            hit_target = current_price <= target_price
        
        if hit_stop or hit_target:
            exit_reason = 'stop' if hit_stop else 'target'
            fees = 0.0014 * 2  # 0.14% per side for perps
            net_pct = gross_pct - fees
            net_usd = net_pct / 100 * POSITION_SIZE_USD
            
            # Update trade record
            trades[idx]['outcome'] = exit_reason
            trades[idx]['exit_price'] = current_price
            trades[idx]['exit_timestamp'] = now.isoformat()
            trades[idx]['exit_reason'] = exit_reason
            trades[idx]['pnl_pct'] = round(gross_pct, 4)
            trades[idx]['net_pnl_pct'] = round(net_pct, 4)
            trades[idx]['pnl_usd'] = round(net_usd, 4)
            
            closed_this_cycle.append({
                'pair': pair,
                'side': side,
                'entry': entry_price,
                'exit': current_price,
                'reason': exit_reason,
                'pnl_usd': net_usd,
                'pnl_pct': net_pct,
            })
            
            print(f'  [{exit_reason.upper()}] {pair}: {side.upper()} @ {entry_price:.4f} -> {current_price:.4f}, P&L=${net_usd:+.2f} ({net_pct:+.2f}%)')
        else:
            still_open.add(pair)
            unrealized = gross_pct
            print(f'  [OPEN] {pair}: {side.upper()} @ {entry_price:.4f}, now={current_price:.4f}, unrealized={unrealized:+.2f}%')
    
    # Also mark duplicates as closed (same exit, just dedup cleanup)
    for pair in list(still_open):
        binance_sym = pair.replace('-PERP', 'USDT')
        current_price = current_prices.get(binance_sym)
        if current_price is None:
            continue
        
        # Find all duplicates (same pair, still open)
        dupes = [(i, t) for i, t in enumerate(trades) 
                 if t.get('pair') == pair and t.get('outcome') == 'open' and t is not open_map.get(pair, (None, {}))[1]]
        
        for idx, dupe in dupes:
            entry_price = dupe['entry_price']
            side = dupe['side']
            notes = dupe.get('notes', '')
            stop_pct, target_pct = parse_stop_target(notes)
            
            if side == 'long':
                gross_pct = (current_price - entry_price) / entry_price * LEVERAGE
            else:
                gross_pct = (entry_price - current_price) / entry_price * LEVERAGE
            
            fees = 0.0014 * 2
            net_pct = gross_pct - fees
            net_usd = net_pct / 100 * POSITION_SIZE_USD
            
            trades[idx]['outcome'] = 'duplicate_closed'
            trades[idx]['exit_price'] = current_price
            trades[idx]['exit_timestamp'] = now.isoformat()
            trades[idx]['exit_reason'] = 'dedup_cleanup'
            trades[idx]['pnl_pct'] = round(gross_pct, 4)
            trades[idx]['net_pnl_pct'] = round(net_pct, 4)
            trades[idx]['pnl_usd'] = round(net_usd, 4)
    
    # Save updated trades
    save_trades(trades)
    print(f'\n  Closed this cycle: {len(closed_this_cycle)}')
    
    # =========================================================================
    # STEP 2: Scan for new signals (skip open pairs and disabled)
    # =========================================================================
    print('\n--- STEP 2: SCAN NEW SIGNALS ---')
    print(f'  Skipping open: {still_open or "none"}')
    print(f'  Disabled: {DISABLED_PAIRS}')
    
    new_trades_opened = []
    
    for pair in PAIRS:
        perp_pair = SYMBOL_MAP[pair]
        
        if perp_pair in still_open:
            print(f'  {pair}: SKIP (open)')
            continue
        if pair in DISABLED_PAIRS:
            print(f'  {pair}: SKIP (disabled)')
            continue
        
        path = DATA_DIR / f'binance_{pair}_240m.parquet'
        if not path.exists():
            continue
        
        try:
            df = pd.read_parquet(path)
            sig = detect_recent_signal(df, pair, max_bars_back=2)
            
            if sig:
                atr_pct = sig['atr_pct']
                regime_params = get_regime_params(atr_pct)
                entry = sig['entry_price']
                
                print(f'  {pair}: NEW SIGNAL {sig["side"].upper()}')
                print(f'    RSI={sig["rsi"]:.1f}, Vol={sig["volume_ratio"]:.1f}x, ATR={atr_pct:.1f}%')
                print(f'    Entry=${entry:.4f}, Stop={regime_params["stop"]*100:.1f}%, Target={regime_params["target"]*100:.1f}%')
                
                # Create new trade record directly
                trade_id = f'paper_{now.strftime("%Y%m%d%H%M%S")}_{pair[:4].lower()}'
                
                if sig['side'] == 'long':
                    stop = entry * (1 - regime_params['stop'])
                    target = entry * (1 + regime_params['target'])
                else:
                    stop = entry * (1 + regime_params['stop'])
                    target = entry * (1 - regime_params['target'])
                
                new_trade = {
                    'trade_id': trade_id,
                    'venue': 'jupiter_perps',
                    'strategy': 'mean_reversion',
                    'pair': perp_pair,
                    'side': sig['side'],
                    'leverage': LEVERAGE,
                    'entry_timestamp': now.isoformat(),
                    'entry_price': entry,
                    'exit_timestamp': None,
                    'exit_price': None,
                    'position_size_usd': POSITION_SIZE_USD,
                    'regime_state': 'RISK_ON',
                    'outcome': 'open',
                    'exit_reason': None,
                    'r_multiple': None,
                    'pnl_usd': None,
                    'pnl_pct': None,
                    'hold_duration_hours': None,
                    'fees_paid': 0.0,
                    'borrow_fees': 0.0,
                    'llm_estimate': None,
                    'market_price': None,
                    'brier_score': None,
                    'narrative_category': None,
                    'notes': f"MR: RSI={sig['rsi']:.1f}, Vol={sig['volume_ratio']:.1f}x, "
                             f"ATR={atr_pct:.1f}%, Stop={regime_params['stop']*100:.1f}%, "
                             f"Target={regime_params['target']*100:.1f}%",
                    'logged_at': now.isoformat(),
                    'stop_price': stop,
                    'target_price': target,
                }
                
                # Append to trades file
                with open(PAPER_TRADES_PATH, 'a') as f:
                    f.write(json.dumps(new_trade) + '\n')
                
                # Log signal
                with open(SIGNAL_LOG_PATH, 'a') as f:
                    f.write(json.dumps({**sig, 'scan_time': now.isoformat()}) + '\n')
                
                new_trades_opened.append(new_trade)
                print(f'    -> Opened: {trade_id}')
            else:
                print(f'  {pair}: No signal')
                
        except Exception as e:
            print(f'  {pair}: Error - {e}')
    
    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    all_trades = load_trades()
    open_trades = [t for t in all_trades if t.get('outcome') == 'open']
    closed_trades = [t for t in all_trades if t.get('outcome') in ('target', 'stop', 'duplicate_closed')]
    wins = sum(1 for t in closed_trades if (t.get('pnl_usd', 0) or 0) > 0)
    losses = sum(1 for t in closed_trades if (t.get('pnl_usd', 0) or 0) <= 0)
    total_pnl = sum(t.get('pnl_usd', 0) or 0 for t in closed_trades)
    
    # Per-pair breakdown
    pair_stats = {}
    for t in closed_trades:
        p = t.get('pair', 'unknown')
        if p not in pair_stats:
            pair_stats[p] = {'n': 0, 'wins': 0, 'pnl': 0.0}
        pair_stats[p]['n'] += 1
        if (t.get('pnl_usd', 0) or 0) > 0:
            pair_stats[p]['wins'] += 1
        pair_stats[p]['pnl'] += t.get('pnl_usd', 0) or 0
    
    print('\n' + '=' * 60)
    print('=== CYCLE COMPLETE ===')
    print(f'\nOpen positions ({len(open_trades)}):')
    for t in open_trades:
        entry = t['entry_price']
        side = t['side']
        notes = t.get('notes', '')
        stop_pct, target_pct = parse_stop_target(notes)
        pair = t['pair']
        binance_sym = pair.replace('-PERP', 'USDT')
        current = current_prices.get(binance_sym, 0)
        
        if side == 'long':
            unrealized = (current - entry) / entry * 100 * LEVERAGE if current else 0
        else:
            unrealized = (entry - current) / entry * 100 * LEVERAGE if current else 0
        
        print(f'  {t["trade_id"]}: {pair} {side.upper()} @ {entry:.4f} -> {current:.4f} ({unrealized:+.1f}%)')
    
    print(f'\nClosed trades: {len(closed_trades)} (W:{wins} L:{losses}, {wins/max(len(closed_trades),1)*100:.0f}% WR)')
    print(f'Total P&L: ${total_pnl:+.2f}')
    print(f'\nPer-pair breakdown:')
    for pair, stats in sorted(pair_stats.items()):
        print(f'  {pair}: {stats["n"]} trades, {stats["wins"]}W, ${stats["pnl"]:+.2f}')
    
    print(f'\nNew signals this cycle: {len(new_trades_opened)}')
    print('=' * 60)
    
    return {
        'timestamp': now.isoformat(),
        'open_positions': len(open_trades),
        'closed_this_cycle': len(closed_this_cycle),
        'total_closed': len(closed_trades),
        'wins': wins,
        'losses': losses,
        'total_pnl': total_pnl,
        'new_signals': len(new_trades_opened),
        'new_trades': [t['trade_id'] for t in new_trades_opened],
    }

if __name__ == '__main__':
    result = run_cycle()
    # Write result for downstream consumption
    with open(DATA_DIR / 'last_scan_result.json', 'w') as f:
        json.dump(result, f, indent=2)
