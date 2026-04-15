"""
MR Strategy Grid Search Optimization - Fast Version
Precomputes all indicators once, then does fast threshold-based grid search.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd
import src.quant.indicators as ind
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"
CAPITAL = 10_000.0
FRICTION = 0.0050

PAIRS = {
    "SOL": "SOL/USDT",
    "AVAX": "AVAX/USDT",
    "ETH": "ETH/USDT",
    "LINK": "LINK/USDT",
    "BTC": "BTC/USD",
}

ATR_LOW_THRESH = 0.02
ATR_HIGH_THRESH = 0.04


def load_pair(pair_name):
    symbol = PAIRS[pair_name]
    safe = symbol.replace("/", "_")
    p = DATA_DIR / f"binance_{safe}_240m.parquet"
    return pd.read_parquet(p).sort_index()


def df_to_arrays(df):
    ts = df.index.astype("int64").values / 1e9
    return (ts, df["open"].values.astype(float), df["high"].values.astype(float),
            df["low"].values.astype(float), df["close"].values.astype(float),
            df["volume"].values.astype(float))


def precompute_all(o, h, l, c, v):
    """Precompute all indicators once. Returns dict of arrays."""
    rsi_vals = ind.rsi(c, 14)
    vol_sma = ind.sma(v, 20)
    atr_vals = ind.atr(h, l, c, 14)
    atr_pct = atr_vals / c

    # Bollinger Bands at multiple std devs
    bb_075 = ind.bollinger_bands(c, period=20, mult=0.75)
    bb_100 = ind.bollinger_bands(c, period=20, mult=1.0)
    bb_125 = ind.bollinger_bands(c, period=20, mult=1.25)
    bb_150 = ind.bollinger_bands(c, period=20, mult=1.5)

    bb_lower = {
        0.75: bb_075.lower,
        1.0: bb_100.lower,
        1.25: bb_125.lower,
        1.5: bb_150.lower,
    }

    # Reversal candle (close > open)
    reversal = c > o

    return {
        "rsi": rsi_vals,
        "vol_sma": vol_sma,
        "atr_pct": atr_pct,
        "bb_lower": bb_lower,
        "reversal": reversal,
    }


def make_signal_mask(indicators, params, n, start=0):
    """
    Fast signal mask from precomputed indicators.
    Indicators are full-length arrays. We slice from start to start+n.
    """
    end = start + n
    rsi = indicators["rsi"][start:end]
    bb_l = indicators["bb_lower"][params["bb_std"]][start:end]
    vol_sma = indicators["vol_sma"][start:end]
    v = indicators["_v"][start:end]
    c = indicators["_c"][start:end]
    rev = indicators["reversal"][start:end]

    warmup = 21

    rsi_ok = np.zeros(n, dtype=bool)
    bb_ok = np.zeros(n, dtype=bool)
    vol_ok = np.zeros(n, dtype=bool)

    rsi_ok[warmup:] = ~np.isnan(rsi[warmup:]) & (rsi[warmup:] < params["rsi_thresh"])
    bb_ok[warmup:] = ~np.isnan(bb_l[warmup:]) & (c[warmup:] <= bb_l[warmup:])
    vol_ok[warmup:] = ~np.isnan(vol_sma[warmup:]) & (v[warmup:] > params["vol_mult"] * vol_sma[warmup:])

    if params["reversal_candle"]:
        return rsi_ok & bb_ok & vol_ok & rev
    else:
        return rsi_ok & bb_ok & vol_ok


def run_backtest_fast(ts, o, h, l, c, signal_mask, atr_pct, params):
    """Fast backtester. Returns list of trade dicts."""
    n = len(ts)

    # Regime
    regime = np.full(n, 1, dtype=int)
    regime[atr_pct < ATR_LOW_THRESH] = 0
    regime[atr_pct > ATR_HIGH_THRESH] = 2

    stop_map = {0: params["low_stop"], 1: params["mid_stop"], 2: params["high_stop"]}
    target_map = {0: params["low_target"], 1: params["mid_target"], 2: params["high_target"]}

    trades = []
    i = 21
    last_exit = -999
    counter = 0

    while i < n - 2:
        if i - last_exit < 1:
            i += 1
            continue
        if not signal_mask[i]:
            i += 1
            continue

        eb = i + 1
        if eb >= n:
            break

        ep = o[eb]
        reg = regime[i]
        stop_pct = stop_map[reg]
        target_pct = target_map[reg]
        stop_p = ep * (1 - stop_pct)
        target_p = ep * (1 + target_pct)
        time_limit = eb + params["time_exit"]
        pos = CAPITAL * 0.02

        xr = "TIME"
        xb = eb

        for j in range(1, min(params["time_exit"] + 1, n - eb)):
            bar = eb + j
            if bar >= n:
                break
            if l[bar] <= stop_p:
                xb = bar
                xr = "SL"
                break
            if h[bar] >= target_p:
                xb = bar
                xr = "TP"
                break

        if xr == "TIME":
            xb = min(time_limit, n - 1)

        xp = c[xb] if xr == "TIME" else (stop_p if xr == "SL" else target_p)
        pnl_pct = (xp - ep) / ep - FRICTION  # friction applied

        trades.append({
            "pnl_pct": pnl_pct,
            "pnl_dollars": pnl_pct * pos,
            "exit_reason": xr,
        })

        last_exit = xb
        i = xb + 1

    return trades


def compute_stats_fast(trades):
    if not trades:
        return {"n": 0, "pf": 0, "wr": 0, "pnl_pct": 0, "expectancy": 0, "max_dd": 0}
    pnls = np.array([t["pnl_dollars"] for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0)
    wr = len(wins) / len(pnls)

    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    max_dd = dd.max() if len(dd) > 0 else 0

    avg_pnl = np.mean([t["pnl_pct"] for t in trades]) * 100

    return {
        "n": len(trades),
        "pf": round(pf, 4),
        "wr": round(wr, 4),
        "pnl_pct": round(float(pnls.sum() / CAPITAL * 100), 4),
        "expectancy": round(avg_pnl, 4),
        "max_dd": round(float(max_dd / CAPITAL * 100), 4),
    }


# Grid params
GRID_KEYS = ["rsi_thresh", "bb_std", "vol_mult", "reversal_candle",
             "low_stop", "low_target", "mid_stop", "mid_target",
             "high_stop", "high_target", "time_exit"]
GRID_VALS = [
    [25, 30, 35, 40, 45],          # rsi_thresh
    [0.75, 1.0, 1.25, 1.5],        # bb_std
    [1.0, 1.2, 1.5, 2.0],          # vol_mult
    [True, False],                   # reversal_candle
    [0.01, 0.015, 0.02],           # low_stop
    [0.02, 0.03, 0.04],            # low_target
    [0.005, 0.01, 0.015],          # mid_stop
    [0.05, 0.075, 0.10],           # mid_target
    [0.003, 0.005, 0.01],          # high_stop
    [0.05, 0.075, 0.10],           # high_target
    [5, 10, 15, 20],               # time_exit
]

GRID_SIZE = 1
for v in GRID_VALS:
    GRID_SIZE *= len(v)


def grid_search_fast(indicators, ts, o, h, l, c, atr_pct, max_samples=1500, ind_start=0):
    """Fast grid search using precomputed indicators. ind_start is the offset into the full indicator arrays."""
    from itertools import product
    all_combos = list(product(*GRID_VALS))
    rng = np.random.default_rng(42)
    if len(all_combos) > max_samples:
        indices = rng.choice(len(all_combos), max_samples, replace=False)
        all_combos = [all_combos[i] for i in indices]

    n = len(ts)
    best_score = -1
    best_params = None
    best_stats = None

    for combo in all_combos:
        params = dict(zip(GRID_KEYS, combo))

        mask = make_signal_mask(indicators, params, n, start=ind_start)
        n_signals = mask.sum()
        if n_signals < 5:
            continue

        trades = run_backtest_fast(ts, o, h, l, c, mask, atr_pct, params)
        stats = compute_stats_fast(trades)
        if stats["n"] < 5:
            continue

        score = stats["pf"] * np.sqrt(stats["n"])
        if score > best_score:
            best_score = score
            best_params = params
            best_stats = stats

    return best_params, best_stats


def walk_forward_fast(ts, o, h, l, c, v, n_splits=5):
    """Walk-forward with precomputed indicators per segment."""
    n = len(ts)
    segment_size = n // n_splits
    results = []

    for split in range(n_splits):
        split_start = split * segment_size
        split_end = (split + 1) * segment_size if split < n_splits - 1 else n
        split_n = split_end - split_start
        is_n = int(split_n * 0.8)

        s_ts = ts[split_start:split_end]
        s_o = o[split_start:split_end]
        s_h = h[split_start:split_end]
        s_l = l[split_start:split_end]
        s_c = c[split_start:split_end]
        s_v = v[split_start:split_end]

        # Precompute on full segment
        s_ind = precompute_all(s_o, s_h, s_l, s_c, s_v)
        s_ind["_c"] = s_c
        s_ind["_v"] = s_v

        # Grid search on IS (first 80% of segment)
        best_params, is_stats = grid_search_fast(
            s_ind, s_ts[:is_n], s_o[:is_n], s_h[:is_n],
            s_l[:is_n], s_c[:is_n], s_ind["atr_pct"][:is_n],
            max_samples=1200
        )

        if best_params is None:
            results.append({"split": split+1, "is_stats": None,
                          "oos_stats": {"n": 0, "pf": 0, "wr": 0}, "best_params": None})
            continue

        # Apply to OOS (last 20% of segment)
        mask_full = make_signal_mask(s_ind, best_params, split_n)
        mask_oos = mask_full[is_n:]
        oos_trades = run_backtest_fast(
            s_ts[is_n:], s_o[is_n:], s_h[is_n:], s_l[is_n:],
            s_c[is_n:], mask_oos, s_ind["atr_pct"][is_n:], best_params
        )
        oos_stats = compute_stats_fast(oos_trades)

        print(f"    Split {split+1}: IS PF={is_stats['pf']:.2f} N={is_stats['n']}  "
              f"OOS PF={oos_stats['pf']:.2f} N={oos_stats['n']}")

        results.append({
            "split": split+1,
            "is_stats": is_stats,
            "oos_stats": oos_stats,
            "best_params": best_params,
        })

    return results


def main():
    print("=" * 70)
    print("MR STRATEGY GRID SEARCH OPTIMIZATION (Fast)")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)
    print(f"Pairs: {list(PAIRS.keys())}")
    print(f"Friction: {FRICTION*100:.2f}% round-trip")
    print(f"Grid space: {GRID_SIZE:,} combinations (sampling 1500 per run)")
    print()

    all_results = {}
    wf_results = {}

    for pair_name in PAIRS:
        t0 = time.time()
        print(f"\n{'='*60}")
        print(f"PAIR: {pair_name}")
        print(f"{'='*60}")

        try:
            df = load_pair(pair_name)
        except FileNotFoundError as e:
            print(f"  Data not found: {e}")
            continue

        ts, o, h, l, c, v = df_to_arrays(df)
        n = len(ts)
        split_idx = int(n * 0.8)

        print(f"  Data: {n} bars, {df.index[0]} to {df.index[-1]}")
        print(f"  Train: {split_idx} bars | Test: {n - split_idx} bars")

        # Precompute indicators
        t1 = time.time()
        indicators = precompute_all(o, h, l, c, v)
        indicators["_c"] = c
        indicators["_v"] = v
        atr_pct = indicators["atr_pct"]
        print(f"  Indicators: {time.time()-t1:.1f}s")

        # Grid search on train
        print(f"  Running grid search on train set...")
        t2 = time.time()
        best_params, train_stats = grid_search_fast(
            indicators, ts[:split_idx], o[:split_idx], h[:split_idx],
            l[:split_idx], c[:split_idx], atr_pct[:split_idx], max_samples=1500,
            ind_start=0
        )
        t_gs = time.time() - t2
        print(f"  Grid search: {t_gs:.1f}s")

        if best_params is None:
            print("  No valid params found!")
            continue

        print(f"  Best params:")
        for k, val in best_params.items():
            print(f"    {k}: {val}")
        print(f"  Train: PF={train_stats['pf']:.2f} WR={train_stats['wr']:.2f} N={train_stats['n']}")

        # Apply to test
        test_mask = make_signal_mask(indicators, best_params, n - split_idx, start=split_idx)
        test_trades = run_backtest_fast(
            ts[split_idx:], o[split_idx:], h[split_idx:],
            l[split_idx:], c[split_idx:], test_mask, atr_pct[split_idx:], best_params
        )
        test_stats = compute_stats_fast(test_trades)
        degrade = (1 - test_stats['pf']/train_stats['pf'])*100 if train_stats['pf'] > 0 else 0

        print(f"  Test:  PF={test_stats['pf']:.2f} WR={test_stats['wr']:.2f} N={test_stats['n']}")
        print(f"  Degradation: {degrade:.1f}%")

        all_results[pair_name] = {
            "best_params": best_params,
            "train_stats": train_stats,
            "test_stats": test_stats,
            "degradation_pct": round(degrade, 1),
        }

        # Walk-forward
        print(f"  Walk-forward (5 splits)...")
        wf = walk_forward_fast(ts, o, h, l, c, v, n_splits=5)
        oos_pfs = [r["oos_stats"]["pf"] for r in wf if r["oos_stats"]["n"] >= 3]
        avg_oos = np.mean(oos_pfs) if oos_pfs else 0
        total_oos = sum(r["oos_stats"]["n"] for r in wf)

        wf_results[pair_name] = {"splits": wf, "avg_oos_pf": round(avg_oos, 2), "total_oos": total_oos}
        print(f"  WF OOS: avg PF={avg_oos:.2f}, total trades={total_oos}")
        print(f"  Pair time: {time.time()-t0:.1f}s")

    # --- Report ---
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"\n{'Pair':<8} {'Train PF':>9} {'Test PF':>8} {'Degrade%':>9} {'WF OOS PF':>10} {'WF Trades':>10}")
    print("-" * 56)

    test_pfs = []
    wf_pfs = []

    for pair_name in all_results:
        r = all_results[pair_name]
        w = wf_results.get(pair_name, {})
        print(f"{pair_name:<8} {r['train_stats']['pf']:>9.2f} {r['test_stats']['pf']:>8.2f} "
              f"{r['degradation_pct']:>8.1f}% {w.get('avg_oos_pf', 0):>10.2f} {w.get('total_oos', 0):>10}")
        if r['test_stats']['n'] >= 5:
            test_pfs.append(r['test_stats']['pf'])
        if w.get('total_oos', 0) >= 5:
            wf_pfs.append(w.get('avg_oos_pf', 0))

    avg_test = np.mean(test_pfs) if test_pfs else 0
    avg_wf = np.mean(wf_pfs) if wf_pfs else 0

    print(f"\nAvg test PF: {avg_test:.2f}")
    print(f"Avg WF OOS PF: {avg_wf:.2f}")
    print(f"Baseline PF: 3.01")

    beats_test = avg_test > 3.01
    beats_wf = avg_wf > 3.01
    print(f"\nBeats 3.01 on test? {'YES' if beats_test else 'NO'}")
    print(f"Beats 3.01 on WF OOS? {'YES' if beats_wf else 'NO'}")

    # Save
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": "grid_search_fast_80_20_with_walkforward",
        "pairs": list(PAIRS.keys()),
        "friction": FRICTION,
        "grid_size": GRID_SIZE,
        "sample_per_run": 1500,
        "pair_results": {},
        "walk_forward_results": {},
        "summary": {
            "avg_test_pf": round(avg_test, 2),
            "avg_wf_oos_pf": round(avg_wf, 2),
            "baseline_pf": 3.01,
            "beats_baseline_test": beats_test,
            "beats_baseline_wf": beats_wf,
        },
    }

    for pn in all_results:
        r = all_results[pn]
        output["pair_results"][pn] = {
            "best_params": {k: float(v) if isinstance(v, float) else v for k, v in r["best_params"].items()},
            "train_stats": r["train_stats"],
            "test_stats": r["test_stats"],
            "degradation_pct": r["degradation_pct"],
        }

    for pn in wf_results:
        r = wf_results[pn]
        output["walk_forward_results"][pn] = {
            "avg_oos_pf": r["avg_oos_pf"],
            "total_oos_trades": r["total_oos"],
            "splits": [
                {
                    "split": s["split"],
                    "is_stats": s["is_stats"],
                    "oos_stats": s["oos_stats"],
                    "best_params": {k: float(v) if isinstance(v, float) else v
                                   for k, v in s["best_params"].items()} if s["best_params"] else None,
                }
                for s in r["splits"]
            ],
        }

    out_path = DATA_DIR / "edge_discovery" / "mr_optimization.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
