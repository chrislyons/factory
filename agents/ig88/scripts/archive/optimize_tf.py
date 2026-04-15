#!/usr/bin/env python3
"""
Optimize Trend Following Parameters
=====================================
Find the best parameters for TF strategy.
"""
import json
import subprocess
import numpy as np
from pathlib import Path
from itertools import product

DATA = Path('/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery')

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


def test_tf_params(pair, params, data=None):
    """Test TF with specific parameters."""
    if data is None:
        data = fetch_binance(pair, '4h', 1000)
    if not data or len(data['close']) < 200:
        return None
    
    closes = np.array(data['close'])
    highs = np.array(data['high'])
    lows = np.array(data['low'])
    
    # Parameters
    ema_fast = params.get('ema_fast', 9)
    ema_slow = params.get('ema_slow', 21)
    ema_trend = params.get('ema_trend', 55)
    rsi_period = params.get('rsi_period', 14)
    rsi_entry = params.get('rsi_entry', 50)
    rsi_exit = params.get('rsi_exit', 70)
    adx_threshold = params.get('adx_threshold', 25)
    stop_loss = params.get('stop_loss', 0.97)
    trailing = params.get('trailing', 0.97)
    leverage = params.get('leverage', 1)
    
    # Calculate EMAs
    ema_f = np.convolve(closes, np.ones(ema_fast)/ema_fast, mode='same')
    ema_s = np.convolve(closes, np.ones(ema_slow)/ema_slow, mode='same')
    ema_t = np.convolve(closes, np.ones(ema_trend)/ema_trend, mode='same')
    
    rsi = calc_rsi(closes, rsi_period)
    adx = calc_adx(highs, lows, closes, 14)
    
    trades = []
    position = None
    
    min_len = min(len(closes), len(adx))
    
    for i in range(150, min_len):
        is_trending = adx[i] > adx_threshold
        ema_bull = ema_f[i] > ema_s[i] > ema_t[i]
        
        if position is None:
            if is_trending and ema_bull and ema_f[i-1] <= ema_s[i-1]:
                position = {
                    'entry': closes[i],
                    'stop': closes[i] * stop_loss,
                    'trailing': closes[i] * trailing,
                }
        
        elif position is not None:
            new_trailing = highs[i] * trailing
            position['trailing'] = max(position['trailing'], new_trailing)
            
            exit_price = None
            
            if lows[i] <= max(position['stop'], position['trailing']):
                exit_price = max(position['stop'], position['trailing'])
            elif ema_f[i] < ema_s[i]:
                exit_price = closes[i]
            elif rsi[i] > rsi_exit:
                exit_price = closes[i]
            
            if exit_price:
                pnl = (exit_price / position['entry'] - 1) * 100 * leverage
                trades.append(pnl)
                position = None
    
    if len(trades) < 5:
        return None
    
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    
    return {
        'trades': len(trades),
        'win_rate': len(wins) / len(trades) if trades else 0,
        'total_pnl': sum(trades),
        'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 999,
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
    }


def grid_search(pair):
    """Grid search for optimal TF parameters."""
    print(f"\nGrid search for {pair}...")
    
    data = fetch_binance(pair, '4h', 1000)
    
    # Parameter grid
    param_grid = {
        'ema_fast': [8, 9, 12],
        'ema_slow': [21, 26, 34],
        'ema_trend': [55, 89],
        'adx_threshold': [20, 25, 30],
        'stop_loss': [0.96, 0.97, 0.98],
        'trailing': [0.96, 0.97, 0.98],
        'rsi_exit': [70, 75, 80],
    }
    
    best = None
    best_pnl = -999
    tested = 0
    
    # Generate combinations (limited to avoid explosion)
    combos = []
    for ef in param_grid['ema_fast']:
        for es in param_grid['ema_slow']:
            for et in param_grid['ema_trend']:
                if ef < es < et:
                    for adx_t in param_grid['adx_threshold']:
                        for sl in param_grid['stop_loss']:
                            for tr in param_grid['trailing']:
                                if sl <= tr:  # Trailing should be >= stop
                                    combos.append({
                                        'ema_fast': ef,
                                        'ema_slow': es,
                                        'ema_trend': et,
                                        'adx_threshold': adx_t,
                                        'stop_loss': sl,
                                        'trailing': tr,
                                        'rsi_exit': 70,
                                    })
    
    print(f"  Testing {len(combos)} parameter combinations...")
    
    for params in combos[:200]:  # Limit to 200
        result = test_tf_params(pair, params, data)
        tested += 1
        
        if result and result['total_pnl'] > best_pnl and result['profit_factor'] > 1.2:
            best_pnl = result['total_pnl']
            best = {**params, **result}
    
    if best:
        print(f"  Best: PnL={best['total_pnl']:+.1f}%, PF={best['profit_factor']:.2f}, WR={best['win_rate']:.0%}")
        print(f"  Params: EMA={best['ema_fast']}/{best['ema_slow']}/{best['ema_trend']}, ADX>{best['adx_threshold']}, SL={best['stop_loss']}, Tr={best['trailing']}")
    
    return best


def run_optimization():
    """Optimize TF for all pairs."""
    print("=" * 80)
    print("TREND FOLLOWING PARAMETER OPTIMIZATION")
    print("=" * 80)
    
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'UNIUSDT', 'AVAXUSDT']
    
    all_best = {}
    
    for pair in pairs:
        best = grid_search(pair)
        if best:
            all_best[pair] = best
    
    # Summary
    print("\n" + "=" * 80)
    print("OPTIMIZATION RESULTS")
    print("=" * 80)
    
    for pair, params in all_best.items():
        print(f"\n{pair}:")
        print(f"  PnL: {params['total_pnl']:+.1f}%")
        print(f"  PF: {params['profit_factor']:.2f}")
        print(f"  WR: {params['win_rate']:.0%}")
        print(f"  Trades: {params['trades']}")
        print(f"  EMA: {params['ema_fast']}/{params['ema_slow']}/{params['ema_trend']}")
        print(f"  ADX: {params['adx_threshold']}")
        print(f"  Stop: {params['stop_loss']}, Trail: {params['trailing']}")
    
    # Save
    with open(DATA / 'tf_optimization.json', 'w') as f:
        json.dump(all_best, f, indent=2, default=str)
    
    return all_best


if __name__ == '__main__':
    run_optimization()
