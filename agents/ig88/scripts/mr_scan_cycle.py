#!/usr/bin/env python3
"""Complete MR Scanner Cycle: Check positions -> Close exits -> Scan new -> Execute.
Dedup fix: skip pairs with existing open positions.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trading.config import load_config
from src.trading.paper_trader import PaperTrader

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PAIRS = ['SOLUSDT', 'AVAXUSDT', 'ETHUSDT', 'NEARUSDT', 'LINKUSDT', 'BTCUSDT']
DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
PAPER_TRADES_PATH = DATA_DIR / 'paper_trades.jsonl'
SIGNAL_LOG_PATH = DATA_DIR / 'mr_signals.jsonl'

# Strategy parameters
RSI_THRESHOLD = 35
BB_MULTIPLIER = 1.0
VOLUME_MULTIPLIER = 1.2
POSITION_SIZE_USD = 500.0
LEVERAGE = 2.0

# Adaptive stop/target based on volatility regime (validated IG88037)
REGIME_STOPS = {
    'low_vol': {'atr_pct': 2.0, 'stop': 0.015, 'target': 0.03},
    'mid_vol': {'atr_pct': 4.0, 'stop': 0.01, 'target': 0.075},
    'high_vol': {'atr_pct': 999, 'stop': 0.005, 'target': 0.075},
}

# Map CoinGecko IDs to Binance symbols
SYMBOL_MAP = {
    'SOLUSDT': 'SOL-PERP',
    'AVAXUSDT': 'AVAX-PERP',
    'ETHUSDT': 'ETH-PERP',
    'NEARUSDT': 'NEAR-PERP',
    'LINKUSDT': 'LINK-PERP',
    'BTCUSDT': 'BTC-PERP',
}

def get_regime_params(atr_pct: float) -> dict:
    if atr_pct < 2.0:
        return REGIME_STOPS['low_vol']
    elif atr_pct < 4.0:
        return REGIME_STOPS['mid_vol']
    else:
        return REGIME_STOPS['high_vol']

# ---------------------------------------------------------------------------
# Load current paper trades
# ---------------------------------------------------------------------------
def load_paper_trades() -> list[dict]:
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

def get_open_positions(trades: list[dict]) -> dict:
    """Return dict of {pair_symbol: latest_open_trade} for dedup."""
    open_by_pair = {}
    for t in trades:
        if t.get('outcome') == 'open':
            pair = t.get('pair', '')
            # Keep latest entry per pair
            if pair not in open_by_pair or t.get('entry_timestamp', '') > open_by_pair[pair].get('entry_timestamp', ''):
                open_by_pair[pair] = t
    return open_by_pair

# ---------------------------------------------------------------------------
# Check open positions against current prices
# ---------------------------------------------------------------------------
def check_open_positions(trades: list[dict], current_prices: dict) -> list[dict]:
    """Check open positions against stops/targets, return list of closed trades."""
    closed = []
    open_by_pair = get_open_positions(trades)
    
    for pair, trade in open_by_pair.items():
        entry_price = trade['entry_price']
        side = trade['side']
        notes = trade.get('notes', '')
        
        # Parse stop/target from notes
        stop_pct = 0.015  # default
        target_pct = 0.03  # default
        if 'Stop=' in notes:
            try:
                stop_str = notes.split('Stop=')[1].split('%')[0]
                stop_pct = float(stop_str) / 100.0
            except:
                pass
        if 'Target=' in notes:
            try:
                target_str = notes.split('Target=')[1].split('%')[0]
                target_pct = float(target_str) / 100.0
            except:
                pass
        
        current_price = current_prices.get(pair.replace('-PERP', 'USDT'))
        if current_price is None:
            print(f'  {pair}: No current price available')
            continue
        
        if side == 'long':
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            
            if current_price <= stop_price:
                print(f'  [STOP HIT] {pair}: LONG @ {entry_price:.4f}, stopped at {current_price:.4f}')
                closed.append({**trade, 'exit_price': current_price, 'exit_reason': 'stop'})
            elif current_price >= target_price:
                print(f'  [TARGET HIT] {pair}: LONG @ {entry_price:.4f}, target at {current_price:.4f}')
                closed.append({**trade, 'exit_price': current_price, 'exit_reason': 'target'})
            else:
                pnl_pct = (current_price - entry_price) / entry_price * 100 * LEVERAGE
                print(f'  [OPEN] {pair}: LONG @ {entry_price:.4f}, current={current_price:.4f}, P&L={pnl_pct:+.2f}%, stop={stop_price:.4f}, target={target_price:.4f}')
        
        elif side == 'short':
            stop_price = entry_price * (1 + stop_pct)
            target_price = entry_price * (1 - target_pct)
            
            if current_price >= stop_price:
                print(f'  [STOP HIT] {pair}: SHORT @ {entry_price:.4f}, stopped at {current_price:.4f}')
                closed.append({**trade, 'exit_price': current_price, 'exit_reason': 'stop'})
            elif current_price <= target_price:
                print(f'  [TARGET HIT] {pair}: SHORT @ {entry_price:.4f}, target at {current_price:.4f}')
                closed.append({**trade, 'exit_price': current_price, 'exit_reason': 'target'})
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100 * LEVERAGE
                print(f'  [OPEN] {pair}: SHORT @ {entry_price:.4f}, current={current_price:.4f}, P&L={pnl_pct:+.2f}%, stop={stop_price:.4f}, target={target_price:.4f}')
    
    return closed

# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss))
    
    # Bollinger Bands
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_lower'] = df['sma20'] - BB_MULTIPLIER * df['std20']
    df['bb_upper'] = df['sma20'] + BB_MULTIPLIER * df['std20']
    
    # Volume
    df['vol_sma20'] = df['volume'].rolling(20).mean()
    
    # ATR
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['atr_pct'] = (df['atr'] / df['close']) * 100
    
    return df

# ---------------------------------------------------------------------------
# Signal Detection
# ---------------------------------------------------------------------------
def detect_signals(df: pd.DataFrame, pair: str) -> list[dict]:
    df = compute_indicators(df)
    signals = []
    
    for i in range(20, len(df) - 1):
        row = df.iloc[i]
        
        # Volume filter
        if row['volume'] < row['vol_sma20'] * VOLUME_MULTIPLIER:
            continue
        
        atr_pct = float(row['atr_pct']) if not pd.isna(row['atr_pct']) else 3.0
        
        # Long: RSI oversold + below BB + reversal candle
        if (row['rsi'] < RSI_THRESHOLD and 
            row['close'] < row['bb_lower'] and
            row['close'] > row['open']):
            
            signals.append({
                'timestamp': df.index[i].isoformat() if hasattr(df.index[i], 'isoformat') else str(df.index[i]),
                'pair': pair,
                'side': 'long',
                'entry_price': float(df.iloc[i + 1]['open']) if i + 1 < len(df) else float(row['close']),
                'rsi': float(row['rsi']),
                'close': float(row['close']),
                'bb_lower': float(row['bb_lower']),
                'volume_ratio': float(row['volume'] / row['vol_sma20']),
                'atr_pct': atr_pct,
            })
        
        # Short: RSI overbought + above BB + reversal candle
        elif (row['rsi'] > (100 - RSI_THRESHOLD) and
              row['close'] > row['bb_upper'] and
              row['close'] < row['open']):
            
            signals.append({
                'timestamp': df.index[i].isoformat() if hasattr(df.index[i], 'isoformat') else str(df.index[i]),
                'pair': pair,
                'side': 'short',
                'entry_price': float(df.iloc[i + 1]['open']) if i + 1 < len(df) else float(row['close']),
                'rsi': float(row['rsi']),
                'close': float(row['close']),
                'bb_upper': float(row['bb_upper']),
                'volume_ratio': float(row['volume'] / row['vol_sma20']),
                'atr_pct': atr_pct,
            })
    
    return signals

# ---------------------------------------------------------------------------
# Main Cycle
# ---------------------------------------------------------------------------
def run_cycle():
    print('=' * 60)
    print('=== MEAN REVERSION SCANNER CYCLE ===')
    print(f'Time: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}')
    print('=' * 60)
    
    # Load existing trades
    trades = load_paper_trades()
    open_before = get_open_positions(trades)
    print(f'\nExisting open positions: {len(open_before)}')
    for pair, t in open_before.items():
        print(f'  {pair}: {t["side"].upper()} @ {t["entry_price"]:.4f}')
    
    # Fetch live prices for position check
    import urllib.request
    ids_map = {
        'SOLUSDT': 'solana',
        'AVAXUSDT': 'avalanche-2',
        'ETHUSDT': 'ethereum',
        'NEARUSDT': 'near',
        'LINKUSDT': 'chainlink',
        'BTCUSDT': 'bitcoin'
    }
    current_prices = {}
    try:
        ids = ','.join(ids_map.values())
        url = f'https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        cg_data = json.loads(resp.read())
        reverse_map = {v: k for k, v in ids_map.items()}
        for cg_id, info in cg_data.items():
            binance_sym = reverse_map.get(cg_id)
            if binance_sym:
                current_prices[binance_sym] = info['usd']
        print(f'\nLive prices fetched: {len(current_prices)} pairs')
    except Exception as e:
        print(f'\nWARNING: Could not fetch live prices: {e}')
        # Fallback to parquet data
        for pair in PAIRS:
            path = DATA_DIR / f'binance_{pair}_240m.parquet'
            if path.exists():
                df = pd.read_parquet(path)
                current_prices[pair] = float(df.iloc[-1]['close'])
        print(f'Using parquet data for {len(current_prices)} pairs')
    
    # Step 1: Check open positions against stops/targets
    print('\n--- STEP 1: CHECK OPEN POSITIONS ---')
    closed_trades = check_open_positions(trades, current_prices)
    
    if closed_trades:
        print(f'\n  Positions that closed: {len(closed_trades)}')
        # Update trades file - mark as closed
        for closed in closed_trades:
            trade_id = closed['trade_id']
            exit_price = closed['exit_price']
            exit_reason = closed['exit_reason']
            
            # Find and update the trade in the records
            updated_trades = []
            for t in trades:
                if t.get('trade_id') == trade_id:
                    t['outcome'] = exit_reason
                    t['exit_price'] = exit_price
                    t['exit_timestamp'] = datetime.now(timezone.utc).isoformat()
                    t['exit_reason'] = exit_reason
                    
                    # Calculate P&L
                    entry = t['entry_price']
                    side = t['side']
                    if side == 'long':
                        pnl_pct = (exit_price - entry) / entry * 100 * LEVERAGE
                    else:
                        pnl_pct = (entry - exit_price) / entry * 100 * LEVERAGE
                    t['pnl_pct'] = pnl_pct
                    t['pnl_usd'] = pnl_pct / 100 * POSITION_SIZE_USD
                    t['hold_duration_hours'] = None  # simplified
                    
                updated_trades.append(t)
            trades = updated_trades
            print(f'    {trade_id}: {exit_reason} @ {exit_price:.4f}')
    else:
        print('  No positions hit stops/targets this cycle.')
    
    # Step 2: Scan for new signals (with dedup)
    print('\n--- STEP 2: SCAN FOR NEW MR SIGNALS ---')
    
    # Get pairs with open positions to skip
    open_pairs_after_check = set()
    for t in trades:
        if t.get('outcome') == 'open':
            open_pairs_after_check.add(t.get('pair', ''))
    
    print(f'  Skipping pairs with open positions: {open_pairs_after_check or "none"}')
    
    all_new_signals = []
    trader = None  # lazy load
    
    for pair in PAIRS:
        perp_pair = SYMBOL_MAP.get(pair, pair)
        
        # DEDUP: Skip if already have open position
        if perp_pair in open_pairs_after_check:
            print(f'  {pair}: SKIPPED (already open)')
            continue
        
        path = DATA_DIR / f'binance_{pair}_240m.parquet'
        if not path.exists():
            print(f'  {pair}: No data file')
            continue
        
        try:
            df = pd.read_parquet(path)
            signals = detect_signals(df, pair)
            
            recent = signals[-1:] if signals else []
            
            if recent:
                sig = recent[0]
                atr_pct = sig.get('atr_pct', 3.0)
                regime_params = get_regime_params(atr_pct)
                
                print(f'  {pair}: SIGNAL DETECTED')
                print(f'    Side: {sig["side"]}')
                print(f'    RSI: {sig["rsi"]:.1f}')
                print(f'    Volume: {sig["volume_ratio"]:.1f}x')
                print(f'    ATR: {atr_pct:.1f}%')
                print(f'    Stop: {regime_params["stop"]*100:.1f}%, Target: {regime_params["target"]*100:.1f}%')
                
                # Log signal
                with open(SIGNAL_LOG_PATH, 'a') as f:
                    f.write(json.dumps(sig) + '\n')
                
                all_new_signals.append(sig)
                
                # Execute as paper trade
                if trader is None:
                    from src.quant.regime import RegimeAssessment, RegimeSignal, RegimeState
                    cfg = load_config()
                    trader = PaperTrader(cfg, portfolio_value=10_000.0, trades_path=PAPER_TRADES_PATH)
                    regime = RegimeAssessment(
                        state=RegimeState.RISK_ON,
                        score=7.0,
                        signals=[RegimeSignal(name="paper_mode", value=1.0, score=7.0, weight=1.0)],
                        timestamp=datetime.now(tz=timezone.utc),
                        confidence=0.8,
                    )
                    trader.set_regime(regime)
                
                entry = sig['entry_price']
                if sig['side'] == 'long':
                    stop = entry * (1 - regime_params['stop'])
                    target = entry * (1 + regime_params['target'])
                else:
                    stop = entry * (1 + regime_params['stop'])
                    target = entry * (1 - regime_params['target'])
                
                trade, msg = trader.open_position(
                    venue='jupiter_perps',
                    pair=perp_pair,
                    side=sig['side'],
                    entry_price=entry,
                    position_size_usd=POSITION_SIZE_USD,
                    strategy='mean_reversion',
                    stop_level=stop,
                    target_level=target,
                    leverage=LEVERAGE,
                    expected_move_pct=regime_params['target'],
                    notes=f"MR: RSI={sig['rsi']:.1f}, Vol={sig['volume_ratio']:.1f}x, "
                          f"ATR={atr_pct:.1f}%, Stop={regime_params['stop']*100:.1f}%, Target={regime_params['target']*100:.1f}%",
                )
                
                if trade:
                    print(f'    -> Paper trade opened: {trade.trade_id}')
                else:
                    print(f'    -> Trade rejected: {msg}')
            else:
                print(f'  {pair}: No signal')
                
        except Exception as e:
            print(f'  {pair}: Error - {e}')
    
    # Summary
    print('\n' + '=' * 60)
    print('=== CYCLE SUMMARY ===')
    print(f'  Positions checked: {len(open_before)}')
    print(f'  Positions closed: {len(closed_trades)}')
    print(f'  New signals: {len(all_new_signals)}')
    print(f'  New trades opened: {len(all_new_signals)}')
    
    # Get updated summary
    closed_total = sum(1 for t in trades if t.get('outcome') != 'open')
    open_total = sum(1 for t in trades if t.get('outcome') == 'open')
    wins = sum(1 for t in trades if t.get('outcome') in ('target', 'win'))
    losses = sum(1 for t in trades if t.get('outcome') in ('stop', 'loss'))
    
    total_pnl = sum(t.get('pnl_usd', 0) for t in trades if t.get('pnl_usd') is not None)
    
    print(f'\n  Total trades: {len(trades)}')
    print(f'  Closed: {closed_total} (W:{wins} L:{losses})')
    print(f'  Open: {open_total}')
    print(f'  Total P&L: ${total_pnl:+.2f}')
    print('=' * 60)
    
    return {
        'closed_trades': closed_trades,
        'new_signals': all_new_signals,
        'open_positions': open_total,
        'total_pnl': total_pnl,
        'wins': wins,
        'losses': losses,
    }

if __name__ == '__main__':
    result = run_cycle()
