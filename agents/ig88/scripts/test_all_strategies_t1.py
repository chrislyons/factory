"""
Strategy Portfolio Overview with T1 Entry Timing
=================================================
Test all validated strategies with T1 timing:
1. H3-A (Ichimoku + Volume)
2. H3-B (Volume Ignition)
3. MR (RSI + BB + Volume)
4. MR Adaptive (with regime-based stops)

Show: PF, WR, Expectancy, Sharpe, Annual Return
"""
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

@dataclass
class StrategyConfig:
    name: str
    signal_fn: object
    stop_pct: float
    target_pct: float
    use_adaptive_stops: bool = False
    entry_offset: int = 1  # T1 default

def load_data(pair='SOL', timeframe='240m'):
    for p in [f'{pair}_USDT', f'{pair}USDT', pair]:
        path = DATA_DIR / f'binance_{p}_{timeframe}.parquet'
        if path.exists():
            return pd.read_parquet(path)
    return None

def compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, min_periods=period).mean()
    return (100 - (100 / (1 + gain / loss))).values

def compute_indicators(df):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    rsi = compute_rsi(df['close'])
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_l = sma20 - std20
    bb_h = sma20 + std20
    
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    atr_pct = (atr / c) * 100
    
    # Ichimoku
    tenkan = (df['high'].rolling(9).max() + df['low'].rolling(9).min()) / 2
    kijun = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((df['high'].rolling(52).max() + df['low'].rolling(52).min()) / 2).shift(26)
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'bb_l': bb_l, 'bb_h': bb_h,
        'vol_ratio': vol_ratio, 'atr_pct': atr_pct,
        'tenkan': tenkan.values, 'kijun': kijun.values,
        'span_a': span_a.values, 'span_b': span_b.values,
    }

# Signal functions
def signal_mr_long(ind, i):
    return ind['rsi'][i] < 35 and ind['c'][i] < ind['bb_l'][i] and ind['vol_ratio'][i] > 1.2

def signal_mr_short(ind, i):
    return ind['rsi'][i] > 65 and ind['c'][i] > ind['bb_h'][i] and ind['vol_ratio'][i] > 1.2

def signal_mr_combined(ind, i):
    return signal_mr_long(ind, i) or signal_mr_short(ind, i)

def signal_h3a_long(ind, i):
    if np.isnan(ind['tenkan'][i]) or np.isnan(ind['kijun'][i]) or np.isnan(ind['span_a'][i]):
        return False
    cloud_bull = ind['c'][i] > max(ind['span_a'][i], ind['span_b'][i])
    tk_cross = ind['tenkan'][i] > ind['kijun'][i]
    return cloud_bull and tk_cross and ind['vol_ratio'][i] > 1.0

def signal_h3a_short(ind, i):
    if np.isnan(ind['tenkan'][i]) or np.isnan(ind['kijun'][i]) or np.isnan(ind['span_a'][i]):
        return False
    cloud_bear = ind['c'][i] < min(ind['span_a'][i], ind['span_b'][i])
    tk_cross = ind['tenkan'][i] < ind['kijun'][i]
    return cloud_bear and tk_cross and ind['vol_ratio'][i] > 1.0

def signal_h3b_long(ind, i):
    # Volume ignition: volume spike + price momentum
    if i < 10:
        return False
    vol_spike = ind['vol_ratio'][i] > 1.5
    momentum = ind['c'][i] > ind['c'][i-1]
    return vol_spike and momentum and ind['rsi'][i] < 65  # Not overbought

def signal_h3b_short(ind, i):
    if i < 10:
        return False
    vol_spike = ind['vol_ratio'][i] > 1.5
    momentum = ind['c'][i] < ind['c'][i-1]
    return vol_spike and momentum and ind['rsi'][i] > 35  # Not oversold

def get_stop_target(atr_pct, fixed_stop=0.01, fixed_target=0.075, adaptive=True):
    if not adaptive:
        return fixed_stop, fixed_target
    if atr_pct < 2.0:
        return 0.015, 0.03
    elif atr_pct < 4.0:
        return 0.01, 0.075
    else:
        return 0.005, 0.075

def run_strategy_test(df, signal_fn, entry_offset=1, friction=0.0025, 
                      fixed_stop=0.01, fixed_target=0.075, adaptive_stops=True,
                      lookahead=8):
    ind = compute_indicators(df)
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    
    trades = []
    equity = [10000]
    
    for i in range(100, len(c) - entry_offset - lookahead - 1):
        if not signal_fn(ind, i):
            continue
        
        entry_bar = i + entry_offset
        if entry_bar >= len(c) - lookahead:
            continue
        
        # Determine signal direction
        is_long = signal_fn in [signal_mr_long, signal_h3a_long, signal_h3b_long] or \
                  (signal_fn == signal_mr_combined and ind['rsi'][i] < 35)
        
        entry = o[entry_bar]
        
        # Check signal persistence (T1 filter)
        if is_long:
            if c[entry_bar] > ind['bb_l'][entry_bar] and signal_fn == signal_mr_long:
                continue
        else:
            if c[entry_bar] < ind['bb_h'][entry_bar] and signal_fn == signal_mr_short:
                continue
        
        # Stop/target
        atr_val = ind['atr_pct'][entry_bar] if not np.isnan(ind['atr_pct'][entry_bar]) else 3.0
        stop_pct, target_pct = get_stop_target(atr_val, fixed_stop, fixed_target, adaptive_stops)
        
        if is_long:
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
        else:
            stop = entry * (1 + stop_pct)
            target = entry * (1 - target_pct)
        
        # Exit check
        exited = False
        for j in range(1, lookahead + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            
            bar_h, bar_l = h[bar], l[bar]
            
            if is_long:
                if bar_l <= stop and bar_h >= target:
                    ret = -stop_pct - friction
                    trades.append(ret)
                    exited = True
                    break
                elif bar_l <= stop:
                    trades.append(-stop_pct - friction)
                    exited = True
                    break
                elif bar_h >= target:
                    trades.append(target_pct - friction)
                    exited = True
                    break
            else:
                if bar_h >= stop and bar_l <= target:
                    trades.append(-stop_pct - friction)
                    exited = True
                    break
                elif bar_h >= stop:
                    trades.append(-stop_pct - friction)
                    exited = True
                    break
                elif bar_l <= target:
                    trades.append(target_pct - friction)
                    exited = True
                    break
        
        if not exited:
            exit_price = c[min(entry_bar + lookahead, len(c) - 1)]
            if is_long:
                ret = (exit_price - entry) / entry - friction
            else:
                ret = (entry - exit_price) / entry - friction
            trades.append(ret)
    
    return np.array(trades) if trades else np.array([])

def compute_stats(trades, label=""):
    if len(trades) < 10:
        return {'label': label, 'n': len(trades), 'pf': np.nan, 'wr': np.nan, 
                'exp': np.nan, 'sharpe': np.nan, 'ann_ret': np.nan}
    
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    wr = len(w) / len(trades) * 100
    exp = trades.mean() * 100
    sharpe = trades.mean() / trades.std() * np.sqrt(252/8) if trades.std() > 0 else 0  # Annualized for 4h bars
    
    # Rough annual return estimate (1 trade per 4h avg)
    trades_per_year = len(trades) / (10968 / (365 * 6))  # bars / (bars / 4h periods in a year)
    ann_ret = ((1 + trades.mean()) ** trades_per_year - 1) * 100
    
    return {
        'label': label,
        'n': len(trades),
        'pf': round(pf, 3),
        'wr': round(wr, 1),
        'exp': round(exp, 3),
        'sharpe': round(sharpe, 2),
        'ann_ret': round(ann_ret, 1),
    }

print("="*90)
print("STRATEGY PORTFOLIO OVERVIEW (T1 Entry Timing)")
print("="*90)
print(f"\nVenue: Jupiter Perps (0.25% friction) | Timeframe: 4h | Exit: 8 bars (32h)\n")

pairs = ['SOL', 'BTC', 'ETH', 'NEAR', 'LINK', 'AVAX']

# Define strategies
strategies = [
    {
        'name': 'MR (Fixed 1%/7.5%)',
        'signal_fn': signal_mr_combined,
        'stop_pct': 0.01,
        'target_pct': 0.075,
        'adaptive': False,
    },
    {
        'name': 'MR (Adaptive Stops)',
        'signal_fn': signal_mr_combined,
        'stop_pct': 0.01,
        'target_pct': 0.075,
        'adaptive': True,
    },
    {
        'name': 'H3-A (Ichimoku)',
        'signal_fn': signal_h3a_long,
        'stop_pct': 0.01,
        'target_pct': 0.075,
        'adaptive': True,
    },
    {
        'name': 'H3-B (Vol Ignition)',
        'signal_fn': signal_h3b_long,
        'stop_pct': 0.01,
        'target_pct': 0.075,
        'adaptive': True,
    },
]

# Test each strategy on each pair
all_results = {}

for strat in strategies:
    print(f"\n--- {strat['name']} ---\n")
    print(f"{'Pair':>6} {'n':>5} {'PF':>7} {'WR':>6} {'Exp%':>7} {'Sharpe':>7} {'Ann%':>7}")
    print("-" * 55)
    
    strat_trades = []
    strat_details = []
    
    for pair in pairs:
        df = load_data(pair)
        if df is None:
            continue
        
        trades = run_strategy_test(
            df, 
            strat['signal_fn'],
            entry_offset=1,
            friction=0.0025,
            fixed_stop=strat['stop_pct'],
            fixed_target=strat['target_pct'],
            adaptive_stops=strat['adaptive'],
        )
        
        s = compute_stats(trades, pair)
        strat_trades.extend(trades)
        strat_details.append(s)
        
        if s['pf'] and not np.isnan(s['pf']):
            print(f"{pair:>6} {s['n']:5} {s['pf']:7.3f} {s['wr']:5.1f}% {s['exp']:6.3f}% {s['sharpe']:7.2f} {s['ann_ret']:6.1f}%")
    
    # Aggregate
    s_agg = compute_stats(np.array(strat_trades), "TOTAL")
    print("-" * 55)
    print(f"{'TOTAL':>6} {s_agg['n']:5} {s_agg['pf']:7.3f} {s_agg['wr']:5.1f}% {s_agg['exp']:6.3f}% {s_agg['sharpe']:7.2f} {s_agg['ann_ret']:6.1f}%")
    
    all_results[strat['name']] = {
        'details': strat_details,
        'aggregate': s_agg,
    }

# Portfolio comparison
print("\n" + "="*90)
print("PORTFOLIO COMPARISON")
print("="*90)
print(f"\n{'Strategy':>25} {'Total Trades':>13} {'PF':>7} {'WR':>6} {'Exp%':>7} {'Ann%':>7}")
print("-" * 75)

for strat_name, results in all_results.items():
    s = results['aggregate']
    print(f"{strat_name:>25} {s['n']:13} {s['pf']:7.3f} {s['wr']:5.1f}% {s['exp']:6.3f}% {s['ann_ret']:6.1f}%")

# Best pair analysis
print("\n" + "="*90)
print("BEST PAIR BY STRATEGY")
print("="*90)

for strat_name, results in all_results.items():
    best = max(results['details'], key=lambda x: x['pf'] if not np.isnan(x['pf']) else 0)
    print(f"{strat_name}: {best['label']} (PF={best['pf']:.3f}, WR={best['wr']:.1f}%)")

# Combined portfolio (equal weight all strategies)
print("\n" + "="*90)
print("COMBINED PORTFOLIO (Equal Weight)")
print("="*90)

# Simple simulation: alternate strategies on each trade
print("\nNote: Combined portfolio assumes trades are distributed across strategies.")
print("In practice, correlation between strategies reduces diversification benefit.\n")
