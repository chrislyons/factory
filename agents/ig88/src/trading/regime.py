"""
Regime Detection Module
=======================
Determines current market regime based on:
1. BTC 20-bar return (primary)
2. BTC price vs 200-SMA (macro filter)
3. 30-day realized volatility (volatility filter)

Regimes: RISK_OFF, BEARISH, RANGING, BULLISH, EUPHORIA
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
STATE_FILE = Path('/Users/nesbitt/dev/factory/agents/ig88/data/regime_state.json')


def load_btc_data():
    """Load BTC 4h OHLCV data."""
    path = DATA_DIR / 'binance_BTC_USDT_240m.parquet'
    if not path.exists():
        raise FileNotFoundError(f"BTC data not found: {path}")
    return pd.read_parquet(path)


def compute_btc_20bar_return(df):
    """BTC 20-bar (80-hour) return."""
    return df['close'].pct_change(20).iloc[-1]


def compute_btc_price_vs_200sma(df):
    """BTC price relative to 200-period SMA."""
    sma200 = df['close'].rolling(200).mean().iloc[-1]
    current = df['close'].iloc[-1]
    return current, sma200, current > sma200


def compute_realized_volatility(df, lookback=180):
    """30-day (180 bars of 4h) realized volatility (annualized)."""
    returns = df['close'].pct_change()
    vol = returns.rolling(lookback).std().iloc[-1]
    # Annualize (6 periods per day * 365 days)
    return vol * np.sqrt(6 * 365)


def determine_regime(btc_20bar_return, price_above_200sma, realized_vol):
    """
    Determine market regime based on multiple signals.
    
    Returns:
        tuple: (regime_name, regime_weights, metadata)
    """
    # Primary regime from BTC 20-bar return
    # KEY INSIGHT: MR works in ALL regimes except extreme crash
    # MR needs VOLATILITY (oversold conditions) — BEARISH is good for MR
    # H3 needs TREND — only BULLISH/EUPHORIA are good for H3
    
    if btc_20bar_return < -0.10:
        primary = 'CRASH'
        mr_weight, h3_weight = 0.0, 0.0  # Even MR fails in crash
    elif btc_20bar_return < -0.03:
        primary = 'BEARISH'
        mr_weight, h3_weight = 0.9, 0.1  # MR excels here (oversold bounces)
    elif btc_20bar_return < 0.03:
        primary = 'RANGING'
        mr_weight, h3_weight = 0.9, 0.1  # MR is king in ranging
    elif btc_20bar_return < 0.08:
        primary = 'BULLISH'
        mr_weight, h3_weight = 0.6, 0.4  # Both work, slight MR bias
    else:
        primary = 'EUPHORIA'
        mr_weight, h3_weight = 0.3, 0.7  # H3 dominates in strong trends
    
    # Macro adjustment: price below 200-SMA
    macro_adjustment = 1.0
    if not price_above_200sma:
        macro_adjustment = 0.75  # Reduce weights by 25%
        primary += '_BELOW_SMA'
    
    # Volatility adjustment: high volatility
    vol_adjustment = 1.0
    if realized_vol > 0.04:  # >4% daily vol annualized
        vol_adjustment = 0.75  # Reduce weights by 25%
        primary += '_HIGH_VOL'
    
    # Apply adjustments
    mr_weight *= macro_adjustment * vol_adjustment
    h3_weight *= macro_adjustment * vol_adjustment
    
    # Total allocation (may be < 1.0 due to adjustments)
    total = mr_weight + h3_weight
    if total > 0:
        cash_weight = 1.0 - total
    else:
        cash_weight = 1.0
    
    metadata = {
        'btc_20bar_return': float(btc_20bar_return),
        'price_above_200sma': bool(price_above_200sma),
        'realized_vol_30d': float(realized_vol),
        'macro_adjustment': macro_adjustment,
        'vol_adjustment': vol_adjustment,
        'primary_regime': primary.split('_')[0],  # Base regime without suffixes
    }
    
    weights = {
        'mr': mr_weight,
        'h3': h3_weight,
        'cash': cash_weight,
    }
    
    return primary, weights, metadata


def get_current_regime():
    """Get current market regime with all details."""
    df = load_btc_data()
    
    btc_20bar = compute_btc_20bar_return(df)
    price, sma200, above_sma = compute_btc_price_vs_200sma(df)
    realized_vol = compute_realized_volatility(df)
    
    regime, weights, metadata = determine_regime(btc_20bar, above_sma, realized_vol)
    
    return {
        'regime': regime,
        'weights': weights,
        'metadata': metadata,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'btc_price': float(df['close'].iloc[-1]),
        'btc_sma200': float(sma200),
    }


def save_state(state):
    """Save regime state to disk."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def load_state():
    """Load saved regime state."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return None


def check_regime_transition(old_state, new_state):
    """Check if regime has changed and return transition details."""
    if old_state is None:
        return True, 'INIT', new_state['regime']
    
    old_regime = old_state['regime'].split('_')[0]  # Base regime
    new_regime = new_state['regime'].split('_')[0]
    
    if old_regime != new_regime:
        return True, old_regime, new_regime
    
    return False, old_regime, new_regime


if __name__ == '__main__':
    # Direct execution: print current regime
    state = get_current_regime()
    save_state(state)
    
    print("=" * 60)
    print("CURRENT MARKET REGIME")
    print("=" * 60)
    print(f"\nRegime: {state['regime']}")
    print(f"\nBTC Price: ${state['btc_price']:,.0f}")
    print(f"BTC 200-SMA: ${state['btc_sma200']:,.0f}")
    print(f"BTC 20-bar Return: {state['metadata']['btc_20bar_return']*100:.2f}%")
    print(f"30-day Realized Vol: {state['metadata']['realized_vol_30d']*100:.1f}%")
    print(f"Price > 200-SMA: {state['metadata']['price_above_200sma']}")
    
    print(f"\nAllocation Weights:")
    print(f"  MR (Mean Reversion): {state['weights']['mr']*100:.0f}%")
    print(f"  H3 (Trend):          {state['weights']['h3']*100:.0f}%")
    print(f"  Cash:                {state['weights']['cash']*100:.0f}%")
    
    print(f"\nMacro Adjustment: {state['metadata']['macro_adjustment']*100:.0f}%")
    print(f"Vol Adjustment:   {state['metadata']['vol_adjustment']*100:.0f}%")
