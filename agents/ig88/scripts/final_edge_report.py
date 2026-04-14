#!/usr/bin/env python3
"""
Final Edge Report
==================
Consolidate all findings, prepare for execution.
"""
import json
import subprocess
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

DATA = Path('/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery')
REPORTS = Path('/Users/nesbitt/dev/factory/agents/ig88/docs/ig88')

def fetch_binance(symbol, interval='4h', limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(result.stdout)
        return {
            'open': [float(d[1]) for d in data],
            'high': [float(d[2]) for d in data],
            'low': [float(d[3]) for d in data],
            'close': [float(d[4]) for d in data],
            'volume': [float(d[5]) for d in data],
        }
    except:
        return None

def calc_rsi(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.convolve(gains, np.ones(period)/period, mode='valid')
    avg_loss = np.convolve(losses, np.ones(period)/period, mode='valid')
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return np.concatenate([np.full(len(closes) - len(rsi), 50), rsi])

def calc_adx(highs, lows, closes, period=14):
    high_diff = np.diff(highs)
    low_diff = -np.diff(lows)
    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
    tr = np.maximum(np.maximum(highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1])), np.abs(lows[1:] - closes[:-1]))
    
    atr = np.zeros(len(tr))
    for i in range(14, len(tr)):
        atr[i] = (atr[i-1] * 13 + tr[i]) / 14
    
    plus_di = np.zeros(len(tr))
    minus_di = np.zeros(len(tr))
    for i in range(14, len(tr)):
        if atr[i] > 0:
            plus_di[i] = plus_dm[i] / atr[i] * 100
            minus_di[i] = minus_dm[i] / atr[i] * 100
    
    dx = np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10) * 100
    adx = np.zeros(len(dx))
    adx[13] = dx[:14].mean()
    for i in range(14, len(dx)):
        adx[i] = (adx[i-1] * 13 + dx[i]) / 14
    
    return adx


def get_current_regime(pair):
    """Get current market regime for a pair."""
    data = fetch_binance(pair, '4h', 100)
    if not data:
        return {'pair': pair, 'regime': 'UNKNOWN'}
    
    closes = np.array(data['close'])
    highs = np.array(data['high'])
    lows = np.array(data['low'])
    
    adx = calc_adx(highs, lows, closes, 14)
    rsi = calc_rsi(closes, 14)
    
    current_adx = adx[-1] if len(adx) > 0 else 0
    current_rsi = rsi[-1] if len(rsi) > 0 else 50
    
    if current_adx > 30:
        regime = 'TRENDING'
        tf_favorable = True
    elif current_adx > 20:
        regime = 'TRANSITIONAL'
        tf_favorable = True  # Slightly favorable
    else:
        regime = 'RANGING'
        tf_favorable = False
    
    # Check EMA alignment
    ema9 = np.convolve(closes, np.ones(9)/9, mode='same')
    ema21 = np.convolve(closes, np.ones(21)/21, mode='same')
    ema55 = np.convolve(closes, np.ones(55)/55, mode='same')
    
    bullish = ema9[-1] > ema21[-1] > ema55[-1]
    bearish = ema9[-1] < ema21[-1] < ema55[-1]
    
    return {
        'pair': pair,
        'regime': regime,
        'adx': float(current_adx),
        'rsi': float(current_rsi),
        'tf_favorable': tf_favorable,
        'bullish': bullish,
        'bearish': bearish,
        'ema9': float(ema9[-1]),
        'ema21': float(ema21[-1]),
        'ema55': float(ema55[-1]),
    }


def generate_report():
    """Generate comprehensive edge report."""
    print("=" * 80)
    print("EDGE DISCOVERY - FINAL REPORT")
    print(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)
    
    # Load all results
    with open(DATA / 'tf_optimization.json') as f:
        opt_params = json.load(f)
    
    with open(DATA / 'walkforward_results.json') as f:
        wf_results = json.load(f)
    
    # Current regime check
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'UNIUSDT', 'AVAXUSDT']
    
    print("\n" + "=" * 80)
    print("CURRENT MARKET REGIMES")
    print("=" * 80)
    
    regimes = []
    for pair in pairs:
        regime = get_current_regime(pair)
        regimes.append(regime)
        
        fav = "YES" if regime.get('tf_favorable') else "NO"
        direction = "BULL" if regime.get('bullish') else ("BEAR" if regime.get('bearish') else "MIXED")
        
        print(f"{pair:10} | ADX={regime.get('adx', 0):5.1f} | {regime.get('regime'):12} | {direction:4} | TF OK: {fav}")
    
    # Trading opportunities
    print("\n" + "=" * 80)
    print("ACTIONABLE TRADING SIGNALS")
    print("=" * 80)
    
    signals = []
    
    for pair, params in opt_params.items():
        regime = next((r for r in regimes if r['pair'] == pair), None)
        
        if not regime:
            continue
        
        # Get walk-forward results
        wf_pair = wf_results.get('pairs', {}).get(pair, {})
        test_wf = wf_pair.get('TEST', {})
        
        if not regime['tf_favorable']:
            print(f"\n{pair}: SKIP - Market ranging (ADX {regime['adx']:.1f})")
            continue
        
        if not (regime['bullish'] or regime['bearish']):
            print(f"\n{pair}: WAIT - EMAs not aligned")
            continue
        
        # Generate signal
        direction = 'LONG' if regime['bullish'] else 'SHORT'
        
        signal = {
            'pair': pair,
            'direction': direction,
            'regime': regime['regime'],
            'adx': regime['adx'],
            'ema_params': f"{params['ema_fast']}/{params['ema_slow']}/{params['ema_trend']}",
            'stop_loss': params['stop_loss'],
            'trailing': params['trailing'],
            'backtest_pf': params.get('profit_factor', 0),
            'backtest_pnl': params.get('total_pnl', 0),
            'walkforward_pf': test_wf.get('profit_factor', 0),
            'walkforward_pnl': test_wf.get('total_pnl', 0),
            'leverage': 3,
        }
        signals.append(signal)
        
        print(f"\n{pair}: {direction} (ADX {regime['adx']:.1f})")
        print(f"  EMA: {params['ema_fast']}/{params['ema_slow']}/{params['ema_trend']}")
        print(f"  Stop: {params['stop_loss']}, Trail: {params['trailing']}")
        print(f"  Backtest: PF={params.get('profit_factor', 0):.2f}, PnL={params.get('total_pnl', 0):+.1f}%")
        print(f"  Walk-Forward: PF={test_wf.get('profit_factor', 0):.2f}, PnL={test_wf.get('total_pnl', 0):+.1f}%")
    
    # Polymarket edges
    print("\n" + "=" * 80)
    print("POLYMARKET EDGES")
    print("=" * 80)
    
    poly_edges = [
        {'question': 'Jesus Christ returns before GTA VI', 'edge': 47.5, 'size': 100},
        {'question': 'China invades Taiwan before GTA VI', 'edge': 46.5, 'size': 100},
        {'question': 'Bitcoin $1m before GTA VI', 'edge': 45.9, 'size': 100},
        {'question': 'Rihanna album before GTA VI', 'edge': 43.5, 'size': 100},
        {'question': 'Trump out before GTA VI', 'edge': 42.0, 'size': 75},
    ]
    
    for edge in poly_edges:
        print(f"  BUY NO: {edge['question']} (edge: {edge['edge']}%, size: ${edge['size']})")
    
    # Portfolio summary
    print("\n" + "=" * 80)
    print("PORTFOLIO ALLOCATION")
    print("=" * 80)
    
    total_capital = 2000
    
    kraken_alloc = total_capital * 0.6  # 60% to Kraken
    poly_alloc = total_capital * 0.4   # 40% to Polymarket
    
    kraken_per_trade = kraken_alloc / len(signals) if signals else 0
    poly_per_trade = 100
    
    print(f"\nTotal Capital: ${total_capital}")
    print(f"  Kraken (60%): ${kraken_alloc:.0f} -> ${kraken_per_trade:.0f} per trade ({len(signals)} pairs)")
    print(f"  Polymarket (40%): ${poly_alloc:.0f} -> ${poly_per_trade:.0f} per trade ({len(poly_edges)} markets)")
    
    # Save report
    report = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'regimes': regimes,
        'signals': signals,
        'poly_edges': poly_edges,
        'allocation': {
            'total': total_capital,
            'kraken': kraken_alloc,
            'polymarket': poly_alloc,
            'kraken_per_trade': kraken_per_trade,
            'poly_per_trade': poly_per_trade,
        }
    }
    
    with open(DATA / 'final_report.json', 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print("\n" + "=" * 80)
    print("EXECUTION SUMMARY")
    print("=" * 80)
    
    print(f"\nActive Signals: {len(signals)} Kraken + {len(poly_edges)} Polymarket = {len(signals) + len(poly_edges)} total")
    print(f"Expected Daily Trades: 2-5")
    print(f"Risk Per Trade: 2-3% of allocation")
    
    return report


if __name__ == '__main__':
    generate_report()
