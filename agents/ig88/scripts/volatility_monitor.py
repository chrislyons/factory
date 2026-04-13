#!/usr/bin/env python3
"""Real-time volatility monitor for flash crash detection.

Monitors intrabar price action and triggers circuit breakers when:
- Single pair moves >X% in Y minutes (local crash detection)
- Multiple pairs moving in same direction >X% (correlated crash)
- Binance API errors (exchange-level issue)

Outputs a regime assessment that the position monitor can use to:
- Tighten stops during high volatility
- Pause new entries
- Close all positions in extreme scenarios
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import urllib.request

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
REGIME_STATE_PATH = DATA_DIR / 'current_regime.json'

# Circuit breaker thresholds
THRESHOLDS = {
    'panic_move_pct': 5.0,      # Single move >5% triggers WARNING
    'crash_move_pct': 8.0,      # Single move >8% triggers CRASH
    'correlated_move_pct': 3.0, # All pairs >3% same direction triggers CORRELATED
    'monitoring_window_sec': 900,  # 15 minutes
    'stop_tighten_factor': 0.5, # Tighten stops to 50% during WARNING
    'close_all_threshold': 12.0, # Close all positions if move >12%
}

# Pairs to monitor
MONITOR_PAIRS = ['SOLUSDT', 'AVAXUSDT', 'ETHUSDT', 'NEARUSDT', 'LINKUSDT', 'BTCUSDT']

def get_prices() -> dict:
    """Fetch current prices from Binance."""
    prices = {}
    for symbol in MONITOR_PAIRS:
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                prices[symbol] = float(data['price'])
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
    return prices

def get_recent_candles(symbol: str, intervals: str = '15m', limit: int = 4) -> list:
    """Fetch recent candles for volatility calculation."""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={intervals}&limit={limit}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  Error fetching candles for {symbol}: {e}")
        return []

def calculate_volatility(candles: list) -> dict:
    """Calculate volatility metrics from candles."""
    if len(candles) < 2:
        return {'pct_move': 0, 'high_low_pct': 0, 'volume_spike': False}
    
    # Candle format: [time, open, high, low, close, volume, ...]
    opens = [float(c[1]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]
    
    # Price move from first open to last close
    pct_move = ((closes[-1] - opens[0]) / opens[0]) * 100
    
    # High-low range across all candles
    period_high = max(highs)
    period_low = min(lows)
    high_low_pct = ((period_high - period_low) / period_low) * 100
    
    # Volume spike detection (current vs previous)
    avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    volume_spike = volumes[-1] > avg_vol * 2
    
    return {
        'pct_move': round(pct_move, 2),
        'high_low_pct': round(high_low_pct, 2),
        'volume_spike': volume_spike,
        'avg_volume': avg_vol,
        'current_volume': volumes[-1],
    }

def assess_regime() -> dict:
    """Assess current market regime based on real-time data."""
    prices = get_prices()
    
    if not prices:
        return {
            'state': 'UNKNOWN',
            'severity': 'ERROR',
            'message': 'Could not fetch prices',
            'triggers': [],
        }
    
    # Check each pair
    pair_data = {}
    triggers = []
    max_drop = 0
    max_rise = 0
    drops = 0
    rises = 0
    
    for symbol in MONITOR_PAIRS:
        candles = get_recent_candles(symbol, '15m', 4)  # Last hour
        vol = calculate_volatility(candles)
        pair_data[symbol] = vol
        
        pct = vol['pct_move']
        if pct < -max_drop:
            max_drop = abs(pct)
        if pct > max_rise:
            max_rise = pct
        
        if pct < -THRESHOLDS['panic_move_pct']:
            triggers.append(f"{symbol}: {pct:.1f}% DROP")
            drops += 1
        elif pct > THRESHOLDS['panic_move_pct']:
            triggers.append(f"{symbol}: +{pct:.1f}% RISE")
            rises += 1
    
    # Determine regime state
    if max_drop >= THRESHOLDS['close_all_threshold']:
        state = 'CRASH'
        severity = 'EXTREME'
        message = f"CRASH DETECTED: Max drop {max_drop:.1f}% - CLOSE ALL POSITIONS"
    elif max_drop >= THRESHOLDS['crash_move_pct']:
        state = 'CRASH'
        severity = 'HIGH'
        message = f"CRASH DETECTED: {max_drop:.1f}% drop - Tighten stops aggressively"
    elif drops >= 3:
        state = 'CORRELATED_CRASH'
        severity = 'HIGH'
        message = f"Correlated sell-off: {drops} pairs dropping >{THRESHOLDS['panic_move_pct']}%"
    elif max_drop >= THRESHOLDS['panic_move_pct']:
        state = 'WARNING'
        severity = 'MEDIUM'
        message = f"Volatility warning: {max_drop:.1f}% drop detected"
    elif max_rise >= THRESHOLDS['panic_move_pct'] * 1.5:
        state = 'PUMP_WARNING'
        severity = 'MEDIUM'
        message = f"Pump warning: {max_rise:.1f}% rise detected"
    elif rises >= 3:
        state = 'CORRELATED_PUMP'
        severity = 'MEDIUM'
        message = f"Correlated pump: {rises} pairs rising >{THRESHOLDS['panic_move_pct']}%"
    else:
        state = 'NORMAL'
        severity = 'LOW'
        message = "Market stable"
    
    return {
        'state': state,
        'severity': severity,
        'message': message,
        'triggers': triggers,
        'pair_data': pair_data,
        'max_drop': max_drop,
        'max_rise': max_rise,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

def save_regime(regime: dict):
    """Save current regime state for other scripts to read."""
    with open(REGIME_STATE_PATH, 'w') as f:
        json.dump(regime, f, indent=2)

def get_regime() -> Optional[dict]:
    """Read saved regime state."""
    if REGIME_STATE_PATH.exists():
        with open(REGIME_STATE_PATH) as f:
            return json.load(f)
    return None

def should_close_all(regime: dict) -> bool:
    """Check if we should close all positions immediately."""
    return regime['state'] in ('CRASH',) and regime['max_drop'] >= THRESHOLDS['close_all_threshold']

def should_tighten_stops(regime: dict) -> bool:
    """Check if we should tighten stops."""
    return regime['state'] in ('WARNING', 'CRASH', 'CORRELATED_CRASH')

def get_stop_adjustment(regime: dict) -> float:
    """Get stop adjustment factor (0.5 = tighten to 50%)."""
    if regime['state'] == 'CRASH':
        return 0.3  # Tighten to 30%
    elif regime['state'] == 'WARNING':
        return THRESHOLDS['stop_tighten_factor']
    return 1.0  # No adjustment

def main():
    print(f"=== Volatility Monitor {datetime.now(timezone.utc).strftime('%H:%M:%S')} ===")
    
    regime = assess_regime()
    save_regime(regime)
    
    print(f"State: {regime['state']} ({regime['severity']})")
    print(f"Message: {regime['message']}")
    
    if regime['triggers']:
        print("\nTriggers:")
        for t in regime['triggers']:
            print(f"  - {t}")
    
    print(f"\nMax Move: -{regime['max_drop']:.1f}% / +{regime['max_rise']:.1f}%")
    
    if should_close_all(regime):
        print("\n⚠️  CIRCUIT BREAKER: CLOSE ALL POSITIONS")
    elif should_tighten_stops(regime):
        adj = get_stop_adjustment(regime)
        print(f"\n⚠️  Tighten stops to {adj*100:.0f}% of original")

if __name__ == '__main__':
    main()
