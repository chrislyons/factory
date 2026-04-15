"""
Aggressive MR Scanner v2 (Validated Strategy)
==============================================
Validated strategy with session + ATR filters.

STRATEGY:
- Entry: RSI<20 + BB<2.0 + Volume>1.5x + ATR>2.5%
- Exit: 0.75x ATR stop OR 2.5x ATR target (15 bars max)
- Session: ASIA+NY (except SUI: all)

PORTFOLIO:
- ARB: +5.20% exp, PF 3.58, 3% size
- ATOM: +3.19% exp, PF 2.40, 2.5% size
- AVAX: +1.43% exp, PF 1.62, 2% size
- AAVE: +1.77% exp, PF 1.85, 2% size
- SUI: +1.43% exp, PF 1.44, 2% size

Total: 58 trades, Exp +2.70%, PF 2.12
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# VALIDATED PORTFOLIO (2026-04-13)
PORTFOLIO = {
    'ARB': {
        'rsi_thresh': 20, 'bb_std': 2.0, 'vol_mult': 1.5,
        'stop_atr': 0.75, 'target_atr': 2.5, 'bars': 15,
        'base_size': 3.0, 'session_filter': ['ASIA', 'NY'],
    },
    'ATOM': {
        'rsi_thresh': 20, 'bb_std': 2.0, 'vol_mult': 1.5,
        'stop_atr': 0.75, 'target_atr': 2.5, 'bars': 15,
        'base_size': 2.5, 'session_filter': ['ASIA', 'NY'],
    },
    'AVAX': {
        'rsi_thresh': 20, 'bb_std': 2.0, 'vol_mult': 1.5,
        'stop_atr': 0.75, 'target_atr': 2.5, 'bars': 15,
        'base_size': 2.0, 'session_filter': ['ASIA', 'NY'],
    },
    'AAVE': {
        'rsi_thresh': 20, 'bb_std': 2.0, 'vol_mult': 1.5,
        'stop_atr': 0.75, 'target_atr': 2.5, 'bars': 15,
        'base_size': 2.0, 'session_filter': ['ASIA', 'NY'],
    },
    'SUI': {
        'rsi_thresh': 20, 'bb_std': 2.0, 'vol_mult': 1.5,
        'stop_atr': 0.75, 'target_atr': 2.5, 'bars': 15,
        'base_size': 2.0, 'session_filter': None,  # All sessions
    },
}

MIN_ATR_PCT = 2.5  # Minimum ATR as % of price


def get_session(hour):
    """Get trading session from hour (UTC)."""
    if 0 <= hour < 8: return 'ASIA'
    elif 8 <= hour < 13: return 'LONDON'
    elif 13 <= hour < 16: return 'LONDON_NY'
    elif 16 <= hour < 21: return 'NY'
    else: return 'OFF_HOURS'


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    """Compute RSI, BB, Volume, ATR."""
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = atr / c * 100
    
    # Volume
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    # Session from index (4h bars)
    if isinstance(df.index, pd.DatetimeIndex):
        hours = df.index.hour
    else:
        hours = [(i * 4) % 24 for i in range(len(df))]
    session = np.array([get_session(h) for h in hours])
    
    return {
        'close': c, 'open': o, 'high': h, 'low': l,
        'rsi': rsi, 'bb_lower': bb_lower,
        'atr': atr, 'atr_pct': atr_pct, 'vol_ratio': vol_ratio,
        'session': session,
    }


def check_signal(pair, params, ind):
    """Check for deep oversold MR signal with ALL filters."""
    i = -1
    c = ind['close']
    
    if np.isnan(ind['rsi'][i]) or np.isnan(ind['atr'][i]) or np.isnan(ind['bb_lower'][i]):
        return None
    
    # Session filter
    current_session = ind['session'][i]
    if params['session_filter'] and current_session not in params['session_filter']:
        return None
    
    # ATR filter (regime robustness)
    if ind['atr_pct'][i] < MIN_ATR_PCT:
        return None
    
    # DEEP OVERSOLD SIGNAL
    if (ind['rsi'][i] < params['rsi_thresh'] and 
        c[i] < ind['bb_lower'][i] and 
        ind['vol_ratio'][i] > params['vol_mult']):
        
        entry_price = c[i]
        atr_val = ind['atr'][i]
        stop_dist = atr_val * params['stop_atr']
        target_dist = atr_val * params['target_atr']
        
        return {
            'pair': pair,
            'entry': round(entry_price, 6),
            'stop': round(entry_price - stop_dist, 6),
            'target': round(entry_price + target_dist, 6),
            'stop_pct': round(stop_dist / entry_price * 100, 2),
            'target_pct': round(target_dist / entry_price * 100, 2),
            'rr_ratio': round(target_dist / stop_dist, 1),
            'rsi': round(ind['rsi'][i], 1),
            'atr_pct': round(ind['atr_pct'][i], 2),
            'vol_ratio': round(ind['vol_ratio'][i], 2),
            'session': current_session,
            'bars': params['bars'],
        }
    return None


def scan():
    """Scan all validated pairs for signals."""
    signals = []
    
    for pair, params in PORTFOLIO.items():
        try:
            df = load_data(pair)
            ind = compute_indicators(df)
            signal = check_signal(pair, params, ind)
            
            if signal:
                signal['timestamp'] = datetime.now(timezone.utc).isoformat()
                signal['size'] = params['base_size']
                signals.append(signal)
        
        except Exception as e:
            print(f"Error scanning {pair}: {e}")
    
    return signals


def format_signal(s):
    """Format signal for display."""
    return (f"{s['pair']:<8} "
            f"Entry={s['entry']:<10.4f} "
            f"Stop={s['stop_pct']:.1f}% "
            f"Target={s['target_pct']:.1f}% "
            f"R:R={s['rr_ratio']:.1f} "
            f"RSI={s['rsi']:.0f} "
            f"ATR={s['atr_pct']:.1f}% "
            f"Vol={s['vol_ratio']:.1f}x "
            f"Sess={s['session']} "
            f"Size={s['size']}%")


if __name__ == '__main__':
    print("=" * 100)
    print("AGGRESSIVE MR SCANNER v2 (Validated Strategy)")
    print("Entry: RSI<20 + BB<2.0 + Volume>1.5x + ATR>2.5%")
    print("Session: ASIA+NY (except SUI: all)")
    print(f"Friction: {FRICTION*100:.0f}% | Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 100)
    
    signals = scan()
    
    print(f"\nSignals: {len(signals)}")
    if signals:
        print("-" * 100)
        for s in signals:
            print(format_signal(s))
    else:
        print("\nNo signals right now.")
        print("These are rare setups - expect ~4-5 trades/month across all pairs.")
    
    print(f"\nEligible pairs: {len(PORTFOLIO)}")
    print(f"Expected trades/month: ~4-5")
