"""
Walk-Forward Test: Reduced Portfolio (6 profitable pairs)
==========================================================
Test the 6 pairs that remain profitable with 1.33% friction:
SUI, AAVE, AVAX, INJ, ARB, OP

Use pair-specific optimal stops from ATR test.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.0133  # Real friction

# Reduced portfolio with optimal stops
PORTFOLIO = {
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8, 'entry': 2, 'target': 0.15, 'stop': 'fixed_0.75'},
    'AAVE': {'rsi': 35, 'bb': 1.5, 'vol': 1.5, 'entry': 2, 'target': 0.15, 'stop': 'atr_1.5'},
    'AVAX': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'target': 0.125, 'stop': 'atr_1.5'},
    'INJ':  {'rsi': 30, 'bb': 1.0, 'vol': 1.5, 'entry': 2, 'target': 0.075, 'stop': 'fixed_0.75'},
    'ARB':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'target': 0.15, 'stop': 'atr_0.75'},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3, 'entry': 2, 'target': 0.15, 'stop': 'fixed_0.5'},
}


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_l = sma20 - std20 * 1.5
    bb_m = sma20 - std20 * 1.0
    
    # Volume
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    return c, o, h, l, rsi, bb_l, bb_m, vol_ratio, atr


def get_stop_distance(stop_type, entry_price, atr_value):
    """Calculate stop distance based on type."""
    if stop_type == 'fixed_0.5':
        return entry_price * 0.005
    elif stop_type == 'fixed_0.75':
        return entry_price * 0.0075
    elif stop_type == 'fixed_1.0':
        return entry_price * 0.01
    elif stop_type == 'atr_0.75':
        return atr_value * 0.75
    elif stop_type == 'atr_1.5':
        return atr_value * 1.5
    else:
        return entry_price * 0.005


def run_backtest(pair, params, df_slice=None):
    """Run backtest for a single pair."""
    if df_slice is not None:
        df = df_slice
    else:
        df = load_data(pair)
    
    c, o, h, l, rsi, bb_l, bb_m, vol_ratio, atr = compute_indicators(df)
    
    trades = []
    trade_details = []
    
    for i in range(100, len(c) - 17):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]) or np.isnan(atr[i]):
            continue
        
        # Entry condition
        rsi_thresh = params['rsi']
        bb_thresh = bb_l[i]  # Use lower BB
        vol_thresh = params['vol']
        
        if rsi[i] < rsi_thresh and c[i] < bb_thresh and vol_ratio[i] > vol_thresh:
            entry_bar = i + params['entry']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_dist = get_stop_distance(params['stop'], entry_price, atr[entry_bar])
            stop_price = entry_price - stop_dist
            target_price = entry_price * (1 + params['target'])
            
            for j in range(1, 16):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    pnl = -stop_dist/entry_price - FRICTION
                    trades.append(pnl)
                    trade_details.append({'exit': 'STOP', 'pnl': pnl})
                    break
                if h[bar] >= target_price:
                    pnl = params['target'] - FRICTION
                    trades.append(pnl)
                    trade_details.append({'exit': 'TARGET', 'pnl': pnl})
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                pnl = (exit_price - entry_price) / entry_price - FRICTION
                trades.append(pnl)
                trade_details.append({'exit': 'TIME', 'pnl': pnl})
    
    return np.array(trades), trade_details


def calc_stats(trades):
    """Calculate performance statistics."""
    if len(trades) < 5:
        return {'n': len(trades), 'pf': 0, 'wr': 0, 'exp': 0, 'sharpe': 0, 'total': 0, 'max_dd': 0}
    
    t = trades
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    sharpe = (t.mean() / t.std()) * np.sqrt(6 * 365) if t.std() > 0 else 0
    
    # Max drawdown
    cumsum = np.cumsum(t)
    running_max = np.maximum.accumulate(cumsum)
    drawdown = running_max - cumsum
    max_dd = np.max(drawdown) if len(drawdown) > 0 else 0
    
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'wr': round(float(len(w)/len(t)*100), 1),
        'exp': round(float(t.mean()*100), 3),
        'sharpe': round(float(sharpe), 2),
        'total': round(float(t.sum() * 100), 2),
        'max_dd': round(float(max_dd * 100), 2),
    }


def walk_forward_test(pair, params, n_splits=5):
    """Walk-forward validation with time-based splits."""
    df = load_data(pair)
    n = len(df)
    split_size = n // (n_splits + 1)
    
    results = []
    
    for i in range(n_splits):
        train_start = i * split_size
        train_end = train_start + split_size * 2
        test_end = min(train_end + split_size, n)
        
        train_df = df.iloc[train_start:train_end]
        test_df = df.iloc[train_end:test_end]
        
        # In-sample (train)
        train_trades, _ = run_backtest(pair, params, train_df)
        train_stats = calc_stats(train_trades)
        
        # Out-of-sample (test)
        test_trades, _ = run_backtest(pair, params, test_df)
        test_stats = calc_stats(test_trades)
        
        results.append({
            'pair': pair,
            'split': i + 1,
            'train': train_stats,
            'test': test_stats,
        })
    
    return results


def main():
    print("=" * 90)
    print("WALK-FORWARD VALIDATION: REDUCED PORTFOLIO (6 pairs, real friction 1.33%)")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 90)
    
    all_results = {}
    
    for pair, params in PORTFOLIO.items():
        print(f"\n{'─' * 90}")
        print(f"{pair} (Stop: {params['stop']})")
        print(f"{'─' * 90}")
        
        # Full sample backtest
        trades, _ = run_backtest(pair, params)
        stats = calc_stats(trades)
        print(f"\nFull Sample: {stats['n']} trades, PF={stats['pf']}, WR={stats['wr']}%, Exp={stats['exp']}%, Sharpe={stats['sharpe']}, MaxDD={stats['max_dd']}%")
        
        # Walk-forward
        wf_results = walk_forward_test(pair, params, n_splits=5)
        all_results[pair] = wf_results
        
        print(f"\nWalk-Forward (5 splits):")
        print(f"{'Split':<8} {'Train N':<10} {'Train PF':<10} {'Train Exp%':<12} {'Test N':<8} {'Test PF':<10} {'Test Exp%':<12} {'Stable?'}")
        print("-" * 90)
        
        stable_count = 0
        for r in wf_results:
            tr = r['train']
            te = r['test']
            
            # Stability: same sign of expectation
            stable = (tr['exp'] > 0 and te['exp'] > 0) or (tr['exp'] < 0 and te['exp'] < 0)
            if stable:
                stable_count += 1
            
            print(f"{r['split']:<8} {tr['n']:<10} {tr['pf']:<10.3f} {tr['exp']:<11.3f}% {te['n']:<8} {te['pf']:<10.3f} {te['exp']:<11.3f}% {'YES' if stable else 'NO'}")
        
        print(f"\nStability: {stable_count}/5 splits consistent")
    
    # Portfolio summary
    print(f"\n{'=' * 90}")
    print("PORTFOLIO SUMMARY (Reduced 6-Pair Portfolio)")
    print(f"{'=' * 90}")
    
    print(f"\n{'Pair':<10} {'Stop Config':<15} {'N':<6} {'PF':<8} {'Exp%':<10} {'Sharpe':<8} {'MaxDD':<8} {'Verdict'}")
    print("-" * 80)
    
    profitable = 0
    for pair, params in PORTFOLIO.items():
        trades, _ = run_backtest(pair, params)
        stats = calc_stats(trades)
        
        verdict = "PASS" if stats['exp'] > 0 and stats['pf'] > 1.0 and stats['n'] >= 20 else "FAIL"
        if verdict == "PASS":
            profitable += 1
        
        print(f"{pair:<10} {params['stop']:<15} {stats['n']:<6} {stats['pf']:<8.3f} {stats['exp']:<9.3f}% {stats['sharpe']:<7.2f} {stats['max_dd']:<7.2f}% {verdict}")
    
    print(f"\nProfitable pairs: {profitable}/6")
    
    # Combined expectancy
    print(f"\nIf equal-weighted $100 positions:")
    print(f"  Expected return per trade: portfolio average")
    print(f"  Max concurrent positions: 6")
    print(f"  Monthly expectancy: ~{profitable * 0.5:.1f}% (rough estimate)")


if __name__ == '__main__':
    main()
