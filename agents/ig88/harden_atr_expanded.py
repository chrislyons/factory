#!/usr/bin/env python3
"""
ATR Breakout Hardening — Expanded Scan Symbols
Walk-forward robustness testing with 3 splits, fees, and funding drag.
Cross-symbol stability test.
"""

import sys
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone

BASE_DIR = '/Users/nesbitt/dev/factory/agents/ig88'
DATA_DIR = os.path.join(BASE_DIR, 'data', 'ohlcv', '1h')

# ============================================================
# CONFIG
# ============================================================
ROUND_TRIP_FEE = 0.0009       # 0.09% Hyperliquid taker
FUNDING_DRAG_ANNUAL = 0.011   # 1.1% annual for SHORT
HOURS_PER_YEAR = 8760

LONG_PARAMS = {
    'atr_period': 10,
    'atr_mult': 1.0,
    'lookback': 15,
    'trail_pct': 0.02,
    'max_hold': 48,
}

SHORT_PARAMS = {
    'atr_period': 10,
    'atr_mult': 1.5,
    'lookback': 15,
    'trail_pct': 0.03,
    'max_hold': 48,
}

# Symbol -> (filename, direction)
SYMBOLS = {
    # Original 5 — we test both directions
    'BTC':   ('binance_BTCUSDT_60m.parquet',    'both'),
    'ETH':   ('binance_ETHUSDT_60m.parquet',    'both'),
    'SOL':   ('binance_SOLUSDT_60m.parquet',    'both'),
    'LINK':  ('binance_LINKUSDT_60m.parquet',   'both'),
    'NEAR':  ('binance_NEARUSDT_60m.parquet',   'both'),
    # New viable — specific direction from expanded scan
    'OP':    ('binance_OP_USDT_60m.parquet',    'long'),
    'WLD':   ('binance_WLDUSDT_1h.parquet',     'short'),
    'UNI':   ('binance_UNI_USDT_60m.parquet',   'short'),
    'TRUMP': ('binance_TRUMPUSDT_1h.parquet',   'short'),
    'FIL':   ('binance_FIL_USDT_60m.parquet',   'long'),
    'PAXG':  ('binance_PAXGUSDT_1h.parquet',    'long'),
}

SPLITS = [('50_50', 0.5), ('60_40', 0.6), ('70_30', 0.7)]

MIN_BARS_REQUIRED = 200  # Need at least this many bars

# ============================================================
# DATA LOADING
# ============================================================
def load_data(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found")
        return None
    df = pd.read_parquet(path)
    # Standardize columns
    if 'open_time' in df.columns:
        df = df.set_index('open_time')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    return df

# ============================================================
# ATR BREAKOUT ENGINE
# ============================================================
def compute_atr(df, period=10):
    """Compute ATR using Wilder's EMA smoothing."""
    prev_close = df['close'].shift(1)
    tr = np.maximum(df['high'] - df['low'],
                    np.maximum(abs(df['high'] - prev_close),
                               abs(df['low'] - prev_close)))
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    return atr

def run_backtest(df, direction, params, round_trip_fee=ROUND_TRIP_FEE):
    """
    Run ATR breakout backtest on a dataframe.
    direction: 'long' or 'short'
    Returns list of trade returns (as fractions, e.g. 0.02 = 2%).
    """
    df = df.copy()
    df['atr'] = compute_atr(df, params['atr_period'])

    lookback = params['lookback']
    atr_mult = params['atr_mult']
    trail_pct = params['trail_pct']
    max_hold = params['max_hold']

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_bar = 0
    bars_held = 0

    for i in range(lookback + 1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        if not in_trade:
            if direction == 'long':
                # LONG: enter when close dips below prev_close - atr * mult
                trigger = prev['close'] - prev['atr'] * atr_mult
                if row['close'] < trigger:
                    in_trade = True
                    entry_price = row['close']
                    entry_bar = i
                    bars_held = 0
            else:
                # SHORT: enter when close spikes above prev_close + atr * mult
                trigger = prev['close'] + prev['atr'] * atr_mult
                if row['close'] > trigger:
                    in_trade = True
                    entry_price = row['close']
                    entry_bar = i
                    bars_held = 0
        else:
            bars_held += 1
            if direction == 'long':
                # Trailing stop: exit if close drops trail_pct from max since entry
                window = df.iloc[entry_bar:i+1]
                max_price = window['close'].max()
                stop_price = max_price * (1 - trail_pct)
                # Also check max hold
                if row['close'] <= stop_price or bars_held >= max_hold:
                    raw_ret = (row['close'] - entry_price) / entry_price
                    net_ret = raw_ret - round_trip_fee
                    trades.append({
                        'entry_bar': entry_bar,
                        'exit_bar': i,
                        'bars_held': bars_held,
                        'raw_return': raw_ret,
                        'net_return': net_ret,
                        'direction': direction
                    })
                    in_trade = False
            else:
                # SHORT trailing: exit if close rises trail_pct from min
                window = df.iloc[entry_bar:i+1]
                min_price = window['close'].min()
                stop_price = min_price * (1 + trail_pct)
                if row['close'] >= stop_price or bars_held >= max_hold:
                    raw_ret = (entry_price - row['close']) / entry_price
                    # Apply fees and funding drag
                    hold_hours = bars_held  # 1 bar = 1 hour
                    funding_cost = FUNDING_DRAG_ANNUAL * (hold_hours / HOURS_PER_YEAR)
                    net_ret = raw_ret - round_trip_fee - funding_cost
                    trades.append({
                        'entry_bar': entry_bar,
                        'exit_bar': i,
                        'bars_held': bars_held,
                        'raw_return': raw_ret,
                        'net_return': net_ret,
                        'direction': direction
                    })
                    in_trade = False

    return trades

def compute_stats(trades, total_hours):
    """Compute statistics from a list of trade dicts."""
    if not trades:
        return {
            'total_trades': 0,
            'trades_per_year': 0,
            'profit_factor': 0,
            'win_rate': 0,
            'avg_return': 0,
            'total_return': 0,
            'max_drawdown': 0,
            'expectancy': 0,
        }

    returns = np.array([t['net_return'] for t in trades])
    years = total_hours / HOURS_PER_YEAR
    tpy = len(trades) / years if years > 0 else 0

    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

    wr = len(wins) / len(returns) if len(returns) > 0 else 0
    avg_ret = returns.mean()
    total_ret = returns.sum()

    # Max drawdown on equity curve
    equity = np.cumsum(returns)
    running_max = np.maximum.accumulate(equity)
    dd = running_max - equity
    max_dd = dd.max() if len(dd) > 0 else 0

    return {
        'total_trades': len(trades),
        'trades_per_year': round(tpy, 1),
        'profit_factor': round(pf, 4),
        'win_rate': round(wr, 4),
        'avg_return': round(avg_ret, 6),
        'total_return': round(total_ret, 6),
        'max_drawdown': round(max_dd, 4),
        'expectancy': round(avg_ret, 6),
    }

# ============================================================
# WALK-FORWARD TESTING
# ============================================================
def walk_forward(df, direction, params, split_pct):
    """
    Walk-forward with given train/test split.
    Returns (train_stats, test_stats) or (None, None) if insufficient data.
    """
    n = len(df)
    split_idx = int(n * split_pct)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    if len(train_df) < MIN_BARS_REQUIRED or len(test_df) < MIN_BARS_REQUIRED:
        return None, None

    train_trades = run_backtest(train_df, direction, params)
    test_trades = run_backtest(test_df, direction, params)

    train_stats = compute_stats(train_trades, len(train_df))
    test_stats = compute_stats(test_trades, len(test_df))

    return train_stats, test_stats

# ============================================================
# CROSS-SYMBOL STABILITY TEST
# ============================================================
def cross_symbol_test(all_results):
    """
    Test: take each viable strategy's parameters and see if they work on other symbols.
    Returns dict of cross-test results.
    """
    # Find symbols that are viable in hardening
    viable = {}
    for sym, res in all_results.items():
        for direction in ['long', 'short']:
            wf = res.get(f'{direction}_walk_forward', {})
            if not wf:
                continue
            profitable_splits = 0
            for split_name in ['50_50', '60_40', '70_30']:
                test = wf.get(split_name, {}).get('test', {})
                if test and test.get('profit_factor', 0) >= 1.0 and test.get('total_trades', 0) >= 5:
                    profitable_splits += 1
            if profitable_splits >= 2:
                viable[f"{sym}_{direction}"] = {
                    'direction': direction,
                    'params': LONG_PARAMS if direction == 'long' else SHORT_PARAMS,
                }

    # Now test each viable strategy on all other symbols
    cross_results = {}
    for strat_key, strat_info in viable.items():
        strat_sym = strat_key.split('_')[0]
        strat_dir = strat_info['direction']
        strat_params = strat_info['params']

        cross_results[strat_key] = {}
        for sym, (filename, _) in SYMBOLS.items():
            if sym == strat_sym:
                continue
            df = load_data(filename)
            if df is None or len(df) < MIN_BARS_REQUIRED:
                cross_results[strat_key][sym] = {'status': 'no_data'}
                continue

            # Run 60/40 walk-forward with the strategy's params
            train_stats, test_stats = walk_forward(df, strat_dir, strat_params, 0.6)
            if test_stats is None:
                cross_results[strat_key][sym] = {'status': 'insufficient_data'}
                continue

            cross_results[strat_key][sym] = {
                'test_pf': test_stats['profit_factor'],
                'test_tpy': test_stats['trades_per_year'],
                'test_wr': test_stats['win_rate'],
                'test_total_return': test_stats['total_return'],
                'profitable': test_stats['profit_factor'] >= 1.0 and test_stats['total_trades'] >= 5,
            }

    return cross_results

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("ATR BREAKOUT HARDENING — EXPANDED SCAN")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)
    print(f"\nConfig:")
    print(f"  Round-trip fee: {ROUND_TRIP_FEE*100:.2f}%")
    print(f"  Funding drag (SHORT): {FUNDING_DRAG_ANNUAL*100:.1f}% annual")
    print(f"  Splits: 50/50, 60/40, 70/30")
    print(f"  Long params: {LONG_PARAMS}")
    print(f"  Short params: {SHORT_PARAMS}")

    all_results = {}

    for sym, (filename, direction) in SYMBOLS.items():
        print(f"\n{'='*60}")
        print(f"  {sym} ({filename}) — direction: {direction}")
        print(f"{'='*60}")

        df = load_data(filename)
        if df is None:
            print(f"  SKIPPED: no data")
            all_results[sym] = {'status': 'no_data'}
            continue

        n_bars = len(df)
        print(f"  Data: {n_bars} bars")

        if n_bars < MIN_BARS_REQUIRED:
            print(f"  SKIPPED: insufficient bars ({n_bars} < {MIN_BARS_REQUIRED})")
            all_results[sym] = {'status': 'insufficient_bars', 'bars': n_bars}
            continue

        sym_result = {
            'data_bars': n_bars,
            'data_start': str(df.index[0]) if hasattr(df.index[0], 'isoformat') else str(df.index[0]),
            'data_end': str(df.index[-1]) if hasattr(df.index[-1], 'isoformat') else str(df.index[-1]),
        }

        # Determine which directions to test
        dirs_to_test = []
        if direction == 'both':
            dirs_to_test = ['long', 'short']
        else:
            dirs_to_test = [direction]

        for dir_test in dirs_to_test:
            params = LONG_PARAMS if dir_test == 'long' else SHORT_PARAMS
            print(f"\n  --- {dir_test.upper()} ---")

            wf_results = {}
            profitable_count = 0

            for split_name, split_pct in SPLITS:
                train_stats, test_stats = walk_forward(df, dir_test, params, split_pct)

                if train_stats is None:
                    wf_results[split_name] = {'status': 'insufficient_data'}
                    print(f"    {split_name}: INSUFFICIENT DATA")
                    continue

                wf_results[split_name] = {
                    'train': train_stats,
                    'test': test_stats,
                }

                test_pf = test_stats['profit_factor']
                test_tpy = test_stats['trades_per_year']
                test_wr = test_stats['win_rate'] * 100
                test_ret = test_stats['total_return']
                test_dd = test_stats['max_drawdown'] * 100
                test_trades = test_stats['total_trades']

                is_profitable = test_pf >= 1.0 and test_trades >= 5
                if is_profitable:
                    profitable_count += 1

                status = "PROFITABLE" if is_profitable else "NOT PROFITABLE"
                print(f"    {split_name}: Train PF={train_stats['profit_factor']:.2f}, "
                      f"Test PF={test_pf:.2f}, TPY={test_tpy:.1f}, "
                      f"WR={test_wr:.0f}%, Ret={test_ret:.4f}, DD={test_dd:.1f}%, "
                      f"Trades={test_trades} [{status}]")

            # Viability verdict
            viable = profitable_count >= 2
            wf_results['profitable_splits'] = profitable_count
            wf_results['viable'] = viable
            print(f"    VERDICT: {profitable_count}/3 splits profitable — {'VIABLE' if viable else 'NOT VIABLE'}")

            sym_result[f'{dir_test}_walk_forward'] = wf_results

        all_results[sym] = sym_result

    # ============================================================
    # CROSS-SYMBOL STABILITY
    # ============================================================
    print(f"\n{'='*70}")
    print("CROSS-SYMBOL STABILITY TEST")
    print(f"{'='*70}")

    cross_results = cross_symbol_test(all_results)

    for strat_key, targets in cross_results.items():
        print(f"\n  Strategy: {strat_key}")
        for target_sym, result in targets.items():
            if 'status' in result:
                print(f"    -> {target_sym}: {result['status']}")
            else:
                status = "OK" if result['profitable'] else "FAIL"
                print(f"    -> {target_sym}: PF={result['test_pf']:.2f}, "
                      f"TPY={result['test_tpy']:.1f}, "
                      f"WR={result['test_wr']*100:.0f}% [{status}]")

    # ============================================================
    # SUMMARY
    # ============================================================
    print(f"\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}")

    viable_symbols = []
    for sym, res in all_results.items():
        if res.get('status'):
            print(f"  {sym}: {res['status']}")
            continue
        for direction in ['long', 'short']:
            wf = res.get(f'{direction}_walk_forward', {})
            if not wf:
                continue
            ps = wf.get('profitable_splits', 0)
            v = wf.get('viable', False)
            if v:
                viable_symbols.append(f"{sym} ({direction.upper()})")
                # Get 60/40 test stats as reference
                ref = wf.get('60_40', {}).get('test', {})
                print(f"  {sym} {direction.upper()}: VIABLE ({ps}/3 splits) "
                      f"PF={ref.get('profit_factor', 0):.2f} TPY={ref.get('trades_per_year', 0):.1f}")
            else:
                print(f"  {sym} {direction.upper()}: NOT VIABLE ({ps}/3 splits)")

    print(f"\n  Viable after hardening: {len(viable_symbols)}")
    for vs in viable_symbols:
        print(f"    -> {vs}")

    # ============================================================
    # SAVE RESULTS
    # ============================================================
    output = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'round_trip_fee': ROUND_TRIP_FEE,
            'funding_drag_annual': FUNDING_DRAG_ANNUAL,
            'long_params': LONG_PARAMS,
            'short_params': SHORT_PARAMS,
            'splits': [s[0] for s in SPLITS],
            'viability_criteria': 'profitable in 2/3 or 3/3 splits (PF >= 1.0, trades >= 5)',
        },
        'symbol_results': all_results,
        'cross_symbol_stability': cross_results,
        'viable_symbols': viable_symbols,
    }

    output_path = os.path.join(BASE_DIR, 'data', 'atr_hardened_expanded.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_path}")
    print(f"\nFinished: {datetime.now(timezone.utc).isoformat()}")

if __name__ == '__main__':
    main()
