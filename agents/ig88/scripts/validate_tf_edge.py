#!/usr/bin/env python3
"""
Validate Trend Following Edge
==============================
Deep dive on the TF signal that showed profit.
"""
import json
import subprocess
import numpy as np
from pathlib import Path

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
    plus_di = np.zeros(len(tr))
    minus_di = np.zeros(len(tr))
    
    atr[period-1] = tr[:period].mean()
    for i in range(period, len(tr)):
        atr[i] = (atr[i-1] * 13 + tr[i]) / 14
    
    for i in range(period-1, len(tr)):
        if atr[i] > 0:
            plus_di[i] = plus_dm[i] / atr[i] * 100
            minus_di[i] = minus_dm[i] / atr[i] * 100
    
    dx = np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10) * 100
    adx = np.zeros(len(dx))
    adx[period-1] = dx[:period].mean()
    for i in range(period, len(dx)):
        adx[i] = (adx[i-1] * 13 + dx[i]) / 14
    
    return adx


def deep_test_tf(pair, leverage=1):
    """Deep test trend following on one pair."""
    data = fetch_binance(pair, '4h', 1000)
    if not data:
        return None
    
    closes = np.array(data['close'])
    highs = np.array(data['high'])
    lows = np.array(data['low'])
    volumes = np.array(data['volume'])
    
    if len(closes) < 200:
        return None
    
    # Indicators
    rsi = calc_rsi(closes, 14)
    adx = calc_adx(highs, lows, closes, 14)
    
    ema9 = np.convolve(closes, np.ones(9)/9, mode='same')
    ema21 = np.convolve(closes, np.ones(21)/21, mode='same')
    ema55 = np.convolve(closes, np.ones(55)/55, mode='same')
    
    trades = []
    trades_detail = []
    position = None
    
    min_len = min(len(closes), len(adx), len(rsi))
    
    for i in range(100, min_len):
        is_trending = adx[i] > 25
        ema_alignment = ema9[i] > ema21[i] > ema55[i]  # Bullish
        
        if position is None:
            # Entry: EMA cross up + RSI > 50 + ADX > 25
            if is_trending and ema_alignment:
                if ema9[i-1] <= ema21[i-1]:  # Crossover just happened
                    position = {
                        'entry': closes[i],
                        'idx': i,
                        'stop': closes[i] * 0.97,
                        'trailing': closes[i] * 0.97,
                    }
        
        elif position is not None:
            # Update trailing stop (3% from high)
            new_trailing = highs[i] * 0.97
            position['trailing'] = max(position['trailing'], new_trailing)
            
            # Exit conditions
            exit_price = None
            exit_reason = None
            
            if lows[i] <= max(position['stop'], position['trailing']):
                exit_price = max(position['stop'], position['trailing'])
                exit_reason = 'STOP'
            elif ema9[i] < ema21[i]:  # EMA cross down
                exit_price = closes[i]
                exit_reason = 'EMA_CROSS'
            elif rsi[i] > 80:  # Overbought
                exit_price = closes[i]
                exit_reason = 'RSI_OVERBOUGHT'
            
            if exit_price:
                pnl = (exit_price / position['entry'] - 1) * 100 * leverage
                trades.append(pnl)
                trades_detail.append({
                    'entry_price': position['entry'],
                    'exit_price': exit_price,
                    'entry_idx': position['idx'],
                    'exit_idx': i,
                    'pnl': pnl,
                    'exit_reason': exit_reason,
                })
                position = None
    
    if not trades:
        return {'pair': pair, 'trades': 0}
    
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    
    return {
        'pair': pair,
        'leverage': leverage,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades),
        'avg_win': np.mean(wins) if wins else 0,
        'avg_loss': np.mean(losses) if losses else 0,
        'total_pnl': sum(trades),
        'max_drawdown': min(trades),
        'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else np.inf,
        'sharpe': np.mean(trades) / np.std(trades) if np.std(trades) > 0 else 0,
        'trades_detail': trades_detail[-5:],  # Last 5 trades
    }


def run_validation():
    """Run deep validation on trend following strategy."""
    print("=" * 80)
    print("TREND FOLLOWING EDGE VALIDATION")
    print("=" * 80)
    
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'LINKUSDT', 'NEARUSDT', 'UNIUSDT']
    
    all_results = []
    
    for pair in pairs:
        print(f"\nTesting {pair}...")
        
        # Test at 1x and 3x leverage
        for lev in [1, 3]:
            result = deep_test_tf(pair, leverage=lev)
            if result and result['trades'] >= 3:
                all_results.append(result)
                print(f"  {lev}x: {result['trades']} trades, WR={result['win_rate']:.0%}, PF={result['profit_factor']:.2f}, PnL={result['total_pnl']:+.1f}%")
    
    # Aggregate by leverage
    print("\n" + "=" * 80)
    print("AGGREGATE RESULTS")
    print("=" * 80)
    
    for lev in [1, 3]:
        lev_results = [r for r in all_results if r['leverage'] == lev]
        if lev_results:
            total_trades = sum(r['trades'] for r in lev_results)
            avg_wr = np.mean([r['win_rate'] for r in lev_results])
            total_pnl = sum(r['total_pnl'] for r in lev_results)
            avg_pf = np.mean([r['profit_factor'] for r in lev_results if r['profit_factor'] != np.inf])
            
            print(f"\n{lev}x Leverage ({len(lev_results)} pairs):")
            print(f"  Total trades: {total_trades}")
            print(f"  Avg win rate: {avg_wr:.1%}")
            print(f"  Avg profit factor: {avg_pf:.2f}")
            print(f"  Total PnL: {total_pnl:+.1f}%")
    
    # Save
    with open(DATA / 'tf_validation.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    
    return all_results


if __name__ == '__main__':
    run_validation()
