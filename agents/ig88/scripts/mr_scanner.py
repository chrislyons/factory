#!/usr/bin/env python3
"""Mean Reversion Scanner for Paper Trading.

Scans 4h candles for RSI<35 + BB_Lower + Reversal + Vol>1.2x signals.
Logs signals to paper trading system.

Strategy: IG88036 Mean Reversion
Entry: RSI(14) < 35 AND Close < BB_Lower(1σ) AND Reversal candle
Exit: T2 mid-bar (realistic execution)
Filter: Volume > 1.2x SMA20
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Add project root to path
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
DAILY_REPORT_PATH = DATA_DIR / 'mr_daily_report.md'

# Strategy parameters (validated 2026-04-13, IG88037)
RSI_THRESHOLD = 35
BB_MULTIPLIER = 1.0
VOLUME_MULTIPLIER = 1.2
POSITION_SIZE_USD = 500.0
LEVERAGE = 2.0

# Adaptive stop/target based on volatility regime
# Validated: tight stops + wide targets = highest PF for MR
REGIME_STOPS = {
    'low_vol': {'atr_pct': 2.0, 'stop': 0.015, 'target': 0.03},    # <2% ATR
    'mid_vol': {'atr_pct': 4.0, 'stop': 0.01, 'target': 0.075},    # 2-4% ATR
    'high_vol': {'atr_pct': 999, 'stop': 0.005, 'target': 0.075},  # >4% ATR
}

def get_regime_params(atr_pct: float) -> dict:
    """Get stop/target based on current volatility."""
    if atr_pct < 2.0:
        return REGIME_STOPS['low_vol']
    elif atr_pct < 4.0:
        return REGIME_STOPS['mid_vol']
    else:
        return REGIME_STOPS['high_vol']

# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute RSI, BB, Volume SMA, ATR."""
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
    
    # ATR (14-period, as % of price)
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
    """Detect mean reversion signals."""
    df = compute_indicators(df)
    signals = []
    
    for i in range(20, len(df) - 1):
        row = df.iloc[i]
        
        # Volume filter
        if row['volume'] < row['vol_sma20'] * VOLUME_MULTIPLIER:
            continue
        
        atr_pct = float(row['atr_pct']) if not pd.isna(row['atr_pct']) else 3.0
        
        # Long signal: RSI oversold + below BB + reversal candle
        if (row['rsi'] < RSI_THRESHOLD and 
            row['close'] < row['bb_lower'] and
            row['close'] > row['open']):  # Reversal candle
            
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
        
        # Short signal: RSI overbought + above BB + reversal candle
        elif (row['rsi'] > (100 - RSI_THRESHOLD) and
              row['close'] > row['bb_upper'] and
              row['close'] < row['open']):  # Reversal candle
            
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
# Paper Trading Execution
# ---------------------------------------------------------------------------

def load_paper_trader() -> PaperTrader:
    """Load or create paper trader."""
    cfg = load_config()
    trader = PaperTrader(cfg, portfolio_value=10_000.0, trades_path=PAPER_TRADES_PATH)
    return trader

def execute_signal(trader: PaperTrader, signal: dict, atr_pct: float = 3.0) -> tuple:
    """Execute a signal as a paper trade.
    
    Args:
        signal: Signal dict from detect_signals()
        atr_pct: Current ATR as % of price (for regime-adaptive stops)
    """
    from src.quant.regime import RegimeAssessment, RegimeSignal, RegimeState
    
    # Set regime to RISK_ON for paper trading
    regime = RegimeAssessment(
        state=RegimeState.RISK_ON,
        score=7.0,
        signals=[RegimeSignal(name="paper_mode", value=1.0, score=7.0, weight=1.0)],
        timestamp=datetime.now(tz=timezone.utc),
        confidence=0.8,
    )
    trader.set_regime(regime)
    
    # Adaptive stop/target based on current volatility (validated IG88037)
    entry = signal['entry_price']
    regime_params = get_regime_params(atr_pct)
    stop_pct = regime_params['stop']
    target_pct = regime_params['target']
    
    if signal['side'] == 'long':
        stop = entry * (1 - stop_pct)
        target = entry * (1 + target_pct)
    else:
        stop = entry * (1 + stop_pct)
        target = entry * (1 - target_pct)
    
    trade, msg = trader.open_position(
        venue='jupiter_perps',
        pair=f"{signal['pair'].replace('USDT', '')}-PERP",
        side=signal['side'],
        entry_price=entry,
        position_size_usd=POSITION_SIZE_USD,
        strategy='mean_reversion',
        stop_level=stop,
        target_level=target,
        leverage=LEVERAGE,
        expected_move_pct=target_pct,
        notes=f"MR: RSI={signal['rsi']:.1f}, Vol={signal['volume_ratio']:.1f}x, "
              f"ATR={atr_pct:.1f}%, Stop={stop_pct*100:.1f}%, Target={target_pct*100:.1f}%",
    )
    
    return trade, msg

# ---------------------------------------------------------------------------
# Main Scan
# ---------------------------------------------------------------------------

def scan():
    """Run the mean reversion scan."""
    print(f"=== Mean Reversion Scanner ===")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Pairs: {', '.join(PAIRS)}")
    print()
    
    all_signals = []
    trader = load_paper_trader()
    
    for pair in PAIRS:
        path = DATA_DIR / f'binance_{pair}_240m.parquet'
        if not path.exists():
            print(f"  {pair}: No data file")
            continue
        
        try:
            df = pd.read_parquet(path)
            signals = detect_signals(df, pair)
            
            # Get most recent signal (last bar with reversal)
            recent = signals[-1:] if signals else []
            
            if recent:
                sig = recent[0]
                atr_pct = sig.get('atr_pct', 3.0)
                regime_params = get_regime_params(atr_pct)
                
                print(f"  {pair}: SIGNAL DETECTED")
                print(f"    Side: {sig['side']}")
                print(f"    RSI: {sig['rsi']:.1f}")
                print(f"    Volume: {sig['volume_ratio']:.1f}x")
                print(f"    ATR: {atr_pct:.1f}% ({'high' if atr_pct > 4 else 'mid' if atr_pct > 2 else 'low'} vol)")
                print(f"    Stop: {regime_params['stop']*100:.1f}%, Target: {regime_params['target']*100:.1f}%")
                
                # Log signal
                with open(SIGNAL_LOG_PATH, 'a') as f:
                    f.write(json.dumps(sig) + '\n')
                
                all_signals.append(sig)
                
                # Execute as paper trade with ATR-based stops
                trade, msg = execute_signal(trader, sig, atr_pct=atr_pct)
                if trade:
                    print(f"    Paper trade opened: {trade.trade_id}")
                else:
                    print(f"    Trade rejected: {msg}")
            else:
                print(f"  {pair}: No signal")
                
        except Exception as e:
            print(f"  {pair}: Error - {e}")
    
    print(f"\nTotal signals: {len(all_signals)}")
    return all_signals

if __name__ == '__main__':
    scan()
