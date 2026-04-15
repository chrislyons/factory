"""
Production Scanner (7-pair MR portfolio)
==========================================
Validated pairs at 2% friction via walk-forward testing.
Strategy: Mean Reversion (RSI + BB + Volume) ONLY.

VALIDATED PAIRS:
- ARB: RSI<20, BB<2.0, Vol>1.8x (PF 3.8, Exp +3.2% OOS)
- AAVE: RSI<25, BB<2.0, Vol>1.3x (PF 4.1, Exp +5.5% OOS)
- INJ: RSI<30, BB<2.0, Vol>1.5x (PF 3.2, Exp +4.3% OOS)
- SUI: RSI<25, BB<2.0, Vol>1.5x (PF 2.8, Exp +3.8% OOS)
- AVAX: RSI<25, BB<2.0, Vol>1.5x (PF 2.1, Exp +2.0% OOS)
- LINK: RSI<30, BB<2.0, Vol>1.3x (PF 2.5, Exp +4.0% OOS)
- POL: RSI<25, BB<2.0, Vol>1.5x (PF 1.5, Exp +1.3% OOS)
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
STATE_FILE = Path('/Users/nesbitt/dev/factory/agents/ig88/data/production_state.json')
FRICTION = 0.02  # Design for 2% friction

# VALIDATED PAIRS (walk-forward optimized parameters)
PORTFOLIO = {
    'ARB': {'rsi_thresh': 20, 'bb_std': 2.0, 'vol_mult': 1.8, 'stop_atr': 0.75, 'target_atr': 3.0},
    'AAVE': {'rsi_thresh': 25, 'bb_std': 2.0, 'vol_mult': 1.3, 'stop_atr': 1.0, 'target_atr': 2.5},
    'INJ': {'rsi_thresh': 30, 'bb_std': 2.0, 'vol_mult': 1.5, 'stop_atr': 1.0, 'target_atr': 2.5},
    'SUI': {'rsi_thresh': 25, 'bb_std': 2.0, 'vol_mult': 1.5, 'stop_atr': 0.75, 'target_atr': 2.5},
    'AVAX': {'rsi_thresh': 25, 'bb_std': 2.0, 'vol_mult': 1.5, 'stop_atr': 1.0, 'target_atr': 2.0},
    'LINK': {'rsi_thresh': 30, 'bb_std': 2.0, 'vol_mult': 1.3, 'stop_atr': 1.0, 'target_atr': 2.5},
    'POL': {'rsi_thresh': 25, 'bb_std': 2.0, 'vol_mult': 1.5, 'stop_atr': 1.0, 'target_atr': 2.0},
}

# Regime-conditional trading
REGIME_ACTIONS = {
    'BULLISH': {'trade': True, 'size_mult': 1.0},
    'BEARISH': {'trade': True, 'size_mult': 0.7},
    'RANGING': {'trade': True, 'size_mult': 0.5},
    'RISK_OFF': {'trade': False, 'size_mult': 0.0},
}

# Pair-specific regime eligibility (from earlier analysis)
PAIR_REGIMES = {
    'SUI': ['BULLISH', 'BEARISH', 'RANGING'],  # Works everywhere
    'OP': ['BULLISH'],  # Only bull market
    'ARB': ['BULLISH', 'BEARISH'],  # High momentum, works in trends
    'AVAX': ['BULLISH', 'BEARISH'],
    'AAVE': ['BULLISH'],
    'LINK': ['BULLISH', 'BEARISH'],
    'INJ': ['BULLISH'],
    'POL': ['BULLISH'],
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
    """Compute RSI, BB, Volume for MR signals."""
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
    bb_mid = sma20
    
    # ATR for stops
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Volume
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, o, h, l, rsi, bb_lower, bb_mid, atr, vol_ratio


def check_signal(pair, params, c, o, h, l, rsi, bb_lower, atr, vol_ratio):
    """Check for MR signal on latest bar."""
    i = -1
    
    if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
        return None
    
    # Mean reversion entry: RSI oversold + Below BB lower + Volume surge
    if rsi[i] < params['rsi_thresh'] and c[i] < bb_lower[i] and vol_ratio[i] > params['vol_mult']:
        entry_price = c[i]
        stop_price = entry_price - atr[i] * params['stop_atr']
        target_price = entry_price + atr[i] * params['target_atr']
        
        return {
            'pair': pair,
            'type': 'MR',
            'entry': round(entry_price, 6),
            'stop': round(stop_price, 6),
            'target': round(target_price, 6),
            'stop_pct': round(atr[i] * params['stop_atr'] / entry_price * 100, 2),
            'target_pct': round(atr[i] * params['target_atr'] / entry_price * 100, 2),
            'rsi': round(rsi[i], 1),
            'bb_dist': round((bb_lower[i] - c[i]) / c[i] * 100, 2),
            'vol_ratio': round(vol_ratio[i], 2),
        }
    return None


def scan(regime=None):
    """
    Scan all validated pairs for MR signals.
    Returns list of signals with position sizing.
    """
    # Load BTC for regime
    btc_df = load_btc()
    if regime is None:
        regime = get_regime(btc_df)
    
    regime_config = REGIME_ACTIONS.get(regime, {'trade': False, 'size_mult': 0.0})
    
    if not regime_config['trade']:
        return [], regime
    
    signals = []
    
    for pair, params in PORTFOLIO.items():
        # Check pair-specific regime eligibility
        eligible_regimes = PAIR_REGIMES.get(pair, ['BULLISH'])
        if regime not in eligible_regimes:
            continue
        
        try:
            df = load_data(pair)
            c, o, h, l, rsi, bb_lower, bb_mid, atr, vol_ratio = compute_indicators(df)
            
            signal = check_signal(pair, params, c, o, h, l, rsi, bb_lower, atr, vol_ratio)
            if signal:
                signal['regime'] = regime
                signal['base_size'] = 5.0  # 5% base position
                signal['size'] = round(5.0 * regime_config['size_mult'], 1)
                signals.append(signal)
        
        except Exception as e:
            print(f"Error scanning {pair}: {e}")
            continue
    
    return signals, regime


def run_paper_cycle():
    """Run one paper trading cycle."""
    signals, regime = scan()
    
    # Load existing trades
    trades_file = DATA_DIR / 'paper_trades.jsonl'
    trades = []
    if trades_file.exists():
        trades = trades_file.read_text().strip().split('\n')
        trades = [json.loads(t) for t in trades if t]
    
    # Log signals
    for signal in signals:
        signal['timestamp'] = datetime.now(timezone.utc).isoformat()
        signal['status'] = 'SIGNAL'
        with open(trades_file, 'a') as f:
            f.write(json.dumps(signal) + '\n')
    
    return {
        'regime': regime,
        'signals': len(signals),
        'trades': signals,
    }


if __name__ == '__main__':
    print("=" * 80)
    print("PRODUCTION SCANNER (7-pair MR portfolio)")
    print(f"Design friction: {FRICTION*100:.0f}%")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)
    
    result = run_paper_cycle()
    
    print(f"\nRegime: {result['regime']}")
    
    if result['regime'] == 'RISK_OFF':
        print("RISK_OFF detected - no trading")
    else:
        regime_config = REGIME_ACTIONS[result['regime']]
        print(f"Position sizing: {regime_config['size_mult']*100:.0f}% of base")
    
    print(f"\nSignals found: {result['signals']}")
    
    if result['trades']:
        print(f"\n{'Pair':<8} {'Entry':<12} {'Stop':<12} {'Target':<12} {'Stop%':<8} {'Target%':<8} {'Size'}")
        print("-" * 70)
        for s in result['trades']:
            print(f"{s['pair']:<8} {s['entry']:<12.4f} {s['stop']:<12.4f} {s['target']:<12.4f} {s['stop_pct']:<8.2f} {s['target_pct']:<8.2f} {s['size']}%")
    
    # Show eligible pairs
    regime = result['regime']
    eligible = [p for p, regimes in PAIR_REGIMES.items() if regime in regimes]
    print(f"\nEligible pairs in {regime}: {', '.join(eligible)}")
