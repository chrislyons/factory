"""
deep_dive.py — Deep investigation of top combo candidates.

Focus areas:
  A. vol_spike_breakout + rsi_momentum_cross  — SOL 4h PF 8.4 OOS, p=0.002
     Is it real or is the n=9 hiding overfitting?
     Test on: all 6 assets, longer window (1h data), alt pairs

  B. rsi_momentum_cross + kama_cross — Structurally robust (3/5 assets)
     Good n=39 OOS, PF 1.75. Real but modest. Best broad-based signal?
     Test on: LINK, AVAX, XRP, NEAR (alt coins, different dynamics)

  C. vol_spike_breakout + klinger_cross — OOS PF 2.66, p=0.068
     Volume-on-volume combination. Sensible conceptually.

  D. Three-way combinations from top pairs:
     vol_spike + rsi_cross + [klinger / ichi_score3 / kama]
     rsi_cross + kama + [volume confirm]

  E. Parameter sensitivity: vol_spike at 1.5×, 2×, 2.5× and rsi_cross
     at 48, 50, 52 crossing threshold
"""

from __future__ import annotations

import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import src.quant.indicators as ind
from src.quant.indicator_research import (
    SignalBacktester, backtest_signal, build_all_signals,
    signals_vol_spike_break, signals_rsi_momentum_cross,
    signals_kama_cross, signals_klinger_cross,
    signals_ichimoku_h3a,
)
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"


def run_wf(ts, o, h, l, c, v, regime, atr_v, mask, exit_ma=None,
           capital=10_000.0, bar_hours=4.0):
    SPLIT = int(len(ts) * 0.70)
    tr_exit = exit_ma[:SPLIT] if exit_ma is not None else None
    te_exit = exit_ma[SPLIT:] if exit_ma is not None else None
    tr = backtest_signal(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                         c[:SPLIT], v[:SPLIT], mask[:SPLIT], regime[:SPLIT],
                         atr_v[:SPLIT], tr_exit, capital, bar_hours)
    te = backtest_signal(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                         c[SPLIT:], v[SPLIT:], mask[SPLIT:], regime[SPLIT:],
                         atr_v[SPLIT:], te_exit, capital, bar_hours)
    return tr, te


def print_wf(name, tr, te, ref_pf=None):
    def fmt(r, star_thresh=0.10):
        if not r: return "   0 trades"
        star = "*" if r["p"] < star_thresh else " "
        return (f"n={r['n']:3d} WR={r['wr']:.1%} PF={r['pf']:.3f} "
                f"Sh={r['sharpe']:+.3f} p={r['p']:.3f}{star}")
    delta = f"  ΔPF={te['pf']-ref_pf:+.3f}" if (ref_pf and te) else ""
    print(f"  {name:<40}")
    print(f"    TRAIN: {fmt(tr)}")
    print(f"    TEST:  {fmt(te)}{delta}")


if __name__ == "__main__":
    print("=" * 80)
    print("DEEP DIVE — Top Combo Candidates")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)

    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    results_all = {}

    # -----------------------------------------------------------------------
    # A. vol_spike + rsi_cross — cross-asset extended test
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("A. vol_spike_breakout + rsi_momentum_cross  [PF 8.4 OOS SOL 4h]")
    print("=" * 80)

    assets_4h = [
        ("SOL/USDT", 240, 4.0, "SOL 4h"),
        ("ETH/USDT", 240, 4.0, "ETH 4h"),
        ("BTC/USD",  240, 4.0, "BTC 4h"),
        ("SOL/USDT", 60,  1.0, "SOL 1h"),
        ("BTC/USD",  60,  1.0, "BTC 1h"),
    ]

    # Alt coins daily — more assets to test
    assets_daily_alts = [
        ("LINK/USD",  1440, 24.0, "LINK 1d"),
        ("AVAX/USD",  1440, 24.0, "AVAX 1d"),
        ("NEAR/USD",  1440, 24.0, "NEAR 1d"),
        ("XRP/USD",   1440, 24.0, "XRP 1d"),
        ("DOGE/USD",  1440, 24.0, "DOGE 1d"),
        ("INJ/USD",   1440, 24.0, "INJ 1d"),
        ("GRT/USD",   1440, 24.0, "GRT 1d"),
    ]

    combo_A_results = {}
    print(f"\n  {'Asset':<12} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  {'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}")
    print(f"  {'-'*12} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7} {'-'*7}")

    for sym, itvl, bh, label in assets_4h + assets_daily_alts:
        try:
            df = load_binance(sym, itvl)
        except FileNotFoundError:
            print(f"  {label:<12} [no data]")
            continue

        ts, o, h, l, c, v = df_to_arrays(df)
        if len(ts) < 200: continue
        regime = build_btc_trend_regime(btc_c, ts, btc_ts)
        atr_v = ind.atr(h, l, c, 14)

        m_vol, _  = signals_vol_spike_break(c, v)
        m_rsi, _  = signals_rsi_momentum_cross(c)
        combo_m   = m_vol & m_rsi

        tr, te = run_wf(ts, o, h, l, c, v, regime, atr_v, combo_m, bar_hours=bh)
        oos_flag = ""
        if te and te["n"] >= 5:
            if te["pf"] > 2.0: oos_flag = " *** STRONG"
            elif te["pf"] > 1.5: oos_flag = " * pass"
            elif te["pf"] < 0.8: oos_flag = "   fail"

        tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['p']:7.3f}" if tr else "    0       -       -"
        te_s = f"{te['n']:5d} {te['pf']:7.3f} {te['sharpe']:7.3f} {te['p']:7.3f}" if te else "    0       -       -       -"
        star = "*" if (te and te["p"] < 0.10) else " "
        print(f"  {label:<12} {tr_s}  {te_s}{star}{oos_flag}")
        combo_A_results[label] = {"train": tr, "test": te}

    # -----------------------------------------------------------------------
    # B. rsi_momentum + kama_cross — alt coin test (broad robustness)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("B. rsi_momentum_cross + kama_cross  [Structurally robust, 3/5 assets]")
    print("=" * 80)

    combo_B_results = {}
    print(f"\n  {'Asset':<12} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  {'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}")
    print(f"  {'-'*12} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7} {'-'*7}")

    for sym, itvl, bh, label in assets_4h + assets_daily_alts:
        try:
            df = load_binance(sym, itvl)
        except FileNotFoundError:
            continue
        ts, o, h, l, c, v = df_to_arrays(df)
        if len(ts) < 200: continue
        regime = build_btc_trend_regime(btc_c, ts, btc_ts)
        atr_v = ind.atr(h, l, c, 14)
        m_rsi, _  = signals_rsi_momentum_cross(c)
        m_kama, exit_kama = signals_kama_cross(c)
        combo_m   = m_rsi & m_kama
        tr, te = run_wf(ts, o, h, l, c, v, regime, atr_v, combo_m, exit_kama, bar_hours=bh)
        tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['p']:7.3f}" if tr else "    0       -       -"
        te_s = f"{te['n']:5d} {te['pf']:7.3f} {te['sharpe']:7.3f} {te['p']:7.3f}" if te else "    0       -       -       -"
        star = "*" if (te and te["p"] < 0.10) else " "
        oos_flag = ""
        if te and te["n"] >= 5:
            if te["pf"] > 1.5: oos_flag = " * pass"
            elif te["pf"] < 0.8: oos_flag = "   fail"
        print(f"  {label:<12} {tr_s}  {te_s}{star}{oos_flag}")
        combo_B_results[label] = {"train": tr, "test": te}

    # -----------------------------------------------------------------------
    # C. Three-way combinations from top pairs
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("C. Three-way combinations on SOL 4h")
    print("=" * 80)

    sol_df = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    regime_sol = build_btc_trend_regime(btc_c, ts, btc_ts)
    atr_sol = ind.atr(h, l, c, 14)
    all_sigs_sol = build_all_signals(o, h, l, c, v)

    m_vol,  _    = all_sigs_sol["vol_spike_breakout"]
    m_rsi,  _    = all_sigs_sol["rsi_momentum_cross"]
    m_kama, e_k  = all_sigs_sol["kama_cross"]
    m_klin, _    = all_sigs_sol["klinger_cross"]
    m_obv,  _    = all_sigs_sol["obv_sma_cross"]
    m_ichi, e_i  = all_sigs_sol["ichimoku_base"]
    _, e_i3      = all_sigs_sol["ichimoku_h3a"]
    m_dema, e_d  = all_sigs_sol["dema_9_21_cross"]

    three_way_combos = {
        "vol+rsi+klinger":        (m_vol & m_rsi & m_klin, None),
        "vol+rsi+kama":           (m_vol & m_rsi & m_kama, e_k),
        "vol+rsi+obv":            (m_vol & m_rsi & m_obv,  None),
        "vol+rsi+ichi_base":      (m_vol & m_rsi & m_ichi, e_i),
        "rsi+kama+klinger":       (m_rsi & m_kama & m_klin, e_k),
        "rsi+kama+vol":           (m_rsi & m_kama & m_vol,  e_k),
        "rsi+kama+obv":           (m_rsi & m_kama & m_obv,  e_k),
        "rsi+dema+vol":           (m_rsi & m_dema & m_vol,  e_d),
        "rsi+dema+kama":          (m_rsi & m_dema & m_kama, e_d),
        "ichimoku_h3a+vol_spike": (all_sigs_sol["ichimoku_h3a"][0] & m_vol, e_i),
        "ichimoku_h3a+rsi_cross": (all_sigs_sol["ichimoku_h3a"][0] & m_rsi, e_i),
        "ichimoku_h3a+kama":      (all_sigs_sol["ichimoku_h3a"][0] & m_kama, e_k),
    }

    print(f"\n  {'Combo':<30} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  {'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}")
    print(f"  {'-'*30} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7} {'-'*7}")

    combo_C_results = {}
    for name, (cmask, cexit) in three_way_combos.items():
        tr, te = run_wf(ts, o, h, l, c, v, regime_sol, atr_sol, cmask, cexit, bar_hours=4.0)
        tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['p']:7.3f}" if tr else "    0       -       -"
        te_s = f"{te['n']:5d} {te['pf']:7.3f} {te['sharpe']:7.3f} {te['p']:7.3f}" if te else "    0       -       -       -"
        star = "*" if (te and te["p"] < 0.10) else " "
        oos_flag = ""
        if te and te["n"] >= 5:
            if te["pf"] > 2.0: oos_flag = " *** STRONG"
            elif te["pf"] > 1.3: oos_flag = " * pass"
        print(f"  {name:<30} {tr_s}  {te_s}{star}{oos_flag}")
        combo_C_results[name] = {"train": tr, "test": te}

    # -----------------------------------------------------------------------
    # D. Parameter sensitivity: vol_spike multiplier × rsi threshold
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("D. Parameter sensitivity: vol multiplier × RSI crossing threshold")
    print("=" * 80)

    param_results = {}
    print(f"\n  {'vol_mult':>9} {'rsi_thr':>8}  {'Tr-n':>5} {'Tr-PF':>7}  {'Te-n':>5} {'Te-PF':>7} {'Te-p':>7}")
    print(f"  {'-'*9} {'-'*8}  {'-'*5} {'-'*7}  {'-'*5} {'-'*7} {'-'*7}")

    for vol_mult in [1.5, 2.0, 2.5, 3.0]:
        for rsi_cross in [48, 50, 52, 55]:
            # Build parameterised signals
            rsi_v = ind.rsi(c, 14)
            vol_ma = ind.sma(v, 20)
            n = len(c)
            m_vol_p = np.zeros(n, dtype=bool)
            m_rsi_p = np.zeros(n, dtype=bool)
            for i in range(1, n):
                if not np.isnan(vol_ma[i]) and vol_ma[i] > 0:
                    m_vol_p[i] = v[i] > vol_mult * vol_ma[i] and (c[i] - c[i-1]) / c[i-1] > 0.005
                if not np.isnan(rsi_v[i]) and not np.isnan(rsi_v[i-1]):
                    m_rsi_p[i] = rsi_v[i] > rsi_cross and rsi_v[i-1] <= rsi_cross
            combo_mp = m_vol_p & m_rsi_p
            tr, te = run_wf(ts, o, h, l, c, v, regime_sol, atr_sol, combo_mp, bar_hours=4.0)
            star = "*" if (te and te["p"] < 0.10) else " "
            tr_s = f"{tr['n']:5d} {tr['pf']:7.3f}" if tr else "    0       -"
            te_s = f"{te['n']:5d} {te['pf']:7.3f} {te['p']:7.3f}{star}" if te else "    0       -       -"
            print(f"  {vol_mult:>9.1f} {rsi_cross:>8}  {tr_s}  {te_s}")
            param_results[f"vol{vol_mult}_rsi{rsi_cross}"] = {"train": tr, "test": te}

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SUMMARY — Strategy Leaderboard (All combos, OOS PF ranked)")
    print("=" * 80)

    all_findings = []

    for label, r in combo_A_results.items():
        te = r.get("test"); tr = r.get("train")
        if te and te["n"] >= 5:
            all_findings.append(("vol+rsi / " + label, tr, te))

    for label, r in combo_B_results.items():
        te = r.get("test"); tr = r.get("train")
        if te and te["n"] >= 5:
            all_findings.append(("rsi+kama / " + label, tr, te))

    for name, r in combo_C_results.items():
        te = r.get("test"); tr = r.get("train")
        if te and te["n"] >= 5:
            all_findings.append((f"3way: {name}", tr, te))

    # Include H3-A as reference
    m_h3a, e_h3a = all_sigs_sol["ichimoku_h3a"]
    tr_h3a, te_h3a = run_wf(ts, o, h, l, c, v, regime_sol, atr_sol, m_h3a, e_h3a, bar_hours=4.0)
    all_findings.append(("H3-A (ichi_h3a) SOL 4h", tr_h3a, te_h3a))

    all_findings.sort(key=lambda x: (x[2] or {}).get("pf", 0) * (1 - (x[2] or {}).get("p", 1)), reverse=True)

    print(f"\n  {'Strategy':<45} {'Te-n':>5} {'Te-WR':>7} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}")
    print(f"  {'-'*45} {'-'*5} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
    shown = set()
    for name, tr, te in all_findings[:25]:
        if not te or te["n"] < 5: continue
        key = f"{te['pf']:.3f}_{te['n']}"
        if key in shown: continue
        shown.add(key)
        star = "*" if te["p"] < 0.10 else " "
        print(f"  {name:<45} {te['n']:>5} {te['wr']:>6.1%} {te['pf']:>7.3f} "
              f"{te['sharpe']:>7.3f} {te['p']:>7.3f}{star}")

    # Save
    out_path = DATA_DIR / "deep_dive_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "run_at": datetime.now(timezone.utc).isoformat(),
            "combo_A": combo_A_results,
            "combo_B": combo_B_results,
            "combo_C": combo_C_results,
            "param_sensitivity": param_results,
        }, f, indent=2)
    print(f"\nSaved: {out_path}")
