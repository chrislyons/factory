#!/usr/bin/env python3
"""
Walk-Forward Bootstrap Validation for ATR Breakout Strategy
- Rolling train/test splits (70/30)
- Bootstrap CI for PF, WR, Sharpe, net return
- Long + Short on validated pairs
"""
import pandas as pd
import numpy as np
import os
import json
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"

# Pairs confirmed profitable from initial backtest
LONG_PAIRS = ["ETHUSDT", "AVAXUSDT", "NEARUSDT", "LINKUSDT", "DOT_USDT",
              "DOGEUSDT", "MATIC_USDT", "ALGO_USDT"]
SHORT_PAIRS = ["SOLUSDT", "WLDUSDT", "TAOUSDT", "UNI_USDT"]  # TAO only 1h

ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0
TRAIL_PCT = 0.01
INITIAL_CAPITAL = 10000

def load_60m(symbol):
    """Load 60m parquet with correct datetime index."""
    # Strip underscore for flexible matching, and try multiple patterns
    sym_clean = symbol.replace("_", "")
    search_patterns = [
        f"binance_{symbol}_60m.parquet",  # exact: binance_DOT_USDT_60m
        f"binance_{sym_clean}_60m.parquet",  # stripped: binance_DOTUSDT_60m
        f"binance_{symbol}_1h.parquet",  # 1h variant
        f"binance_{sym_clean}_1h.parquet",  # 1h stripped
        f"binance_{symbol}.parquet",
        f"binance_{sym_clean}.parquet",
    ]
    for fname in search_patterns:
        path = os.path.join(DATA_DIR, fname)
        if os.path.exists(path):
            df = pd.read_parquet(path)
            if 'time' in df.columns:
                df.index = pd.to_datetime(df['time'], unit='s')
            elif not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.iloc[:, 0])
            df = df.sort_index()
            if len(df) > 1000:
                return df
    return None

def compute_atr(df, period=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def run_atr_long(df, trail_pct=0.01):
    """Run ATR breakout LONG strategy. Returns list of trades."""
    atr = compute_atr(df, ATR_PERIOD)
    sma100 = df['close'].rolling(100).mean()
    upper = df['high'].shift(1) + ATR_MULTIPLIER * atr.shift(1)
    in_pos = False
    entry = trail = 0
    trades = []

    for i in range(200, len(df)):
        row = df.iloc[i]
        close = row['close']
        regime_ok = close > sma100.iloc[i]

        if not in_pos and regime_ok and close > upper.iloc[i]:
            in_pos = True
            entry = close
            trail = close * (1 - trail_pct)
        elif in_pos:
            if close < trail:
                pnl = (close - entry) / entry
                trades.append(pnl)
                in_pos = False
            else:
                new_trail = close * (1 - trail_pct)
                trail = max(trail, new_trail)
    return trades

def run_atr_short(df, trail_pct=0.01):
    """Run ATR breakout SHORT strategy. Returns list of trades."""
    atr = compute_atr(df, ATR_PERIOD)
    sma100 = df['close'].rolling(100).mean()
    lower = df['low'].shift(1) - ATR_MULTIPLIER * atr.shift(1)
    in_pos = False
    entry = trail = 0
    trades = []

    for i in range(200, len(df)):
        row = df.iloc[i]
        close = row['close']
        regime_ok = close < sma100.iloc[i]

        if not in_pos and regime_ok and close < lower.iloc[i]:
            in_pos = True
            entry = close
            trail = close * (1 + trail_pct)
        elif in_pos:
            if close > trail:
                pnl = (entry - close) / entry
                trades.append(pnl)
                in_pos = False
            else:
                new_trail = close * (1 + trail_pct)
                trail = min(trail, new_trail)
    return trades

def compute_metrics(trades):
    """Compute PF, WR, Sharpe, return from list of trade returns."""
    if len(trades) < 5:
        return None
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gross_p = sum(wins)
    gross_l = abs(sum(losses))
    pf = gross_p / gross_l if gross_l > 0 else float('inf')
    wr = len(wins) / len(trades)
    avg = np.mean(trades)
    std = np.std(trades, ddof=1) if len(trades) > 1 else 1e-10
    sharpe = (avg / std) * np.sqrt(len(trades)) if std > 0 else 0
    # Compound return
    cumulative = 1
    for t in trades:
        cumulative *= (1 + t)
    total_return = (cumulative - 1) * 100

    return {
        'trades': len(trades),
        'pf': pf,
        'wr': wr,
        'avg_trade_pct': avg * 100,
        'sharpe': sharpe,
        'return_pct': total_return,
        'max_loss_pct': min(trades) * 100 if trades else 0,
    }

def bootstrap_ci(trades, metric_fn, n_boot=2000, ci=0.95):
    """Bootstrap confidence interval for a metric function."""
    n = len(trades)
    if n < 5:
        return (None, None, None)
    arr = np.array(trades)
    boot_vals = []
    for _ in range(n_boot):
        sample = np.random.choice(arr, size=n, replace=True)
        v = metric_fn(sample)
        if np.isfinite(v):
            boot_vals.append(v)
    if not boot_vals:
        return (None, None, None)
    boot_vals = np.array(boot_vals)
    lower = np.percentile(boot_vals, (1-ci)/2 * 100)
    upper = np.percentile(boot_vals, (1+ci)/2 * 100)
    return (np.mean(boot_vals), lower, upper)

def walk_forward(df, strategy_fn, n_splits=5):
    """Rolling walk-forward with 70/30 split."""
    total = len(df)
    test_size = int(total * 0.3 / n_splits)
    train_pct = 0.70

    results = []
    for i in range(n_splits):
        test_start = int(total * (1 - 0.3 + i * 0.3/n_splits))
        test_end = min(test_start + test_size, total)
        train_start = max(0, int(test_start * 0.4))

        train_df = df.iloc[train_start:test_start]
        test_df = df.iloc[test_start:test_end]

        if len(train_df) < 500 or len(test_df) < 200:
            continue

        # Run on test window only (no optimization — same params)
        trades = strategy_fn(test_df)
        metrics = compute_metrics(trades)

        if metrics:
            # Bootstrap CI
            pf_ci = bootstrap_ci(trades,
                lambda s: (sum(x for x in s if x > 0) / abs(sum(x for x in s if x <= 0)))
                if sum(x for x in s if x <= 0) != 0 else float('inf'))
            wr_ci = bootstrap_ci(trades, lambda s: np.mean(s > 0))
            ret_ci = bootstrap_ci(trades, lambda s: np.prod(1 + s) - 1)

            results.append({
                'split': i + 1,
                'train': len(train_df),
                'test': len(test_df),
                'test_start': str(df.index[test_start].date()),
                'test_end': str(df.index[min(test_end-1, total-1)].date()),
                'metrics': metrics,
                'pf_ci': (round(pf_ci[0], 2), round(pf_ci[1], 2), round(pf_ci[2], 2)) if pf_ci[0] else None,
                'wr_ci': (round(wr_ci[0]*100, 1), round(wr_ci[1]*100, 1), round(wr_ci[2]*100, 1)) if wr_ci[0] else None,
                'ret_ci': (round(ret_ci[0]*100, 1), round(ret_ci[1]*100, 1), round(ret_ci[2]*100, 1)) if ret_ci[0] else None,
            })
    return results

def main():
    print("=" * 70)
    print("WALK-FORWARD BOOTSTRAP VALIDATION — ATR Breakout (60m)")
    print("=" * 70)

    all_results = []

    for side, pairs, fn in [("LONG", LONG_PAIRS, run_atr_long),
                             ("SHORT", SHORT_PAIRS, run_atr_short)]:
        print(f"\n{'='*50}")
        print(f"  {side} STRATEGIES")
        print(f"{'='*50}")

        for symbol in pairs:
            df = load_60m(symbol)
            if df is None:
                print(f"\n{symbol}: NO DATA")
                continue

            print(f"\n--- {symbol} ({len(df)} bars, {df.index[0].date()} to {df.index[-1].date()}) ---")

            # Full-sample
            all_trades = fn(df)
            full = compute_metrics(all_trades)
            if not full:
                print("  Insufficient trades")
                continue

            print(f"  Full: {full['trades']} trades, PF={full['pf']:.2f}, WR={full['wr']*100:.1f}%, "
                  f"Return={full['return_pct']:.1f}%")

            # Walk-forward
            wf = walk_forward(df, fn, n_splits=5)
            if not wf:
                print("  Walk-forward: insufficient data for splits")
                continue

            # Summary
            pfs = [r['metrics']['pf'] for r in wf]
            wrs = [r['metrics']['wr'] for r in wf]
            rets = [r['metrics']['return_pct'] for r in wf]

            print(f"  WF Splits: {len(wf)}")
            print(f"  PF range: {min(pfs):.2f} - {max(pfs):.2f} (avg={np.mean(pfs):.2f})")
            print(f"  WR range: {min(wrs)*100:.1f}% - {max(wrs)*100:.1f}% (avg={np.mean(wrs)*100:.1f}%)")
            print(f"  Return range: {min(rets):.1f}% - {max(rets):.1f}% (avg={np.mean(rets):.1f}%)")

            # Flag if any split is < 1.0 PF
            bad_splits = [r for r in wf if r['metrics']['pf'] < 1.0]
            if bad_splits:
                print(f"  WARNING: {len(bad_splits)} splits with PF < 1.0")
                for b in bad_splits:
                    print(f"    Split {b['split']} ({b['test_start']} to {b['test_end']}): PF={b['metrics']['pf']:.2f}")

            # Show CI for worst split
            worst = min(wf, key=lambda r: r['metrics']['pf'])
            if worst['pf_ci']:
                print(f"  Worst split PF 95% CI: [{worst['pf_ci'][1]}, {worst['pf_ci'][2]}]")

            all_results.append({
                'symbol': symbol,
                'side': side,
                'full': full,
                'wf': wf,
            })

    # Portfolio-level analysis
    print(f"\n{'='*70}")
    print("PORTFOLIO WALK-FORWARD ANALYSIS")
    print(f"{'='*70}")

    if all_results:
        # Collect all WF returns per split
        split_n = min(len(r['wf']) for r in all_results)
        portfolio_returns = []

        for s in range(split_n):
            split_returns = []
            for r in all_results:
                if s < len(r['wf']):
                    split_returns.append(r['wf'][s]['metrics']['return_pct'] / 100)
            if split_returns:
                # Equal weight portfolio (1x each)
                port_ret = np.mean(split_returns)
                portfolio_returns.append({
                    'split': s + 1,
                    'components': len(split_returns),
                    'portfolio_return_pct': port_ret * 100,
                    'individual_returns': [r * 100 for r in split_returns],
                })

        for pr in portfolio_returns:
            print(f"\n  Split {pr['split']}: {pr['components']} strategies, "
                  f"Portfolio return: {pr['portfolio_return_pct']:.1f}%")

        # Average
        avg_port = np.mean([pr['portfolio_return_pct'] for pr in portfolio_returns])
        min_port = min([pr['portfolio_return_pct'] for pr in portfolio_returns])
        max_port = max([pr['portfolio_return_pct'] for pr in portfolio_returns])
        print(f"\n  Portfolio (equal-weight, 1x):")
        print(f"  Avg return per split: {avg_port:.1f}%")
        print(f"  Range: {min_port:.1f}% to {max_port:.1f}%")
        print(f"  All splits positive: {'YES' if min_port > 0 else 'NO — CONSISTENCY ISSUE'}")

    # Save
    out = "/Users/nesbitt/dev/factory/agents/ig88/data/walk_forward_bootstrap.json"
    with open(out, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {out}")

if __name__ == "__main__":
    np.random.seed(42)
    main()
