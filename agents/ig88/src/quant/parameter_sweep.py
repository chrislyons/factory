"""
parameter_sweep.py — Systematic parameter sensitivity analysis.

Tests whether the winning strategies are robust to parameter variation
or dependent on specific magic numbers.

For each strategy, sweeps key parameters and checks OOS stability:

H3-A (Ichimoku):
  - Tenkan period: 7, 9, 11, 14
  - Kijun period: 21, 26, 30
  - RSI threshold: 50, 53, 55, 58, 60
  - Ichi score threshold: 2, 3, 4

H3-B (Volume ignition):
  - Vol multiplier: 1.2, 1.5, 1.8, 2.0, 2.5
  - RSI cross level: 45, 48, 50, 52, 55
  - Price gain threshold: 0.3%, 0.5%, 0.8%, 1.0%

H3-C (RSI + KAMA):
  - KAMA period: 4, 6, 8, 10
  - RSI cross level: 45, 48, 50, 52
  - KAMA fast/slow: (2,20), (2,30), (3,30)

A parameter set is "robust" if OOS PF > 1.2 across a 2×2 neighborhood.
"""

from __future__ import annotations

import json, sys
from datetime import datetime, timezone
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import src.quant.indicators as ind
from src.quant.indicator_research import SignalBacktester, backtest_signal
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine
from src.quant.regime import RegimeState
from src.quant.research_loop import ExitResearchBacktester

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"


def run_wf_quick(ts, o, h, l, c, v, regime, mask, exit_method="atr_trail",
                 capital=10_000.0, bar_hours=4.0, split=0.70):
    """Quick walk-forward returning (train_pf, test_pf, test_p, test_n)."""
    N = len(ts); SPLIT = int(N * split)
    bt = ExitResearchBacktester(capital, bar_hours)
    tr_tr = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                         c[:SPLIT], v[:SPLIT], regime[:SPLIT], mask[:SPLIT], exit_method)
    te_tr = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                         c[SPLIT:], v[SPLIT:], regime[SPLIT:], mask[SPLIT:], exit_method)

    def s(trades):
        if not trades: return (0, 0.0, 1.0, 0)
        eng = BacktestEngine(capital); eng.add_trades(trades)
        st = eng.compute_stats(venue=VENUE)
        return (st.n_trades, round(st.profit_factor, 3),
                round(st.p_value, 4), round(st.win_rate, 3))

    tr_n, tr_pf, tr_p, tr_wr = s(tr_tr)
    te_n, te_pf, te_p, te_wr = s(te_tr)
    return tr_pf, te_pf, te_p, te_n, te_wr


# ---------------------------------------------------------------------------
# H3-A parameter sweep
# ---------------------------------------------------------------------------

def sweep_h3a(ts, o, h, l, c, v, regime):
    print("\n" + "=" * 72)
    print("H3-A PARAMETER SWEEP (Ichimoku)")
    print("=" * 72)

    # Base: tenkan=9, kijun=26, senkou_b=52, rsi_thresh=55, score_thresh=3
    tenkan_periods  = [7, 9, 11, 14]
    kijun_periods   = [21, 26, 30]
    rsi_thresholds  = [50, 53, 55, 58, 60]
    score_thresholds = [2, 3, 4]

    all_rows = []

    print(f"\n  Sweep: tenkan × kijun (rsi=55, score=3)")
    print(f"  {'tenkan':>8} {'kijun':>7} {'Tr-PF':>7} {'Te-PF':>7} {'Te-p':>7} {'Te-n':>5}  robust")
    print(f"  {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*5}  ------")

    for t_per in tenkan_periods:
        for k_per in kijun_periods:
            if k_per <= t_per: continue
            sb_per = k_per * 2

            ichi  = ind.ichimoku(h, l, c, tenkan_period=t_per,
                                 kijun_period=k_per, senkou_b_period=sb_per)
            score = ind.ichimoku_composite_score(ichi, c)
            rsi_v = ind.rsi(c, 14)
            tk    = ichi.tk_cross_signals()

            n = len(c)
            mask = np.zeros(n, dtype=bool)
            for i in range(n):
                ct = max(ichi.senkou_span_a[i] if not np.isnan(ichi.senkou_span_a[i]) else -np.inf,
                         ichi.senkou_span_b[i] if not np.isnan(ichi.senkou_span_b[i]) else -np.inf)
                mask[i] = (tk[i] == 1 and c[i] > ct
                           and not np.isnan(rsi_v[i]) and rsi_v[i] > 55
                           and score[i] >= 3
                           and regime[i] != RegimeState.RISK_OFF)

            tr_pf, te_pf, te_p, te_n, te_wr = run_wf_quick(ts, o, h, l, c, v, regime, mask)
            star = "*" if te_p < 0.10 else " "
            is_base = "BASE" if (t_per == 9 and k_per == 26) else ""
            print(f"  {t_per:>8} {k_per:>7} {tr_pf:>7.3f} {te_pf:>7.3f} "
                  f"{te_p:>7.3f}{star} {te_n:>5}  {is_base}")
            all_rows.append({"type": "h3a_tk", "t": t_per, "k": k_per,
                              "tr_pf": tr_pf, "te_pf": te_pf, "te_p": te_p, "te_n": te_n})

    print(f"\n  Sweep: RSI threshold (tenkan=9, kijun=26, score=3)")
    print(f"  {'rsi_thresh':>10} {'Tr-PF':>7} {'Te-PF':>7} {'Te-p':>7} {'Te-n':>5}")
    print(f"  {'-'*10} {'-'*7} {'-'*7} {'-'*7} {'-'*5}")

    ichi_base = ind.ichimoku(h, l, c)
    score_base = ind.ichimoku_composite_score(ichi_base, c)
    rsi_v = ind.rsi(c, 14)
    tk_base = ichi_base.tk_cross_signals()

    for rsi_thr in rsi_thresholds:
        n = len(c)
        mask = np.zeros(n, dtype=bool)
        for i in range(n):
            ct = max(ichi_base.senkou_span_a[i] if not np.isnan(ichi_base.senkou_span_a[i]) else -np.inf,
                     ichi_base.senkou_span_b[i] if not np.isnan(ichi_base.senkou_span_b[i]) else -np.inf)
            mask[i] = (tk_base[i] == 1 and c[i] > ct
                       and not np.isnan(rsi_v[i]) and rsi_v[i] > rsi_thr
                       and score_base[i] >= 3
                       and regime[i] != RegimeState.RISK_OFF)
        tr_pf, te_pf, te_p, te_n, _ = run_wf_quick(ts, o, h, l, c, v, regime, mask)
        star = "*" if te_p < 0.10 else " "
        base = " BASE" if rsi_thr == 55 else ""
        print(f"  {rsi_thr:>10} {tr_pf:>7.3f} {te_pf:>7.3f} {te_p:>7.3f}{star} {te_n:>5}{base}")
        all_rows.append({"type": "h3a_rsi", "rsi": rsi_thr,
                         "tr_pf": tr_pf, "te_pf": te_pf, "te_p": te_p, "te_n": te_n})

    print(f"\n  Sweep: Ichi score threshold (tenkan=9, kijun=26, rsi=55)")
    print(f"  {'score_thr':>9} {'Tr-PF':>7} {'Te-PF':>7} {'Te-p':>7} {'Te-n':>5}")
    print(f"  {'-'*9} {'-'*7} {'-'*7} {'-'*7} {'-'*5}")

    for sc_thr in score_thresholds:
        n = len(c)
        mask = np.zeros(n, dtype=bool)
        for i in range(n):
            ct = max(ichi_base.senkou_span_a[i] if not np.isnan(ichi_base.senkou_span_a[i]) else -np.inf,
                     ichi_base.senkou_span_b[i] if not np.isnan(ichi_base.senkou_span_b[i]) else -np.inf)
            mask[i] = (tk_base[i] == 1 and c[i] > ct
                       and not np.isnan(rsi_v[i]) and rsi_v[i] > 55
                       and score_base[i] >= sc_thr
                       and regime[i] != RegimeState.RISK_OFF)
        tr_pf, te_pf, te_p, te_n, _ = run_wf_quick(ts, o, h, l, c, v, regime, mask)
        star = "*" if te_p < 0.10 else " "
        base = " BASE" if sc_thr == 3 else ""
        print(f"  {sc_thr:>9} {tr_pf:>7.3f} {te_pf:>7.3f} {te_p:>7.3f}{star} {te_n:>5}{base}")
        all_rows.append({"type": "h3a_score", "score": sc_thr,
                         "tr_pf": tr_pf, "te_pf": te_pf, "te_p": te_p, "te_n": te_n})

    return all_rows


# ---------------------------------------------------------------------------
# H3-B parameter sweep
# ---------------------------------------------------------------------------

def sweep_h3b(ts, o, h, l, c, v, regime):
    print("\n" + "=" * 72)
    print("H3-B PARAMETER SWEEP (Volume Ignition)")
    print("=" * 72)

    vol_mults   = [1.2, 1.5, 1.8, 2.0, 2.5, 3.0]
    rsi_levels  = [45, 48, 50, 52, 55]
    price_gains = [0.003, 0.005, 0.008, 0.010]

    rsi_vals = ind.rsi(c, 14)
    vol_ma   = ind.sma(v, 20)
    n = len(c)

    all_rows = []

    print(f"\n  Full grid: vol_mult × rsi_cross (price_gain=0.5%)")
    print(f"  {'vol×rsi':>12} {'Tr-PF':>7} {'Te-PF':>7} {'Te-p':>7} {'Te-n':>5}  flag")
    print(f"  {'-'*12} {'-'*7} {'-'*7} {'-'*7} {'-'*5}  ----")

    best_te_pf = 0.0; best_params = None
    for vm, rl in product(vol_mults, rsi_levels):
        mask = np.zeros(n, dtype=bool)
        for i in range(1, n):
            if np.isnan(vol_ma[i]) or vol_ma[i] <= 0: continue
            if np.isnan(rsi_vals[i]) or np.isnan(rsi_vals[i-1]): continue
            vol_ok   = v[i] > vm * vol_ma[i]
            price_ok = (c[i] - c[i-1]) / c[i-1] > 0.005
            rsi_ok   = rsi_vals[i] > rl and rsi_vals[i-1] <= rl
            regime_ok = regime[i] != RegimeState.RISK_OFF
            mask[i] = vol_ok and price_ok and rsi_ok and regime_ok

        tr_pf, te_pf, te_p, te_n, _ = run_wf_quick(ts, o, h, l, c, v, regime, mask)
        star = "*" if te_p < 0.10 else " "
        flag = "BASE" if (vm == 1.5 and rl == 50) else ""
        if te_n >= 5 and te_pf > best_te_pf:
            best_te_pf = te_pf; best_params = (vm, rl)
        if te_n >= 5 or (vm == 1.5 and rl == 50):
            print(f"  {vm:.1f}×rsi{rl:>2} {tr_pf:>7.3f} {te_pf:>7.3f} {te_p:>7.3f}{star} "
                  f"{te_n:>5}  {flag}")
        all_rows.append({"vm": vm, "rl": rl, "tr_pf": tr_pf, "te_pf": te_pf,
                         "te_p": te_p, "te_n": te_n})

    if best_params:
        print(f"\n  Best: vol={best_params[0]:.1f}× rsi={best_params[1]}  "
              f"OOS PF={best_te_pf:.3f}")

    # Price gain sensitivity at best vol/rsi
    if best_params:
        vm, rl = best_params
        print(f"\n  Price gain sensitivity (vol={vm:.1f}×, rsi={rl}):")
        print(f"  {'gain%':>7} {'Tr-PF':>7} {'Te-PF':>7} {'Te-p':>7} {'Te-n':>5}")
        for pg in price_gains:
            mask = np.zeros(n, dtype=bool)
            for i in range(1, n):
                if np.isnan(vol_ma[i]) or vol_ma[i] <= 0: continue
                if np.isnan(rsi_vals[i]) or np.isnan(rsi_vals[i-1]): continue
                mask[i] = (v[i] > vm * vol_ma[i]
                           and (c[i] - c[i-1]) / c[i-1] > pg
                           and rsi_vals[i] > rl and rsi_vals[i-1] <= rl
                           and regime[i] != RegimeState.RISK_OFF)
            tr_pf, te_pf, te_p, te_n, _ = run_wf_quick(ts, o, h, l, c, v, regime, mask)
            star = "*" if te_p < 0.10 else " "
            base = " BASE" if pg == 0.005 else ""
            print(f"  {pg*100:>7.1f}% {tr_pf:>7.3f} {te_pf:>7.3f} {te_p:>7.3f}{star} {te_n:>5}{base}")
            all_rows.append({"pg": pg, "tr_pf": tr_pf, "te_pf": te_pf,
                             "te_p": te_p, "te_n": te_n})

    return all_rows


# ---------------------------------------------------------------------------
# H3-C parameter sweep
# ---------------------------------------------------------------------------

def sweep_h3c(ts, o, h, l, c, v, regime):
    print("\n" + "=" * 72)
    print("H3-C PARAMETER SWEEP (RSI + KAMA)")
    print("=" * 72)

    kama_periods = [4, 6, 8, 10, 14]
    rsi_levels   = [45, 48, 50, 52, 55]
    fast_slow    = [(2, 20), (2, 30), (3, 30), (2, 10)]

    n = len(c)
    all_rows = []

    print(f"\n  KAMA period × RSI cross (fast=2, slow=30)")
    print(f"  {'kama_p':>7} {'rsi':>5} {'Tr-PF':>7} {'Te-PF':>7} {'Te-p':>7} {'Te-n':>5}")
    print(f"  {'-'*7} {'-'*5} {'-'*7} {'-'*7} {'-'*7} {'-'*5}")

    for kp, rl in product(kama_periods, rsi_levels):
        kama_v = ind.kama(c, period=kp, fast_period=2, slow_period=30)
        rsi_v  = ind.rsi(c, 14)
        mask = np.zeros(n, dtype=bool)
        for i in range(1, n):
            if np.isnan(kama_v[i]) or np.isnan(kama_v[i-1]): continue
            if np.isnan(rsi_v[i]) or np.isnan(rsi_v[i-1]): continue
            rsi_x  = rsi_v[i] > rl and rsi_v[i-1] <= rl
            kama_x = c[i] > kama_v[i] and c[i-1] <= kama_v[i-1]
            mask[i] = rsi_x and kama_x and regime[i] != RegimeState.RISK_OFF

        tr_pf, te_pf, te_p, te_n, _ = run_wf_quick(ts, o, h, l, c, v, regime, mask,
                                                      exit_method="atr_2_3")
        star = "*" if te_p < 0.10 else " "
        base = " BASE" if (kp == 6 and rl == 50) else ""
        if te_n >= 10:
            print(f"  {kp:>7} {rl:>5} {tr_pf:>7.3f} {te_pf:>7.3f} "
                  f"{te_p:>7.3f}{star} {te_n:>5}{base}")
        all_rows.append({"kp": kp, "rl": rl, "tr_pf": tr_pf, "te_pf": te_pf,
                         "te_p": te_p, "te_n": te_n})

    return all_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 72)
    print("PARAMETER SWEEP — H3-A, H3-B, H3-C robustness")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    sol_df = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)

    r_a = sweep_h3a(ts, o, h, l, c, v, regime)
    r_b = sweep_h3b(ts, o, h, l, c, v, regime)
    r_c = sweep_h3c(ts, o, h, l, c, v, regime)

    # Summary: parameter robustness
    print("\n" + "=" * 72)
    print("ROBUSTNESS SUMMARY")
    print("=" * 72)

    # H3-A: count configurations with OOS PF > 1.5
    h3a_robust = [r for r in r_a if r["te_pf"] > 1.5 and r["te_n"] >= 5]
    h3b_robust = [r for r in r_b if r.get("te_pf", 0) > 2.0 and r.get("te_n", 0) >= 5]
    h3c_robust = [r for r in r_c if r["te_pf"] > 1.3 and r["te_n"] >= 10]

    print(f"\n  H3-A: {len(h3a_robust)}/{len([r for r in r_a if r['te_n']>=5])} "
          f"param configs with OOS PF > 1.5 (n>=5)")
    print(f"  H3-B: {len(h3b_robust)}/{len([r for r in r_b if r.get('te_n',0)>=5])} "
          f"param configs with OOS PF > 2.0 (n>=5)")
    print(f"  H3-C: {len(h3c_robust)}/{len([r for r in r_c if r['te_n']>=10])} "
          f"param configs with OOS PF > 1.3 (n>=10)")

    # Save
    out_path = DATA_DIR / "parameter_sweep_results.json"
    with open(out_path, "w") as f:
        json.dump({"run_at": datetime.now(timezone.utc).isoformat(),
                   "h3a": r_a, "h3b": r_b, "h3c": r_c}, f, indent=2)
    print(f"\nSaved: {out_path}")
