#!/usr/bin/env python3
"""
Walk-Forward Validation for BB Mean Reversion in CHOP regime.
Tests whether the edge survives out-of-sample.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

ATR_PERIOD = 10
BB_PERIOD = 20
BB_STD = 2.0
MR_MAX_HOLD = 48
FRICTION = 0.0014
SPLITS = 3


def load_pair(pair):
    for pat in [f"binance_{pair}_60m.parquet", f"binance_{pair}_1h.parquet"]:
        f = DATA_DIR / pat
        if f.exists():
            df = pd.read_parquet(f)
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df = df.set_index('time').sort_index()
                return df
    return None


def classify_chop(btc_df):
    c = btc_df['close'].values
    sma50 = pd.Series(c).rolling(50).mean().values
    sma200 = pd.Series(c).rolling(200).mean().values
    chop = pd.Series(False, index=btc_df.index)
    for i in range(200, len(c)):
        if c[i] > sma50[i] > sma200[i]:
            pass  # BULL
        elif c[i] < sma50[i] < sma200[i]:
            pass  # BEAR
        else:
            chop.iloc[i] = True
    return chop


def run_bb_mr(df, chop_mask, start_bar=0, end_bar=None, direction="long"):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    sma = pd.Series(c).rolling(BB_PERIOD).mean().values
    std = pd.Series(c).rolling(BB_PERIOD).std().values
    lower_bb = sma - BB_STD * std
    upper_bb = sma + BB_STD * std
    if end_bar is None:
        end_bar = len(c)

    trades, in_trade = [], False
    entry_price = entry_bar = 0
    for i in range(BB_PERIOD + 1, len(c)):
        if i < start_bar or i >= end_bar:
            continue
        if not chop_mask.iloc[i]:
            if in_trade:
                if direction == "long":
                    pnl = (c[i] - entry_price) / entry_price - FRICTION
                else:
                    pnl = (entry_price - c[i]) / entry_price - FRICTION
                trades.append({"pnl": pnl})
                in_trade = False
            continue

        if in_trade:
            hours = i - entry_bar
            if direction == "long":
                if c[i] >= sma[i] or hours >= MR_MAX_HOLD:
                    exit_p = max(sma[i], c[i])
                    if c[i] >= upper_bb[i]:
                        exit_p = upper_bb[i]
                    pnl = (exit_p - entry_price) / entry_price - FRICTION
                    trades.append({"pnl": pnl})
                    in_trade = False
            else:
                if c[i] <= sma[i] or hours >= MR_MAX_HOLD:
                    exit_p = min(sma[i], c[i])
                    if c[i] <= lower_bb[i]:
                        exit_p = lower_bb[i]
                    pnl = (entry_price - exit_p) / entry_price - FRICTION
                    trades.append({"pnl": pnl})
                    in_trade = False

        if not in_trade:
            if direction == "long" and l[i] <= lower_bb[i]:
                in_trade = True
                entry_price = lower_bb[i]
                entry_bar = i
            elif direction == "short" and h[i] >= upper_bb[i]:
                in_trade = True
                entry_price = upper_bb[i]
                entry_bar = i

    return trades


def analyze(trades):
    if not trades:
        return {"n": 0, "pf": 0, "wr": 0, "avg": 0}
    pnls = [t['pnl'] for t in trades]
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else float('inf')
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    return {"n": len(trades), "pf": pf, "wr": wr, "avg": np.mean(pnls) * 100}


# === MAIN ===
print("=" * 100)
print(f"WALK-FORWARD VALIDATION — BB MEAN REVERSION IN CHOP ({SPLITS} splits)")
print("=" * 100)

btc = load_pair("BTCUSDT")
chop_mask = classify_chop(btc)

ASSETS = [
    "ETHUSDT", "AVAXUSDT", "LINKUSDT", "SOLUSDT",
    "DOGEUSDT", "LTCUSDT", "NEARUSDT", "ARBUSDT", "OPUSDT", "AAVEUSDT"
]

wf_results = []

for pair in ASSETS:
    df = load_pair(pair)
    if df is None:
        continue

    chop_aligned = chop_mask.reindex(df.index, method='ffill')
    n_bars = len(df)
    split_size = n_bars // (SPLITS + 1)

    print(f"\n{pair}:")

    for direction in ["long", "short"]:
        test_results = []
        for s in range(SPLITS):
            train_start = split_size * s
            train_end = split_size * (s + 1)
            test_start = train_end
            test_end = min(split_size * (s + 2), n_bars)

            # Run on test split
            test_trades = run_bb_mr(df, chop_aligned, test_start, test_end, direction)
            v = analyze(test_trades)
            test_results.append(v)

        test_pfs = [r['pf'] for r in test_results if r['n'] >= 5]
        test_ns = [r['n'] for r in test_results]

        if test_pfs:
            avg_pf = np.mean(test_pfs)
            min_pf = min(test_pfs)
            all_profitable = all(p > 1.0 for p in test_pfs)
            verdict = "PASS" if all_profitable and avg_pf >= 1.2 else "MARGINAL" if avg_pf >= 1.0 else "FAIL"
            print(f"  MR {direction:5s}:  "
                  f"Split1 n={test_ns[0]:3d} PF={test_results[0]['pf']:5.2f}  "
                  f"Split2 n={test_ns[1]:3d} PF={test_results[1]['pf']:5.2f}  "
                  f"Split3 n={test_ns[2]:3d} PF={test_results[2]['pf']:5.2f}  "
                  f"Avg={avg_pf:.2f}  {verdict}")
            wf_results.append({"pair": pair, "direction": direction,
                               "avg_pf": avg_pf, "min_pf": min_pf, "verdict": verdict})
        else:
            print(f"  MR {direction:5s}:  Insufficient trades")


# === COMBINED ANALYSIS ===
print("\n\n" + "=" * 100)
print("BB MR IN CHOP — WALK-FORWARD SUMMARY")
print("=" * 100)

passing = [r for r in wf_results if r['verdict'] == "PASS"]
failing = [r for r in wf_results if r['verdict'] == "FAIL"]
marginal = [r for r in wf_results if r['verdict'] == "MARGINAL"]

print(f"\nPASS: {len(passing)} combinations")
for r in passing:
    print(f"  {r['pair']:12s} {r['direction']:5s}  Avg PF={r['avg_pf']:.2f}  Min PF={r['min_pf']:.2f}")

print(f"\nMARGINAL: {len(marginal)} combinations")
for r in marginal:
    print(f"  {r['pair']:12s} {r['direction']:5s}  Avg PF={r['avg_pf']:.2f}  Min PF={r['min_pf']:.2f}")

print(f"\nFAIL: {len(failing)} combinations")
for r in failing:
    print(f"  {r['pair']:12s} {r['direction']:5s}  Avg PF={r['avg_pf']:.2f}  Min PF={r['min_pf']:.2f}")
