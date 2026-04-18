#!/usr/bin/env python3
"""
ATR Breakout SHORT Variant Grid Search — VECTORIZED
Search for profitable SHORT parameter combinations on ETH.
Full-sample grid search, then walk-forward on survivors.
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from itertools import product

BASE_DIR = '/Users/nesbitt/dev/factory/agents/ig88'
DATA_DIR = os.path.join(BASE_DIR, 'data', 'ohlcv', '1h')
DATA_FILE = 'binance_ETHUSDT_60m.parquet'

ROUND_TRIP_FEE = 0.0014
FUNDING_DRAG_ANNUAL = 0.011
HOURS_PER_YEAR = 8760
ATR_PERIOD = 10

LOOKBACKS = [10, 15, 20, 25, 30]
ATR_MULTS = [1.5, 2.0, 2.5, 3.0]
TRAIL_PCTS = [0.01, 0.015, 0.02, 0.025, 0.03]
MAX_HOLDS = [24, 48, 72, 96]

MIN_TRADES = 30

WALKFORWARD_SPLITS = [
    ('60_40', 0.60),
    ('70_30', 0.70),
    ('80_20', 0.80),
]

OUTPUT_FILE = os.path.join(BASE_DIR, 'data', 'atr_short_grid_search.json')

# ============================================================
# DATA LOADING
# ============================================================
def load_data():
    path = os.path.join(DATA_DIR, DATA_FILE)
    df = pd.read_parquet(path)
    if 'open_time' in df.columns:
        df = df.set_index('open_time')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    if 'time' in df.columns:
        df.index = pd.to_datetime(df['time'], unit='s')
    elif not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except:
            pass
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")
    return df

# ============================================================
# VECTORIZED ATR
# ============================================================
def compute_atr(df, period=ATR_PERIOD):
    prev_close = df['close'].shift(1)
    tr = np.maximum(df['high'] - df['low'],
                    np.maximum(abs(df['high'] - prev_close),
                               abs(df['low'] - prev_close)))
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    return atr.values

# ============================================================
# VECTORIZED BACKTEST
# ============================================================
def run_backtest_short_vectorized(close, atr, lookback, atr_mult, trail_pct, max_hold):
    """
    Fully vectorized SHORT backtest.
    close, atr: numpy arrays
    Returns list of net returns.
    """
    n = len(close)
    if n < lookback + 2:
        return []

    # Entry signal: close[i] > close[i-1] + atr[i-1] * atr_mult
    trigger = np.full(n, np.nan)
    for i in range(lookback + 1, n):
        trigger[i] = close[i-1] + atr[i-1] * atr_mult
    
    entry_signal = close > trigger
    # Don't enter during NaN regions
    entry_signal[:lookback + 2] = False

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_idx = 0
    min_price = 0.0
    
    # Use indices where entry_signal is True
    signal_indices = np.where(entry_signal)[0]
    signal_ptr = 0
    
    for i in range(lookback + 2, n):
        if not in_trade:
            # Check if there's a signal at this bar
            while signal_ptr < len(signal_indices) and signal_indices[signal_ptr] < i:
                signal_ptr += 1
            if signal_ptr < len(signal_indices) and signal_indices[signal_ptr] == i:
                in_trade = True
                entry_price = close[i]
                entry_idx = i
                min_price = close[i]
                signal_ptr += 1
        else:
            bars_held = i - entry_idx
            # Update min price
            if close[i] < min_price:
                min_price = close[i]
            # Check exit
            stop_price = min_price * (1 + trail_pct)
            if close[i] >= stop_price or bars_held >= max_hold:
                raw_ret = (entry_price - close[i]) / entry_price
                funding_cost = FUNDING_DRAG_ANNUAL * (bars_held / HOURS_PER_YEAR)
                net_ret = raw_ret - ROUND_TRIP_FEE - funding_cost
                trades.append(net_ret)
                in_trade = False

    return trades

def run_backtest_on_df(df, params):
    """Run backtest and return trade returns."""
    close = df['close'].values
    atr = compute_atr(df)
    return run_backtest_short_vectorized(
        close, atr,
        params['lookback'],
        params['atr_mult'],
        params['trail_pct'],
        params['max_hold']
    )

def compute_stats(trade_returns, total_bars):
    """Compute stats from list of net returns."""
    if not trade_returns:
        return {
            'total_trades': 0, 'trades_per_year': 0, 'profit_factor': 0,
            'win_rate': 0, 'avg_return': 0, 'total_return': 0,
            'max_drawdown': 0, 'expectancy': 0,
        }

    returns = np.array(trade_returns)
    years = total_bars / HOURS_PER_YEAR
    tpy = len(returns) / years if years > 0 else 0

    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

    wr = len(wins) / len(returns) if len(returns) > 0 else 0
    avg_ret = returns.mean()
    total_ret = returns.sum()

    equity = np.cumsum(returns)
    running_max = np.maximum.accumulate(equity)
    drawdowns = equity - running_max
    max_dd = abs(drawdowns.min()) if len(drawdowns) > 0 else 0

    return {
        'total_trades': len(returns),
        'trades_per_year': round(tpy, 1),
        'profit_factor': round(pf, 3),
        'win_rate': round(wr, 3),
        'avg_return': round(avg_ret, 5),
        'total_return': round(total_ret, 4),
        'max_drawdown': round(max_dd, 4),
        'expectancy': round(avg_ret, 5),
    }

# ============================================================
# GRID SEARCH
# ============================================================
def run_full_sample_grid(df):
    total_hours = len(df)
    grid = list(product(LOOKBACKS, ATR_MULTS, TRAIL_PCTS, MAX_HOLDS))
    results = []

    print(f"\nRunning full-sample grid search: {len(grid)} combinations")
    print(f"  lookback={LOOKBACKS}")
    print(f"  atr_mult={ATR_MULTS}")
    print(f"  trail_pct={[p*100 for p in TRAIL_PCTS]}%")
    print(f"  max_hold={MAX_HOLDS} bars")
    print(f"  friction={ROUND_TRIP_FEE*100}% round-trip")
    print()

    for idx, (lb, am, tp, mh) in enumerate(grid):
        params = {
            'lookback': lb,
            'atr_mult': am,
            'trail_pct': tp,
            'max_hold': mh,
        }
        trade_returns = run_backtest_on_df(df, params)
        stats = compute_stats(trade_returns, total_hours)
        stats['params'] = params
        results.append(stats)

        if (idx + 1) % 50 == 0:
            print(f"  ... {idx+1}/{len(grid)} done")

    results.sort(key=lambda x: x['profit_factor'], reverse=True)
    return results

# ============================================================
# WALK-FORWARD
# ============================================================
def run_walk_forward(df, params, split_ratio):
    split_idx = int(len(df) * split_ratio)
    test_df = df.iloc[split_idx:]
    trade_returns = run_backtest_on_df(test_df, params)
    return compute_stats(trade_returns, len(test_df))

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("ATR BREAKOUT SHORT — GRID SEARCH (VECTORIZED)")
    print("=" * 70)
    print(f"Data: {DATA_FILE}")
    print(f"Friction: {ROUND_TRIP_FEE*100}% round-trip")
    print(f"Funding drag: {FUNDING_DRAG_ANNUAL*100}% annual")
    print()

    df = load_data()

    # Phase 1: Full-sample grid search
    print("\n" + "=" * 70)
    print("PHASE 1: FULL-SAMPLE GRID SEARCH")
    print("=" * 70)

    all_results = run_full_sample_grid(df)

    valid = [r for r in all_results if r['total_trades'] >= MIN_TRADES]
    print(f"\nValid results (>= {MIN_TRADES} trades): {len(valid)}")
    print(f"Results with PF > 1.0: {len([r for r in valid if r['profit_factor'] > 1.0])}")
    print(f"Results with PF > 1.25: {len([r for r in valid if r['profit_factor'] > 1.25])}")
    print(f"Results with PF > 1.5: {len([r for r in valid if r['profit_factor'] > 1.5])}")

    top20 = valid[:20] if len(valid) >= 20 else valid
    print("\n--- TOP 20 FULL-SAMPLE RESULTS ---")
    print(f"{'Rank':<5} {'PF':<8} {'WR':<8} {'Trades':<8} {'TPY':<8} {'Ret':<10} {'MDD':<8} Params")
    print("-" * 120)
    for i, r in enumerate(top20):
        p = r['params']
        print(f"{i+1:<5} {r['profit_factor']:<8.3f} {r['win_rate']*100:<7.1f}% "
              f"{r['total_trades']:<8} {r['trades_per_year']:<8.1f} "
              f"{r['total_return']*100:<9.2f}% {r['max_drawdown']*100:<7.2f}% "
              f"LB={p['lookback']} AM={p['atr_mult']} TP={p['trail_pct']*100:.1f}% MH={p['max_hold']}")

    # Phase 2: Walk-forward on survivors
    print("\n" + "=" * 70)
    print("PHASE 2: WALK-FORWARD ON SURVIVORS")
    print("=" * 70)

    survivors = valid[:30]
    print(f"Testing {len(survivors)} survivors with {len(WALKFORWARD_SPLITS)} walk-forward splits")

    wf_results = []
    for surv in survivors:
        params = surv['params']
        wf_detail = {'params': params, 'full_sample_pf': surv['profit_factor']}

        all_pf_pass = True
        split_stats = []
        for split_name, split_ratio in WALKFORWARD_SPLITS:
            wf_stat = run_walk_forward(df, params, split_ratio)
            wf_stat['split_name'] = split_name
            wf_stat['split_ratio'] = split_ratio
            split_stats.append(wf_stat)
            if wf_stat['profit_factor'] < 1.0:
                all_pf_pass = False

        wf_detail['splits'] = split_stats
        wf_detail['all_pf_pass'] = all_pf_pass

        oos_pfs = [s['profit_factor'] for s in split_stats]
        wf_detail['avg_oos_pf'] = round(np.mean(oos_pfs), 3)
        wf_detail['min_oos_pf'] = round(min(oos_pfs), 3)

        wf_results.append(wf_detail)

    wf_results.sort(key=lambda x: x['avg_oos_pf'], reverse=True)

    print("\n--- WALK-FORWARD RESULTS (sorted by avg OOS PF) ---")
    print(f"{'Rank':<5} {'Full PF':<9} {'Avg OOS':<9} {'Min OOS':<9} {'All>1.0':<9} Params")
    print("-" * 100)
    for i, wr in enumerate(wf_results[:20]):
        p = wr['params']
        status = "YES" if wr['all_pf_pass'] else "NO "
        print(f"{i+1:<5} {wr['full_sample_pf']:<9.3f} {wr['avg_oos_pf']:<9.3f} "
              f"{wr['min_oos_pf']:<9.3f} {status:<9} "
              f"LB={p['lookback']} AM={p['atr_mult']} TP={p['trail_pct']*100:.1f}% MH={p['max_hold']}")

        for s in wr['splits']:
            print(f"      {s['split_name']}: PF={s['profit_factor']:.3f} "
                  f"WR={s['win_rate']*100:.1f}% Trades={s['total_trades']}")

    # Phase 3: Top 5
    print("\n" + "=" * 70)
    print("TOP 5 PARAMETER COMBINATIONS")
    print("=" * 70)

    wf_results.sort(key=lambda x: (x['all_pf_pass'], x['avg_oos_pf'], x['full_sample_pf']), reverse=True)
    top5 = wf_results[:5]

    for i, wr in enumerate(top5):
        p = wr['params']
        print(f"\n#{i+1}: LB={p['lookback']} AM={p['atr_mult']} "
              f"TP={p['trail_pct']*100:.1f}% MH={p['max_hold']}")
        print(f"    Full-sample PF: {wr['full_sample_pf']:.3f}")
        print(f"    Avg OOS PF:     {wr['avg_oos_pf']:.3f}")
        print(f"    Min OOS PF:     {wr['min_oos_pf']:.3f}")
        print(f"    All splits >1.0: {'YES' if wr['all_pf_pass'] else 'NO'}")
        for s in wr['splits']:
            print(f"    {s['split_name']} ({int(s['split_ratio']*100)}/{int((1-s['split_ratio'])*100)}): "
                  f"PF={s['profit_factor']:.3f} WR={s['win_rate']*100:.1f}% "
                  f"Trades={s['total_trades']} TPY={s['trades_per_year']}")

    # Save results
    output = {
        'metadata': {
            'strategy': 'ATR Breakout SHORT',
            'symbol': 'ETHUSDT',
            'timeframe': '1h',
            'data_rows': len(df),
            'date_range': f"{df.index[0]} to {df.index[-1]}",
            'round_trip_fee': ROUND_TRIP_FEE,
            'funding_drag_annual': FUNDING_DRAG_ANNUAL,
            'atr_period': ATR_PERIOD,
            'grid': {
                'lookback': LOOKBACKS,
                'atr_mult': ATR_MULTS,
                'trail_pct': [p*100 for p in TRAIL_PCTS],
                'max_hold': MAX_HOLDS,
            },
            'total_combinations': len(LOOKBACKS) * len(ATR_MULTS) * len(TRAIL_PCTS) * len(MAX_HOLDS),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        },
        'full_sample_top20': [{
            'rank': i+1,
            'params': r['params'],
            'profit_factor': r['profit_factor'],
            'win_rate': r['win_rate'],
            'total_trades': r['total_trades'],
            'trades_per_year': r['trades_per_year'],
            'total_return': r['total_return'],
            'max_drawdown': r['max_drawdown'],
        } for i, r in enumerate(valid[:20])],
        'walk_forward_results': [{
            'params': wr['params'],
            'full_sample_pf': wr['full_sample_pf'],
            'avg_oos_pf': wr['avg_oos_pf'],
            'min_oos_pf': wr['min_oos_pf'],
            'all_pf_above_1': wr['all_pf_pass'],
            'splits': wr['splits'],
        } for wr in wf_results[:30]],
        'top5': [{
            'rank': i+1,
            'params': wr['params'],
            'full_sample_pf': wr['full_sample_pf'],
            'avg_oos_pf': wr['avg_oos_pf'],
            'min_oos_pf': wr['min_oos_pf'],
            'all_pf_above_1': wr['all_pf_pass'],
            'splits': wr['splits'],
        } for i, wr in enumerate(top5)],
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {OUTPUT_FILE}")

    # Final verdict
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    pf_above_15 = [r for r in valid if r['profit_factor'] > 1.5]
    print(f"Full-sample results with PF > 1.5: {len(pf_above_15)}")
    robust_15 = [wr for wr in wf_results if wr['min_oos_pf'] > 1.0 and wr['avg_oos_pf'] > 1.5]
    print(f"Walk-forward survivors with avg OOS PF > 1.5: {len(robust_15)}")
    if robust_15:
        print("YES — Found robust SHORT variants with PF > 1.5")
    else:
        print("NO — No robust SHORT variants found with PF > 1.5 in walk-forward")
        oos_positive = [wr for wr in wf_results if wr['min_oos_pf'] > 1.0]
        print(f"Walk-forward survivors with all OOS PF > 1.0: {len(oos_positive)}")
        if oos_positive:
            best = oos_positive[0]
            p = best['params']
            print(f"Best OOS: LB={p['lookback']} AM={p['atr_mult']} "
                  f"TP={p['trail_pct']*100:.1f}% MH={p['max_hold']} "
                  f"Avg OOS PF={best['avg_oos_pf']:.3f}")

if __name__ == '__main__':
    main()
