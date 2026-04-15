#!/usr/bin/env python3
"""
MR 4h Strategy: Long vs Short vs Combined Walk-Forward Test
============================================================
Tests whether the SHORT side (RSI>65 + BB upper breach + bearish reversal candle)
works as well as the validated LONG side (RSI<35 + BB lower breach).

Walk-forward: 5 splits, Kraken 0.32% round-trip friction.
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
OUTPUT = DATA_DIR / "edge_discovery" / "short_side_mr.json"

PAIRS = {
    "SOL": "binance_SOL_USDT_240m.parquet",
    "AVAX": "binance_AVAX_USDT_240m.parquet",
    "ETH": "binance_ETH_USDT_240m.parquet",
    "LINK": "binance_LINK_USDT_240m.parquet",
    "BTC": "binance_BTC_USDT_240m.parquet",
}

FRICTION = 0.0032  # 0.32% round-trip

# ATR regime thresholds (percentile-based)
ATR_LOW_PCT = 0.33
ATR_HIGH_PCT = 0.67

# Stop/target by regime
REGIME_CONFIG = {
    "LOW":  {"stop": 0.015, "target": 0.030},
    "MID":  {"stop": 0.010, "target": 0.075},
    "HIGH": {"stop": 0.005, "target": 0.075},
}

# Indicator params
RSI_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2.0
VOL_SMA_PERIOD = 20
VOL_FILTER_MULT = 1.2
ATR_PERIOD = 14

# Entry thresholds
RSI_LONG_THRESH = 35
RSI_SHORT_THRESH = 65


def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_bollinger(series, period=20, std_mult=2.0):
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    return upper, lower, sma


def is_bearish_reversal(df):
    """Bearish reversal candle: close < open AND upper wick >= body"""
    body = df['close'] - df['open']  # negative for bearish
    upper_wick = df['high'] - df[['open', 'close']].max(axis=1)
    is_red = df['close'] < df['open']
    has_upper_wick = upper_wick >= body.abs()
    return is_red & has_upper_wick


def is_bullish_reversal(df):
    """Bullish reversal candle: close > open AND lower wick >= body"""
    body = df['close'] - df['open']  # positive for bullish
    lower_wick = df[['open', 'close']].min(axis=1) - df['low']
    is_green = df['close'] > df['open']
    has_lower_wick = lower_wick >= body.abs()
    return is_green & has_lower_wick


def classify_regime(atr_series):
    """Classify ATR into LOW/MID/HIGH regimes by percentile"""
    p33 = atr_series.quantile(ATR_LOW_PCT)
    p67 = atr_series.quantile(ATR_HIGH_PCT)
    regime = pd.Series(index=atr_series.index, dtype=str)
    regime[atr_series <= p33] = "LOW"
    regime[(atr_series > p33) & (atr_series <= p67)] = "MID"
    regime[atr_series > p67] = "HIGH"
    return regime


def prepare_indicators(df):
    """Add all indicators to dataframe"""
    df = df.copy()
    df['rsi'] = calc_rsi(df['close'], RSI_PERIOD)
    df['bb_upper'], df['bb_lower'], df['bb_mid'] = calc_bollinger(
        df['close'], BB_PERIOD, BB_STD
    )
    df['atr'] = calc_atr(df, ATR_PERIOD)
    df['vol_sma'] = df['volume'].rolling(VOL_SMA_PERIOD).mean()
    df['regime'] = classify_regime(df['atr'])
    df['bearish_rev'] = is_bearish_reversal(df)
    df['bullish_rev'] = is_bullish_reversal(df)
    return df.dropna()


def generate_signals(df, mode):
    """
    Generate entry signals based on mode.
    mode: 'long', 'short', 'both'
    
    Long: RSI < 35 AND close < bb_lower (BB lower breach)
          Note: original validated strategy doesn't require bullish reversal candle
    Short: RSI > 65 AND close > bb_upper AND bearish reversal candle
    """
    signals = pd.DataFrame(index=df.index)
    signals['long_entry'] = False
    signals['short_entry'] = False
    
    # Volume filter
    vol_ok = df['volume'] > df['vol_sma'] * VOL_FILTER_MULT
    
    # Long conditions: RSI < 35 + close below BB lower (breach)
    if mode in ('long', 'both'):
        long_cond = (df['rsi'] < RSI_LONG_THRESH) & (df['close'] < df['bb_lower']) & vol_ok
        signals['long_entry'] = long_cond
    
    # Short conditions: RSI > 65 + close above BB upper + bearish reversal
    if mode in ('short', 'both'):
        short_cond = (df['rsi'] > RSI_SHORT_THRESH) & (df['close'] > df['bb_upper']) & df['bearish_rev'] & vol_ok
        signals['short_entry'] = short_cond
    
    return signals


def simulate_trades(df, signals, mode):
    """
    Simulate trades with T1 entry (next bar open), adaptive stops/targets.
    Returns list of trade dicts.
    """
    trades = []
    n = len(df)
    close_arr = df['close'].values
    open_arr = df['open'].values
    high_arr = df['high'].values
    low_arr = df['low'].values
    regime_arr = df['regime'].values
    long_sig = signals['long_entry'].values
    short_sig = signals['short_entry'].values
    
    i = 0
    while i < n - 1:
        # Check for entry signal at bar i, enter at bar i+1 open
        entry_bar = i + 1
        if entry_bar >= n:
            break
        
        is_long = long_sig[i] and mode in ('long', 'both')
        is_short = short_sig[i] and mode in ('short', 'both')
        
        if not (is_long or is_short):
            i += 1
            continue
        
        # Prefer long if both signal (shouldn't happen with RSI thresholds but just in case)
        direction = 'long' if is_long else 'short'
        
        entry_price = open_arr[entry_bar]
        regime = regime_arr[entry_bar]
        if regime not in REGIME_CONFIG:
            # fallback
            regime = "MID"
        
        cfg = REGIME_CONFIG[regime]
        stop_pct = cfg['stop']
        target_pct = cfg['target']
        
        if direction == 'long':
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
        else:
            stop_price = entry_price * (1 + stop_pct)
            target_price = entry_price * (1 - target_pct)
        
        # Walk forward from entry_bar+1
        exit_bar = None
        exit_price = None
        exit_reason = None
        max_hold = min(50, n - entry_bar - 1)  # max 50 bars hold
        
        for j in range(entry_bar + 1, entry_bar + 1 + max_hold):
            if j >= n:
                break
            
            if direction == 'long':
                # Check stop first (conservative)
                if low_arr[j] <= stop_price:
                    exit_bar = j
                    exit_price = stop_price
                    exit_reason = "STOP"
                    break
                # Then target
                if high_arr[j] >= target_price:
                    exit_bar = j
                    exit_price = target_price
                    exit_reason = "TARGET"
                    break
            else:  # short
                if high_arr[j] >= stop_price:
                    exit_bar = j
                    exit_price = stop_price
                    exit_reason = "STOP"
                    break
                if low_arr[j] <= target_price:
                    exit_bar = j
                    exit_price = target_price
                    exit_reason = "TARGET"
                    break
        
        # Time exit if no stop/target hit
        if exit_bar is None:
            exit_bar = min(entry_bar + max_hold, n - 1)
            exit_price = close_arr[exit_bar]
            exit_reason = "TIME"
        
        # Calculate PnL
        if direction == 'long':
            raw_pnl = (exit_price - entry_price) / entry_price
        else:
            raw_pnl = (entry_price - exit_price) / entry_price
        
        net_pnl = raw_pnl - FRICTION
        
        trades.append({
            'direction': direction,
            'entry_bar': int(entry_bar),
            'exit_bar': int(exit_bar),
            'entry_price': float(entry_price),
            'exit_price': float(exit_price),
            'regime': regime,
            'raw_pnl_pct': float(raw_pnl * 100),
            'net_pnl_pct': float(net_pnl * 100),
            'exit_reason': exit_reason,
        })
        
        # Skip ahead to after exit to avoid overlapping trades
        i = exit_bar + 1
    
    return trades


def calc_metrics(trades):
    """Calculate performance metrics from trade list"""
    if not trades:
        return {
            'trades': 0, 'wins': 0, 'losses': 0,
            'win_rate': 0, 'profit_factor': 0,
            'total_pnl_pct': 0, 'avg_win_pct': 0, 'avg_loss_pct': 0,
            'long_trades': 0, 'short_trades': 0,
            'long_pf': 0, 'short_pf': 0,
            'long_wr': 0, 'short_wr': 0,
            'long_n': 0, 'short_n': 0,
        }
    
    pnls = [t['net_pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else (999 if gross_profit > 0 else 0)
    
    # Split by direction
    long_trades = [t for t in trades if t['direction'] == 'long']
    short_trades = [t for t in trades if t['direction'] == 'short']
    
    def dir_metrics(dtrades):
        if not dtrades:
            return 0, 0, 0
        dpnls = [t['net_pnl_pct'] for t in dtrades]
        dwins = [p for p in dpnls if p > 0]
        dlosses = [p for p in dpnls if p <= 0]
        dgross = sum(dwins) if dwins else 0
        dloss = abs(sum(dlosses)) if dlosses else 0
        dpf = dgross / dloss if dloss > 0 else (999 if dgross > 0 else 0)
        dwr = len(dwins) / len(dtrades) if dtrades else 0
        return dpf, dwr, len(dtrades)
    
    lpf, lwr, ln = dir_metrics(long_trades)
    spf, swr, sn = dir_metrics(short_trades)
    
    return {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) if trades else 0,
        'profit_factor': pf,
        'total_pnl_pct': sum(pnls),
        'avg_win_pct': np.mean(wins) if wins else 0,
        'avg_loss_pct': np.mean(losses) if losses else 0,
        'long_pf': lpf,
        'long_wr': lwr,
        'long_n': ln,
        'short_pf': spf,
        'short_wr': swr,
        'short_n': sn,
    }


def walk_forward(df, signals, mode, n_splits=5):
    """
    Walk-forward test with n_splits.
    Each split: use first portion as in-sample awareness (we don't optimize params,
    but we track if edge persists). Test on last portion.
    Actually for this test, we just split data into n_splits chronological chunks
    and report per-split + aggregate metrics.
    """
    n = len(df)
    split_size = n // (n_splits + 1)  # leave room
    
    split_results = []
    
    for s in range(n_splits):
        test_start = s * split_size
        test_end = (s + 1) * split_size
        
        test_df = df.iloc[test_start:test_end].copy()
        test_sig = signals.iloc[test_start:test_end].copy()
        
        # Recreate signal index for simulate_trades
        test_sig = test_sig.reset_index(drop=True)
        test_df = test_df.reset_index(drop=True)
        
        trades = simulate_trades(test_df, test_sig, mode)
        metrics = calc_metrics(trades)
        metrics['split'] = s + 1
        metrics['bars'] = len(test_df)
        split_results.append(metrics)
    
    return split_results


def test_pair(pair_name, filename, mode):
    """Test a single pair with given mode"""
    filepath = DATA_DIR / filename
    df = pd.read_parquet(filepath)
    df = prepare_indicators(df)
    signals = generate_signals(df, mode)
    splits = walk_forward(df, signals, mode, n_splits=5)
    
    # Aggregate across splits
    all_trades = sum(s['trades'] for s in splits)
    all_pnl = sum(s['total_pnl_pct'] for s in splits)
    all_wins = sum(s['wins'] for s in splits)
    all_losses = sum(s['losses'] for s in splits)
    
    agg_pf_list = [s['profit_factor'] for s in splits if s['trades'] > 0]
    agg_wr_list = [s['win_rate'] for s in splits if s['trades'] > 0]
    
    return {
        'pair': pair_name,
        'mode': mode,
        'splits': splits,
        'aggregate': {
            'total_trades': all_trades,
            'total_pnl_pct': round(all_pnl, 2),
            'avg_pf': round(np.mean(agg_pf_list), 2) if agg_pf_list else 0,
            'median_pf': round(np.median(agg_pf_list), 2) if agg_pf_list else 0,
            'avg_wr': round(np.mean(agg_wr_list), 3) if agg_wr_list else 0,
            'total_wins': all_wins,
            'total_losses': all_losses,
            'overall_wr': round(all_wins / all_trades, 3) if all_trades > 0 else 0,
            'splits_with_pf_gt_1': sum(1 for pf in agg_pf_list if pf > 1.0),
            'splits_tested': len(agg_pf_list),
        }
    }


def main():
    print("=" * 70)
    print("MR 4h STRATEGY: LONG vs SHORT vs COMBINED WALK-FORWARD TEST")
    print("=" * 70)
    print(f"Pairs: {', '.join(PAIRS.keys())}")
    print(f"Friction: {FRICTION*100:.2f}% round-trip (Kraken)")
    print(f"Stops: LOW=1.5% MID=1.0% HIGH=0.5%")
    print(f"Targets: LOW=3.0% MID=7.5% HIGH=7.5%")
    print(f"Walk-forward splits: 5")
    print()
    
    results = {
        'config': {
            'friction_pct': FRICTION * 100,
            'stops': {k: v['stop']*100 for k, v in REGIME_CONFIG.items()},
            'targets': {k: v['target']*100 for k, v in REGIME_CONFIG.items()},
            'rsi_long_thresh': RSI_LONG_THRESH,
            'rsi_short_thresh': RSI_SHORT_THRESH,
            'bb_period': BB_PERIOD,
            'bb_std': BB_STD,
            'vol_filter': VOL_FILTER_MULT,
            'splits': 5,
        },
        'modes': {}
    }
    
    for mode in ['long', 'short', 'both']:
        print(f"\n{'='*70}")
        print(f"MODE: {mode.upper()}")
        print(f"{'='*70}")
        
        mode_results = []
        for pair_name, filename in PAIRS.items():
            print(f"\n  Testing {pair_name}...")
            res = test_pair(pair_name, filename, mode)
            mode_results.append(res)
            
            agg = res['aggregate']
            print(f"    Trades: {agg['total_trades']}  |  WR: {agg['overall_wr']*100:.1f}%  |  "
                  f"PF: {agg['avg_pf']:.2f} (median {agg['median_pf']:.2f})  |  "
                  f"PnL: {agg['total_pnl_pct']:.2f}%  |  "
                  f"Splits PF>1: {agg['splits_with_pf_gt_1']}/{agg['splits_tested']}")
            
            # Per-split detail
            for s in res['splits']:
                if s['trades'] > 0:
                    print(f"      Split {s['split']}: {s['trades']} trades  "
                          f"WR={s['win_rate']*100:.0f}%  PF={s['profit_factor']:.2f}  "
                          f"L={s['long_n']} S={s['short_n']}  "
                          f"L_pf={s['long_pf']:.2f} S_pf={s['short_pf']:.2f}")
        
        results['modes'][mode] = mode_results
    
    # ---- COMPARISON SUMMARY ----
    print(f"\n{'='*70}")
    print("COMPARISON SUMMARY")
    print(f"{'='*70}")
    
    comparison = {}
    for pair_name in PAIRS:
        pair_comp = {}
        for mode in ['long', 'short', 'both']:
            mode_data = results['modes'][mode]
            pair_data = next(r for r in mode_data if r['pair'] == pair_name)
            pair_comp[mode] = pair_data['aggregate']
        comparison[pair_name] = pair_comp
    
    results['comparison'] = comparison
    
    # Print comparison table
    print(f"\n{'Pair':<6} {'Mode':<8} {'Trades':>7} {'WR':>7} {'Avg PF':>8} {'Med PF':>8} {'PnL%':>8} {'S>1':>5}")
    print("-" * 60)
    for pair_name in PAIRS:
        for mode in ['long', 'short', 'both']:
            agg = comparison[pair_name][mode]
            print(f"{pair_name:<6} {mode:<8} {agg['total_trades']:>7} "
                  f"{agg['overall_wr']*100:>6.1f}% "
                  f"{agg['avg_pf']:>8.2f} "
                  f"{agg['median_pf']:>8.2f} "
                  f"{agg['total_pnl_pct']:>7.2f}% "
                  f"{agg['splits_with_pf_gt_1']:>3}/{agg['splits_tested']}")
        print()
    
    # Cross-pair averages
    print(f"\n{'='*70}")
    print("CROSS-PAIR AVERAGES")
    print(f"{'='*70}")
    
    for mode in ['long', 'short', 'both']:
        trades = [comparison[p][mode]['total_trades'] for p in PAIRS]
        pfs = [comparison[p][mode]['avg_pf'] for p in PAIRS]
        wrs = [comparison[p][mode]['overall_wr'] for p in PAIRS]
        pnls = [comparison[p][mode]['total_pnl_pct'] for p in PAIRS]
        
        print(f"\n  {mode.upper()}:")
        print(f"    Avg trades/pair: {np.mean(trades):.1f}")
        print(f"    Avg PF: {np.mean(pfs):.2f}")
        print(f"    Avg WR: {np.mean(wrs)*100:.1f}%")
        print(f"    Avg PnL: {np.mean(pnls):.2f}%")
    
    # KEY QUESTION ANSWER
    print(f"\n{'='*70}")
    print("KEY QUESTION: Do shorts work as well as longs?")
    print(f"{'='*70}")
    
    long_avg_pf = np.mean([comparison[p]['long']['avg_pf'] for p in PAIRS])
    short_avg_pf = np.mean([comparison[p]['short']['avg_pf'] for p in PAIRS])
    long_avg_trades = np.mean([comparison[p]['long']['total_trades'] for p in PAIRS])
    short_avg_trades = np.mean([comparison[p]['short']['total_trades'] for p in PAIRS])
    both_avg_pf = np.mean([comparison[p]['both']['avg_pf'] for p in PAIRS])
    both_avg_trades = np.mean([comparison[p]['both']['total_trades'] for p in PAIRS])
    
    print(f"\n  Long-only:  Avg PF={long_avg_pf:.2f}  Avg trades/pair={long_avg_trades:.1f}")
    print(f"  Short-only: Avg PF={short_avg_pf:.2f}  Avg trades/pair={short_avg_trades:.1f}")
    print(f"  Combined:   Avg PF={both_avg_pf:.2f}  Avg trades/pair={both_avg_trades:.1f}")
    print(f"  Trade multiplier: {both_avg_trades/long_avg_trades:.2f}x")
    
    if short_avg_pf > 1.0:
        print(f"\n  >>> SHORTS VIABLE! PF={short_avg_pf:.2f} > 1.0")
        print(f"  >>> Combined strategy with {both_avg_trades/long_avg_trades:.1f}x trades is feasible")
    else:
        print(f"\n  >>> SHORTS NOT VIABLE. PF={short_avg_pf:.2f} < 1.0")
        print(f"  >>> Stick with long-only")
    
    results['summary'] = {
        'long_avg_pf': round(long_avg_pf, 3),
        'short_avg_pf': round(short_avg_pf, 3),
        'both_avg_pf': round(both_avg_pf, 3),
        'long_avg_trades': round(long_avg_trades, 1),
        'short_avg_trades': round(short_avg_trades, 1),
        'both_avg_trades': round(both_avg_trades, 1),
        'trade_multiplier': round(both_avg_trades / long_avg_trades, 2) if long_avg_trades > 0 else 0,
        'shorts_viable': short_avg_pf > 1.0,
    }
    
    # Save
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResults saved to: {OUTPUT}")


if __name__ == '__main__':
    main()
