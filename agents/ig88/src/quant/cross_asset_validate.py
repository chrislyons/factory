"""
cross_asset_validate.py — Cross-asset validation of top convergence combos.

Tests the three winning combos from convergence_backtest.py on:
  - ETH/USDT 4h (3yr)
  - BTC/USD 4h (3yr)
  - SOL/USDT 1440m daily (5yr) — different timeframe same asset
  - ETH/USDT 1440m daily (8yr)
  - BTC/USD 1440m daily (8yr)

A combo is considered structurally sound if OOS PF > 1.2 on >= 2 of 5 assets.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

from src.quant.convergence_backtest import (
    IndicatorCache, ConvergenceBacktester, build_filters, run_filter_test
)
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")

# Winners from convergence_backtest.py (in order of combined OOS quality)
WINNING_COMBOS = [
    "rsi_55+ichi_score3",
    "rsi_55+chikou_bull+klinger_bull",
    "chikou_bull+klinger_bull",
]

# Add the baseline for comparison
ALL_COMBOS = ["BASELINE"] + WINNING_COMBOS

# Assets to cross-validate
ASSETS = [
    ("SOL/USDT", 240,  4.0,  "SOL 4h (origin)"),
    ("ETH/USDT", 240,  4.0,  "ETH 4h"),
    ("BTC/USD",  240,  4.0,  "BTC 4h"),
    ("SOL/USDT", 1440, 24.0, "SOL daily"),
    ("ETH/USDT", 1440, 24.0, "ETH daily"),
    ("BTC/USD",  1440, 24.0, "BTC daily"),
]


def run_asset_combo(symbol, interval_min, bar_hours, btc_ts, btc_c,
                    combo_filters: list[str], label: str) -> tuple[dict | None, dict | None]:
    """Returns (train_stats, test_stats)."""
    try:
        df = load_binance(symbol, interval_min)
    except FileNotFoundError:
        return None, None

    ts, o, h, l, c, v = df_to_arrays(df)
    n = len(ts)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    SPLIT = int(n * 0.70)

    results = []
    for phase_ts, phase_o, phase_h, phase_l, phase_c, phase_v, phase_regime in [
        (ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT], regime[:SPLIT]),
        (ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:], c[SPLIT:], v[SPLIT:], regime[SPLIT:]),
    ]:
        if len(phase_ts) < 100:
            results.append(None)
            continue

        ic = IndicatorCache(phase_o, phase_h, phase_l, phase_c, phase_v)
        filters = build_filters(ic)

        if not combo_filters:  # baseline
            mask = np.ones(len(phase_ts), dtype=bool)
        else:
            mask = np.ones(len(phase_ts), dtype=bool)
            for f in combo_filters:
                if f in filters:
                    mask &= filters[f]

        r = run_filter_test(phase_ts, phase_o, phase_h, phase_l, phase_c, phase_v,
                            ic, phase_regime, mask, bh=bar_hours)
        results.append(r)

    return results[0], results[1]


if __name__ == "__main__":
    print("=" * 80)
    print("CROSS-ASSET VALIDATION")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)

    # Load BTC daily for regime
    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    all_results = {}

    for combo_name in ALL_COMBOS:
        if combo_name == "BASELINE":
            combo_filters = []
        else:
            combo_filters = combo_name.split("+")

        print(f"\n{'='*80}")
        print(f"COMBO: {combo_name}")
        print(f"{'='*80}")
        print(f"  {'Asset':<18} {'Phase':<7} {'n':>4} {'WR':>6} {'PF':>7} {'Sh':>7} {'DD%':>5} {'p':>7}")
        print(f"  {'-'*18} {'-'*7} {'-'*4} {'-'*6} {'-'*7} {'-'*7} {'-'*5} {'-'*7}")

        asset_results = {}
        for symbol, interval_min, bar_hours, asset_label in ASSETS:
            train_r, test_r = run_asset_combo(
                symbol, interval_min, bar_hours, btc_ts, btc_c, combo_filters, asset_label
            )

            asset_results[asset_label] = {"train": train_r, "test": test_r}

            for phase_label, r in [("TRAIN", train_r), ("TEST", test_r)]:
                if r:
                    star = "*" if r["p"] < 0.10 else " "
                    print(f"  {asset_label:<18} {phase_label:<7} {r['n']:>4} {r['wr']:>5.1%} "
                          f"{r['pf']:>7.3f} {r['sharpe']:>7.3f} {r['dd']:>5.1f}% {r['p']:>7.3f}{star}")
                else:
                    print(f"  {asset_label:<18} {phase_label:<7}    0")

        # Summary: how many assets pass OOS PF > 1.2?
        oos_pass = [
            label for label, res in asset_results.items()
            if res["test"] and res["test"]["pf"] > 1.2 and res["test"]["n"] >= 5
        ]
        oos_fail = [
            label for label, res in asset_results.items()
            if res["test"] and (res["test"]["pf"] <= 1.2 or res["test"]["n"] < 5)
        ]
        print(f"\n  OOS PASS (PF>1.2, n>=5): {len(oos_pass)}/{len(ASSETS)} — {oos_pass}")
        if oos_fail:
            print(f"  OOS FAIL:               {oos_fail}")

        all_results[combo_name] = {
            "assets": asset_results,
            "oos_pass_count": len(oos_pass),
            "oos_pass_assets": oos_pass,
        }

    # -----------------------------------------------------------------------
    # Master summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("MASTER SUMMARY — Cross-asset OOS robustness")
    print("=" * 80)
    print(f"\n  {'Combo':<40} {'OOS pass':>10}  Assets passing")
    print(f"  {'-'*40} {'-'*10}  {'-'*30}")
    for combo_name in ALL_COMBOS:
        r = all_results[combo_name]
        print(f"  {combo_name:<40} {r['oos_pass_count']:>3}/{len(ASSETS)}        "
              f"{', '.join(r['oos_pass_assets'])}")

    # Structural combos: pass on >= 3 assets
    structural = [c for c in ALL_COMBOS
                  if all_results[c]["oos_pass_count"] >= 3]

    print(f"\nStructurally robust (>= 3 assets OOS PF > 1.2): {structural}")

    # Best combo OOS across all assets
    best_combo = max(WINNING_COMBOS,
                     key=lambda c: all_results[c]["oos_pass_count"] * 10 +
                                   sum((all_results[c]["assets"].get(a, {}).get("test") or {}).get("pf", 0)
                                       for _, _, _, a in ASSETS))

    best_avg_oos_pf = np.mean([
        (all_results[best_combo]["assets"].get(a, {}).get("test") or {}).get("pf", 0)
        for _, _, _, a in ASSETS
        if (all_results[best_combo]["assets"].get(a, {}).get("test") or {}).get("n", 0) >= 5
    ])

    print(f"\nBest combo overall: {best_combo}")
    print(f"  Avg OOS PF across qualifying assets: {best_avg_oos_pf:.3f}")

    # Save
    out_path = DATA_DIR / "cross_asset_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "run_at": datetime.now(timezone.utc).isoformat(),
            "combos_tested": ALL_COMBOS,
            "assets_tested": [a for _, _, _, a in ASSETS],
            "results": {
                combo: {
                    "oos_pass_count": all_results[combo]["oos_pass_count"],
                    "oos_pass_assets": all_results[combo]["oos_pass_assets"],
                }
                for combo in ALL_COMBOS
            },
        }, f, indent=2)
    print(f"\nSaved: {out_path}")
