#!/usr/bin/env python3
"""
Debug TF Backtest - Find the Bias
===================================
PF > 15 is impossible. Find what's wrong.
"""
import json
import subprocess
import numpy as np
from pathlib import Path

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

def calc_rsi_safe(closes, period=14):
    """RSI with NO look-ahead."""
    rsi = np.full(len(closes), 50.0)
    for i in range(period, len(closes)):
        gains = []
        losses = []
        for j in range(i - period + 1, i + 1):
            delta = closes[j] - closes[j-1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(-delta)
        
        avg_gain = np.mean(gains) if gains else 0
        avg_loss = np.mean(losses) if losses else 0.001
        rs = avg_gain / avg_loss
        rsi[i] = 100 - (100 / (1 + rs))
    return rsi

def calc_ema_safe(prices, period):
    """Standard EMA formula - no convolution look-ahead."""
    ema = np.full(len(prices), np.nan)
    ema[period-1] = np.mean(prices[:period])
    multiplier = 2 / (period + 1)
    for i in range(period, len(prices)):
        ema[i] = (prices[i] - ema[i-1]) * multiplier + ema[i-1]
    return ema

def calc_adx_safe(highs, lows, closes, period=14):
    """ADX with no look-ahead."""
    n = len(closes)
    adx = np.full(n, np.nan)
    
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    
    for i in range(1, n):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0
        
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i-1])
        lc = abs(lows[i] - closes[i-1])
        tr[i] = max(hl, hc, lc)
    
    # Wilder smoothing
    atr = np.zeros(n)
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    
    atr[period] = np.mean(tr[1:period+1])
    plus_dm_smooth = np.mean(plus_dm[1:period+1])
    minus_dm_smooth = np.mean(minus_dm[1:period+1])
    
    for i in range(period+1, n):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
        plus_dm_smooth = (plus_dm_smooth * (period-1) + plus_dm[i]) / period
        minus_dm_smooth = (minus_dm_smooth * (period-1) + minus_dm[i]) / period
        
        if atr[i] > 0:
            plus_di[i] = (plus_dm_smooth / atr[i]) * 100
            minus_di[i] = (minus_dm_smooth / atr[i]) * 100
    
    # DX and ADX
    for i in range(period*2, n):
        if plus_di[i] + minus_di[i] > 0:
            dx = abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i]) * 100
        else:
            dx = 0
        
        if np.isnan(adx[i-1]):
            adx[i] = dx
        else:
            adx[i] = (adx[i-1] * (period-1) + dx) / period
    
    return adx


def test_with_safe_indicators(pair, params):
    """Test using safe indicators with no look-ahead."""
    data = fetch_binance(pair, '4h', 1000)
    if not data or len(data['close']) < 200:
        return None
    
    closes = np.array(data['close'])
    highs = np.array(data['high'])
    lows = np.array(data['low'])
    
    # Safe indicators
    ema_f = calc_ema_safe(closes, params['ema_fast'])
    ema_s = calc_ema_safe(closes, params['ema_slow'])
    ema_t = calc_ema_safe(closes, params['ema_trend'])
    rsi = calc_rsi_safe(closes, 14)
    adx = calc_adx_safe(highs, lows, closes, 14)
    
    trades = []
    trades_detail = []
    position = None
    
    min_valid = params['ema_trend'] + 20  # Wait for all indicators
    
    for i in range(min_valid, len(closes)):
        # Skip if indicators not valid
        if np.isnan(ema_f[i]) or np.isnan(ema_s[i]) or np.isnan(ema_t[i]) or np.isnan(adx[i]):
            continue
        
        is_trending = adx[i] > params['adx_threshold']
        ema_bull = ema_f[i] > ema_s[i] > ema_t[i]
        
        if position is None:
            # Entry: EMA cross up
            if is_trending and ema_bull:
                if not np.isnan(ema_f[i-1]) and not np.isnan(ema_s[i-1]):
                    if ema_f[i-1] <= ema_s[i-1]:  # Crossover
                        position = {
                            'entry': closes[i],
                            'entry_idx': i,
                            'stop': closes[i] * params['stop_loss'],
                            'trailing': closes[i] * params['trailing'],
                        }
        
        elif position is not None:
            # Update trailing
            new_trailing = highs[i] * params['trailing']
            position['trailing'] = max(position['trailing'], new_trailing)
            
            exit_price = None
            exit_reason = None
            
            if lows[i] <= max(position['stop'], position['trailing']):
                exit_price = max(position['stop'], position['trailing'])
                exit_reason = 'STOP'
            elif not np.isnan(ema_f[i]) and not np.isnan(ema_s[i]) and ema_f[i] < ema_s[i]:
                exit_price = closes[i]
                exit_reason = 'EMA_CROSS'
            elif rsi[i] > params.get('rsi_exit', 70):
                exit_price = closes[i]
                exit_reason = 'RSI'
            
            if exit_price:
                pnl = (exit_price / position['entry'] - 1) * 100
                trades.append(pnl)
                trades_detail.append({
                    'entry_idx': position['entry_idx'],
                    'exit_idx': i,
                    'entry_price': position['entry'],
                    'exit_price': exit_price,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                })
                position = None
    
    if len(trades) < 3:
        return {'pair': pair, 'trades': 0, 'note': 'insufficient trades'}
    
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    
    return {
        'pair': pair,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) if trades else 0,
        'total_pnl': sum(trades),
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
        'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 0,
        'max_win': max(trades) if trades else 0,
        'max_loss': min(trades) if trades else 0,
        'trades_detail': trades_detail[-3:],  # Last 3 trades for inspection
    }


def run_debug():
    """Debug the TF strategy."""
    print("=" * 80)
    print("DEBUG: TREND FOLLOWING - LOOKING FOR BIAS")
    print("=" * 80)
    
    # Load optimized params
    with open('/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery/tf_optimization.json') as f:
        opt_params = json.load(f)
    
    pairs = ['BTCUSDT', 'ETHUSDT', 'UNIUSDT', 'LINKUSDT']
    
    for pair in pairs:
        if pair not in opt_params:
            continue
        
        params = opt_params[pair]
        print(f"\n{pair}:")
        print(f"  Params: EMA={params['ema_fast']}/{params['ema_slow']}/{params['ema_trend']}, ADX>{params['adx_threshold']}")
        print(f"  Claimed: PnL={params['total_pnl']:+.1f}%, PF={params['profit_factor']:.2f}, WR={params['win_rate']:.0%}")
        
        result = test_with_safe_indicators(pair, params)
        
        if result and 'total_pnl' in result:
            print(f"  Safe Test: PnL={result['total_pnl']:+.1f}%, PF={result['profit_factor']:.2f}, WR={result['win_rate']:.0%}, Trades={result['trades']}")
        elif result:
            print(f"  Safe Test: {result}")


if __name__ == '__main__':
    run_debug()
