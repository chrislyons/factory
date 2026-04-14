#!/usr/bin/env python3
"""
Walk-Forward Validation for Trend Following
=============================================
Validate the optimized TF parameters don't overfit.
"""
import json
import subprocess
import numpy as np
from pathlib import Path

DATA = Path('/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery')

def fetch_binance(symbol, interval='4h', limit=1500):
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


def run_walkforward(pair, params, data, window_bars=500):
    """
    Walk-forward: optimize on first window, test on second.
    """
    closes = np.array(data['close'])
    highs = np.array(data['high'])
    lows = np.array(data['low'])
    
    total = len(closes)
    if total < window_bars * 2:
        return None
    
    # Split: first half for training, second half for testing
    train_end = total // 2
    test_start = train_end
    
    results = {}
    
    for period_name, start, end in [('TRAIN', 0, train_end), ('TEST', test_start, total)]:
        c = closes[start:end]
        h = highs[start:end]
        l = lows[start:end]
        
        # Calculate indicators
        ema_f = np.convolve(c, np.ones(params['ema_fast'])/params['ema_fast'], mode='same')
        ema_s = np.convolve(c, np.ones(params['ema_slow'])/params['ema_slow'], mode='same')
        ema_t = np.convolve(c, np.ones(params['ema_trend'])/params['ema_trend'], mode='same')
        rsi = calc_rsi(c, 14)
        adx = calc_adx(h, l, c, 14)
        
        trades = []
        position = None
        
        min_len = min(len(c), len(adx))
        for i in range(150, min_len):
            is_trending = adx[i] > params['adx_threshold'] if i < len(adx) else False
            ema_bull = ema_f[i] > ema_s[i] > ema_t[i]
            
            if position is None:
                if is_trending and ema_bull and ema_f[i-1] <= ema_s[i-1]:
                    position = {
                        'entry': c[i],
                        'stop': c[i] * params['stop_loss'],
                        'trailing': c[i] * params['trailing'],
                    }
            
            elif position is not None:
                new_trailing = h[i] * params['trailing']
                position['trailing'] = max(position['trailing'], new_trailing)
                
                exit_price = None
                
                if l[i] <= max(position['stop'], position['trailing']):
                    exit_price = max(position['stop'], position['trailing'])
                elif ema_f[i] < ema_s[i]:
                    exit_price = c[i]
                elif rsi[i] > params.get('rsi_exit', 70):
                    exit_price = c[i]
                
                if exit_price:
                    pnl = (exit_price / position['entry'] - 1) * 100
                    trades.append(pnl)
                    position = None
        
        if trades:
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            
            results[period_name] = {
                'trades': len(trades),
                'win_rate': len(wins) / len(trades),
                'total_pnl': sum(trades),
                'profit_factor': abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 999,
                'avg_win': np.mean(wins) if wins else 0,
                'avg_loss': np.mean(losses) if losses else 0,
            }
    
    return results


def run_validation():
    """Run walk-forward validation on optimized parameters."""
    print("=" * 80)
    print("WALK-FORWARD VALIDATION")
    print("=" * 80)
    
    # Load optimized parameters
    with open(DATA / 'tf_optimization.json') as f:
        opt_params = json.load(f)
    
    # Test on extended data
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'UNIUSDT', 'AVAXUSDT']
    
    all_results = {}
    
    for pair in pairs:
        if pair not in opt_params:
            continue
        
        print(f"\n{pair}...")
        data = fetch_binance(pair, '4h', 1500)
        
        if not data:
            print("  No data")
            continue
        
        results = run_walkforward(pair, opt_params[pair], data)
        
        if results:
            all_results[pair] = results
            
            for period in ['TRAIN', 'TEST']:
                if period in results:
                    r = results[period]
                    print(f"  {period:5}: {r['trades']:3} trades, WR={r['win_rate']:.0%}, PF={r['profit_factor']:.2f}, PnL={r['total_pnl']:+.1f}%")
    
    # Summary
    print("\n" + "=" * 80)
    print("WALK-FORWARD SUMMARY")
    print("=" * 80)
    
    test_results = []
    
    for pair, results in all_results.items():
        if 'TEST' in results:
            test_r = results['TEST']
            train_r = results.get('TRAIN', {})
            
            test_results.append({
                'pair': pair,
                'test_pf': test_r['profit_factor'],
                'test_pnl': test_r['total_pnl'],
                'test_wr': test_r['win_rate'],
                'test_trades': test_r['trades'],
                'train_pf': train_r.get('profit_factor', 0),
                'train_pnl': train_r.get('total_pnl', 0),
            })
    
    print(f"\n{'Pair':8} {'Train PF':8} {'Test PF':8} {'Test PnL':9} {'Test WR':8} {'Trades':6}")
    print("-" * 55)
    
    for r in test_results:
        print(f"{r['pair']:8} {r['train_pf']:8.2f} {r['test_pf']:8.2f} {r['test_pnl']:+8.1f}% {r['test_wr']:7.0%} {r['test_trades']:6}")
    
    # Aggregate
    if test_results:
        avg_test_pf = np.mean([r['test_pf'] for r in test_results if r['test_pf'] < 999])
        avg_test_pnl = np.mean([r['test_pnl'] for r in test_results])
        total_trades = sum(r['test_trades'] for r in test_results)
        
        print(f"\nAggregate:")
        print(f"  Avg Test PF: {avg_test_pf:.2f}")
        print(f"  Avg Test PnL: {avg_test_pnl:+.1f}%")
        print(f"  Total Test Trades: {total_trades}")
    
    # Save
    with open(DATA / 'walkforward_results.json', 'w') as f:
        json.dump({'pairs': all_results, 'summary': test_results}, f, indent=2, default=str)
    
    return all_results


if __name__ == '__main__':
    run_validation()
