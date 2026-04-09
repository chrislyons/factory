"""
research_loop.py — Autonomous research loop: indicators, exits, regimes, stability.

Runs four studies in sequence:

STUDY 1: H3-B Alt-Coin Expansion
  Test vol_spike+rsi_cross on high-volatility alt coins (daily data).
  Hypothesis: volume ignition is universal on momentum-driven alts.

STUDY 2: Indicator Orthogonality Matrix
  Compute pairwise signal correlation across all 23 indicators.
  Goal: find which pairs are genuinely independent (low correlation = more info).

STUDY 3: Exit Strategy Comparison
  For H3-A and H3-B on SOL 4h, compare:
  - Current: 2× ATR stop / 3× ATR target
  - Trailing Kijun: exit when close < Kijun (trend exit)
  - Trailing ATR: progressive stop raised by 0.5× ATR each bar
  - Bollinger midband: exit when close < BB 20-period midline
  - Time stop: exit after 5 bars regardless

STUDY 4: Rolling Window Stability
  Run H3-A and H3-B on 6-month rolling windows across the full SOL 4h history.
  Check if PF is stable or decaying. Detect regime sensitivity.
"""

from __future__ import annotations

import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

import src.quant.indicators as ind
from src.quant.indicator_research import (
    SignalBacktester, backtest_signal,
    signals_vol_spike_break, signals_rsi_momentum_cross,
    signals_kama_cross, signals_ichimoku_h3a,
)
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade
from src.quant.regime import RegimeState

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"
MAKER_FEE = 0.0016


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def load_asset(symbol, interval_min):
    try:
        return load_binance(symbol, interval_min)
    except FileNotFoundError:
        return None


def run_wf(ts, o, h, l, c, v, regime, atr_v, mask, exit_ma=None,
           capital=10_000.0, bar_hours=4.0, split=0.70):
    N = len(ts)
    SPLIT = int(N * split)
    te = exit_ma[SPLIT:] if exit_ma is not None else None
    tr_exit = exit_ma[:SPLIT] if exit_ma is not None else None
    tr = backtest_signal(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                         c[:SPLIT], v[:SPLIT], mask[:SPLIT], regime[:SPLIT],
                         atr_v[:SPLIT], tr_exit, capital, bar_hours)
    te = backtest_signal(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                         c[SPLIT:], v[SPLIT:], mask[SPLIT:], regime[SPLIT:],
                         atr_v[SPLIT:], exit_ma[SPLIT:] if exit_ma is not None else None,
                         capital, bar_hours)
    return tr, te


def fmt_r(r, label=""):
    if not r:
        return f"{label:8s} n=  0"
    star = "*" if r["p"] < 0.10 else " "
    return (f"{label:8s} n={r['n']:3d} WR={r['wr']:.1%} "
            f"PF={r['pf']:.3f} Sh={r['sharpe']:+.3f} p={r['p']:.3f}{star}")


# ---------------------------------------------------------------------------
# STUDY 1: H3-B alt-coin expansion
# ---------------------------------------------------------------------------

def study1_altcoin_expansion(btc_ts, btc_c):
    print("\n" + "=" * 72)
    print("STUDY 1: H3-B (vol+rsi) Alt-Coin Expansion")
    print("=" * 72)

    # High-vol alt coins with daily data available
    alts = [
        ("NEAR/USD",  1440, 24.0, "NEAR 1d"),
        ("INJ/USD",   1440, 24.0, "INJ 1d"),
        ("WIF/USD",   1440, 24.0, "WIF 1d"),
        ("BONK/USD",  1440, 24.0, "BONK 1d"),
        ("SEI/USD",   1440, 24.0, "SEI 1d"),
        ("ORDI/USD",  1440, 24.0, "ORDI 1d"),
        ("GRT/USD",   1440, 24.0, "GRT 1d"),
        ("TIA/USD",   1440, 24.0, "TIA 1d"),
        ("PYTH/USD",  1440, 24.0, "PYTH 1d"),
        ("RENDER/USD",1440, 24.0, "RENDER 1d"),
        ("FET/USD",   1440, 24.0, "FET 1d"),
        ("LINK/USD",  1440, 24.0, "LINK 1d"),
        ("AVAX/USD",  1440, 24.0, "AVAX 1d"),
        ("ATOM/USD",  1440, 24.0, "ATOM 1d"),
        ("XRP/USD",   1440, 24.0, "XRP 1d"),
        ("SOL/USDT",  1440, 24.0, "SOL 1d"),    # reference
        ("SOL/USDT",  240,  4.0,  "SOL 4h"),    # known good
    ]

    results = {}
    print(f"\n  {'Asset':<14} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  "
          f"{'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}  flag")
    print(f"  {'-'*14} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7} {'-'*7}  ----")

    for sym, itvl, bh, label in alts:
        df = load_asset(sym, itvl)
        if df is None or len(df) < 200:
            print(f"  {label:<14} [no data]")
            continue

        ts, o, h, l, c, v = df_to_arrays(df)
        regime = build_btc_trend_regime(btc_c, ts, btc_ts)
        atr_v = ind.atr(h, l, c, 14)

        m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
        m_rsi, _ = signals_rsi_momentum_cross(c)
        mask = m_vol & m_rsi

        tr, te = run_wf(ts, o, h, l, c, v, regime, atr_v, mask, bar_hours=bh)

        flag = ""
        if te and te["n"] >= 5:
            if te["pf"] > 2.0 and te["p"] < 0.10: flag = "STRONG*"
            elif te["pf"] > 1.5: flag = "pass"
            elif te["pf"] < 0.8: flag = "fail"

        tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['p']:7.3f}" if tr else "    0       -       -"
        te_s = (f"{te['n']:5d} {te['pf']:7.3f} {te['sharpe']:7.3f} {te['p']:7.3f}"
                if te else "    0       -       -       -")
        star = "*" if (te and te["p"] < 0.10) else " "
        print(f"  {label:<14} {tr_s}  {te_s}{star}  {flag}")
        results[label] = {"train": tr, "test": te}

    pass_assets = [k for k, v in results.items()
                   if v["test"] and v["test"]["n"] >= 5 and v["test"]["pf"] > 1.5]
    print(f"\n  H3-B passes (OOS PF > 1.5, n >= 5): {pass_assets}")
    return results


# ---------------------------------------------------------------------------
# STUDY 2: Indicator orthogonality / correlation matrix
# ---------------------------------------------------------------------------

def study2_orthogonality(ts, o, h, l, c, v):
    print("\n" + "=" * 72)
    print("STUDY 2: Indicator Signal Correlation Matrix")
    print("=" * 72)
    print("  (% of bars where both signals fire simultaneously)")

    from src.quant.indicator_research import build_all_signals
    all_sigs = build_all_signals(o, h, l, c, v)

    # Only include signals that generate > 10 fires
    active = {k: m for k, (m, _) in all_sigs.items()
              if np.sum(m) >= 10}
    names = list(active.keys())
    n_sig = len(names)
    masks = np.array([active[k].astype(float) for k in names])

    # Compute Jaccard similarity: |A∩B| / |A∪B|
    print(f"\n  Jaccard similarity (high = correlated, use only one):")
    print(f"  Threshold: show pairs with Jaccard >= 0.15")

    pairs = []
    for i in range(n_sig):
        for j in range(i+1, n_sig):
            a = masks[i]; b = masks[j]
            intersection = np.sum(a * b)
            union = np.sum(np.clip(a + b, 0, 1))
            jaccard = float(intersection / union) if union > 0 else 0.0
            if jaccard >= 0.15:
                pairs.append((jaccard, names[i], names[j]))

    pairs.sort(reverse=True)
    for j, n1, n2 in pairs[:20]:
        print(f"  {j:.3f}  {n1:<28} ↔  {n2}")

    # Find most orthogonal productive pairs
    print(f"\n  Most ORTHOGONAL pairs (Jaccard < 0.05, both have >= 20 fires):")
    orth_pairs = []
    for i in range(n_sig):
        for j in range(i+1, n_sig):
            a = masks[i]; b = masks[j]
            if np.sum(a) < 20 or np.sum(b) < 20:
                continue
            intersection = np.sum(a * b)
            union = np.sum(np.clip(a + b, 0, 1))
            jaccard = float(intersection / union) if union > 0 else 0.0
            if jaccard < 0.05:
                orth_pairs.append((jaccard, names[i], names[j],
                                   int(np.sum(a)), int(np.sum(b)),
                                   int(intersection)))

    orth_pairs.sort(key=lambda x: x[5], reverse=True)  # sort by intersection count
    for j, n1, n2, c1, c2, inter in orth_pairs[:15]:
        print(f"  J={j:.3f}  {n1:<28} ↔  {n2:<28}  fires=({c1},{c2})  overlap={inter}")

    return pairs, orth_pairs


# ---------------------------------------------------------------------------
# STUDY 3: Exit strategy comparison
# ---------------------------------------------------------------------------

class ExitResearchBacktester:
    """
    Tests different exit strategies for the same entry signal.
    Uses H3-A or H3-B entry mask, swaps only the exit logic.
    """

    EXIT_METHODS = ["atr_2_3", "atr_1_5_2_5", "atr_3_4",
                    "kijun_trail", "atr_trail", "bb_mid", "time5", "time10"]

    def __init__(self, initial_capital=10_000.0, bar_hours=4.0):
        self.initial_capital = initial_capital
        self.bar_hours = bar_hours

    def run_exit(self, ts, o, h, l, c, v, regime, signal_mask, exit_method,
                 atr_stop_mult=2.0, atr_target_mult=3.0):
        n = len(ts)
        wallet = self.initial_capital
        min_hold = max(1, int(2 / max(self.bar_hours, 1)))
        cooldown = max(1, int(2 / max(self.bar_hours, 1)))

        atr_v = ind.atr(h, l, c, 14)
        ichi  = ind.ichimoku(h, l, c)
        bb    = ind.bollinger_bands(c, 20)

        trades = []
        counter = 0
        last_exit = -999
        daily_pnl = 0.0; halted = False; cur_day = -1

        i = 60
        while i < n - min_hold - 2:
            day = int(ts[i] // 86400)
            if day != cur_day:
                cur_day = day; daily_pnl = 0.0; halted = False
            if halted: i += 1; continue
            if i - last_exit < cooldown: i += 1; continue
            if regime[i] == RegimeState.RISK_OFF: i += 1; continue
            if not signal_mask[i]: i += 1; continue

            av = atr_v[i]
            if np.isnan(av) or av <= 0: i += 1; continue

            eb = i + 1
            if eb >= n: break

            ep = o[eb]
            pos = wallet * 0.02
            if pos < 1.0: i += 1; continue

            # Set stops based on method
            if exit_method == "atr_1_5_2_5":
                stop_p = ep - 1.5 * av; target_p = ep + 2.5 * av
            elif exit_method == "atr_3_4":
                stop_p = ep - 3.0 * av; target_p = ep + 4.0 * av
            else:  # default atr_2_3
                stop_p = ep - atr_stop_mult * av; target_p = ep + atr_target_mult * av

            et = datetime.fromtimestamp(ts[eb], tz=timezone.utc)
            trade = Trade(
                trade_id=f"EXIT-{counter:05d}", venue=VENUE, strategy=exit_method,
                pair="SOL/USDT", entry_timestamp=et, entry_price=ep,
                position_size_usd=pos, regime_state=regime[i],
                side="long", leverage=1.0,
                stop_level=stop_p, target_level=target_p,
                fees_paid=pos * MAKER_FEE,
            )
            counter += 1

            # Progressive trailing stop
            trail_stop = stop_p

            xb = eb; xp = ep; xr = ExitReason.TIME_STOP
            for j in range(1, n - eb):
                bar = eb + j
                if bar >= n: break

                cur_av = atr_v[bar] if not np.isnan(atr_v[bar]) else av

                # Update trailing stop
                if exit_method == "atr_trail":
                    trail_stop = max(trail_stop, c[bar] - 2.0 * cur_av)
                    if c[bar] < trail_stop and j >= min_hold:
                        xb = bar; xp = trail_stop; xr = ExitReason.STOP_HIT; break

                # Standard stop/target
                if c[bar] < stop_p if exit_method != "atr_trail" else False:
                    if c[bar] < stop_p:
                        xb = bar; xp = stop_p; xr = ExitReason.STOP_HIT; break
                if h[bar] >= target_p:
                    xb = bar; xp = target_p; xr = ExitReason.TARGET_HIT; break

                # Low-based stop
                if l[bar] <= stop_p and exit_method != "atr_trail":
                    xb = bar; xp = stop_p; xr = ExitReason.STOP_HIT; break

                # Kijun trailing exit
                if exit_method == "kijun_trail" and j >= min_hold:
                    kj = ichi.kijun_sen[bar]
                    if not np.isnan(kj) and c[bar] < kj:
                        xb = bar; xp = c[bar]; xr = ExitReason.TIME_STOP; break

                # BB midline exit
                if exit_method == "bb_mid" and j >= min_hold:
                    bm = bb.middle[bar]
                    if not np.isnan(bm) and c[bar] < bm:
                        xb = bar; xp = c[bar]; xr = ExitReason.TIME_STOP; break

                # Time stops
                if exit_method == "time5" and j >= 5:
                    xb = bar; xp = c[bar]; xr = ExitReason.TIME_STOP; break
                if exit_method == "time10" and j >= 10:
                    xb = bar; xp = c[bar]; xr = ExitReason.TIME_STOP; break

                if regime[bar] == RegimeState.RISK_OFF and j >= min_hold:
                    xb = bar; xp = c[bar]; xr = ExitReason.REGIME_EXIT; break

            xt = datetime.fromtimestamp(ts[min(xb, n-1)], tz=timezone.utc)
            trade.close(xp, xt, xr, fees=pos * MAKER_FEE)
            if trade.pnl_usd is not None:
                wallet += trade.pnl_usd
                daily_pnl += trade.pnl_usd
                if daily_pnl < -(self.initial_capital * 0.03):
                    halted = True

            last_exit = xb
            trades.append(trade)
            i = xb + cooldown

        return trades


def study3_exit_comparison(ts, o, h, l, c, v, regime, atr_v):
    print("\n" + "=" * 72)
    print("STUDY 3: Exit Strategy Comparison (SOL 4h)")
    print("=" * 72)

    SPLIT = int(len(ts) * 0.70)
    m_h3a, _ = signals_ichimoku_h3a(h, l, c)
    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    m_h3b = m_vol & m_rsi

    bt = ExitResearchBacktester(bar_hours=4.0)

    for strategy_name, mask in [("H3-A", m_h3a), ("H3-B", m_h3b)]:
        print(f"\n  -- {strategy_name} --")
        print(f"  {'Exit Method':<18} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-Sh':>7} "
              f"{'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}  note")
        print(f"  {'-'*18} {'-'*5} {'-'*7} {'-'*7} "
              f"{'-'*5} {'-'*7} {'-'*7} {'-'*7}  ----")

        exit_results = {}
        for exit_method in ExitResearchBacktester.EXIT_METHODS:
            tr_trades = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                                    c[:SPLIT], v[:SPLIT], regime[:SPLIT],
                                    mask[:SPLIT], exit_method)
            te_trades = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                                    c[SPLIT:], v[SPLIT:], regime[SPLIT:],
                                    mask[SPLIT:], exit_method)

            def stats(trades):
                if not trades: return None
                eng = BacktestEngine(10_000.0)
                eng.add_trades(trades)
                s = eng.compute_stats(venue=VENUE)
                return {"n": s.n_trades, "wr": s.win_rate, "pf": s.profit_factor,
                        "sharpe": s.sharpe_ratio, "dd": s.max_drawdown_pct,
                        "pnl": s.total_pnl_pct, "p": s.p_value}

            tr = stats(tr_trades); te = stats(te_trades)

            tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['sharpe']:7.3f}" if tr else "    0       -       -"
            te_s = (f"{te['n']:5d} {te['pf']:7.3f} {te['sharpe']:7.3f} {te['p']:7.3f}"
                    if te else "    0       -       -       -")
            star = "*" if (te and te["p"] < 0.10) else " "

            # Flag vs current best
            note = ""
            if te and te["n"] >= 5:
                if exit_method == "atr_2_3":
                    note = "(current)"
                elif te["pf"] > 3.5 and strategy_name == "H3-A": note = "BETTER"
                elif te["pf"] > 4.5 and strategy_name == "H3-B": note = "BETTER"

            print(f"  {exit_method:<18} {tr_s}  {te_s}{star}  {note}")
            exit_results[exit_method] = {"train": tr, "test": te}

        # Best exit for this strategy
        best = max(
            [(k, v) for k, v in exit_results.items() if v["test"] and v["test"]["n"] >= 5],
            key=lambda x: x[1]["test"]["pf"] * (1 - x[1]["test"]["p"]),
            default=(None, None)
        )
        if best[0]:
            te = best[1]["test"]
            print(f"\n  Best exit for {strategy_name}: {best[0]}  "
                  f"OOS PF={te['pf']:.3f} Sh={te['sharpe']:+.3f} p={te['p']:.3f}")

    return {}


# ---------------------------------------------------------------------------
# STUDY 4: Rolling window stability
# ---------------------------------------------------------------------------

def study4_rolling_stability(ts, o, h, l, c, v, regime, atr_v, window_bars=1095):
    """
    Roll a window of `window_bars` bars across the full history.
    For each window, measure H3-A and H3-B OOS PF.
    Shows whether the edge is stable or regime-dependent.
    window_bars=1095: ~6 months of 4h bars (182 days × 6 bars/day).
    """
    print("\n" + "=" * 72)
    print(f"STUDY 4: Rolling Window Stability ({window_bars} bars = ~6mo 4h)")
    print("=" * 72)

    m_h3a, _ = signals_ichimoku_h3a(h, l, c)
    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    m_h3b = m_vol & m_rsi

    N = len(ts)
    step = window_bars // 3  # step 1/3 window at a time
    INNER_SPLIT = int(window_bars * 0.60)  # 60/40 inside each window

    print(f"\n  {'Window':<28} {'H3-A OOS PF':>12} {'H3-A n':>8}  "
          f"{'H3-B OOS PF':>12} {'H3-B n':>8}")
    print(f"  {'-'*28} {'-'*12} {'-'*8}  {'-'*12} {'-'*8}")

    stability_rows = []
    start = 0
    while start + window_bars <= N:
        end = start + window_bars
        w_ts = ts[start:end]; w_o = o[start:end]; w_h = h[start:end]
        w_l  = l[start:end];  w_c = c[start:end]; w_v = v[start:end]
        w_regime = regime[start:end]; w_atr = atr_v[start:end]
        w_h3a = m_h3a[start:end]; w_h3b = m_h3b[start:end]

        sp = INNER_SPLIT

        def oos_pf(mask):
            te = backtest_signal(w_ts[sp:], w_o[sp:], w_h[sp:], w_l[sp:],
                                 w_c[sp:], w_v[sp:], mask[sp:], w_regime[sp:],
                                 w_atr[sp:], None, 10_000.0, 4.0)
            return te

        r_a = oos_pf(w_h3a)
        r_b = oos_pf(w_h3b)

        period_start = datetime.fromtimestamp(w_ts[0], tz=timezone.utc).strftime("%Y-%m")
        period_end   = datetime.fromtimestamp(w_ts[-1], tz=timezone.utc).strftime("%Y-%m")
        period_label = f"{period_start} → {period_end}"

        a_str = f"{r_a['pf']:12.3f}" if (r_a and r_a["n"] >= 3) else "           -"
        a_n   = f"{r_a['n']:8d}"      if (r_a and r_a["n"] >= 3) else "       -"
        b_str = f"{r_b['pf']:12.3f}" if (r_b and r_b["n"] >= 3) else "           -"
        b_n   = f"{r_b['n']:8d}"      if (r_b and r_b["n"] >= 3) else "       -"

        print(f"  {period_label:<28} {a_str} {a_n}  {b_str} {b_n}")
        stability_rows.append({
            "period": period_label,
            "h3a_pf": r_a["pf"] if (r_a and r_a["n"] >= 3) else None,
            "h3a_n":  r_a["n"]  if (r_a and r_a["n"] >= 3) else 0,
            "h3b_pf": r_b["pf"] if (r_b and r_b["n"] >= 3) else None,
            "h3b_n":  r_b["n"]  if (r_b and r_b["n"] >= 3) else 0,
        })
        start += step

    # Stability summary
    h3a_pfs = [r["h3a_pf"] for r in stability_rows if r["h3a_pf"] is not None]
    h3b_pfs = [r["h3b_pf"] for r in stability_rows if r["h3b_pf"] is not None]

    if h3a_pfs:
        print(f"\n  H3-A PF range: {min(h3a_pfs):.3f} – {max(h3a_pfs):.3f}  "
              f"mean={np.mean(h3a_pfs):.3f}  positive_windows={sum(1 for x in h3a_pfs if x > 1)}/{len(h3a_pfs)}")
    if h3b_pfs:
        print(f"  H3-B PF range: {min(h3b_pfs):.3f} – {max(h3b_pfs):.3f}  "
              f"mean={np.mean(h3b_pfs):.3f}  positive_windows={sum(1 for x in h3b_pfs if x > 1)}/{len(h3b_pfs)}")

    return stability_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 72)
    print("IG-88 RESEARCH LOOP — Indicators, Exits, Stability")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    sol_df = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    regime_sol = build_btc_trend_regime(btc_c, ts, btc_ts)
    atr_sol = ind.atr(h, l, c, 14)

    all_results = {}

    # Study 1
    s1 = study1_altcoin_expansion(btc_ts, btc_c)
    all_results["altcoin_expansion"] = s1
    todos_done = ["1"]

    # Study 2
    s2_corr, s2_orth = study2_orthogonality(ts, o, h, l, c, v)
    all_results["orthogonality_top_corr"] = [(j, n1, n2) for j, n1, n2 in s2_corr[:10]]
    all_results["orthogonality_top_orth"] = [(j, n1, n2, c1, c2, inter)
                                              for j, n1, n2, c1, c2, inter in s2_orth[:10]]

    # Study 3
    s3 = study3_exit_comparison(ts, o, h, l, c, v, regime_sol, atr_sol)
    all_results["exit_comparison"] = s3

    # Study 4
    s4 = study4_rolling_stability(ts, o, h, l, c, v, regime_sol, atr_sol)
    all_results["rolling_stability"] = s4

    # Save
    out_path = DATA_DIR / "research_loop_results.json"
    with open(out_path, "w") as f:
        json.dump({"run_at": datetime.now(timezone.utc).isoformat(),
                   "results": all_results}, f, indent=2, default=str)
    print(f"\nAll results saved: {out_path}")
