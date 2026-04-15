"""
Aggressive MR Scanner (Deep Oversold)
=======================================
Production scanner using optimized aggressive parameters.
Design: RSI<20, deep BB, high volume = rare but high-quality setups.

KEY INSIGHT: Quality over quantity. These setups are rare (87 total across 7 pairs)
but produce +5.4% expectancy even at 2% friction.

TARGETS:
- INJ: +7.21% exp, PF 5.79
- ARB: +6.87% exp, PF 4.95
- SUI: +6.76% exp, PF 4.20
- AAVE: +6.53% exp, PF 726
- AVAX: +4.78% exp, PF 4.11
- LINK: +2.85% exp, PF 2.22
- POL: +2.30% exp, PF 1.95
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# OPTIMIZED PARAMETERS PER PAIR (from deep_optimizer.py)
PORTFOLIO = {
    'INJ': {
        'rsi_thresh': 20, 'bb_std': 2.0, 'vol_mult': 2.5,
        'stop_atr': 0.75, 'target_atr': 2.5, 'bars': 25,
        'base_size': 3.0,  # Position size %
    },
    'ARB': {
        'rsi_thresh': 20, 'bb_std': 2.0, 'vol_mult': 2.0,
        'stop_atr': 0.5, 'target_atr': 2.5, 'bars': 15,
        'base_size': 3.0,
    },
    'SUI': {
        'rsi_thresh': 20, 'bb_std': 3.0, 'vol_mult': 1.5,
        'stop_atr': 0.75, 'target_atr': 4.0, 'bars': 15,
        'base_size': 3.0,
    },
    'AAVE': {
        'rsi_thresh': 20, 'bb_std': 3.0, 'vol_mult': 2.5,
        'stop_atr': 1.0, 'target_atr': 5.0, 'bars': 15,
        'base_size': 2.5,
    },
    'AVAX': {
        'rsi_thresh': 20, 'bb_std': 2.5, 'vol_mult': 2.5,
        'stop_atr': 0.5, 'target_atr': 5.0, 'bars': 15,
        'base_size': 2.5,
    },
    'LINK': {
        'rsi_thresh': 20, 'bb_std': 2.5, 'vol_mult': 2.5,
        'stop_atr': 1.0, 'target_atr': 2.0, 'bars': 20,
        'base_size': 2.0,
    },
    'POL': {
        'rsi_thresh': 20, 'bb_std': 2.0, 'vol_mult': 1.5,
        'stop_atr': 0.75, 'target_atr': 5.0, 'bars': 25,
        'base_size': 1.5,
    },
}

# Regime rules
REGIME_ACTIONS = {
    'BULLISH': {'trade': True, 'size_mult': 1.0},
    'BEARISH': {'trade': True, 'size_mult': 0.7},  # MR works in bear markets
    'RANGING': {'trade': True, 'size_mult': 0.5},  # Smaller in ranging
    'RISK_OFF': {'trade': False, 'size_mult': 0.0},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def load_btc():
    return pd.read_parquet(DATA_DIR / 'binance_BTC_USDT_240m.parquet')


def get_regime(btc_df):
    """Determine market regime from BTC."""
    btc_c = btc_df['close'].values
    btc_sma200 = btc_df['close'].rolling(200).mean().values
    btc_vol = btc_df['close'].pct_change().rolling(20).std().values * np.sqrt(6 * 365)
    
    i = -1
    above_sma = btc_c[i] > btc_sma200[i]
    high_vol = btc_vol[i] > 0.40
    
    if not above_sma and not high_vol:
        return 'RISK_OFF'
    elif not above_sma and high_vol:
        return 'BEARISH'
    elif above_sma and not high_vol:
        return 'RANGING'
    else:
        return 'BULLISH'


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
    
    # Bollinger Bands (multiple std devs)
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower_2 = sma20 - std20 * 2
    bb_lower_25 = sma20 - std20 * 2.5
    bb_lower_3 = sma20 - std20 * 3
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Volume
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return {
        'close': c, 'open': o, 'high': h, 'low': l,
        'rsi': rsi,
        'bb_lower_2': bb_lower_2, 'bb_lower_25': bb_lower_25, 'bb_lower_3': bb_lower_3,
        'atr': atr, 'vol_ratio': vol_ratio,
    }


def check_signal(pair, params, ind):
    """Check for deep oversold MR signal."""
    i = -1
    c = ind['close']
    
    if np.isnan(ind['rsi'][i]) or np.isnan(ind['atr'][i]):
        return None
    
    # Select BB based on std parameter
    bb_key = f"bb_lower_{str(params['bb_std']).replace('.', '')}"
    if bb_key not in ind:
        bb_key = 'bb_lower_2'
    bb_low = ind[bb_key]
    
    if np.isnan(bb_low[i]):
        return None
    
    # DEEP OVERSOLD SIGNAL
    if (ind['rsi'][i] < params['rsi_thresh'] and 
        c[i] < bb_low[i] and 
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
            'bb_std': params['bb_std'],
            'vol_ratio': round(ind['vol_ratio'][i], 2),
            'expected_value': round(params.get('expected_value', 5.0), 2),
        }
    return None


def scan(regime=None):
    """Scan all pairs for deep oversold signals."""
    btc_df = load_btc()
    if regime is None:
        regime = get_regime(btc_df)
    
    regime_config = REGIME_ACTIONS.get(regime, {'trade': False, 'size_mult': 0.0})
    
    if not regime_config['trade']:
        return [], regime
    
    signals = []
    
    for pair, params in PORTFOLIO.items():
        try:
            df = load_data(pair)
            ind = compute_indicators(df)
            signal = check_signal(pair, params, ind)
            
            if signal:
                signal['regime'] = regime
                signal['base_size'] = params['base_size']
                signal['size'] = round(params['base_size'] * regime_config['size_mult'], 1)
                signal['timestamp'] = datetime.now(timezone.utc).isoformat()
                signals.append(signal)
        
        except Exception as e:
            print(f"Error scanning {pair}: {e}")
    
    return signals, regime


def format_signal(s):
    """Format signal for display."""
    return (f"{s['pair']:<8} "
            f"Entry={s['entry']:<10.4f} "
            f"Stop={s['stop_pct']:.1f}% "
            f"Target={s['target_pct']:.1f}% "
            f"R:R={s['rr_ratio']:.1f} "
            f"RSI={s['rsi']:.0f} "
            f"BB{s['bb_std']} "
            f"Vol={s['vol_ratio']:.1f}x "
            f"Size={s['size']}%")


if __name__ == '__main__':
    print("=" * 100)
    print("AGGRESSIVE MR SCANNER (Deep Oversold)")
    print("Design: RSI<20, deep BB, high volume = rare but high-quality setups")
    print(f"Friction: {FRICTION*100:.0f}% | Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 100)
    
    signals, regime = scan()
    
    print(f"\nRegime: {regime}")
    regime_config = REGIME_ACTIONS.get(regime, {'size_mult': 0})
    print(f"Size Multiplier: {regime_config['size_mult']*100:.0f}%")
    
    print(f"\nSignals: {len(signals)}")
    if signals:
        print("-" * 100)
        for s in signals:
            print(format_signal(s))
    else:
        print("\nNo deep oversold signals right now.")
        print("These are rare setups - expect 2-3 trades per month per pair.")
    
    print(f"\nEligible pairs: {len(PORTFOLIO)}")
    print(f"Expected trades/month: ~{len(PORTFOLIO) * 1} (rare setups)")
