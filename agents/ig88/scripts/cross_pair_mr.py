#!/usr/bin/env python3
"""
Cross-Pair MR Filter Test v2
=============================
The original MR signal is too rare for cross-pair filtering.

Instead, we use a LOOSER base MR signal and test whether cross-pair
conditions improve the win rate / profit factor of those signals.

Base signal: RSI < 40 AND price <= BB_lower * 1.01 (any oversold + near BB)
Cross-pair filters test whether market regime conditions help select better signals.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
OUT_PATH = DATA_DIR / "edge_discovery" / "cross_pair_mr.json"
PAIRS = ["SOL", "AVAX", "ETH", "LINK", "BTC"]
FRICTION = 0.005
N_SPLITS = 5

def load_all_pairs():
    data = {}
    for pair in PAIRS:
        path = DATA_DIR / f"binance_{pair}_USDT_240m.parquet"
        if not path.exists():
            path = DATA_DIR / f"binance_{pair}USDT_240m.parquet"
        df = pd.read_parquet(path)
        if "timestamp" not in df.columns:
            if "time" in df.columns:
                df = df.rename(columns={"time": "timestamp"})
            else:
                df = df.reset_index()
                if "datetime" in df.columns:
                    df = df.rename(columns={"datetime": "timestamp"})
        df = df.sort_values("timestamp").reset_index(drop=True)
        data[pair] = df
        print(f"  {pair}: {len(df)} bars")
    return data

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def bollinger(series, period=20, std_mult=2):
    sma = series.rolling(period, min_periods=period).mean()
    std = series.rolling(period, min_periods=period).std()
    return sma - std_mult * std, sma, sma + std_mult * std

def adx(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    up = h - h.shift(1)
    dn = l.shift(1) - l
    pdm = ((up > dn) & (up > 0)).astype(float) * up.clip(lower=0)
    ndm = ((dn > up) & (dn > 0)).astype(float) * dn.clip(lower=0)
    atr = tr.rolling(period, min_periods=period).mean()
    pdi = 100 * pdm.rolling(period).mean() / atr
    mdi = 100 * ndm.rolling(period).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.rolling(period).mean()

def compute_indicators(df):
    c = df["close"]
    bb_lo, bb_mid, bb_up = bollinger(c)
    vol_sma = df["volume"].rolling(20, min_periods=20).mean()
    return pd.DataFrame({
        "close": c, "open": df["open"],
        "rsi": rsi(c),
        "bb_lower": bb_lo, "bb_mid": bb_mid, "bb_upper": bb_up,
        "vol_ratio": df["volume"] / vol_sma.replace(0, np.nan),
        "adx": adx(df),
        "ema50": c.ewm(span=50, min_periods=50).mean(),
        "ema20": c.ewm(span=20, min_periods=20).mean(),
        "timestamp": df["timestamp"],
    })

def align_pairs(indicators):
    common = set(indicators[PAIRS[0]]["timestamp"])
    for p in PAIRS[1:]:
        common &= set(indicators[p]["timestamp"])
    common = sorted(common)
    aligned = {}
    for p in PAIRS:
        aligned[p] = indicators[p].set_index("timestamp").loc[common].reset_index(drop=True)
    print(f"  Common bars: {len(common)}")
    return aligned

def build_all(aligned):
    n = len(aligned[PAIRS[0]])

    # Per-pair indicators (vectorized)
    ind = {}
    for p in PAIRS:
        df = aligned[p]
        ind[p] = {
            "rsi": df["rsi"].values,
            "close": df["close"].values,
            "bb_lower": df["bb_lower"].values,
            "bb_mid": df["bb_mid"].values,
            "vol_ratio": df["vol_ratio"].values,
            "adx": df["adx"].values,
            "ema50": df["ema50"].values,
            "open": df["open"].values,
        }

    # === LOOSE MR SIGNAL ===
    # RSI < 40 AND price within 1% of BB lower
    # This gives us enough signals to test cross-pair filtering
    base_mr = {}
    for p in PAIRS:
        r = ind[p]["rsi"]
        bl = ind[p]["bb_lower"]
        c = ind[p]["close"]
        vr = ind[p]["vol_ratio"]
        base_mr[p] = (
            ~np.isnan(r) & (r < 40) &
            ~np.isnan(bl) & (c <= bl * 1.01) &
            ~np.isnan(vr)
        )

    # === STRICT MR SIGNAL (original) ===
    strict_mr = {}
    for p in PAIRS:
        r = ind[p]["rsi"]
        bl = ind[p]["bb_lower"]
        c = ind[p]["close"]
        vr = ind[p]["vol_ratio"]
        o = ind[p]["open"]
        # Reversal candle: close > open and prev close < prev open
        reversal = np.zeros(n, dtype=bool)
        reversal[1:] = (c[1:] > o[1:]) & (c[:-1] < o[:-1])
        strict_mr[p] = (
            ~np.isnan(r) & (r < 35) &
            ~np.isnan(bl) & (c <= bl * 1.005) &
            reversal & ~np.isnan(vr) & (vr > 1.2)
        )

    # === CROSS-PAIR CONDITIONS ===
    # Count pairs in loose MR per bar
    mr_count_loose = sum(base_mr[p].astype(int) for p in PAIRS)
    mr_count_strict = sum(strict_mr[p].astype(int) for p in PAIRS)

    # Ranging regime (ADX < 25)
    ranging = {}
    for p in PAIRS:
        a = ind[p]["adx"]
        ranging[p] = ~np.isnan(a) & (a < 25)
    ranging_count = sum(ranging[p].astype(int) for p in PAIRS)

    # BTC conditions
    btc = ind["BTC"]
    btc_not_downtrend = ~np.isnan(btc["ema50"]) & (btc["close"] >= btc["ema50"])
    btc_rsi_ok = np.isnan(btc["rsi"]) | (btc["rsi"] > 30)
    btc_rsi_oversold = ~np.isnan(btc["rsi"]) & (btc["rsi"] < 40)

    # === FILTER DEFINITIONS ===
    # We test two base signals x multiple filters
    filters = {}

    # With LOOSE base signal
    filters["loose_unfiltered"] = np.ones(n, dtype=bool)
    filters["loose_btc_ok"] = btc_not_downtrend
    filters["loose_3ranging"] = ranging_count >= 3
    filters["loose_btc_rsi_ok"] = btc_rsi_ok
    filters["loose_combo1"] = btc_not_downtrend & (ranging_count >= 3) & btc_rsi_ok
    filters["loose_combo2"] = btc_not_downtrend & (mr_count_loose >= 2)
    filters["loose_combo3"] = btc_not_downtrend & (ranging_count >= 3) & (mr_count_loose >= 2)
    filters["loose_no_panic"] = btc_not_downtrend & (btc["rsi"] > 25)  # BTC not in panic

    # With STRICT base signal
    filters["strict_unfiltered"] = np.ones(n, dtype=bool)
    filters["strict_btc_ok"] = btc_not_downtrend
    filters["strict_3ranging"] = ranging_count >= 3

    print(f"\n  MR signals (loose per pair): {', '.join(f'{p}={base_mr[p].sum()}' for p in PAIRS)}")
    print(f"  MR signals (strict per pair): {', '.join(f'{p}={strict_mr[p].sum()}' for p in PAIRS)}")
    print(f"  Bars with 2+ loose MR: {(mr_count_loose >= 2).sum()}")
    print(f"  Bars with 3+ ranging: {(ranging_count >= 3).sum()}")
    print(f"  BTC not downtrend: {btc_not_downtrend.sum()}")

    return base_mr, strict_mr, filters, ind

def simulate(close_arr, signals, friction, hold=3):
    trades = []
    n = len(close_arr)
    i = 0
    while i < n:
        if signals[i] and i + 1 < n:
            entry = close_arr[i + 1]
            ex = min(i + 1 + hold, n - 1)
            exit_p = close_arr[ex]
            ret = (exit_p - entry) / entry - friction
            trades.append(ret)
            i = ex + 1
        else:
            i += 1
    return trades

def metrics(trades):
    if len(trades) == 0:
        return {"n": 0, "pf": 0, "wr": 0, "avg_ret_pct": 0}
    arr = np.array(trades)
    w = arr[arr > 0]
    l = arr[arr <= 0]
    gp = w.sum() if len(w) > 0 else 0
    gl = abs(l.sum()) if len(l) > 0 else 1e-10
    return {
        "n": len(trades),
        "pf": round(float(gp / gl), 3),
        "wr": round(float(len(w) / len(arr)), 3),
        "avg_ret_pct": round(float(arr.mean() * 100), 3),
    }

def run_walk_forward(aligned, base_mr, strict_mr, filters, ind):
    n = len(aligned[PAIRS[0]])
    split_size = n // (N_SPLITS + 1)
    trade_pairs = [p for p in PAIRS if p != "BTC"]

    results = {fname: [] for fname in filters}

    for si in range(N_SPLITS):
        t0 = split_size * (si + 1)
        t1 = min(t0 + split_size, n)
        if t1 - t0 < 10:
            continue

        for fname, filt in filters.items():
            split_trades = []
            use_strict = fname.startswith("strict_")
            mr = strict_mr if use_strict else base_mr

            for pair in trade_pairs:
                sigs = mr[pair] & filt
                sigs = sigs.copy()
                sigs[:t0] = False
                sigs[t1:] = False
                tr = simulate(ind[pair]["close"], sigs, FRICTION)
                split_trades.extend(tr)

            results[fname].append(metrics(split_trades))

    return results

def main():
    print("=" * 60)
    print("CROSS-PAIR MR FILTER TEST v2")
    print("=" * 60)

    raw = load_all_pairs()
    indicators = {p: compute_indicators(raw[p]) for p in PAIRS}
    aligned = align_pairs(indicators)
    n = len(aligned[PAIRS[0]])

    print("\nBuilding signals...")
    base_mr, strict_mr, filters, ind = build_all(aligned)

    print("\nWalk-forward testing...")
    wf = run_walk_forward(aligned, base_mr, strict_mr, filters, ind)

    # Aggregate
    def agg(splits):
        if not splits:
            return {"avg_pf": 0, "med_pf": 0, "std_pf": 0, "total_n": 0, "avg_wr": 0}
        pfs = [s["pf"] for s in splits if s["n"] > 0]
        wrs = [s["wr"] for s in splits if s["n"] > 0]
        return {
            "avg_pf": round(float(np.mean(pfs)), 3) if pfs else 0,
            "med_pf": round(float(np.median(pfs)), 3) if pfs else 0,
            "std_pf": round(float(np.std(pfs)), 3) if pfs else 0,
            "avg_wr": round(float(np.mean(wrs)), 3) if wrs else 0,
            "total_n": sum(s["n"] for s in splits),
        }

    all_agg = {fname: agg(splits) for fname, splits in wf.items()}

    # Compare loose filters against loose_unfiltered
    loose_base_pf = all_agg["loose_unfiltered"]["avg_pf"]
    strict_base_pf = all_agg["strict_unfiltered"]["avg_pf"]

    per_filter = {}
    for fname in filters:
        a = all_agg[fname]
        base = strict_base_pf if fname.startswith("strict_") else loose_base_pf
        per_filter[fname] = {
            **a,
            "pf_delta": round(a["avg_pf"] - base, 3),
            "improves": a["avg_pf"] > base and a["total_n"] > 0,
        }

    # Find best loose filter
    loose_filters = {k: v for k, v in per_filter.items() if k.startswith("loose_") and k != "loose_unfiltered"}
    best_loose = max(loose_filters, key=lambda k: loose_filters[k]["avg_pf"]) if loose_filters else "none"
    best_loose_pf = loose_filters[best_loose]["avg_pf"] if loose_filters else 0

    output = {
        "test": "cross_pair_mr_filter_v2",
        "description": "Tests cross-pair regime filters on MR signals",
        "config": {
            "pairs": PAIRS, "friction": FRICTION,
            "loose_signal": "RSI<40 AND price<=BB_lower*1.01",
            "strict_signal": "RSI<35 AND price<=BB_lower*1.005 AND reversal AND vol>1.2x",
            "hold_bars": 3, "n_splits": N_SPLITS,
        },
        "filter_descriptions": {
            "loose_btc_ok": "BTC price >= EMA50 (not downtrend)",
            "loose_3ranging": "3+ of 5 pairs ADX < 25 (ranging)",
            "loose_btc_rsi_ok": "BTC RSI > 30 (not panic)",
            "loose_combo1": "BTC ok + 3 ranging + BTC RSI>30",
            "loose_combo2": "BTC ok + 2+ pairs in MR",
            "loose_combo3": "BTC ok + 3 ranging + 2+ MR",
            "loose_no_panic": "BTC ok + BTC RSI > 25",
            "strict_btc_ok": "Strict MR + BTC ok",
            "strict_3ranging": "Strict MR + 3 ranging",
        },
        "results": per_filter,
        "summary": {
            "loose_unfiltered_pf": loose_base_pf,
            "strict_unfiltered_pf": strict_base_pf,
            "best_loose_filter": best_loose,
            "best_loose_pf": best_loose_pf,
            "best_loose_delta": round(best_loose_pf - loose_base_pf, 3),
            "strict_improves_over_loose": strict_base_pf > loose_base_pf,
            "conclusion": "",
        },
    }

    # Build conclusion
    s = output["summary"]
    if s["best_loose_delta"] > 0.05:
        s["conclusion"] = (
            f"YES - Cross-pair filter improves PF. Best filter '{s['best_loose_filter']}' "
            f"achieves PF={s['best_loose_pf']:.3f} vs unfiltered {s['loose_unfiltered_pf']:.3f} "
            f"(+{s['best_loose_delta']:.3f}). Filter removes bad signals during adverse market conditions."
        )
    elif s["best_loose_delta"] > 0:
        s["conclusion"] = (
            f"MARGINAL - Best filter '{s['best_loose_filter']}' shows slight improvement "
            f"PF={s['best_loose_pf']:.3f} vs {s['loose_unfiltered_pf']:.3f} (+{s['best_loose_delta']:.3f}). "
            f"Effect is small, likely due to limited sample size."
        )
    else:
        s["conclusion"] = (
            f"NO - No cross-pair filter improves PF over unfiltered. "
            f"Best filter PF={s['best_loose_pf']:.3f} vs unfiltered {s['loose_unfiltered_pf']:.3f}. "
            f"The MR signal's edge is pair-specific, not regime-dependent."
        )

    if s["strict_improves_over_loose"]:
        s["conclusion"] += (
            f" Note: Strict MR (PF={s['strict_unfiltered_pf']:.3f}) outperforms "
            f"loose MR (PF={s['loose_unfiltered_pf']:.3f}), suggesting signal quality matters more than cross-pair confirmation."
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"SAVED: {OUT_PATH}")
    print(f"{'='*60}")
    print(f"\nResults (LOOSE signal, filters applied):")
    print(f"  {'Filter':<22} {'PF':>6} {'WR':>6} {'Trades':>7} {'Delta':>7}")
    print(f"  {'-'*50}")
    for fname in [k for k in per_filter if k.startswith("loose_")]:
        d = per_filter[fname]
        marker = " *" if fname == best_loose else ""
        print(f"  {fname:<22} {d['avg_pf']:>6.3f} {d['avg_wr']:>6.3f} {d['total_n']:>7d} {d['pf_delta']:>+7.3f}{marker}")

    print(f"\nResults (STRICT signal):")
    for fname in [k for k in per_filter if k.startswith("strict_")]:
        d = per_filter[fname]
        print(f"  {fname:<22} {d['avg_pf']:>6.3f} {d['avg_wr']:>6.3f} {d['total_n']:>7d} {d['pf_delta']:>+7.3f}")

    print(f"\n{s['conclusion']}")

if __name__ == "__main__":
    main()
