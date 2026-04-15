#!/usr/bin/env python3
"""
Test MR strategy with relaxed entry filters to increase trade frequency.
Walk-forward 5 splits, 12 configurations, 5 pairs.
"""

import json
import sys
import os
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np

# ── Configurations ──────────────────────────────────────────────────────
CONFIGS = [
    {"id": "A", "rsi_max": 35, "bb_std": 1.0, "rev_candle": True,  "vol_min": 1.2, "desc": "BASELINE (current)"},
    {"id": "B", "rsi_max": 40, "bb_std": 1.0, "rev_candle": True,  "vol_min": 1.2, "desc": "Wider RSI"},
    {"id": "C", "rsi_max": 35, "bb_std": 1.25, "rev_candle": True, "vol_min": 1.2, "desc": "Wider BB"},
    {"id": "D", "rsi_max": 35, "bb_std": 1.0, "rev_candle": False, "vol_min": 1.2, "desc": "No reversal candle"},
    {"id": "E", "rsi_max": 35, "bb_std": 1.0, "rev_candle": True,  "vol_min": 1.0, "desc": "Lower volume filter"},
    {"id": "F", "rsi_max": 40, "bb_std": 1.25, "rev_candle": True, "vol_min": 1.2, "desc": "Wider RSI + BB"},
    {"id": "G", "rsi_max": 40, "bb_std": 1.0, "rev_candle": False, "vol_min": 1.2, "desc": "Wider RSI, no candle"},
    {"id": "H", "rsi_max": 35, "bb_std": 1.25, "rev_candle": False, "vol_min": 1.2, "desc": "Wider BB, no candle"},
    {"id": "I", "rsi_max": 40, "bb_std": 1.0, "rev_candle": True,  "vol_min": 1.0, "desc": "Wider RSI, lower vol"},
    {"id": "J", "rsi_max": 40, "bb_std": 1.25, "rev_candle": False, "vol_min": 1.0, "desc": "Most relaxed"},
    {"id": "K", "rsi_max": 35, "bb_std": 1.5,  "rev_candle": True,  "vol_min": 1.5, "desc": "TIGHTER (fewer, higher quality)"},
    {"id": "L", "rsi_max": 30, "bb_std": 0.75, "rev_candle": True,  "vol_min": 1.5, "desc": "TIGHTEST"},
]

PAIRS = ["SOLUSDT", "AVAXUSDT", "ETHUSDT", "LINKUSDT", "BTCUSDT"]
DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
FRICTION = 0.005  # 0.50% round-trip
N_SPLITS = 5

def load_pair(pair_name):
    """Load parquet data for a pair, try both naming conventions."""
    for variant in [pair_name, pair_name.replace("USDT", "_USDT")]:
        p = DATA_DIR / f"binance_{variant}_240m.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            break
    else:
        raise FileNotFoundError(f"No parquet found for {pair_name}")
    
    # If index is datetime (open_time), reset to column
    if df.index.dtype.kind == 'M':
        df = df.sort_index().reset_index()
        # Rename the index column to timestamp
        if df.columns[0] not in ('open', 'high', 'low', 'close', 'volume'):
            df = df.rename(columns={df.columns[0]: 'timestamp'})
    elif 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Standardize columns
    col_map = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl == 'open': col_map[c] = 'open'
        elif cl == 'high': col_map[c] = 'high'
        elif cl == 'low': col_map[c] = 'low'
        elif cl == 'close': col_map[c] = 'close'
        elif cl in ('volume', 'vol'): col_map[c] = 'volume'
    df = df.rename(columns=col_map)
    
    return df

def compute_indicators(df):
    """Compute RSI(14), Bollinger Bands (20, n), volume SMA(20)."""
    df = df.copy()
    
    close = df['close'].values
    n = len(close)
    
    # RSI 14
    period = 14
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    avg_gain[period] = np.mean(gain[1:period+1])
    avg_loss[period] = np.mean(loss[1:period+1])
    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + loss[i]) / period
    rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)
    df['rsi'] = 100 - 100 / (1 + rs)
    
    # Bollinger Bands (20-period SMA)
    bb_period = 20
    sma = np.full(n, np.nan)
    std = np.full(n, np.nan)
    for i in range(bb_period - 1, n):
        sma[i] = np.mean(close[i - bb_period + 1:i + 1])
        std[i] = np.std(close[i - bb_period + 1:i + 1])
    df['bb_sma'] = sma
    df['bb_std_val'] = std
    
    # Volume SMA 20
    vol = df['volume'].values.astype(float)
    vol_sma = np.full(n, np.nan)
    for i in range(bb_period - 1, n):
        vol_sma[i] = np.mean(vol[i - bb_period + 1:i + 1])
    df['vol_sma'] = vol_sma
    
    return df

def is_reversal_candle(open_arr, close_arr, i):
    """Check if candle i is a bullish reversal (closes above open)."""
    return close_arr[i] > open_arr[i]

def generate_signals(df, cfg):
    """Generate entry signals based on configuration."""
    df = compute_indicators(df)
    
    open_arr = df['open'].values
    high_arr = df['high'].values
    low_arr = df['low'].values
    close_arr = df['close'].values
    rsi = df['rsi'].values
    bb_sma = df['bb_sma'].values
    bb_std_val = df['bb_std_val'].values
    vol = df['volume'].values.astype(float)
    vol_sma = df['vol_sma'].values
    
    entries = []
    n = len(df)
    
    for i in range(25, n):  # Need indicators warmed up
        if np.isnan(rsi[i]) or np.isnan(bb_sma[i]) or np.isnan(vol_sma[i]):
            continue
        
        # RSI filter
        if rsi[i] >= cfg['rsi_max']:
            continue
        
        # BB lower band filter
        lower_band = bb_sma[i] - cfg['bb_std'] * bb_std_val[i]
        if low_arr[i] > lower_band:
            continue
        
        # Reversal candle filter
        if cfg['rev_candle'] and not is_reversal_candle(open_arr, close_arr, i):
            continue
        
        # Volume filter
        if vol_sma[i] <= 0:
            continue
        if vol[i] / vol_sma[i] < cfg['vol_min']:
            continue
        
        entries.append(i)
    
    return entries, df

def simulate_trades(df, entry_indices, hold_bars=6):
    """Simulate trades: enter at close of signal, exit after hold_bars."""
    close = df['close'].values
    trades = []
    
    for idx in entry_indices:
        exit_idx = idx + hold_bars
        if exit_idx >= len(close):
            continue
        
        entry_price = close[idx]
        exit_price = close[exit_idx]
        gross_ret = (exit_price - entry_price) / entry_price
        net_ret = gross_ret - FRICTION
        
        trades.append({
            'entry_idx': idx,
            'exit_idx': exit_idx,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'net_return': net_ret,
        })
    
    return trades

def walk_forward_test(df, cfg):
    """Run walk-forward with N_SPLITS."""
    entries, df_full = generate_signals(df, cfg)
    all_trades = simulate_trades(df_full, entries)
    
    if len(all_trades) < 5:
        return {
            'oos_pf': 0.0,
            'oos_wr': 0.0,
            'n_trades': len(all_trades),
            'avg_return': 0.0,
            'total_return': 0.0,
            'splits': [],
        }
    
    n = len(all_trades)
    split_size = n // N_SPLITS
    
    splits = []
    for s in range(N_SPLITS):
        start = s * split_size
        end = n if s == N_SPLITS - 1 else (s + 1) * split_size
        split_trades = all_trades[start:end]
        
        returns = [t['net_return'] for t in split_trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 0
        pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        wr = len(wins) / len(returns) if returns else 0
        
        splits.append({
            'split': s + 1,
            'n_trades': len(split_trades),
            'pf': round(pf, 3),
            'wr': round(wr, 3),
            'avg_return': round(np.mean(returns), 5) if returns else 0,
        })
    
    # OOS: use last 20% of trades as primary OOS
    oos_start = int(n * 0.8)
    oos_trades = all_trades[oos_start:]
    oos_returns = [t['net_return'] for t in oos_trades]
    oos_wins = [r for r in oos_returns if r > 0]
    oos_losses = [r for r in oos_returns if r <= 0]
    
    oos_gp = sum(oos_wins) if oos_wins else 0
    oos_gl = abs(sum(oos_losses)) if oos_losses else 0
    oos_pf = oos_gp / oos_gl if oos_gl > 0 else (999.0 if oos_gp > 0 else 0.0)
    oos_wr = len(oos_wins) / len(oos_returns) if oos_returns else 0
    
    all_returns = [t['net_return'] for t in all_trades]
    
    return {
        'oos_pf': round(oos_pf, 3),
        'oos_wr': round(oos_wr, 3),
        'n_trades': len(all_trades),
        'oos_n_trades': len(oos_trades),
        'avg_return': round(np.mean(all_returns), 5),
        'total_return': round(sum(all_returns), 4),
        'splits': splits,
        # Aggregate OOS across all splits (last split is purest OOS)
        'last_split_pf': splits[-1]['pf'],
        'last_split_wr': splits[-1]['wr'],
    }

def main():
    print("=" * 80)
    print("MR RELAXED ENTRY FILTER TEST")
    print("=" * 80)
    print(f"Pairs: {', '.join(PAIRS)}")
    print(f"Friction: {FRICTION*100:.2f}% round-trip")
    print(f"Walk-forward splits: {N_SPLITS}")
    print(f"Configurations: {len(CONFIGS)}")
    print()
    
    results = {}
    summary_rows = []
    
    for pair in PAIRS:
        print(f"\n{'='*60}")
        print(f"  PAIR: {pair}")
        print(f"{'='*60}")
        
        try:
            df = load_pair(pair)
            print(f"  Loaded {len(df)} bars from {df['timestamp'].min()} to {df['timestamp'].max()}")
        except Exception as e:
            print(f"  ERROR loading {pair}: {e}")
            continue
        
        pair_results = {}
        
        for cfg in CONFIGS:
            try:
                res = walk_forward_test(df, cfg)
            except Exception as e:
                res = {'oos_pf': 0, 'oos_wr': 0, 'n_trades': 0, 'error': str(e)}
            
            pair_results[cfg['id']] = res
            
            pf = res.get('oos_pf', 0)
            wr = res.get('oos_wr', 0)
            n = res.get('n_trades', 0)
            
            flag = ""
            if pf > 1.2:
                flag = " *GOOD*"
            elif pf > 1.0:
                flag = " ~OK~"
            
            print(f"  Config {cfg['id']:>2} ({cfg['desc']:<30}): "
                  f"PF={pf:>7.3f}  WR={wr:>6.1%}  Trades={n:>5}{flag}")
            
            summary_rows.append({
                'pair': pair,
                'config_id': cfg['id'],
                'desc': cfg['desc'],
                'oos_pf': pf,
                'oos_wr': wr,
                'n_trades': n,
                'avg_return': res.get('avg_return', 0),
                'last_split_pf': res.get('last_split_pf', 0),
            })
        
        results[pair] = pair_results
    
    # ── Aggregate summary across pairs ──────────────────────────────
    print("\n\n" + "=" * 100)
    print("AGGREGATE SUMMARY (across all pairs)")
    print("=" * 100)
    
    agg_results = {}
    for cfg in CONFIGS:
        cid = cfg['id']
        row_results = [r for r in summary_rows if r['config_id'] == cid]
        
        avg_pf = np.mean([r['oos_pf'] for r in row_results])
        min_pf = np.min([r['oos_pf'] for r in row_results])
        avg_wr = np.mean([r['oos_wr'] for r in row_results])
        total_trades = sum([r['n_trades'] for r in row_results])
        avg_trades_per_pair = total_trades / len(row_results)
        
        agg_results[cid] = {
            'avg_pf': round(avg_pf, 3),
            'min_pf': round(min_pf, 3),
            'avg_wr': round(avg_wr, 3),
            'total_trades': total_trades,
            'avg_trades_per_pair': round(avg_trades_per_pair, 1),
            'desc': cfg['desc'],
        }
        
        flag = ""
        if avg_pf > 1.2:
            flag = " *GOOD*"
        
        print(f"  Config {cid:>2} ({cfg['desc']:<30}): "
              f"Avg PF={avg_pf:>7.3f}  Min PF={min_pf:>7.3f}  "
              f"Avg WR={avg_wr:>6.1%}  Trades/Pair={avg_trades_per_pair:>5.1f}{flag}")
    
    # ── Best configs ────────────────────────────────────────────────
    print("\n\n" + "=" * 100)
    print("RECOMMENDED CONFIGS (Avg PF > 1.2, ordered by trades/pare)")
    print("=" * 100)
    
    good = [(cid, v) for cid, v in agg_results.items() if v['avg_pf'] > 1.2]
    good.sort(key=lambda x: x[1]['avg_trades_per_pair'], reverse=True)
    
    for cid, v in good:
        print(f"  Config {cid:>2} ({v['desc']:<30}): "
              f"Avg PF={v['avg_pf']:.3f}  Trades/Pair={v['avg_trades_per_pair']:.1f}  "
              f"Avg WR={v['avg_wr']:.1%}")
    
    if not good:
        print("  No configurations met PF > 1.2 threshold.")
    
    # ── Save results ────────────────────────────────────────────────
    output = {
        'test_name': 'MR Relaxed Entry Filters',
        'parameters': {
            'friction': FRICTION,
            'n_splits': N_SPLITS,
            'pairs': PAIRS,
            'hold_bars': 6,
        },
        'configurations': CONFIGS,
        'per_pair_results': results,
        'aggregate': agg_results,
        'summary_table': summary_rows,
        'recommended': [
            {'config_id': cid, **v} for cid, v in good
        ],
    }
    
    out_path = DATA_DIR / 'edge_discovery' / 'mr_relaxed_entry.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\nResults saved to: {out_path}")
    print("Done.")

if __name__ == '__main__':
    main()
