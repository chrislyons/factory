import pandas as pd
import numpy as np
import json
from pathlib import Path

SYMBOLS = ['RNDR', 'WLD', 'SUI', 'FIL']
PARAM_COMBOS = [
    {'LB': 10, 'AM': 2.5, 'TP': 2.5, 'MH': 48},
    {'LB': 15, 'AM': 2.5, 'TP': 2.5, 'MH': 48},
    {'LB': 10, 'AM': 2.5, 'TP': 2.5, 'MH': 96},
]
WALK_FORWARD_PCTS = [50, 60, 70, 80]
FRICTION = 0.0014  # 0.14%
DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h')
OUTPUT_PATH = Path('/Users/nesbitt/dev/factory/agents/ig88/data/atr_short_new_assets.json')

def calc_true_range(df):
    """True Range: max(H-L, |H-C_prev|, |L-C_prev|)"""
    high = df['high'].values
    low = df['low'].values
    close_prev = df['close'].shift(1).values
    tr = np.maximum(high - low, np.maximum(np.abs(high - close_prev), np.abs(low - close_prev)))
    return pd.Series(tr, index=df.index)

def calc_atr(df, period):
    """Wilder's ATR using True Range"""
    tr = calc_true_range(df)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def run_backtest(df, params):
    lb = params['LB']
    am = params['AM']
    tp_pct = params['TP'] / 100.0
    mh = params['MH']
    
    df = df.copy()
    df['atr'] = calc_atr(df, lb)
    df['donchian_low'] = df['low'].rolling(lb).min()
    
    n = len(df)
    trades = []
    in_trade = False
    entry_price = 0.0
    entry_idx = 0
    stop_price = 0.0
    
    for i in range(lb + 1, n):
        if in_trade:
            # Check exit: close >= stop_price (short stop is above entry)
            if df['close'].iloc[i] >= stop_price:
                exit_price = stop_price * (1 + FRICTION)  # slippage on exit
                ret = (entry_price - exit_price) / entry_price - FRICTION  # entry friction already applied
                bars_held = i - entry_idx
                trades.append({
                    'entry_idx': entry_idx,
                    'exit_idx': i,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'return': ret,
                    'bars_held': bars_held,
                    'exit_reason': 'stop'
                })
                in_trade = False
            
            # Max hold exit
            elif (i - entry_idx) >= mh:
                exit_price = df['close'].iloc[i] * (1 + FRICTION)
                ret = (entry_price - exit_price) / entry_price - FRICTION
                bars_held = i - entry_idx
                trades.append({
                    'entry_idx': entry_idx,
                    'exit_idx': i,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'return': ret,
                    'bars_held': bars_held,
                    'exit_reason': 'max_hold'
                })
                in_trade = False
            
            # Trailing: tighten stop if price drops (for short, lower is better)
            # TP target: close <= entry * (1 - tp_pct) -> profitable short
            # No explicit TP exit, only stop and max_hold
            
            # Check if TP hit (close drops enough) - we trail stop down
            # Actually re-reading: exit on close >= stop_price. So stop trails down as price drops.
            current_low = df['low'].iloc[i]
            # Trail: new stop = current_low + am * atr(i)
            new_stop = current_low + am * df['atr'].iloc[i]
            if new_stop < stop_price:
                stop_price = new_stop
        
        else:
            # Check entry: close < donchian_low(i-1) - atr(i) * am
            entry_threshold = df['donchian_low'].iloc[i-1] - df['atr'].iloc[i] * am
            if df['close'].iloc[i] < entry_threshold:
                entry_price = df['close'].iloc[i] * (1 - FRICTION)  # short entry, slightly worse
                entry_idx = i
                stop_price = entry_price + am * df['atr'].iloc[i]
                in_trade = True
    
    # Close any open trade at end
    if in_trade:
        exit_price = df['close'].iloc[-1] * (1 + FRICTION)
        ret = (entry_price - exit_price) / entry_price - FRICTION
        bars_held = n - 1 - entry_idx
        trades.append({
            'entry_idx': entry_idx,
            'exit_idx': n - 1,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'return': ret,
            'bars_held': bars_held,
            'exit_reason': 'eod'
        })
    
    return trades

def compute_metrics(trades, total_bars):
    if not trades:
        return {
            'total_trades': 0, 'win_rate': 0, 'profit_factor': 0,
            'avg_return': 0, 'total_return': 0, 'max_drawdown': 0,
            'avg_bars_held': 0, 'expectancy': 0
        }
    
    returns = [t['return'] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    
    total_return = sum(returns)
    win_rate = len(wins) / len(returns) * 100
    
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Equity curve for max drawdown
    equity = [0]
    for r in returns:
        equity.append(equity[-1] + r)
    peak = equity[0]
    max_dd = 0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd
    
    avg_bars = np.mean([t['bars_held'] for t in trades])
    expectancy = np.mean(returns)
    
    return {
        'total_trades': len(trades),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(pf, 4),
        'avg_return': round(np.mean(returns) * 100, 4),
        'total_return': round(total_return * 100, 4),
        'max_drawdown': round(max_dd * 100, 4),
        'avg_bars_held': round(avg_bars, 2),
        'expectancy': round(expectancy * 100, 4)
    }

def walk_forward(df, params, train_pct):
    """Split data into train/test and run backtest on test portion"""
    split_idx = int(len(df) * train_pct / 100)
    test_df = df.iloc[split_idx:].reset_index(drop=True)
    
    if len(test_df) < params['LB'] + 10:
        return [], compute_metrics([], 0)
    
    trades = run_backtest(test_df, params)
    # Adjust trade indices to original df
    for t in trades:
        t['entry_idx'] += split_idx
        t['exit_idx'] += split_idx
    
    metrics = compute_metrics(trades, len(test_df))
    return trades, metrics

def main():
    results = {}
    
    for symbol in SYMBOLS:
        print(f"\n{'='*60}")
        print(f"Testing {symbol}")
        print(f"{'='*60}")
        
        data_path = DATA_DIR / f'binance_{symbol}USDT_60m.parquet'
        if not data_path.exists():
            print(f"  WARNING: Data file not found: {data_path}")
            results[symbol] = {'error': 'data file not found'}
            continue
        
        df = pd.read_parquet(data_path)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        print(f"  Data: {len(df)} bars, {df['time'].iloc[0]} to {df['time'].iloc[-1]}")
        
        symbol_results = {}
        
        for pi, params in enumerate(PARAM_COMBOS):
            combo_key = f"LB{params['LB']}_AM{params['AM']}_TP{params['TP']}_MH{params['MH']}"
            print(f"\n  Combo {pi+1}: {combo_key}")
            
            # Full backtest
            all_trades = run_backtest(df, params)
            full_metrics = compute_metrics(all_trades, len(df))
            print(f"    Full: {full_metrics['total_trades']} trades, PF={full_metrics['profit_factor']}, WR={full_metrics['win_rate']}%, Ret={full_metrics['total_return']}%")
            
            combo_results = {
                'params': params,
                'full_sample': full_metrics,
                'walk_forward': {}
            }
            
            # Walk-forward
            for wf_pct in WALK_FORWARD_PCTS:
                wf_trades, wf_metrics = walk_forward(df, params, wf_pct)
                combo_results['walk_forward'][f'{wf_pct}%'] = wf_metrics
                print(f"    WF {wf_pct}%: {wf_metrics['total_trades']} trades, PF={wf_metrics['profit_factor']}, WR={wf_metrics['win_rate']}%, Ret={wf_metrics['total_return']}%")
            
            symbol_results[combo_key] = combo_results
        
        results[symbol] = symbol_results
    
    # Save results
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Results saved to {OUTPUT_PATH}")
    print(f"{'='*60}")
    
    # Summary
    print("\n\nSUMMARY")
    print("="*80)
    for symbol in SYMBOLS:
        if symbol not in results or 'error' in results[symbol]:
            print(f"\n{symbol}: ERROR - {results.get(symbol, {}).get('error', 'unknown')}")
            continue
        print(f"\n{symbol}:")
        for combo_key, data in results[symbol].items():
            fs = data['full_sample']
            print(f"  {combo_key}: Full PF={fs['profit_factor']}, Ret={fs['total_return']}%")
            for wf_key, wf in data['walk_forward'].items():
                print(f"    WF {wf_key}: PF={wf['profit_factor']}, Ret={wf['total_return']}%")

if __name__ == '__main__':
    main()
