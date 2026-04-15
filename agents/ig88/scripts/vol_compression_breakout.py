#!/usr/bin/env python3
"""
Volatility Compression Breakout Backtest v2
============================================
Strategy #6: Bollinger Band Squeeze -> Directional Breakout

Proper walk-forward: optimize on IS window, test on OOS window.
No cherry-picking best params per OOS window.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product
from scipy import stats

# --- Configuration ---
DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
OUTPUT_PATH = DATA_DIR / "edge_discovery" / "vol_compression_breakout.json"
FRICTION = 0.0032  # 0.32% round-trip (maker)
BB_PERIOD = 20
BB_STD = 2.0
LOOKBACK = 252  # bars for percentile rank

PAIRS = {
    "SOL": "SOL_USDT",
    "AVAX": "AVAX_USDT",
    "ETH": "ETH_USDT",
    "LINK": "LINK_USDT",
    "BTC": "BTC_USDT",
}

SQUEEZE_PCTILES = [5, 10, 15]
EXPANSION_PCTILES = [40, 50, 60]
TIME_EXITS = [4, 8, 12, 16]
VOL_MULTS = [1.0, 1.5, 2.0]


def load_data(pair_code):
    ticker = PAIRS[pair_code]
    path = DATA_DIR / f"binance_{ticker}_240m.parquet"
    if not path.exists():
        alt = DATA_DIR / f"binance_{pair_code}USDT_240m.parquet"
        if alt.exists():
            path = alt
        else:
            raise FileNotFoundError(f"No parquet for {pair_code}")
    df = pd.read_parquet(path)
    df = df.sort_index()
    return df


def compute_indicators(df):
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values
    n = len(close)

    # Bollinger Bands
    middle = pd.Series(close).rolling(BB_PERIOD).mean().values
    std = pd.Series(close).rolling(BB_PERIOD).std().values
    upper = middle + BB_STD * std
    lower = middle - BB_STD * std

    # BB Width percentage
    bb_width = np.full(n, np.nan)
    valid = (middle != 0) & ~np.isnan(middle)
    bb_width[valid] = (upper[valid] - lower[valid]) / middle[valid] * 100

    # Percentile rank: for each bar, what percentile is the current bb_width
    # relative to the prior LOOKBACK bars (NO current bar in the reference)
    bb_pctile = np.full(n, np.nan)
    bw = pd.Series(bb_width)
    for i in range(LOOKBACK + BB_PERIOD, n):
        window = bw.iloc[i - LOOKBACK:i].dropna()
        if len(window) >= 20:
            bb_pctile[i] = stats.percentileofscore(
                window.values, bb_width[i], kind='rank'
            ) / 100.0

    # Volume SMA(20)
    vol_sma = pd.Series(volume).rolling(20).mean().values

    return {
        'close': close, 'high': high, 'low': low, 'volume': volume,
        'bb_upper': upper, 'bb_lower': lower, 'bb_middle': middle,
        'bb_width': bb_width, 'bb_pctile': bb_pctile, 'vol_sma': vol_sma,
        'dates': df.index.values,
    }


def run_backtest(ind, squeeze_pct, expansion_pct, time_exit, vol_mult,
                 start_bar=0, end_bar=None):
    """Run backtest between start_bar and end_bar (exclusive)."""
    n = len(ind['close'])
    if end_bar is None:
        end_bar = n
    # Need LOOKBACK + BB_PERIOD bars before start_bar for indicator context
    actual_start = max(LOOKBACK + BB_PERIOD, start_bar)

    close = ind['close']
    upper = ind['bb_upper']
    lower = ind['bb_lower']
    bb_pctile = ind['bb_pctile']
    volume = ind['volume']
    vol_sma = ind['vol_sma']

    trades = []
    in_trade = False
    entry_idx = None
    direction = None
    entry_price = None

    for i in range(actual_start, end_bar):
        if in_trade:
            elapsed = i - entry_idx
            exit_now = False
            if elapsed >= time_exit:
                exit_now = True
            if not np.isnan(bb_pctile[i]) and bb_pctile[i] > expansion_pct / 100.0:
                exit_now = True

            if exit_now:
                exit_price = close[i]
                if direction == 'long':
                    pnl = (exit_price - entry_price) / entry_price - FRICTION
                else:
                    pnl = (entry_price - exit_price) / entry_price - FRICTION
                trades.append({
                    'entry_bar': int(entry_idx), 'exit_bar': int(i),
                    'direction': direction,
                    'entry_price': float(entry_price), 'exit_price': float(exit_price),
                    'pnl_pct': float(pnl), 'bars_held': int(elapsed),
                })
                in_trade = False
            continue

        # Entry checks
        if np.isnan(bb_pctile[i]) or np.isnan(bb_pctile[i]):
            continue
        if np.isnan(vol_sma[i]) or vol_sma[i] == 0:
            continue
        if volume[i] < vol_mult * vol_sma[i]:
            continue
        if bb_pctile[i] >= squeeze_pct / 100.0:
            continue

        if close[i] > upper[i]:
            direction = 'long'
            entry_price = close[i]
            entry_idx = i
            in_trade = True
        elif close[i] < lower[i]:
            direction = 'short'
            entry_price = close[i]
            entry_idx = i
            in_trade = True

    return trades


def compute_metrics(trades):
    if len(trades) == 0:
        return {'n_trades': 0, 'win_rate': 0, 'pf': 0, 'avg_pnl': 0,
                'total_pnl': 0, 'max_dd': 0}
    pnls = np.array([t['pnl_pct'] for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    gp = wins.sum() if len(wins) > 0 else 0
    gl = abs(losses.sum()) if len(losses) > 0 else 1e-8
    equity = np.cumsum(pnls)
    running_max = np.maximum.accumulate(equity)
    dd = running_max - equity
    return {
        'n_trades': len(trades),
        'win_rate': float(len(wins) / len(trades)),
        'pf': float(gp / gl) if gl > 1e-9 else 0,
        'avg_pnl': float(np.mean(pnls)),
        'total_pnl': float(np.sum(pnls)),
        'max_dd': float(np.max(dd)) if len(dd) > 0 else 0,
    }


def optimize_params(ind, start_bar, end_bar):
    """Find best params on [start_bar, end_bar) using IS metric = PF."""
    best_pf = -999
    best_params = None
    best_metrics = None

    for sq, ex, te, vm in product(SQUEEZE_PCTILES, EXPANSION_PCTILES, TIME_EXITS, VOL_MULTS):
        trades = run_backtest(ind, sq, ex, te, vm, start_bar=start_bar, end_bar=end_bar)
        m = compute_metrics(trades)
        # Require minimum trades for robustness
        if m['n_trades'] >= 5 and m['pf'] > best_pf:
            best_pf = m['pf']
            best_params = {'squeeze_pct': sq, 'expansion_pct': ex,
                           'time_exit': te, 'vol_mult': vm}
            best_metrics = m

    return best_params, best_metrics


def walk_forward(ind, n_splits=5):
    """
    Walk-forward with proper train/test:
    - Split usable data into n_splits + 1 segments
    - For split i: train on segments 0..i, test on segment i+1
    - Parameters selected on train, applied to test
    """
    n = len(ind['close'])
    min_start = LOOKBACK + BB_PERIOD
    usable = n - min_start

    if usable < 500:
        return {'oos_pf': 0, 'oos_trades': 0, 'is_pf': 0, 'splits': []}

    chunk = usable // (n_splits + 1)
    if chunk < 100:
        return {'oos_pf': 0, 'oos_trades': 0, 'is_pf': 0, 'splits': []}

    oos_results = []
    is_results = []

    for split_i in range(1, n_splits + 1):
        # IS window: from min_start to the start of OOS
        is_start = min_start
        is_end = min_start + split_i * chunk
        # OOS window: next chunk
        oos_start = is_end
        oos_end = min(is_end + chunk, n)

        if oos_end - oos_start < 50:
            continue

        # Optimize on IS
        best_params, is_metrics = optimize_params(ind, is_start, is_end)

        if best_params is None:
            # No valid params found, skip
            oos_results.append({'pf': 0, 'n_trades': 0, 'win_rate': 0, 'params': None})
            continue

        # Test on OOS with IS-optimal params
        oos_trades = run_backtest(
            ind,
            best_params['squeeze_pct'],
            best_params['expansion_pct'],
            best_params['time_exit'],
            best_params['vol_mult'],
            start_bar=oos_start,
            end_bar=oos_end
        )
        oos_metrics = compute_metrics(oos_trades)

        oos_results.append({
            'pf': oos_metrics['pf'],
            'n_trades': oos_metrics['n_trades'],
            'win_rate': oos_metrics['win_rate'],
            'params': best_params,
            'is_pf': is_metrics['pf'] if is_metrics else 0,
            'is_n_trades': is_metrics['n_trades'] if is_metrics else 0,
        })
        is_results.append(is_metrics['pf'] if is_metrics else 0)

    if len(oos_results) == 0:
        return {'oos_pf': 0, 'oos_trades': 0, 'is_pf': 0, 'splits': []}

    # Filter to splits that had OOS trades
    valid_oos = [r for r in oos_results if r['n_trades'] > 0]

    if len(valid_oos) == 0:
        return {
            'oos_pf': 0, 'oos_trades': 0,
            'is_pf': float(np.mean(is_results)) if is_results else 0,
            'splits': oos_results
        }

    return {
        'oos_pf': float(np.mean([r['pf'] for r in valid_oos])),
        'oos_trades': int(sum(r['n_trades'] for r in valid_oos)),
        'oos_win_rate': float(np.mean([r['win_rate'] for r in valid_oos])),
        'is_pf': float(np.mean([r['is_pf'] for r in valid_oos])),
        'n_valid_splits': len(valid_oos),
        'splits': oos_results,
    }


def run():
    print("=" * 70)
    print("VOLATILITY COMPRESSION BREAKOUT - Strategy #6")
    print("Walk-forward: optimize IS -> test OOS (no cherry-picking)")
    print("=" * 70)

    param_grid = list(product(SQUEEZE_PCTILES, EXPANSION_PCTILES, TIME_EXITS, VOL_MULTS))
    print(f"Parameter combinations: {len(param_grid)}")
    print(f"Friction: {FRICTION*100:.2f}% round-trip")
    print(f"Pairs: {list(PAIRS.keys())}")

    # Load data
    pair_data = {}
    for code in PAIRS:
        df = load_data(code)
        print(f"\n{code}: {len(df)} bars, {df.index[0]} -> {df.index[-1]}")
        pair_data[code] = compute_indicators(df)

    # Run walk-forward per pair
    pair_results = {}
    all_oos_pfs = []

    for code in PAIRS:
        print(f"\n{'─' * 50}")
        ind = pair_data[code]
        wf = walk_forward(ind, n_splits=5)
        pair_results[code] = wf
        all_oos_pfs.append(wf['oos_pf'])

        print(f"{code}:")
        print(f"  IS avg PF:  {wf['is_pf']:.2f}")
        print(f"  OOS avg PF: {wf['oos_pf']:.2f}")
        print(f"  OOS trades: {wf['oos_trades']}")
        print(f"  Valid splits: {wf.get('n_valid_splits', 0)}/5")
        for i, s in enumerate(wf.get('splits', [])):
            if s.get('params'):
                p = s['params']
                print(f"    Split {i+1}: IS PF={s.get('is_pf',0):.2f} ({s.get('is_n_trades',0)}t) -> "
                      f"OOS PF={s['pf']:.2f} ({s['n_trades']}t) "
                      f"[sq<{p['squeeze_pct']}% ex>{p['expansion_pct']}% te={p['time_exit']} vm={p['vol_mult']}]")
            else:
                print(f"    Split {i+1}: No valid params found")

    # Also run full-sample backtest with "consensus" params (most commonly selected across splits)
    print(f"\n{'=' * 70}")
    print("CONSISTENT PARAMETER ANALYSIS")
    print("=" * 70)

    # Find most commonly selected params per pair
    for code in PAIRS:
        wf = pair_results[code]
        param_counts = {}
        for s in wf.get('splits', []):
            if s.get('params'):
                key = tuple(sorted(s['params'].items()))
                param_counts[key] = param_counts.get(key, 0) + 1

        if param_counts:
            best_key = max(param_counts, key=param_counts.get)
            params = dict(best_key)
            print(f"\n{code}: most selected params (chosen {param_counts[best_key]}x):")
            print(f"  {params}")

            # Full-sample backtest
            ind = pair_data[code]
            trades = run_backtest(
                ind, params['squeeze_pct'], params['expansion_pct'],
                params['time_exit'], params['vol_mult']
            )
            m = compute_metrics(trades)
            print(f"  Full sample: {m['n_trades']} trades, PF={m['pf']:.2f}, "
                  f"WR={m['win_rate']:.1%}, Avg={m['avg_pnl']:.2%}, MaxDD={m['max_dd']:.2%}")

    # Aggregate
    avg_oos_pf = np.mean(all_oos_pfs) if all_oos_pfs else 0
    print(f"\n{'=' * 70}")
    print("AGGREGATE RESULTS")
    print("=" * 70)
    for code in PAIRS:
        wf = pair_results[code]
        print(f"  {code:6s} | OOS PF: {wf['oos_pf']:6.2f} | "
              f"OOS Trades: {wf['oos_trades']:3d} | IS PF: {wf['is_pf']:6.2f}")
    print(f"\n  Average OOS PF across pairs: {avg_oos_pf:.2f}")
    validated = avg_oos_pf > 2.0
    print(f"  VERDICT: {'VALIDATED EDGE' if validated else 'NOT VALIDATED'} "
          f"(threshold: >2.0)")

    # Build output
    output = {
        'strategy': 'volatility_compression_breakout',
        'version': 2,
        'description': 'BB squeeze breakout - proper walk-forward (optimize IS, test OOS)',
        'parameters_tested': {
            'squeeze_percentiles': SQUEEZE_PCTILES,
            'expansion_percentiles': EXPANSION_PCTILES,
            'time_exits': TIME_EXITS,
            'volume_multipliers': VOL_MULTS,
        },
        'bb_period': BB_PERIOD,
        'bb_std': BB_STD,
        'lookback': LOOKBACK,
        'friction': FRICTION,
        'walk_forward_splits': 5,
        'avg_oos_pf': float(avg_oos_pf),
        'validated': validated,
        'pairs': {},
    }

    for code in PAIRS:
        wf = pair_results[code]
        output['pairs'][code] = {
            'oos_pf': float(wf['oos_pf']),
            'oos_trades': wf['oos_trades'],
            'oos_win_rate': float(wf.get('oos_win_rate', 0)),
            'is_pf': float(wf['is_pf']),
            'n_valid_splits': wf.get('n_valid_splits', 0),
            'splits': wf.get('splits', []),
        }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to {OUTPUT_PATH}")
    return output


if __name__ == '__main__':
    run()
