"""
combo_research.py — Combination search across ALL indicator pairs.

Uses the top standalone performers from indicator_research.py as candidates:
  - vol_spike_breakout (strong on 3/5 assets)
  - kama_bands_break (extreme OOS on SOL/BTC/ETH daily, but tiny n)
  - rsi_momentum_cross (ETH 4h, consistent)
  - macd_line_cross / macd_hist_flip (SOL 4h OOS pass)
  - dema_9_21_cross (SOL 4h pass)
  - ema21_50_cross (BTC 4h strong)
  - ichimoku_base (SOL 4h strong)
  - ichimoku_h3a (SOL 4h strongest)

Tests:
  1. Top indicator paired with each other indicator
  2. Walk-forward validated
  3. Cross-asset validated on 3+ assets

Hypothesis: vol_spike_breakout + Ichimoku confirmation could be excellent.
Volume spikes are high-information events; confirming with trend state filters
the direction.
"""

from __future__ import annotations

import json, sys
from datetime import datetime, timezone
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import src.quant.indicators as ind
from src.quant.indicator_research import (
    SignalBacktester, backtest_signal, build_all_signals,
    signals_vol_spike_break, signals_kama_bands_break, signals_rsi_momentum_cross,
    signals_macd_cross, signals_ema_cross, signals_ichimoku_base,
    signals_ichimoku_h3a, signals_donchian_break, signals_bb_breakout,
    signals_obv_break, signals_klinger_cross, signals_dema_cross,
    signals_supertrend, signals_stochrsi_cross,
)
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")


# ---------------------------------------------------------------------------
# Combination signal builder
# ---------------------------------------------------------------------------

def combine_signals(*signal_pairs) -> tuple[np.ndarray, object]:
    """AND-combine multiple (mask, exit_ma) pairs. Use first non-None exit_ma."""
    masks, exits = zip(*signal_pairs)
    combined = masks[0].copy()
    for m in masks[1:]:
        combined &= m
    exit_ma = next((e for e in exits if e is not None), None)
    return combined, exit_ma


def run_wf(ts, o, h, l, c, v, regime, atr, mask, exit_ma=None,
           capital=10_000.0, bar_hours=4.0):
    """Walk-forward backtest: returns (train_r, test_r)."""
    n = len(ts)
    SPLIT = int(n * 0.70)
    tr_exit = exit_ma[:SPLIT] if exit_ma is not None else None
    te_exit = exit_ma[SPLIT:] if exit_ma is not None else None
    tr = backtest_signal(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                         c[:SPLIT], v[:SPLIT], mask[:SPLIT], regime[:SPLIT],
                         atr[:SPLIT], tr_exit, capital, bar_hours)
    te = backtest_signal(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                         c[SPLIT:], v[SPLIT:], mask[SPLIT:], regime[SPLIT:],
                         atr[SPLIT:], te_exit, capital, bar_hours)
    return tr, te


def score_result(tr, te):
    """Composite score weighting OOS more than train."""
    if not te or te["n"] < 5:
        return -999
    oos_score = te["pf"] * (1 - te["p"]) * min(te["n"] / 20.0, 1.0)
    train_score = (tr["pf"] if tr else 1.0) * 0.3
    return oos_score + train_score


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 80)
    print("COMBINATION INDICATOR RESEARCH")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)

    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    # Primary test asset: SOL 4h (most data, known edge)
    sol4h = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol4h)
    n = len(ts)
    SPLIT = int(n * 0.70)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    atr_v = ind.atr(h, l, c, 14)

    # Pre-build all signals on full series
    print("\nBuilding all signal masks on SOL 4h...")
    all_sigs = build_all_signals(o, h, l, c, v)
    print(f"  {len(all_sigs)} signals built")

    # -----------------------------------------------------------------------
    # Phase 1: Top standalones vs each partner
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("PHASE 1: vol_spike_breakout × every other signal (SOL 4h, walk-forward)")
    print("=" * 80)
    print(f"  {'Combo':<35} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  {'Te-n':>5} {'Te-PF':>7} {'Te-p':>7}  {'Score':>8}")
    print(f"  {'-'*35} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7}  {'-'*8}")

    phase1_results = {}
    base_sig = "vol_spike_breakout"
    base_mask, base_exit = all_sigs[base_sig]

    for partner, (pmask, pexit) in all_sigs.items():
        if partner == base_sig: continue
        combo_mask = base_mask & pmask
        exit_ma = base_exit if base_exit is not None else pexit
        tr, te = run_wf(ts, o, h, l, c, v, regime, atr_v, combo_mask, exit_ma)
        sc = score_result(tr, te)
        if tr and te:
            star_t = "*" if tr["p"] < 0.10 else " "
            star_e = "*" if te["p"] < 0.10 else " "
            tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['p']:7.3f}{star_t}"
            te_s = f"{te['n']:5d} {te['pf']:7.3f} {te['p']:7.3f}{star_e}"
            label = f"{base_sig}+{partner}"
            print(f"  {label:<35} {tr_s}  {te_s}  {sc:8.3f}")
            phase1_results[label] = {"train": tr, "test": te, "score": sc}
        elif te and te["n"] < 5:
            print(f"  {base_sig}+{partner:<25}     too few OOS trades")

    # -----------------------------------------------------------------------
    # Phase 2: ichimoku_base × each signal
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("PHASE 2: ichimoku_base × every other signal (SOL 4h)")
    print("=" * 80)
    print(f"  {'Combo':<35} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  {'Te-n':>5} {'Te-PF':>7} {'Te-p':>7}  {'Score':>8}")
    print(f"  {'-'*35} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7}  {'-'*8}")

    phase2_results = {}
    base_sig2 = "ichimoku_base"
    base_mask2, base_exit2 = all_sigs[base_sig2]

    for partner, (pmask, pexit) in all_sigs.items():
        if partner in (base_sig2, "ichimoku_h3a"): continue
        combo_mask = base_mask2 & pmask
        exit_ma = base_exit2 if base_exit2 is not None else pexit
        tr, te = run_wf(ts, o, h, l, c, v, regime, atr_v, combo_mask, exit_ma)
        sc = score_result(tr, te)
        if tr and te:
            star_t = "*" if tr["p"] < 0.10 else " "
            star_e = "*" if te["p"] < 0.10 else " "
            tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['p']:7.3f}{star_t}"
            te_s = f"{te['n']:5d} {te['pf']:7.3f} {te['p']:7.3f}{star_e}"
            label = f"{base_sig2}+{partner}"
            print(f"  {label:<35} {tr_s}  {te_s}  {sc:8.3f}")
            phase2_results[label] = {"train": tr, "test": te, "score": sc}
        elif te and te["n"] < 5:
            pass  # suppress noise

    # -----------------------------------------------------------------------
    # Phase 3: rsi_momentum_cross (ETH 4h leader) × each
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("PHASE 3: rsi_momentum_cross × every other signal (SOL 4h)")
    print("=" * 80)
    print(f"  {'Combo':<35} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  {'Te-n':>5} {'Te-PF':>7} {'Te-p':>7}  {'Score':>8}")
    print(f"  {'-'*35} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7}  {'-'*8}")

    phase3_results = {}
    base_sig3 = "rsi_momentum_cross"
    base_mask3, base_exit3 = all_sigs[base_sig3]

    for partner, (pmask, pexit) in all_sigs.items():
        if partner == base_sig3: continue
        combo_mask = base_mask3 & pmask
        exit_ma = base_exit3 if base_exit3 is not None else pexit
        tr, te = run_wf(ts, o, h, l, c, v, regime, atr_v, combo_mask, exit_ma)
        sc = score_result(tr, te)
        if tr and te and te["n"] >= 5:
            star_t = "*" if tr["p"] < 0.10 else " "
            star_e = "*" if te["p"] < 0.10 else " "
            tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['p']:7.3f}{star_t}"
            te_s = f"{te['n']:5d} {te['pf']:7.3f} {te['p']:7.3f}{star_e}"
            label = f"{base_sig3}+{partner}"
            print(f"  {label:<35} {tr_s}  {te_s}  {sc:8.3f}")
            phase3_results[label] = {"train": tr, "test": te, "score": sc}

    # -----------------------------------------------------------------------
    # Collect all combos, find top candidates
    # -----------------------------------------------------------------------
    all_combos = {**phase1_results, **phase2_results, **phase3_results}
    top_candidates = sorted(
        [(k, v) for k, v in all_combos.items()
         if v["test"] and v["test"]["n"] >= 5 and v["test"]["pf"] > 1.3],
        key=lambda x: x[1]["score"],
        reverse=True
    )[:15]

    print("\n" + "=" * 80)
    print("TOP COMBO CANDIDATES (OOS PF > 1.3, n >= 5, by composite score)")
    print("=" * 80)
    print(f"  {'Combo':<40} {'Te-n':>5} {'Te-WR':>7} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}  {'Score':>8}")
    print(f"  {'-'*40} {'-'*5} {'-'*7} {'-'*7} {'-'*7} {'-'*7}  {'-'*8}")
    for combo_name, res in top_candidates:
        te = res["test"]
        tr = res["train"]
        star = "*" if te["p"] < 0.10 else " "
        print(f"  {combo_name:<40} {te['n']:>5} {te['wr']:>6.1%} {te['pf']:>7.3f} "
              f"{te['sharpe']:>7.3f} {te['p']:>7.3f}{star}  {res['score']:>8.3f}")

    # -----------------------------------------------------------------------
    # Phase 4: Cross-asset validation of top 8 combos
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("PHASE 4: Cross-asset validation of top combos")
    print("=" * 80)

    cross_assets = [
        ("ETH/USDT", 240,  4.0,  "ETH 4h"),
        ("BTC/USD",  240,  4.0,  "BTC 4h"),
        ("ETH/USDT", 1440, 24.0, "ETH 1d"),
        ("BTC/USD",  1440, 24.0, "BTC 1d"),
    ]

    # Pre-build signals for each cross-asset
    cross_asset_data = {}
    for sym, itvl, bh, label in cross_assets:
        try:
            df = load_binance(sym, itvl)
            _ts, _o, _h, _l, _c, _v = df_to_arrays(df)
            _regime = build_btc_trend_regime(btc_c, _ts, btc_ts)
            _atr = ind.atr(_h, _l, _c, 14)
            _sigs = build_all_signals(_o, _h, _l, _c, _v)
            cross_asset_data[label] = (_ts, _o, _h, _l, _c, _v, _regime, _atr, _sigs)
            print(f"  Loaded {label}: {len(_ts)} bars")
        except Exception as e:
            print(f"  [skip] {label}: {e}")

    top8 = top_candidates[:8]

    print(f"\n  {'Combo':<40} {'SOL4h':>8} {'ETH4h':>8} {'BTC4h':>8} {'ETH1d':>8} {'BTC1d':>8}  {'Pass':>5}")
    print(f"  {'-'*40} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}  {'-'*5}")

    final_rankings = []

    for combo_name, sol_res in top8:
        parts = combo_name.split("+", 1)
        sig1_name, sig2_name = parts[0], parts[1] if len(parts) > 1 else parts[0]

        cross_oos = {"SOL 4h": sol_res["test"]}

        for asset_label, (a_ts, a_o, a_h, a_l, a_c, a_v,
                           a_regime, a_atr, a_sigs) in cross_asset_data.items():
            s1 = a_sigs.get(sig1_name)
            s2 = a_sigs.get(sig2_name)
            if s1 is None or s2 is None:
                cross_oos[asset_label] = None
                continue

            m1, e1 = s1; m2, e2 = s2
            combo_m = m1 & m2
            exit_m  = e1 if e1 is not None else e2
            bh = 4.0 if "4h" in asset_label else 24.0
            _, te = run_wf(a_ts, a_o, a_h, a_l, a_c, a_v, a_regime, a_atr, combo_m, exit_m, bar_hours=bh)
            cross_oos[asset_label] = te

        def pf_str(r):
            if r is None: return "     n/a"
            if r["n"] < 5: return f"  n={r['n']:2d}"
            star = "*" if r["p"] < 0.10 else " "
            return f"{r['pf']:7.3f}{star}"

        pass_count = sum(1 for r in cross_oos.values()
                         if r and r["n"] >= 5 and r["pf"] > 1.2)

        print(f"  {combo_name:<40}"
              f"{pf_str(cross_oos.get('SOL 4h'))}"
              f"{pf_str(cross_oos.get('ETH 4h'))}"
              f"{pf_str(cross_oos.get('BTC 4h'))}"
              f"{pf_str(cross_oos.get('ETH 1d'))}"
              f"{pf_str(cross_oos.get('BTC 1d'))}"
              f"  {pass_count}/5")

        final_rankings.append({
            "combo": combo_name,
            "sol4h_test": sol_res["test"],
            "sol4h_train": sol_res["train"],
            "cross_oos": {k: v for k, v in cross_oos.items()},
            "cross_pass": pass_count,
        })

    # -----------------------------------------------------------------------
    # Master verdict
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("MASTER VERDICT — Structural robustness (cross-asset pass >= 3)")
    print("=" * 80)

    structural = [r for r in final_rankings if r["cross_pass"] >= 3]
    if structural:
        structural.sort(key=lambda x: x["cross_pass"] * 10 +
                        (x["sol4h_test"] or {}).get("pf", 0), reverse=True)
        print("\nStructurally robust combos:")
        for r in structural:
            te = r["sol4h_test"]
            print(f"  {r['combo']}")
            print(f"    SOL 4h OOS: PF={te['pf']:.3f} Sh={te['sharpe']:+.3f} "
                  f"WR={te['wr']:.1%} n={te['n']} p={te['p']:.3f}")
            print(f"    Cross-asset pass: {r['cross_pass']}/5")
    else:
        print("\nNo combo passes 3+ assets. Best by cross-pass count:")
        best = sorted(final_rankings, key=lambda x: x["cross_pass"], reverse=True)[:3]
        for r in best:
            te = r["sol4h_test"] or {}
            print(f"  {r['combo']}  cross_pass={r['cross_pass']}  "
                  f"SOL_OOS_PF={te.get('pf', 0):.3f}")

    # Compare best combo to H3-A
    h3a_sol = sol_res  # last one is h3a if it's in top8
    h3a_entry = next((r for r in final_rankings if "ichimoku_h3a" in r["combo"]), None)
    print(f"\nH3-A (ichimoku_h3a) reference:")
    print(f"  SOL 4h OOS: PF=3.524 Sh=+9.48 WR=75% n=8 p=0.064 (from prior session)")

    # Save
    out_path = DATA_DIR / "combo_research_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "run_at": datetime.now(timezone.utc).isoformat(),
            "phase1_top": sorted(
                [(k, v["score"]) for k, v in phase1_results.items() if v["test"] and v["test"]["n"] >= 5],
                key=lambda x: -x[1])[:10],
            "phase2_top": sorted(
                [(k, v["score"]) for k, v in phase2_results.items() if v["test"] and v["test"]["n"] >= 5],
                key=lambda x: -x[1])[:10],
            "phase3_top": sorted(
                [(k, v["score"]) for k, v in phase3_results.items() if v["test"] and v["test"]["n"] >= 5],
                key=lambda x: -x[1])[:10],
            "final_rankings": final_rankings,
            "structural_combos": [r["combo"] for r in structural],
        }, f, indent=2)
    print(f"\nSaved: {out_path}")
