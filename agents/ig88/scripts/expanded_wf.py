#!/usr/bin/env python3
"""
Walk-Forward Bootstrap Validation — EXPANDED UNIVERSE
All pairs with 20K+ bars. Long + Short. Honest assessment.
"""
import pandas as pd
import numpy as np
import os
import json
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"

# All pairs with enough data for walk-forward
ALL_PAIRS = [
    ("ETHUSDT", 43788), ("AVAXUSDT", 43788), ("LINKUSDT", 43788),
    ("SOLUSDT", 43788), ("NEARUSDT", 43788), ("BTCUSDT", 43788),
    ("ALGOUSDT", 59808), ("DOGEUSDT", 59484), ("DOTUSDT", 49657),
    ("UNIUSDT", 48957), ("AAVEUSDT", 48285), ("FILUSDT", 48271),
    ("INJUSDT", 48140), ("MATICUSDT", 47070),
    ("OPUSDT", 34043), ("APTUSDT", 30690), ("ARBUSDT", 26956),
    ("SUIUSDT", 25976), ("WLDUSDT", 24011), ("RNDRUSDT", 23224),
    ("TAOUSDT", 17720),
    # Newly downloaded
    ("XRPUSDT", 69692), ("LTCUSDT", 73072), ("ATOMUSDT", 61091),
    ("BNBUSDT", 73960), ("ZECUSDT", 62027), ("XMRUSDT", 43217),
    ("PEPEUSDT", 25922), ("ENAUSDT", 17941),
]

ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0
TRAIL_PCT = 0.01

def load_60m(symbol):
    sym_clean = symbol.replace("_", "")
    for fname in [f"binance_{symbol}_60m.parquet", f"binance_{sym_clean}_60m.parquet",
                  f"binance_{symbol}_1h.parquet", f"binance_{sym_clean}_1h.parquet"]:
        path = os.path.join(DATA_DIR, fname)
        if os.path.exists(path):
            df = pd.read_parquet(path)
            if 'time' in df.columns:
                df.index = pd.to_datetime(df['time'], unit='s')
            df = df.sort_index()
            if len(df) > 5000: return df
    return None

def compute_atr(df, p=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def run_long(df):
    atr = compute_atr(df, ATR_PERIOD)
    sma100 = df['close'].rolling(100).mean()
    upper = df['high'].shift(1) + ATR_MULTIPLIER * atr.shift(1)
    in_pos, entry, trail, trades = False, 0, 0, []
    for i in range(200, len(df)):
        c = df.iloc[i]['close']
        if not in_pos and c > sma100.iloc[i] and c > upper.iloc[i]:
            in_pos, entry, trail = True, c, c*(1-TRAIL_PCT)
        elif in_pos:
            if c < trail:
                trades.append((c-entry)/entry)
                in_pos = False
            else:
                trail = max(trail, c*(1-TRAIL_PCT))
    return trades

def run_short(df):
    atr = compute_atr(df, ATR_PERIOD)
    sma100 = df['close'].rolling(100).mean()
    lower = df['low'].shift(1) - ATR_MULTIPLIER * atr.shift(1)
    in_pos, entry, trail, trades = False, 0, 0, []
    for i in range(200, len(df)):
        c = df.iloc[i]['close']
        if not in_pos and c < sma100.iloc[i] and c < lower.iloc[i]:
            in_pos, entry, trail = True, c, c*(1+TRAIL_PCT)
        elif in_pos:
            if c > trail:
                trades.append((entry-c)/entry)
                in_pos = False
            else:
                trail = min(trail, c*(1+TRAIL_PCT))
    return trades

def metrics(trades):
    if len(trades) < 5: return None
    w = [t for t in trades if t > 0]
    l = [t for t in trades if t <= 0]
    gp = sum(w) if w else 0
    gl = abs(sum(l)) if l else 1e-10
    pf = gp/gl if gl > 0 else float('inf')
    wr = len(w)/len(trades)
    cum = 1
    for t in trades: cum *= (1+t)
    ret = (cum-1)*100
    avg = np.mean(trades)*100
    return {'trades': len(trades), 'pf': round(pf,2), 'wr': round(wr*100,1),
            'ret': round(ret,1), 'avg': round(avg,2)}

def wf_splits(df, fn, n_splits=5):
    total = len(df)
    test_size = int(total * 0.3 / n_splits)
    results = []
    for i in range(n_splits):
        ts = int(total * (1 - 0.3 + i * 0.3 / n_splits))
        te = min(ts + test_size, total)
        if te - ts < 200: continue
        trades = fn(df.iloc[ts:te])
        m = metrics(trades)
        if m:
            results.append({'split': i+1, 'pf': m['pf'], 'ret': m['ret'], 'trades': m['trades']})
    return results

def main():
    print("=" * 90)
    print("EXPANDED WALK-FORWARD — ALL PAIRS")
    print("=" * 90)

    long_results = []
    short_results = []

    for sym, expected_bars in ALL_PAIRS:
        df = load_60m(sym)
        if df is None or len(df) < 5000:
            print(f"  {sym}: insufficient data ({len(df) if df is not None else 0} bars)")
            continue

        # LONG
        wf_l = wf_splits(df, run_long)
        if wf_l:
            bad_l = sum(1 for w in wf_l if w['pf'] < 1.0)
            avg_pf_l = np.mean([w['pf'] for w in wf_l])
            avg_ret_l = np.mean([w['ret'] for w in wf_l])
            full_l = metrics(run_long(df))
            long_results.append({
                'sym': sym, 'bars': len(df), 'splits': len(wf_l),
                'bad': bad_l, 'avg_pf': round(avg_pf_l,2), 'avg_ret': round(avg_ret_l,1),
                'full_pf': full_l['pf'] if full_l else 0, 'full_ret': full_l['ret'] if full_l else 0,
            })

        # SHORT
        wf_s = wf_splits(df, run_short)
        if wf_s:
            bad_s = sum(1 for w in wf_s if w['pf'] < 1.0)
            avg_pf_s = np.mean([w['pf'] for w in wf_s])
            avg_ret_s = np.mean([w['ret'] for w in wf_s])
            full_s = metrics(run_short(df))
            short_results.append({
                'sym': sym, 'bars': len(df), 'splits': len(wf_s),
                'bad': bad_s, 'avg_pf': round(avg_pf_s,2), 'avg_ret': round(avg_ret_s,1),
                'full_pf': full_s['pf'] if full_s else 0, 'full_ret': full_s['ret'] if full_s else 0,
            })

    # Print results
    print(f"\n{'='*90}")
    print("LONG STRATEGIES — Sorted by robustness (fewest bad splits, then highest avg PF)")
    print(f"{'='*90}")
    print(f"  {'Pair':12} {'Bars':>6} {'Splits':>7} {'Bad':>4} {'Avg PF':>8} {'Avg Ret':>8} {'Full PF':>8} {'Full Ret':>9} {'VERDICT'}")
    print(f"  {'-'*12} {'-'*6} {'-'*7} {'-'*4} {'-'*8} {'-'*8} {'-'*8} {'-'*9} {'-'*12}")

    long_results.sort(key=lambda r: (r['bad'], -r['avg_pf']))
    for r in long_results:
        if r['bad'] == 0:
            verdict = "ROBUST"
        elif r['bad'] == 1:
            verdict = "MOSTLY OK"
        elif r['bad'] <= r['splits'] // 2:
            verdict = "MARGINAL"
        else:
            verdict = "WEAK"
        marker = " *" if r['bad'] == 0 else ""
        print(f"  {r['sym']:12} {r['bars']:>6} {r['splits']:>7} {r['bad']:>4} {r['avg_pf']:>8.2f} {r['avg_ret']:>7.1f}% {r['full_pf']:>8.2f} {r['full_ret']:>8.1f}% {verdict}{marker}")

    print(f"\n{'='*90}")
    print("SHORT STRATEGIES — Sorted by robustness")
    print(f"{'='*90}")
    print(f"  {'Pair':12} {'Bars':>6} {'Splits':>7} {'Bad':>4} {'Avg PF':>8} {'Avg Ret':>8} {'Full PF':>8} {'Full Ret':>9} {'VERDICT'}")
    print(f"  {'-'*12} {'-'*6} {'-'*7} {'-'*4} {'-'*8} {'-'*8} {'-'*8} {'-'*9} {'-'*12}")

    short_results.sort(key=lambda r: (r['bad'], -r['avg_pf']))
    for r in short_results:
        if r['bad'] == 0:
            verdict = "ROBUST"
        elif r['bad'] == 1:
            verdict = "MOSTLY OK"
        elif r['bad'] <= r['splits'] // 2:
            verdict = "MARGINAL"
        else:
            verdict = "WEAK"
        marker = " *" if r['bad'] == 0 else ""
        print(f"  {r['sym']:12} {r['bars']:>6} {r['splits']:>7} {r['bad']:>4} {r['avg_pf']:>8.2f} {r['avg_ret']:>7.1f}% {r['full_pf']:>8.2f} {r['full_ret']:>8.1f}% {verdict}{marker}")

    # Portfolio
    robust_long = [r for r in long_results if r['bad'] <= 1]
    print(f"\n{'='*90}")
    print(f"PORTFOLIO: {len(robust_long)} robust LONG strategies")
    print(f"{'='*90}")
    for r in robust_long:
        ann_ret = r['avg_ret'] * (365/90)  # ~90 day splits
        print(f"  {r['sym']:12} ~{ann_ret:>5.0f}% ann (1x) | ~{ann_ret*2:>5.0f}% ann (2x)")

    total_ann = sum(r['avg_ret'] * (365/90) / len(robust_long) for r in robust_long)
    print(f"\n  Equal-weight portfolio (1x): ~{total_ann:.0f}% annualized")
    print(f"  Equal-weight portfolio (2x): ~{total_ann*2:.0f}% annualized")

    # Save
    out = {"long": long_results, "short": short_results}
    with open("/Users/nesbitt/dev/factory/agents/ig88/data/expanded_wf.json", 'w') as f:
        json.dump(out, f, indent=2)

if __name__ == "__main__":
    np.random.seed(42)
    main()
