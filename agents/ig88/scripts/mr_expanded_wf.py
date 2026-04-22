#!/usr/bin/env python3
"""Mean Reversion walk-forward validation on expanded asset universe.
Mirrors the MR strategy from IG88034/IG88050:
  Long: RSI(14) < 35 AND Close < BB_Lower(2σ) AND Bullish reversal candle
  Exit: T2 (2-bar hold) on 4h timeframe
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

PAIRS = [
    "ETHUSDT", "AVAXUSDT", "LINKUSDT", "SOLUSDT", "NEARUSDT", "BTCUSDT",
    "FILUSDT", "SUIUSDT", "DOGEUSDT", "ALGOUSDT", "DOTUSDT", "UNIUSDT",
    "AAVEUSDT", "INJUSDT", "MATICUSDT", "OPUSDT", "APTUSDT", "ARBUSDT",
    "LTCUSDT", "XRPUSDT", "BNBUSDT", "ZECUSDT", "ATOMUSDT",
]

RSI_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2.0
RSI_THRESHOLD = 35
FRICTION = 0.0014  # Jupiter perps RT

N_SPLITS = 5
TRAIN_RATIO = 0.6


def find_file(pair):
    for pattern in [f"binance_{pair}_60m.parquet", f"binance_{pair}_1h.parquet"]:
        p = DATA_DIR / pattern
        if p.exists():
            return p
    return None


def compute_rsi(close, period=14):
    delta = np.diff(close)
    gains = np.where(delta > 0, delta, 0)
    losses = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gains).rolling(period).mean().values
    avg_loss = pd.Series(losses).rolling(period).mean().values
    rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)
    rsi = np.full(len(close), np.nan)
    rsi[1:] = 100 - (100 / (1 + rs))
    return rsi


def run_mr_backtest(df4h):
    """Run MR backtest on 4h OHLCV data."""
    close = df4h['close'].values
    open_ = df4h['open'].values

    rsi = compute_rsi(close, RSI_PERIOD)
    sma = pd.Series(close).rolling(BB_PERIOD).mean().values
    std = pd.Series(close).rolling(BB_PERIOD).std().values
    bb_lower = sma - BB_STD * std

    trades = []
    for i in range(BB_PERIOD + 1, len(close) - 2):
        # Long entry signal
        if rsi[i] < RSI_THRESHOLD and close[i] < bb_lower[i] and close[i] > open_[i]:
            entry = close[i]
            # T2 exit: hold 2 bars
            exit_price = close[i + 2]
            pnl = (exit_price - entry) / entry - FRICTION
            trades.append({
                'entry_idx': i,
                'exit_idx': i + 2,
                'entry_price': entry,
                'exit_price': exit_price,
                'pnl': pnl,
            })
    return trades


def walk_forward(df4h, n_splits=N_SPLITS):
    n = len(df4h)
    split_size = int(n * (1 - TRAIN_RATIO) / n_splits)
    train_end = int(n * TRAIN_RATIO)

    results = []
    for k in range(n_splits):
        test_start = train_end + k * split_size
        test_end = min(test_start + split_size, n)
        if test_end - test_start < 100:
            continue

        test_df = df4h.iloc[test_start:test_end]
        trades = run_mr_backtest(test_df)
        if trades:
            pnls = [t['pnl'] for t in trades]
            gross_profit = sum(p for p in pnls if p > 0)
            gross_loss = abs(sum(p for p in pnls if p < 0))
            pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            avg_pnl = np.mean(pnls) * 100
        else:
            pf, wr, avg_pnl = 0, 0, 0

        results.append({
            'split': k + 1,
            'n': len(trades),
            'pf': pf,
            'wr': wr,
            'avg_pnl': avg_pnl,
        })
    return results


print("=" * 85)
print("MEAN REVERSION WALK-FORWARD — EXPANDED ASSET UNIVERSE")
print("Strategy: RSI<35 + Below BB Lower(2σ) + Bullish reversal → T2 exit (4h)")
print("=" * 85)

all_results = []
for pair in PAIRS:
    f = find_file(pair)
    if f is None:
        continue

    df = pd.read_parquet(f)
    if 'time' not in df.columns:
        continue
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.set_index('time').sort_index()

    # Resample to 4h
    df4h = df.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum'
    }).dropna()

    if len(df4h) < 1000:
        continue

    results = walk_forward(df4h)
    if not results:
        continue

    avg_pf = np.mean([r['pf'] for r in results if r['pf'] < 100])
    avg_wr = np.mean([r['wr'] for r in results])
    avg_n = np.mean([r['n'] for r in results])
    bad = sum(1 for r in results if r['pf'] < 1.0 and r['n'] >= 5)

    # Full sample
    full_trades = run_mr_backtest(df4h)
    if full_trades:
        fpnls = [t['pnl'] for t in full_trades]
        fg = sum(p for p in fpnls if p > 0)
        fl = abs(sum(p for p in fpnls if p < 0))
        full_pf = fg / fl if fl > 0 else float('inf')
        full_ret = (np.prod([1 + p for p in fpnls]) - 1) * 100
        full_n = len(full_trades)
    else:
        full_pf, full_ret, full_n = 0, 0, 0

    # Verdict
    if bad == 0 and avg_pf >= 1.5 and full_pf >= 1.3:
        verdict = "ROBUST *"
    elif bad <= 1 and avg_pf >= 1.3:
        verdict = "MOSTLY OK"
    elif bad <= 2:
        verdict = "MARGINAL"
    else:
        verdict = "WEAK"

    all_results.append({
        'pair': pair, 'bars': len(df4h), 'splits': len(results),
        'bad': bad, 'avg_pf': avg_pf, 'avg_wr': avg_wr, 'avg_n': avg_n,
        'full_pf': full_pf, 'full_ret': full_ret, 'full_n': full_n,
        'verdict': verdict,
    })

# Sort by robustness
all_results.sort(key=lambda x: (-x['bad'] == 0, -x['avg_pf']))

print(f"\n  {'Pair':12s} {'Bars':>5s} {'Splits':>6s} {'Bad':>4s} {'Avg PF':>8s} {'Avg WR':>7s} {'Avg n':>6s} {'Full PF':>8s} {'Full Ret':>9s} {'Verdict':>12s}")
print("  " + "-" * 82)
for r in all_results:
    print(f"  {r['pair']:12s} {r['bars']:5d} {r['splits']:6d} {r['bad']:4d} {r['avg_pf']:8.2f} {r['avg_wr']:6.1f}% {r['avg_n']:6.0f} {r['full_pf']:8.2f} {r['full_ret']:+8.1f}% {r['verdict']:>12s}")

# Portfolio summary
robust = [r for r in all_results if 'ROBUST' in r['verdict']]
if robust:
    print(f"\n\nPORTFOLIO: {len(robust)} robust MR strategies")
    print("=" * 60)
    total_ann = 0
    for r in robust:
        # Rough annualization: full_ret / years_of_data * (8760/4 / avg_trades_per_year)
        years = r['bars'] * 4 / 8760
        ann = r['full_ret'] / years if years > 0 else 0
        total_ann += ann
        print(f"  {r['pair']:12s} ~ {ann:5.0f}% ann | Full PF: {r['full_pf']:.2f} | {r['full_n']} trades | WR: {r['avg_wr']:.0f}%")
    avg_ann = total_ann / len(robust)
    print(f"\n  Equal-weight portfolio (1x): ~{avg_ann:.0f}% annualized")
