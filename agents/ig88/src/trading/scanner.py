"""
Signal Scanner
==============
Scans all 12 pairs for MR and H3 signals.
Returns actionable trade signals with pair-specific parameters.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from src.trading.regime import load_btc_data, compute_btc_20bar_return

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0025

# ============================================================================
# MR PARAMETERS (pair-specific, validated)
# ============================================================================
# Pair-specific parameters (validated 2026-04-13)
# Entry delay: T2 for all pairs (validated winner, avoids bar-open microstructure)
# Stops: Pair-specific based on stop widening test
#   - 0.50% default (8 pairs optimal)
#   - 0.75% for SUI, LINK, INJ (higher expectancy at wider stop)
# PRODUCTION PORTFOLIO: SUI + OP only (validated 2026-04-12)
# Others rejected: AVAX (103% DD), AAVE (63% DD), ARB/INJ (unstable WF)
# With real friction (1.33%), only these 2 pairs are profitable
#
# REGIME-SPECIFIC RULES (validated 2026-04-13):
#   - BULLISH: Trade both SUI + OP (1.76% exp)
#   - BEARISH: Trade SUI only (OP loses in bearish)
#   - RANGING: Trade SUI only, reduced size
#   - RISK_OFF: SIT OUT (0.21% exp, not worth friction)
#
# TIMEFRAME: 4h ONLY (1h and 2h are losers)
PAIR_PARAMS = {
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol_mult': 1.8, 'entry_delay': 2, 'stop_pct': 0.0075, 'target_pct': 0.15,  'exit_bars': 16,
             'regimes': ['BULLISH', 'BEARISH', 'RANGING']},  # Works in all regimes
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol_mult': 1.3, 'entry_delay': 2, 'stop_pct': 0.005,  'target_pct': 0.15,  'exit_bars': 16,
             'regimes': ['BULLISH']},  # Only trade OP in BULLISH
}

# Regime-specific size multipliers
REGIME_SIZE_MULTIPLIER = {
    'BULLISH': 1.0,    # Full size
    'BEARISH': 1.0,    # Full size (for SUI)
    'RANGING': 0.5,    # Half size
    'RISK_OFF': 0.0,   # No trading
}

# Pairs eligible for H3 strategies
H3A_PAIRS = ['SOL']
H3B_PAIRS = ['SOL', 'AVAX']


def load_pair_data(pair):
    """Load 4h OHLCV data for a pair."""
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if not path.exists():
        raise FileNotFoundError(f"Data not found: {path}")
    return pd.read_parquet(path)


def compute_indicators(df, btc_returns=None):
    """Compute all required indicators."""
    c = df['close'].values
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    h, l = df['high'].values, df['low'].values
    c_arr = c
    
    # Ichimoku for H3
    tenkan = (pd.Series(h).rolling(9).max() + pd.Series(l).rolling(9).min()) / 2
    kijun = (pd.Series(h).rolling(26).max() + pd.Series(l).rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((pd.Series(h).rolling(52).max() + pd.Series(l).rolling(52).min()) / 2).shift(26)
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'sma20': sma20, 'std20': std20,
        'vol_ratio': vol_ratio,
        'tenkan': tenkan.values, 'kijun': kijun.values,
        'senkou_a': senkou_a.values, 'senkou_b': senkou_b.values,
        'btc_returns': btc_returns,
    }


def check_mr_signal(ind, params):
    """
    Check for MR signal on latest bar.
    
    Conditions:
    1. RSI < threshold
    2. Price < BB lower band (sma20 - std20 * bb_std)
    3. Volume > threshold x 20-bar MA
    
    Returns: signal dict or None
    """
    i = len(ind['c']) - 2  # Check second-to-last bar (bar just closed)
    
    rsi = ind['rsi'][i]
    c = ind['c'][i]
    sma20 = ind['sma20'][i]
    std20 = ind['std20'][i]
    vol_ratio = ind['vol_ratio'][i]
    
    if np.isnan(rsi) or np.isnan(sma20) or np.isnan(vol_ratio):
        return None
    
    bb_lower = sma20 - std20 * params['bb']
    
    if rsi < params['rsi'] and c < bb_lower and vol_ratio > params['vol']:
        entry_bar = i + params['entry']
        
        return {
            'strategy': 'MR',
            'pair': None,  # Filled by caller
            'entry_bar': entry_bar,
            'entry_price_est': ind['o'][entry_bar] if entry_bar < len(ind['o']) else None,
            'stop_pct': params['stop'],
            'target_pct': params['target'],
            'rsi': float(rsi),
            'bb_position': float((c - bb_lower) / std20) if std20 > 0 else 0,
            'vol_ratio': float(vol_ratio),
            'confidence': 1.0 - (rsi / params['rsi']),  # Lower RSI = higher confidence
        }
    
    return None


def check_h3a_signal(ind):
    """
    H3-A: Ichimoku Convergence
    
    Conditions:
    1. TK cross (Tenkan > Kijun)
    2. Price above cloud
    3. RSI > 40
    4. Score >= 3
    5. BTC 20-bar return > 0% (regime filter)
    
    Returns: signal dict or None
    """
    i = len(ind['c']) - 2
    
    c = ind['c'][i]
    rsi = ind['rsi'][i]
    tenkan = ind['tenkan'][i]
    kijun = ind['kijun'][i]
    senkou_a = ind['senkou_a'][i]
    senkou_b = ind['senkou_b'][i]
    
    if np.isnan(rsi) or np.isnan(tenkan) or np.isnan(kijun):
        return None
    if np.isnan(senkou_a) or np.isnan(senkou_b):
        return None
    
    # BTC regime filter
    if ind['btc_returns'] is not None and not np.isnan(ind['btc_returns']):
        if ind['btc_returns'] < 0:
            return None
    
    tk_cross = tenkan > kijun
    cloud_top = np.nanmax([senkou_a, senkou_b])
    above_cloud = c > cloud_top
    rsi_ok = rsi > 40
    
    score = int(tk_cross) + int(above_cloud) + int(rsi_ok)
    
    if score >= 3:
        return {
            'strategy': 'H3-A',
            'pair': None,
            'entry_bar': i + 1,
            'entry_price_est': ind['o'][i + 1] if i + 1 < len(ind['o']) else None,
            'exit_bars': 10,
            'score': score,
            'tk_cross': tk_cross,
            'above_cloud': above_cloud,
            'rsi': float(rsi),
            'confidence': min(1.0, score / 4),
        }
    
    return None


def check_h3b_signal(ind):
    """
    H3-B: Volume Ignition + RSI Cross
    
    Conditions:
    1. Volume > 1.5x 20-bar MA
    2. Price gained > 0.5%
    3. RSI crossed above 50
    4. BTC 20-bar return > 0%
    
    Returns: signal dict or None
    """
    i = len(ind['c']) - 2
    
    if i < 1:
        return None
    
    vol_ratio = ind['vol_ratio'][i]
    rsi = ind['rsi'][i]
    rsi_prev = ind['rsi'][i - 1]
    c = ind['c'][i]
    c_prev = ind['c'][i - 1]
    
    if np.isnan(vol_ratio) or np.isnan(rsi) or np.isnan(rsi_prev):
        return None
    
    # BTC regime filter
    if ind['btc_returns'] is not None and not np.isnan(ind['btc_returns']):
        if ind['btc_returns'] < 0:
            return None
    
    vol_spike = vol_ratio > 1.5
    price_gain = (c - c_prev) / c_prev > 0.005
    rsi_cross = rsi > 50 and rsi_prev <= 50
    
    if vol_spike and price_gain and rsi_cross:
        return {
            'strategy': 'H3-B',
            'pair': None,
            'entry_bar': i + 1,
            'entry_price_est': ind['o'][i + 1] if i + 1 < len(ind['o']) else None,
            'exit_bars': 10,
            'vol_ratio': float(vol_ratio),
            'price_gain': float((c - c_prev) / c_prev * 100),
            'rsi': float(rsi),
            'confidence': min(1.0, vol_ratio / 2.0),
        }
    
    return None


def scan_all_pairs(mr_weight=1.0, h3_weight=0.0, regime_name=None):
    """
    Scan all configured pairs for MR and H3 signals.
    
    REGIME-AWARE (validated 2026-04-13):
    - Only scans pairs allowed in current regime
    - Applies regime-specific size multiplier
    
    Args:
        mr_weight: Weight for MR signals (0-1)
        h3_weight: Weight for H3 signals (0-1)
        regime_name: Override regime (for testing)
    
    Returns:
        list of signal dicts
    """
    from src.trading.regime import get_current_regime
    
    signals = []
    
    # Get current regime
    if regime_name is None:
        regime = get_current_regime()
        regime_name = regime['regime']
    
    # Regime-specific size multiplier
    size_mult = REGIME_SIZE_MULTIPLIER.get(regime_name, 0.0)
    if size_mult == 0.0:
        return []  # No trading in this regime
    
    # Get BTC returns for regime filter
    btc_df = load_btc_data()
    btc_returns = float(btc_df['close'].pct_change(20).iloc[-1])
    
    for pair, params in PAIR_PARAMS.items():
        # Check if pair is allowed in this regime
        allowed_regimes = params.get('regimes', ['BULLISH'])
        if regime_name not in allowed_regimes:
            continue
        
        try:
            df = load_pair_data(pair)
            ind = compute_indicators(df, btc_returns)
            
            # MR signal
            if mr_weight > 0:
                mr_signal = check_mr_signal(ind, params)
                if mr_signal:
                    mr_signal['pair'] = pair
                    mr_signal['weight'] = mr_weight * size_mult
                    mr_signal['regime'] = regime_name
                    mr_signal['regime_mult'] = size_mult
                    signals.append(mr_signal)
            
            # H3 signals (only for eligible pairs)
            if h3_weight > 0:
                if pair in H3A_PAIRS:
                    h3a = check_h3a_signal(ind)
                    if h3a:
                        h3a['pair'] = pair
                        h3a['weight'] = h3_weight * 0.5 * size_mult
                        h3a['regime'] = regime_name
                        h3a['regime_mult'] = size_mult
                        signals.append(h3a)
                
                if pair in H3B_PAIRS:
                    h3b = check_h3b_signal(ind)
                    if h3b:
                        h3b['pair'] = pair
                        h3b['weight'] = h3_weight * 0.5 * size_mult
                        h3b['regime'] = regime_name
                        h3b['regime_mult'] = size_mult
                        signals.append(h3b)
        
        except Exception as e:
            print(f"Error scanning {pair}: {e}")
            continue
    
    return signals


if __name__ == '__main__':
    from src.trading.regime import get_current_regime
    
    regime = get_current_regime()
    
    print("=" * 70)
    print("SIGNAL SCANNER")
    print("=" * 70)
    print(f"\nCurrent Regime: {regime['regime']}")
    print(f"MR Weight: {regime['weights']['mr']*100:.0f}%")
    print(f"H3 Weight: {regime['weights']['h3']*100:.0f}%")
    
    signals = scan_all_pairs(
        mr_weight=regime['weights']['mr'],
        h3_weight=regime['weights']['h3']
    )
    
    if not signals:
        print("\nNo signals detected.")
    else:
        print(f"\n{len(signals)} SIGNALS DETECTED:")
        print("-" * 70)
        for s in signals:
            print(f"\n{s['strategy']:5} | {s['pair']:5} | Entry Bar: {s['entry_bar']} | Confidence: {s['confidence']:.2f}")
            if s['strategy'] == 'MR':
                print(f"       RSI={s['rsi']:.1f}, BB_pos={s['bb_position']:.2f}σ, Vol={s['vol_ratio']:.1f}x")
                print(f"       Stop={s['stop_pct']*100:.2f}%, Target={s['target_pct']*100:.1f}%")
            elif s['strategy'] == 'H3-A':
                print(f"       TK={s['tk_cross']}, Cloud={s['above_cloud']}, RSI={s['rsi']:.1f}")
            elif s['strategy'] == 'H3-B':
                print(f"       Vol={s['vol_ratio']:.1f}x, Gain={s['price_gain']:.2f}%, RSI={s['rsi']:.1f}")
