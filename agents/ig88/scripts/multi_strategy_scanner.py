"""
Multi-Strategy Scanner
=======================
Uses OPTIMAL strategy for each pair (from friction optimizer results).
Instead of one-size-fits-all, this adapts to each pair's characteristics.

OPTIMAL STRATEGIES (from optimization at 2% friction):
- ARB: MR (RSI<20, BB<2.0std, Volume>1.8x) - +6.49%
- AVAX: MR (RSI<25, BB<1.5std, Volume>1.5x) - +4.51%
- SUI: Breakout (Donchian20, Volume>1.5x) - +4.08%
- NEAR: Breakout (Donchian20, Volume>1.5x) - +4.20%
- SOL: TF (EMA12/26, ADX>25) - +3.84%
- AAVE: Breakout (Donchian20, Volume>1.5x) - +3.69%
- OP: MR (RSI<30, BB<2.0std, Volume>1.3x) - +3.25%
- POL: Breakout (Donchian20, Volume>1.5x) - +3.32%
- UNI: Breakout (Donchian20, Volume>1.5x) - +3.07%
- INJ: Breakout (Donchian20, Volume>1.5x) - +2.56%
- LINK: MR (RSI<30, BB<2.0std, Volume>1.5x) - +2.49%
- ATOM: MR (RSI<30, BB<2.0std, Volume>1.5x) - +2.03%
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02  # Design for 2% friction (worst case)

# OPTIMAL STRATEGY PER PAIR (from friction_optimizer.py)
PAIR_STRATEGIES = {
    'ARB': {
        'type': 'MR',
        'rsi_period': 14, 'rsi_thresh': 20,
        'bb_std': 2.0, 'volume_mult': 1.8,
        'entry_delay': 3, 'stop_atr': 0.75, 'target_atr': 3.0,
        'exit_bars': 15,
        'regimes': ['BULLISH', 'BEARISH', 'RANGING'],  # Works everywhere
    },
    'AVAX': {
        'type': 'MR',
        'rsi_period': 14, 'rsi_thresh': 25,
        'bb_std': 1.5, 'volume_mult': 1.5,
        'entry_delay': 2, 'stop_atr': 1.0, 'target_atr': 2.5,
        'exit_bars': 15,
        'regimes': ['BULLISH', 'BEARISH'],
    },
    'SUI': {
        'type': 'BREAKOUT',
        'volume_mult': 1.5,
        'entry_delay': 1, 'stop_atr': 1.0, 'target_atr': 2.5,
        'exit_bars': 15,
        'regimes': ['BULLISH', 'BEARISH'],
    },
    'NEAR': {
        'type': 'BREAKOUT',
        'volume_mult': 1.5,
        'entry_delay': 1, 'stop_atr': 1.0, 'target_atr': 2.5,
        'exit_bars': 15,
        'regimes': ['BULLISH'],
    },
    'SOL': {
        'type': 'TF',
        'ema_fast': 12, 'ema_slow': 26, 'adx_thresh': 25,
        'volume_mult': 1.2,
        'entry_delay': 2, 'stop_atr': 1.5, 'target_atr': 3.0,
        'exit_bars': 20,
        'regimes': ['BULLISH'],
    },
    'AAVE': {
        'type': 'BREAKOUT',
        'volume_mult': 1.5,
        'entry_delay': 1, 'stop_atr': 1.0, 'target_atr': 2.5,
        'exit_bars': 15,
        'regimes': ['BULLISH', 'BEARISH'],
    },
    'OP': {
        'type': 'MR',
        'rsi_period': 14, 'rsi_thresh': 30,
        'bb_std': 2.0, 'volume_mult': 1.3,
        'entry_delay': 2, 'stop_atr': 0.5, 'target_atr': 2.0,
        'exit_bars': 15,
        'regimes': ['BULLISH'],
    },
    'POL': {
        'type': 'BREAKOUT',
        'volume_mult': 1.5,
        'entry_delay': 1, 'stop_atr': 1.0, 'target_atr': 2.5,
        'exit_bars': 15,
        'regimes': ['BULLISH'],
    },
    'UNI': {
        'type': 'BREAKOUT',
        'volume_mult': 1.5,
        'entry_delay': 1, 'stop_atr': 1.0, 'target_atr': 2.5,
        'exit_bars': 15,
        'regimes': ['BULLISH', 'BEARISH'],
    },
    'INJ': {
        'type': 'BREAKOUT',
        'volume_mult': 1.5,
        'entry_delay': 1, 'stop_atr': 1.0, 'target_atr': 2.5,
        'exit_bars': 15,
        'regimes': ['BULLISH'],
    },
    'LINK': {
        'type': 'MR',
        'rsi_period': 14, 'rsi_thresh': 30,
        'bb_std': 2.0, 'volume_mult': 1.5,
        'entry_delay': 2, 'stop_atr': 1.0, 'target_atr': 2.5,
        'exit_bars': 15,
        'regimes': ['BULLISH', 'BEARISH'],
    },
    'ATOM': {
        'type': 'MR',
        'rsi_period': 14, 'rsi_thresh': 30,
        'bb_std': 2.0, 'volume_mult': 1.5,
        'entry_delay': 2, 'stop_atr': 1.0, 'target_atr': 2.5,
        'exit_bars': 15,
        'regimes': ['BULLISH', 'BEARISH'],
    },
}

# Regime-specific size multipliers
REGIME_SIZE_MULT = {
    'BULLISH': 1.0,
    'BEARISH': 0.7,
    'RANGING': 0.5,
    'RISK_OFF': 0.0,
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def load_btc():
    return pd.read_parquet(DATA_DIR / 'binance_BTC_USDT_240m.parquet')


def get_regime(btc_df):
    """Get current regime from BTC data."""
    btc_c = btc_df['close'].values
    btc_sma200 = btc_df['close'].rolling(200).mean().values
    btc_vol = btc_df['close'].pct_change().rolling(20).std().values * np.sqrt(6*365)
    
    i = -1  # Latest
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
    """Compute all indicators needed for strategies."""
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    v = df['volume'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower_20 = sma20 - std20 * 2
    bb_lower_15 = sma20 - std20 * 1.5
    
    # EMAs
    ema_12 = df['close'].ewm(span=12, adjust=False).mean().values
    ema_26 = df['close'].ewm(span=26, adjust=False).mean().values
    
    # ADX
    plus_dm = np.maximum(np.diff(h, prepend=h[0]), 0)
    minus_dm = np.maximum(-np.diff(l, prepend=l[0]), 0)
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / atr
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(14).mean().values
    
    # Donchian Channel
    donchian_upper = pd.Series(h).rolling(20).max().values
    
    # Volume
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    return {
        'close': c, 'open': o, 'high': h, 'low': l,
        'rsi': rsi,
        'bb_lower_20': bb_lower_20, 'bb_lower_15': bb_lower_15,
        'ema_12': ema_12, 'ema_26': ema_26,
        'adx': adx, 'atr': atr,
        'donchian_upper': donchian_upper,
        'vol_ratio': vol_ratio,
    }


def check_mr_signal(ind, params):
    """Check Mean Reversion signal."""
    i = -1  # Check latest bar
    if np.isnan(ind['rsi'][i]) or np.isnan(ind['bb_lower_20'][i]):
        return None
    
    bb_key = 'bb_lower_15' if params['bb_std'] == 1.5 else 'bb_lower_20'
    
    if (ind['rsi'][i] < params['rsi_thresh'] and 
        ind['close'][i] < ind[bb_key][i] and
        ind['vol_ratio'][i] > params['volume_mult']):
        return {
            'type': 'MR',
            'entry_price_est': ind['close'][i],
            'stop_pct': params['stop_atr'] * ind['atr'][i] / ind['close'][i],
            'target_pct': params['target_atr'] * ind['atr'][i] / ind['close'][i],
        }
    return None


def check_breakout_signal(ind, params):
    """Check Breakout signal."""
    i = -1
    if np.isnan(ind['donchian_upper'][i]):
        return None
    
    # Price broke above Donchian upper with volume
    if (ind['close'][i] > ind['donchian_upper'][i-1] and
        ind['vol_ratio'][i] > params['volume_mult']):
        return {
            'type': 'BREAKOUT',
            'entry_price_est': ind['close'][i],
            'stop_pct': params['stop_atr'] * ind['atr'][i] / ind['close'][i],
            'target_pct': params['target_atr'] * ind['atr'][i] / ind['close'][i],
        }
    return None


def check_tf_signal(ind, params):
    """Check Trend Following signal."""
    i = -1
    if np.isnan(ind['ema_12'][i]) or np.isnan(ind['ema_26'][i]) or np.isnan(ind['adx'][i]):
        return None
    
    # Bullish trend: EMA12 > EMA26, ADX strong, pullback to EMA12
    if (ind['ema_12'][i] > ind['ema_26'][i] and
        ind['adx'][i] > params['adx_thresh'] and
        ind['close'][i] < ind['ema_12'][i] and
        ind['close'][i] > ind['ema_26'][i] and
        ind['vol_ratio'][i] > params['volume_mult']):
        return {
            'type': 'TF',
            'entry_price_est': ind['close'][i],
            'stop_pct': params['stop_atr'] * ind['atr'][i] / ind['close'][i],
            'target_pct': params['target_atr'] * ind['atr'][i] / ind['close'][i],
        }
    return None


def scan_all_pairs():
    """
    Scan all pairs using their OPTIMAL strategy.
    Returns list of signals.
    """
    # Load BTC for regime
    btc_df = load_btc()
    regime = get_regime(btc_df)
    regime_mult = REGIME_SIZE_MULT.get(regime, 0.0)
    
    if regime_mult == 0.0:
        return [], regime
    
    signals = []
    
    for pair, params in PAIR_STRATEGIES.items():
        # Check regime eligibility
        if regime not in params.get('regimes', ['BULLISH']):
            continue
        
        try:
            df = load_data(pair)
            ind = compute_indicators(df)
            
            # Check appropriate signal type
            signal = None
            if params['type'] == 'MR':
                signal = check_mr_signal(ind, params)
            elif params['type'] == 'BREAKOUT':
                signal = check_breakout_signal(ind, params)
            elif params['type'] == 'TF':
                signal = check_tf_signal(ind, params)
            
            if signal:
                signal['pair'] = pair
                signal['regime'] = regime
                signal['regime_mult'] = regime_mult
                signal['strategy'] = params['type']
                signal['base_size'] = 8.0  # Base position size
                signal['adjusted_size'] = 8.0 * regime_mult
                signals.append(signal)
        
        except Exception as e:
            print(f"Error scanning {pair}: {e}")
            continue
    
    return signals, regime


if __name__ == '__main__':
    print("=" * 80)
    print("MULTI-STRATEGY SCANNER (2% friction design)")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)
    
    signals, regime = scan_all_pairs()
    
    print(f"\nCurrent Regime: {regime}")
    print(f"Regime Size Multiplier: {REGIME_SIZE_MULT.get(regime, 0):.0%}")
    print(f"\nPairs configured: {len(PAIR_STRATEGIES)}")
    print(f"Signals found: {len(signals)}")
    
    if signals:
        print(f"\n{'Pair':<8} {'Strategy':<12} {'Entry':<10} {'Stop':<8} {'Target':<8} {'Size'}")
        print("-" * 60)
        for s in signals:
            print(f"{s['pair']:<8} {s['strategy']:<12} {s['entry_price_est']:<10.4f} {s['stop_pct']*100:<7.2f}% {s['target_pct']*100:<7.2f}% {s['adjusted_size']:.1f}%")
    
    # Show which pairs are eligible in current regime
    print(f"\nEligible pairs in {regime}:")
    eligible = [p for p, params in PAIR_STRATEGIES.items() if regime in params.get('regimes', ['BULLISH'])]
    print(f"  {', '.join(eligible)} ({len(eligible)} pairs)")
