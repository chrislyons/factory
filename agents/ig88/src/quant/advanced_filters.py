"""
advanced_filters.py — Second-pass filter testing: StochRSI, Fibonacci,
multi-timeframe confluence, and Donchian breakout.

Tests whether these filters add independent information on top of
the H3-A signal (rsi_55 + ichi_score3).

Also tests a combined daily+4h timeframe version: take 4h signals only
when the DAILY Ichimoku is also bullish (multi-timeframe confluence).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

import src.quant.indicators as ind
from src.quant.convergence_backtest import (
    IndicatorCache, ConvergenceBacktester, build_filters, run_filter_test
)
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade
from src.quant.regime import RegimeState

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"
MAKER_FEE = 0.0016


# ---------------------------------------------------------------------------
# Advanced filter builder
# ---------------------------------------------------------------------------

def build_advanced_filters(ic: IndicatorCache) -> dict[str, np.ndarray]:
    """Additional filters not included in the first pass."""
    n = len(ic.c)
    filters = {}

    # StochRSI filters
    k, d = ic.srsi_k, ic.srsi_d
    filters["srsi_k50"]     = (~np.isnan(k)) & (k > 50)
    filters["srsi_k_cross"] = np.array([
        (i > 0 and not np.isnan(k[i]) and not np.isnan(d[i])
         and not np.isnan(k[i-1]) and not np.isnan(d[i-1])
         and k[i] > d[i] and k[i-1] <= d[i-1])
        for i in range(n)
    ])
    # StochRSI not overbought (avoid chasing)
    filters["srsi_not_ob"]  = (~np.isnan(k)) & (k < 80)

    # Fibonacci: price within 3% of a Fib support level
    fibs = ind.auto_fib_levels(ic.h, ic.l, depth=10)
    fib_near = np.zeros(n, dtype=bool)
    if fibs:
        fib_prices = list(fibs.values())
        for i in range(n):
            for fp in fib_prices:
                if abs(ic.c[i] - fp) / ic.c[i] < 0.03:  # within 3%
                    fib_near[i] = True
                    break
    filters["fib_support"]  = fib_near

    # Donchian breakout: close > 20-period Donchian upper
    upper_dc, _, _ = ind.donchian_channel(ic.h, ic.l, period=20)
    # Breakout = today's close exceeds yesterday's upper channel
    dc_break = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(upper_dc[i-1]) and ic.c[i] > upper_dc[i-1]:
            dc_break[i] = True
    filters["dc_breakout"]  = dc_break

    # VWAP: price above VWAP (using close as proxy for typical price)
    try:
        vwap_line, vwap_up, vwap_dn = ind.vwap_bands(ic.c, ic.v, ic.h, ic.l)
        filters["above_vwap"] = (~np.isnan(vwap_line)) & (ic.c > vwap_line)
    except Exception:
        filters["above_vwap"] = np.zeros(n, dtype=bool)

    # Bollinger squeeze breakout: %B > 0.7 (in upper 30% of BB)
    filters["bb_upper30"]   = (~np.isnan(ic.bb_pctb)) & (ic.bb_pctb > 0.7)

    # RSI momentum: RSI rising (current > previous bar's RSI)
    rsi_rising = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(ic.rsi[i]) and not np.isnan(ic.rsi[i-1]):
            rsi_rising[i] = ic.rsi[i] > ic.rsi[i-1]
    filters["rsi_rising"]   = rsi_rising

    # Combined volume: OBV slope + Klinger bullish (both volume indicators agree)
    filters["vol_confluence"] = ic.obv_slope > 0
    for i in range(n):
        if not (not np.isnan(ic.klinger_kvo[i]) and not np.isnan(ic.klinger_sig[i])
                and ic.klinger_kvo[i] > ic.klinger_sig[i]):
            filters["vol_confluence"][i] = False

    return filters


# ---------------------------------------------------------------------------
# Multi-timeframe confluence: 4h entry confirmed by daily Ichimoku
# ---------------------------------------------------------------------------

def build_daily_regime_mask(daily_df: pd.DataFrame, intraday_ts: np.ndarray) -> np.ndarray:
    """
    For each 4h bar timestamp, look up the most recent daily bar and check
    whether the daily Ichimoku is bullish (score >= 2, price above cloud).
    Returns a boolean mask of length len(intraday_ts).
    """
    _, o_d, h_d, l_d, c_d, v_d = df_to_arrays(daily_df)
    daily_ts = daily_df.index.astype("int64").values / 1e9

    # Compute daily Ichimoku
    ichi_d = ind.ichimoku(h_d, l_d, c_d)
    score_d = ind.ichimoku_composite_score(ichi_d, c_d)
    cloud_top_d = ichi_d.cloud_top

    n_intraday = len(intraday_ts)
    mask = np.zeros(n_intraday, dtype=bool)

    for j, ts in enumerate(intraday_ts):
        # Find latest daily bar <= this 4h timestamp
        idx = np.searchsorted(daily_ts, ts, side="right") - 1
        if idx < 0:
            continue
        # Daily bullish: score >= 2 AND price above cloud
        if (score_d[idx] >= 2
                and not np.isnan(cloud_top_d[idx])
                and c_d[idx] > cloud_top_d[idx]):
            mask[j] = True

    return mask


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 72)
    print("ADVANCED FILTER TESTING + MULTI-TIMEFRAME CONFLUENCE")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    # Load data
    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    sol4h_df = load_binance("SOL/USDT", 240)
    sol1d_df = load_binance("SOL/USDT", 1440)

    ts, o, h, l, c, v = df_to_arrays(sol4h_df)
    n = len(ts)
    SPLIT = int(n * 0.70)

    regime = build_btc_trend_regime(btc_c, ts, btc_ts)

    # Current winning base mask: rsi_55 + ichi_score3
    print(f"\nBase combo: rsi_55 + ichi_score3 on SOL 4h")
    print(f"Train: {datetime.fromtimestamp(ts[0], tz=timezone.utc).date()} -> {datetime.fromtimestamp(ts[SPLIT-1], tz=timezone.utc).date()}")
    print(f"Test:  {datetime.fromtimestamp(ts[SPLIT], tz=timezone.utc).date()} -> {datetime.fromtimestamp(ts[-1], tz=timezone.utc).date()}")

    # -----------------------------------------------------------------------
    # 1. Advanced single filters on H3-A base (train period)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("ADVANCED FILTERS ON H3-A BASE (rsi_55 + ichi_score3, Train period)")
    print("=" * 72)
    print(f"  {'Filter':<22} {'n':>4} {'WR':>6} {'PF':>7} {'Sh':>7} {'p':>7}  vs base")
    print(f"  {'-'*22} {'-'*4} {'-'*6} {'-'*7} {'-'*7} {'-'*7}  --------")

    ic_train = IndicatorCache(o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT])
    base_filters_train = build_filters(ic_train)
    base_mask_train = base_filters_train["rsi_55"] & base_filters_train["ichi_score3"]

    # Baseline H3-A on train
    base_r = run_filter_test(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                              ic_train, regime[:SPLIT], base_mask_train)
    print(f"  {'H3-A base':<22} {base_r['n']:>4} {base_r['wr']:>5.1%} {base_r['pf']:>7.3f} "
          f"{base_r['sharpe']:>7.3f} {base_r['p']:>7.3f}  (baseline)")

    adv_filters_train = build_advanced_filters(ic_train)
    adv_results = {}

    for fname, fmask in adv_filters_train.items():
        combo_mask = base_mask_train & fmask
        r = run_filter_test(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                            ic_train, regime[:SPLIT], combo_mask)
        if r and r["n"] >= 4:
            star = "*" if r["p"] < 0.10 else " "
            dpf = r["pf"] - base_r["pf"]
            print(f"  {fname:<22} {r['n']:>4} {r['wr']:>5.1%} {r['pf']:>7.3f} "
                  f"{r['sharpe']:>7.3f} {r['p']:>7.3f}{star}  PF{dpf:+.3f}")
            adv_results[fname] = r
        elif r:
            print(f"  {fname:<22} {r['n']:>4}  (too few)")

    # -----------------------------------------------------------------------
    # 2. Multi-timeframe: daily Ichimoku gate on 4h entries
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("MULTI-TIMEFRAME CONFLUENCE (4h entry + daily Ichimoku confirmation)")
    print("=" * 72)

    daily_mask = build_daily_regime_mask(sol1d_df, ts)
    print(f"Daily bullish bars: {np.sum(daily_mask)}/{n} ({np.sum(daily_mask)/n:.1%})")

    # MTF combinations
    mtf_combos = {
        "H3-A + daily_ichi":     base_mask_train & daily_mask[:SPLIT],
        "H3-A + daily + srsi_k50": base_mask_train & daily_mask[:SPLIT] & adv_filters_train.get("srsi_k50", np.ones(SPLIT, dtype=bool)),
        "baseline + daily_ichi": np.ones(SPLIT, dtype=bool) & daily_mask[:SPLIT],  # just daily gate on baseline
    }

    mtf_results = {}
    for name, mask in mtf_combos.items():
        # Note: baseline doesn't have rsi_55 etc baked in, need to handle
        r = run_filter_test(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                            ic_train, regime[:SPLIT], mask)
        if r and r["n"] >= 4:
            star = "*" if r["p"] < 0.10 else " "
            print(f"  {name:<35} n={r['n']:3d} WR={r['wr']:.1%} PF={r['pf']:.3f} "
                  f"Sh={r['sharpe']:+.3f} p={r['p']:.3f}{star}")
            mtf_results[name] = r
        elif r:
            print(f"  {name:<35} n={r['n']:3d}  too few")
        else:
            print(f"  {name:<35} 0 trades")

    # -----------------------------------------------------------------------
    # 3. Walk-forward best advanced combos
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("WALK-FORWARD: Top advanced combos + MTF")
    print("=" * 72)

    ic_test = IndicatorCache(o[SPLIT:], h[SPLIT:], l[SPLIT:], c[SPLIT:], v[SPLIT:])
    base_filters_test = build_filters(ic_test)
    adv_filters_test = build_advanced_filters(ic_test)

    wf_candidates = {}

    # Best single-filter add-ons (PF > base + 0.2)
    for fname, r in adv_results.items():
        if r["pf"] > base_r["pf"] + 0.2:
            wf_candidates[f"H3-A+{fname}"] = {
                "train_mask": base_mask_train & adv_filters_train[fname],
                "test_mask":  base_filters_test["rsi_55"] & base_filters_test["ichi_score3"] & adv_filters_test.get(fname, np.ones(len(ts)-SPLIT, dtype=bool)),
            }

    # MTF versions
    daily_mask_test = build_daily_regime_mask(sol1d_df, ts[SPLIT:])
    wf_candidates["H3-A+daily_ichi"] = {
        "train_mask": base_mask_train & daily_mask[:SPLIT],
        "test_mask":  base_filters_test["rsi_55"] & base_filters_test["ichi_score3"] & daily_mask_test,
    }

    # H3-A itself as reference
    wf_candidates["H3-A (reference)"] = {
        "train_mask": base_mask_train,
        "test_mask":  base_filters_test["rsi_55"] & base_filters_test["ichi_score3"],
    }

    print(f"\n  {'Combo':<35} {'Phase':<7} {'n':>4} {'WR':>6} {'PF':>7} {'Sh':>7} {'p':>7}")
    print(f"  {'-'*35} {'-'*7} {'-'*4} {'-'*6} {'-'*7} {'-'*7} {'-'*7}")

    final_results = []
    for name, masks in wf_candidates.items():
        train_r = run_filter_test(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                                   ic_train, regime[:SPLIT], masks["train_mask"])
        test_r  = run_filter_test(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:], c[SPLIT:], v[SPLIT:],
                                   ic_test, regime[SPLIT:], masks["test_mask"])

        for phase_label, r in [("TRAIN", train_r), ("TEST", test_r)]:
            if r:
                star = "*" if r["p"] < 0.10 else " "
                print(f"  {name:<35} {phase_label:<7} {r['n']:>4} {r['wr']:>5.1%} "
                      f"{r['pf']:>7.3f} {r['sharpe']:>7.3f} {r['p']:>7.3f}{star}")
            else:
                print(f"  {name:<35} {phase_label:<7}    0")

        if train_r and test_r:
            final_results.append({
                "name": name,
                "train": train_r,
                "test":  test_r,
                "improvement": test_r["pf"] > 1.2 and test_r["n"] >= 5,
            })
        print()

    # Summary
    print("=" * 72)
    print("VERDICT")
    print("=" * 72)
    improvements = [r for r in final_results if r["improvement"] and r["name"] != "H3-A (reference)"]
    reference = next((r for r in final_results if r["name"] == "H3-A (reference)"), None)

    if reference:
        print(f"\nH3-A reference OOS: PF={reference['test']['pf']:.3f} Sh={reference['test']['sharpe']:+.3f}")

    if improvements:
        best = max(improvements, key=lambda x: x["test"]["pf"] * x["test"]["sharpe"])
        print(f"\nBest improvement: {best['name']}")
        print(f"  OOS: PF={best['test']['pf']:.3f} Sh={best['test']['sharpe']:+.3f} "
              f"WR={best['test']['wr']:.1%} n={best['test']['n']} p={best['test']['p']:.3f}")
        if reference:
            d_pf = best["test"]["pf"] - reference["test"]["pf"]
            print(f"  Delta PF vs H3-A: {d_pf:+.3f}")
    else:
        print("\nNo advanced filter improves on H3-A OOS. H3-A is the final signal definition.")

    # Save
    out = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "base_train": base_r,
        "adv_filter_results": adv_results,
        "mtf_results": mtf_results,
        "wf_final": final_results,
    }
    out_path = DATA_DIR / "advanced_filter_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved: {out_path}")
