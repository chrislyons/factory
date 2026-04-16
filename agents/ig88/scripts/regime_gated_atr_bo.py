#!/usr/bin/env python3
"""
Regime-Gated ATR Breakout Analysis
Multi-asset regime classification and walk-forward testing.
Uses TRUE RANGE for ATR, exit on close <= stop.
Regimes: BULL (close>SMA200 && SMA50>SMA200), BEAR (close<SMA200 && SMA50<SMA200), SIDEWAYS.
"""

import sys
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone

BASE_DIR = '/Users/nesbitt/dev/factory/agents/ig88'
DATA_DIR = os.path.join(BASE_DIR, 'data', 'ohlcv', '1h')
OUTPUT_PATH = os.path.join(BASE_DIR, 'data', 'regime_multi_asset.json')

# ============================================================
# CONFIG
# ============================================================
ROUND_TRIP_FEE = 0.0009       # 0.09% Hyperliquid taker
HOURS_PER_YEAR = 8760

LONG_PARAMS = {
    'atr_period': 10,
    'atr_mult': 1.0,
    'lookback': 15,
    'trail_pct': 0.02,
    'max_hold': 48,
}

ASSETS = ['AVAX', 'LINK', 'NEAR', 'SOL']

# Correct filenames with full 43,788 rows
FILENAMES = {
    'AVAX': 'binance_AVAXUSDT_60m.parquet',
    'LINK': 'binance_LINKUSDT_60m.parquet',
    'NEAR': 'binance_NEARUSDT_60m.parquet',
    'SOL': 'binance_SOLUSDT_60m.parquet',
}

SPLITS = [('50_50', 0.5), ('60_40', 0.6), ('70_30', 0.7)]
MIN_BARS_REQUIRED = 300  # Need enough bars for SMA200 + trading

# ============================================================
# DATA LOADING
# ============================================================
def load_data(symbol):
    filename = FILENAMES.get(symbol)
    if not filename:
        print(f"  WARNING: No filename mapping for {symbol}")
        return None
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found")
        return None
    df = pd.read_parquet(path)
    if 'time' in df.columns:
        df = df.set_index('time')
    elif 'open_time' in df.columns:
        df = df.set_index('open_time')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    return df

# ============================================================
# REGIME CLASSIFICATION
# ============================================================
def classify_regimes(df):
    """
    Classify market regime based on SMA50 and SMA200.
    BULL: close > SMA200 && SMA50 > SMA200
    BEAR: close < SMA200 && SMA50 < SMA200
    SIDEWAYS: everything else
    """
    df = df.copy()
    df['sma50'] = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()

    conditions = [
        (df['close'] > df['sma200']) & (df['sma50'] > df['sma200']),
        (df['close'] < df['sma200']) & (df['sma50'] < df['sma200']),
    ]
    choices = ['BULL', 'BEAR']
    df['regime'] = np.select(conditions, choices, default='SIDEWAYS')

    return df

# ============================================================
# ATR COMPUTATION (TRUE RANGE)
# ============================================================
def compute_atr(df, period=10):
    """Compute ATR using Wilder's EMA smoothing on TRUE RANGE."""
    prev_close = df['close'].shift(1)
    tr = np.maximum(df['high'] - df['low'],
                    np.maximum(abs(df['high'] - prev_close),
                               abs(df['low'] - prev_close)))
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    return atr

# ============================================================
# ATR BREAKOUT ENGINE
# ============================================================
def run_backtest(df, params, regime_filter=None):
    """
    Run ATR breakout backtest (long only).
    regime_filter: if set, only trade in this regime (e.g., 'BULL')
    Exit on close <= stop (not low).
    Returns list of trade dicts.
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

        # Check regime filter
        if regime_filter and 'regime' in df.columns:
            current_regime = row.get('regime', 'SIDEWAYS')
        else:
            current_regime = None

        if not in_trade:
            # LONG entry: close dips below prev_close - atr * mult
            trigger = prev['close'] - prev['atr'] * atr_mult
            if row['close'] < trigger:
                # Check regime filter for entry
                if regime_filter and current_regime != regime_filter:
                    continue
                in_trade = True
                entry_price = row['close']
                entry_bar = i
                bars_held = 0
                trade_regime = current_regime
        else:
            bars_held += 1
            # Trailing stop: exit if close drops trail_pct from max since entry
            window = df.iloc[entry_bar:i+1]
            max_price = window['close'].max()
            stop_price = max_price * (1 - trail_pct)
            # CRITICAL: exit on close <= stop (not low)
            if row['close'] <= stop_price or bars_held >= max_hold:
                raw_ret = (row['close'] - entry_price) / entry_price
                net_ret = raw_ret - ROUND_TRIP_FEE
                trades.append({
                    'entry_bar': entry_bar,
                    'exit_bar': i,
                    'bars_held': bars_held,
                    'raw_return': raw_ret,
                    'net_return': net_ret,
                    'regime': trade_regime if regime_filter else 'ALL'
                })
                in_trade = False

    return trades

# ============================================================
# STATISTICS
# ============================================================
def compute_stats(trades, total_hours):
    if not trades:
        return {
            'total_trades': 0,
            'profit_factor': 0,
            'win_rate': 0,
            'avg_return': 0,
            'total_return': 0,
        }

    returns = np.array([t['net_return'] for t in trades])
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0

    return {
        'total_trades': len(trades),
        'profit_factor': round(pf, 4),
        'win_rate': round(len(wins) / len(returns), 4) if len(returns) > 0 else 0,
        'avg_return': round(returns.mean(), 6),
        'total_return': round(returns.sum(), 6),
    }

# ============================================================
# REGIME-SPECIFIC ANALYSIS
# ============================================================
def analyze_by_regime(df, params):
    """Run backtest and split results by regime."""
    # Run full backtest to get all trades with regime labels
    all_trades = run_backtest(df, params, regime_filter=None)

    # Tag each trade with regime at entry
    df_regime = df.copy()
    df_regime['sma50'] = df_regime['close'].rolling(50).mean()
    df_regime['sma200'] = df_regime['close'].rolling(200).mean()
    conditions = [
        (df_regime['close'] > df_regime['sma200']) & (df_regime['sma50'] > df_regime['sma200']),
        (df_regime['close'] < df_regime['sma200']) & (df_regime['sma50'] < df_regime['sma200']),
    ]
    df_regime['regime'] = np.select(conditions, ['BULL', 'BEAR'], default='SIDEWAYS')

    # Assign regime to each trade based on entry bar
    for trade in all_trades:
        entry_bar = trade['entry_bar']
        if entry_bar < len(df_regime):
            trade['regime'] = df_regime.iloc[entry_bar]['regime']
        else:
            trade['regime'] = 'UNKNOWN'

    # Split by regime
    regime_trades = {'BULL': [], 'BEAR': [], 'SIDEWAYS': []}
    for trade in all_trades:
        regime = trade.get('regime', 'UNKNOWN')
        if regime in regime_trades:
            regime_trades[regime].append(trade)

    # Compute stats per regime
    regime_stats = {}
    for regime, trades in regime_trades.items():
        regime_stats[regime] = compute_stats(trades, len(df))

    return regime_stats, all_trades

# ============================================================
# WALK-FORWARD WITH REGIME FILTER
# ============================================================
def walk_forward_regime(df, params, split_pct, regime_filter=None):
    """Walk-forward test with optional regime filter."""
    n = len(df)
    split_idx = int(n * split_pct)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    if len(train_df) < MIN_BARS_REQUIRED or len(test_df) < MIN_BARS_REQUIRED:
        return None, None

    # Classify regimes
    train_df = classify_regimes(train_df)
    test_df = classify_regimes(test_df)

    train_trades = run_backtest(train_df, params, regime_filter=regime_filter)
    test_trades = run_backtest(test_df, params, regime_filter=regime_filter)

    train_stats = compute_stats(train_trades, len(train_df))
    test_stats = compute_stats(test_trades, len(test_df))

    return train_stats, test_stats

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("REGIME-GATED ATR BREAKOUT ANALYSIS")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    all_results = {}

    for symbol in ASSETS:
        print(f"\n{'='*60}")
        print(f"  {symbol}")
        print(f"{'='*60}")

        df = load_data(symbol)
        if df is None or len(df) < MIN_BARS_REQUIRED:
            print(f"  SKIPPED: insufficient data")
            all_results[symbol] = {'status': 'no_data'}
            continue

        print(f"  Data: {len(df)} bars")

        # Classify regimes
        df = classify_regimes(df)
        regime_counts = df['regime'].value_counts().to_dict()
        print(f"  Regime distribution: BULL={regime_counts.get('BULL', 0)}, "
              f"BEAR={regime_counts.get('BEAR', 0)}, SIDEWAYS={regime_counts.get('SIDEWAYS', 0)}")

        # 1) Regime-specific analysis (full sample)
        print(f"\n  --- REGIME-SPECIFIC RESULTS (FULL SAMPLE) ---")
        regime_stats, all_trades = analyze_by_regime(df, LONG_PARAMS)

        symbol_result = {
            'data_bars': len(df),
            'regime_distribution': regime_counts,
            'regime_stats': regime_stats,
        }

        for regime, stats in regime_stats.items():
            print(f"    {regime}: PF={stats['profit_factor']:.2f}, "
                  f"Trades={stats['total_trades']}, WR={stats['win_rate']*100:.0f}%")

        # 2) Walk-forward: unfiltered vs BULL filter
        print(f"\n  --- WALK-FORWARD COMPARISON ---")
        wf_unfiltered = {}
        wf_bull_filtered = {}

        for split_name, split_pct in SPLITS:
            # Unfiltered
            train_u, test_u = walk_forward_regime(df, LONG_PARAMS, split_pct, regime_filter=None)
            # BULL filtered
            train_b, test_b = walk_forward_regime(df, LONG_PARAMS, split_pct, regime_filter='BULL')

            if test_u is not None:
                wf_unfiltered[split_name] = {
                    'train': train_u, 'test': test_u
                }
            if test_b is not None:
                wf_bull_filtered[split_name] = {
                    'train': train_b, 'test': test_b
                }

            test_pf_u = test_u['profit_factor'] if test_u else 0
            test_pf_b = test_b['profit_factor'] if test_b else 0
            test_trades_u = test_u['total_trades'] if test_u else 0
            test_trades_b = test_b['total_trades'] if test_b else 0

            improvement = "YES" if test_pf_b > test_pf_u and test_trades_b >= 5 else "NO"
            print(f"    {split_name}: Unfiltered PF={test_pf_u:.2f} ({test_trades_u} trades) | "
                  f"BULL PF={test_pf_b:.2f} ({test_trades_b} trades) | Improved: {improvement}")

        # 3) Average walk-forward PF across splits
        avg_unfiltered_pf = np.mean([
            wf_unfiltered[s]['test']['profit_factor']
            for s in wf_unfiltered
            if wf_unfiltered[s].get('test')
        ]) if wf_unfiltered else 0

        avg_bull_pf = np.mean([
            wf_bull_filtered[s]['test']['profit_factor']
            for s in wf_bull_filtered
            if wf_bull_filtered[s].get('test')
        ]) if wf_bull_filtered else 0

        avg_unfiltered_trades = np.mean([
            wf_unfiltered[s]['test']['total_trades']
            for s in wf_unfiltered
            if wf_unfiltered[s].get('test')
        ]) if wf_unfiltered else 0

        avg_bull_trades = np.mean([
            wf_bull_filtered[s]['test']['total_trades']
            for s in wf_bull_filtered
            if wf_bull_filtered[s].get('test')
        ]) if wf_bull_filtered else 0

        bull_filter_improves = avg_bull_pf > avg_unfiltered_pf and avg_bull_trades >= 5

        print(f"\n  --- WALK-FORWARD SUMMARY ---")
        print(f"    Avg Unfiltered PF: {avg_unfiltered_pf:.2f} (avg {avg_unfiltered_trades:.0f} trades)")
        print(f"    Avg BULL PF:       {avg_bull_pf:.2f} (avg {avg_bull_trades:.0f} trades)")
        print(f"    BULL filter improves WF: {'YES' if bull_filter_improves else 'NO'}")

        symbol_result['walk_forward_unfiltered'] = wf_unfiltered
        symbol_result['walk_forward_bull_filtered'] = wf_bull_filtered
        symbol_result['avg_wf_unfiltered_pf'] = round(avg_unfiltered_pf, 4)
        symbol_result['avg_wf_bull_pf'] = round(avg_bull_pf, 4)
        symbol_result['bull_filter_improves_wf'] = bull_filter_improves

        all_results[symbol] = symbol_result

    # ============================================================
    # CROSS-ASSET SUMMARY
    # ============================================================
    print(f"\n{'='*70}")
    print("CROSS-ASSET SUMMARY")
    print(f"{'='*70}")

    summary = {
        'bull_improves_count': 0,
        'assets_tested': 0,
    }

    for symbol, result in all_results.items():
        if result.get('status'):
            print(f"  {symbol}: {result['status']}")
            continue

        summary['assets_tested'] += 1
        improves = result.get('bull_filter_improves_wf', False)
        if improves:
            summary['bull_improves_count'] += 1

        print(f"\n  {symbol}:")
        for regime in ['BULL', 'BEAR', 'SIDEWAYS']:
            rs = result.get('regime_stats', {}).get(regime, {})
            print(f"    {regime}: PF={rs.get('profit_factor', 0):.2f}, Trades={rs.get('total_trades', 0)}")
        print(f"    WF Unfiltered PF: {result.get('avg_wf_unfiltered_pf', 0):.2f}")
        print(f"    WF BULL PF:       {result.get('avg_wf_bull_pf', 0):.2f}")
        print(f"    BULL filter improves: {'YES' if improves else 'NO'}")

    print(f"\n  BULL filter improves WF on {summary['bull_improves_count']}/{summary['assets_tested']} assets")

    # ============================================================
    # SAVE RESULTS
    # ============================================================
    output = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'round_trip_fee': ROUND_TRIP_FEE,
            'long_params': LONG_PARAMS,
            'assets': ASSETS,
            'regime_definitions': {
                'BULL': 'close > SMA200 && SMA50 > SMA200',
                'BEAR': 'close < SMA200 && SMA50 < SMA200',
                'SIDEWAYS': 'other',
            },
            'notes': [
                'ATR uses TRUE RANGE (not simple H-L)',
                'Exit on close <= stop (not low)',
                'Walk-forward tested with 50/50, 60/40, 70/30 splits',
            ],
        },
        'asset_results': all_results,
        'summary': summary,
    }

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {OUTPUT_PATH}")
    print(f"\nFinished: {datetime.now(timezone.utc).isoformat()}")

if __name__ == '__main__':
    main()
