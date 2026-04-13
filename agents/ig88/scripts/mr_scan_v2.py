#!/usr/bin/env python3
"""MR Scanner v2: Only triggers on RECENT signals (last 1-2 candles).
Fixes stale entry price issue where old reversal candles produce stale entries.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
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

def get_regime_params(atr_pct: float) -> dict:
    if atr_pct < 2.0:
        return REGIME_STOPS['low_vol']
    elif atr_pct < 4.0:
        return REGIME_STOPS['mid_vol']
    else:
        return REGIME_STOPS['high_vol']

def load_paper_trades() -> list:
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

def get_open_positions(trades: list) -> dict:
    open_by_pair = {}
    for t in trades:
        if t.get('outcome') == 'open':
            pair = t.get('pair', '')
            if pair not in open_by_pair or t.get('entry_timestamp', '') > open_by_pair[pair].get('entry_timestamp', ''):
                open_by_pair[pair] = t
    return open_by_pair

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
    """Detect MR signal on RECENT bars only (last N candles).
    Returns the most recent signal if found, None otherwise.
    Uses CURRENT close price as entry for paper trading realism.
    """
    df = compute_indicators(df)
    
    # Only check the last max_bars_back bars for fresh signals
    start_idx = max(20, len(df) - max_bars_back - 1)
    
    for i in range(start_idx, len(df) - 1):
        row = df.iloc[i]
        is_last_bar = (i == len(df) - 2)  # second-to-last is the completed bar
        
        # Volume filter
        if row['volume'] < row['vol_sma20'] * VOLUME_MULTIPLIER:
            continue
        
        atr_pct = float(row['atr_pct']) if not pd.isna(row['atr_pct']) else 3.0
        
        # Long: RSI oversold + below BB + reversal candle
        if (row['rsi'] < RSI_THRESHOLD and 
            row['close'] < row['bb_lower'] and
            row['close'] > row['open']):
            
            # Use current close price as entry (realistic paper trading)
            current_price = float(df.iloc[-1]['close'])
            
            return {
                'timestamp': df.index[i].isoformat() if hasattr(df.index[i], 'isoformat') else str(df.index[i]),
                'pair': pair,
                'side': 'long',
                'entry_price': current_price,  # Use current price, not old candle
                'signal_price': float(row['close']),  # The price that triggered the signal
                'rsi': float(row['rsi']),
                'close': float(row['close']),
                'bb_lower': float(row['bb_lower']),
                'volume_ratio': float(row['volume'] / row['vol_sma20']),
                'atr_pct': atr_pct,
                'is_last_bar': is_last_bar,
            }
        
        # Short: RSI overbought + above BB + reversal candle
        elif (row['rsi'] > (100 - RSI_THRESHOLD) and
              row['close'] > row['bb_upper'] and
              row['close'] < row['open']):
            
            current_price = float(df.iloc[-1]['close'])
            
            return {
                'timestamp': df.index[i].isoformat() if hasattr(df.index[i], 'isoformat') else str(df.index[i]),
                'pair': pair,
                'side': 'short',
                'entry_price': current_price,  # Use current price
                'signal_price': float(row['close']),
                'rsi': float(row['rsi']),
                'close': float(row['close']),
                'bb_upper': float(row['bb_upper']),
                'volume_ratio': float(row['volume'] / row['vol_sma20']),
                'atr_pct': atr_pct,
                'is_last_bar': is_last_bar,
            }
    
    return None

def run_cycle():
    print('=' * 60)
    print('=== MR SCANNER v2 CYCLE ===')
    print(f'Time: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}')
    print('=' * 60)
    
    trades = load_paper_trades()
    open_before = get_open_positions(trades)
    print(f'\nOpen positions: {len(open_before)}')
    for pair, t in open_before.items():
        entry = t['entry_price']
        side = t['side']
        notes = t.get('notes', '')
        
        # Parse stop/target
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
        
        if side == 'long':
            stop_price = entry * (1 - stop_pct)
            target_price = entry * (1 + target_pct)
        else:
            stop_price = entry * (1 + stop_pct)
            target_price = entry * (1 - target_pct)
        
        print(f'  {pair}: {side.upper()} @ {entry:.4f} | stop={stop_price:.4f} | target={target_price:.4f}')
    
    # Fetch live prices
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
    except Exception as e:
        print(f'WARNING: price fetch failed: {e}')
        for pair in PAIRS:
            path = DATA_DIR / f'binance_{pair}_240m.parquet'
            if path.exists():
                df = pd.read_parquet(path)
                current_prices[pair] = float(df.iloc[-1]['close'])
    
    # Check open positions
    print('\n--- POSITION CHECK ---')
    closed_count = 0
    for pair, trade in list(open_before.items()):
        entry_price = trade['entry_price']
        side = trade['side']
        notes = trade.get('notes', '')
        
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
        
        binance_sym = pair.replace('-PERP', 'USDT')
        current_price = current_prices.get(binance_sym)
        if current_price is None:
            print(f'  {pair}: No price data')
            continue
        
        if side == 'long':
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            pnl_pct = (current_price - entry_price) / entry_price * 100 * LEVERAGE
            hit = 'STOP' if current_price <= stop_price else 'TARGET' if current_price >= target_price else None
        else:
            stop_price = entry_price * (1 + stop_pct)
            target_price = entry_price * (1 - target_pct)
            pnl_pct = (entry_price - current_price) / entry_price * 100 * LEVERAGE
            hit = 'STOP' if current_price >= stop_price else 'TARGET' if current_price <= target_price else None
        
        if hit:
            print(f'  [{hit}] {pair}: {side.upper()} @ {entry_price:.4f}, price={current_price:.4f}, P&L={pnl_pct:+.2f}%')
            closed_count += 1
        else:
            print(f'  [OPEN] {pair}: {side.upper()} @ {entry_price:.4f}, price={current_price:.4f}, P&L={pnl_pct:+.2f}%')
    
    print(f'  Closed this cycle: {closed_count}')
    
    # Scan for new signals with dedup
    print('\n--- NEW SIGNAL SCAN ---')
    open_pairs = set(open_before.keys())
    
    # Also skip NEAR (consistently stops out based on history)
    SKIP_PAIRS = {'NEARUSDT'}  # TODO: re-enable after investigation
    
    new_trades = []
    trader = None
    
    for pair in PAIRS:
        perp_pair = SYMBOL_MAP[pair]
        
        if perp_pair in open_pairs:
            print(f'  {pair}: SKIP (position open)')
            continue
        
        if pair in SKIP_PAIRS:
            print(f'  {pair}: SKIP (disabled - consistent losses)')
            continue
        
        path = DATA_DIR / f'binance_{pair}_240m.parquet'
        if not path.exists():
            print(f'  {pair}: No data')
            continue
        
        try:
            df = pd.read_parquet(path)
            sig = detect_recent_signal(df, pair, max_bars_back=2)
            
            if sig:
                atr_pct = sig.get('atr_pct', 3.0)
                regime_params = get_regime_params(atr_pct)
                
                print(f'  {pair}: SIGNAL')
                print(f'    Side: {sig["side"]}')
                print(f'    RSI: {sig["rsi"]:.1f}')
                print(f'    Volume: {sig["volume_ratio"]:.1f}x')
                print(f'    ATR: {atr_pct:.1f}%')
                print(f'    Entry: ${sig["entry_price"]:.4f} (current price)')
                print(f'    Stop: {regime_params["stop"]*100:.1f}%, Target: {regime_params["target"]*100:.1f}%')
                
                with open(SIGNAL_LOG_PATH, 'a') as f:
                    f.write(json.dumps({**sig, 'scan_time': datetime.now(timezone.utc).isoformat()}) + '\n')
                
                # Execute paper trade
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
                    new_trades.append(trade)
                    print(f'    -> Opened: {trade.trade_id}')
            else:
                print(f'  {pair}: No signal')
                
        except Exception as e:
            print(f'  {pair}: Error - {e}')
    
    # Final summary
    all_trades = load_paper_trades()
    closed_trades = [t for t in all_trades if t.get('outcome') != 'open']
    open_trades = [t for t in all_trades if t.get('outcome') == 'open']
    wins = sum(1 for t in closed_trades if t.get('pnl_usd', 0) and t.get('pnl_usd', 0) > 0)
    losses = sum(1 for t in closed_trades if t.get('pnl_usd', 0) and t.get('pnl_usd', 0) <= 0)
    total_pnl = sum(t.get('pnl_usd', 0) or 0 for t in closed_trades)
    
    print('\n' + '=' * 60)
    print('=== FINAL SUMMARY ===')
    print(f'  Open positions: {len(open_trades)}')
    for t in open_trades:
        print(f'    {t["pair"]}: {t["side"].upper()} @ {t["entry_price"]:.4f}')
    print(f'  Closed trades: {len(closed_trades)} (W:{wins} L:{losses})')
    print(f'  Win rate: {wins/len(closed_trades)*100:.1f}%' if closed_trades else '  Win rate: N/A')
    print(f'  Total P&L: ${total_pnl:+.2f}')
    print(f'  New signals this cycle: {len(new_trades)}')
    print('=' * 60)
    
    return {
        'open_positions': len(open_trades),
        'closed_trades': len(closed_trades),
        'wins': wins,
        'losses': losses,
        'total_pnl': total_pnl,
        'new_signals': len(new_trades),
    }

if __name__ == '__main__':
    run_cycle()
