"""
refined_strategies.py — Apply exit optimization and test H3-B on perps.

Uses findings from research_loop.py:
  - H3-A: switch from ATR 2×/3× to ATR trailing stop
  - H3-B: switch from ATR 2×/3× to time-10-bar exit (or ATR trail)
  - H3-B on SOL-PERP: test whether momentum ignition works with leverage

Also builds the regime-conditional composite strategy:
  - RISK_ON:  prefer H3-A (quality, Ichimoku)
  - NEUTRAL:  run H3-B (volume ignition)
  - RISK_OFF: Polymarket only (no spot/perps)
"""

from __future__ import annotations

import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

import src.quant.indicators as ind
from src.quant.research_loop import ExitResearchBacktester
from src.quant.indicator_research import (
    backtest_signal, signals_vol_spike_break,
    signals_rsi_momentum_cross, signals_ichimoku_h3a,
)
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade
from src.quant.regime import RegimeState
from src.quant.perps_backtest import PerpsBacktester

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE_SPOT = "kraken_spot"
VENUE_PERP = "jupiter_perps"
MAKER_FEE  = 0.0016
PERP_FEE   = 0.0007


def run_wf_exit(ts, o, h, l, c, v, regime, mask, exit_method,
                capital=10_000.0, bar_hours=4.0, split=0.70):
    """Walk-forward using ExitResearchBacktester."""
    SPLIT = int(len(ts) * split)
    bt = ExitResearchBacktester(capital, bar_hours)
    tr_trades = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                             c[:SPLIT], v[:SPLIT], regime[:SPLIT], mask[:SPLIT], exit_method)
    te_trades = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                             c[SPLIT:], v[SPLIT:], regime[SPLIT:], mask[SPLIT:], exit_method)

    def stats(trades):
        if not trades: return None
        eng = BacktestEngine(capital)
        eng.add_trades(trades)
        s = eng.compute_stats(venue=VENUE_SPOT)
        return {"n": s.n_trades, "wr": round(s.win_rate, 4),
                "pf": round(s.profit_factor, 4), "sharpe": round(s.sharpe_ratio, 4),
                "dd": round(s.max_drawdown_pct, 4), "pnl_pct": round(s.total_pnl_pct, 4),
                "p": round(s.p_value, 4), "exp_r": round(s.expectancy_r, 4)}

    return stats(tr_trades), stats(te_trades)


# ---------------------------------------------------------------------------
# 1. Final exit validation — confirm best exits hold on cross-asset
# ---------------------------------------------------------------------------

def validate_exits(btc_ts, btc_c):
    print("\n" + "=" * 72)
    print("REFINED EXIT VALIDATION — Best exits on multiple assets")
    print("=" * 72)

    assets = [
        ("SOL/USDT", 240,  4.0,  "SOL 4h"),
        ("ETH/USDT", 240,  4.0,  "ETH 4h"),
        ("BTC/USD",  240,  4.0,  "BTC 4h"),
        ("ETH/USDT", 1440, 24.0, "ETH 1d"),
    ]

    results = {}

    for sym, itvl, bh, label in assets:
        try:
            df = load_binance(sym, itvl)
        except FileNotFoundError:
            continue
        ts, o, h, l, c, v = df_to_arrays(df)
        regime = build_btc_trend_regime(btc_c, ts, btc_ts)

        m_h3a, _ = signals_ichimoku_h3a(h, l, c)
        m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
        m_rsi, _ = signals_rsi_momentum_cross(c)
        m_h3b = m_vol & m_rsi

        print(f"\n  [{label}]")
        print(f"  {'Strategy+Exit':<30} {'Tr-PF':>7} {'Tr-p':>7}  {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}")
        print(f"  {'-'*30} {'-'*7} {'-'*7}  {'-'*7} {'-'*7} {'-'*7}")

        for strat_name, mask in [("H3-A", m_h3a), ("H3-B", m_h3b)]:
            for exit_m in ["atr_2_3", "atr_trail", "time5" if strat_name == "H3-A" else "time10"]:
                tr, te = run_wf_exit(ts, o, h, l, c, v, regime, mask, exit_m,
                                     bar_hours=bh)
                if tr and te:
                    star = "*" if te["p"] < 0.10 else " "
                    combo = f"{strat_name}+{exit_m}"
                    print(f"  {combo:<30} {tr['pf']:7.3f} {tr['p']:7.3f}  "
                          f"{te['pf']:7.3f} {te['sharpe']:7.3f} {te['p']:7.3f}{star}")
                    results[f"{label}_{strat_name}_{exit_m}"] = {"train": tr, "test": te}

    return results


# ---------------------------------------------------------------------------
# 2. H3-B on Jupiter Perps (SOL-PERP)
# ---------------------------------------------------------------------------

def test_h3b_perps(btc_ts, btc_c):
    """
    CORRECTED perps simulation.

    BUG FIXED: The old code divided ATR by leverage making stops impossibly tight
    (0 or very few trades generated). Correct approach:
      1. Run standard backtester with NORMAL ATR stops (unmodified)
      2. Collect spot-equivalent trades
      3. Post-process: pnl_pct_perp = pnl_pct_spot * leverage + fee_savings
         fee_savings = spot_RT_fee - perp_RT_fee = 0.32% - 0.14% = +0.18% per trade
         (perps are CHEAPER than spot, so fee_savings is positive)
      4. Borrow fees (~0.01%/hr) NOT modeled -- stated clearly

    Fee rates:
      Spot:  0.16%/side × 2 = 0.32% RT
      Perps: 0.07%/side × 2 = 0.14% RT  => saves 0.18% per trade
    """
    import math

    print("\\n" + "=" * 72)
    print("H3-B ON JUPITER PERPS — CORRECTED SIMULATION (bug fixed)")
    print("=" * 72)
    print("  FIX: ATR stops are kept in NORMAL price terms (not divided by leverage).")
    print("  Post-trade scaling: pnl_pct_perp = pnl_pct_spot * leverage + fee_savings")
    print(f"  fee_savings per trade = +0.18% (perp 0.14% RT vs spot 0.32% RT)")
    print("  BORROW FEES (~0.01%/hr) NOT MODELED -- account for these in live trading.")

    sol_df = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    n = len(ts)
    SPLIT = int(n * 0.70)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)

    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    signal_mask = m_vol & m_rsi

    # Step 1: collect spot-equivalent trades using normal ATR stops
    bt = ExitResearchBacktester(initial_capital=5_000.0, bar_hours=4.0)
    tr_trades = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                             c[:SPLIT], v[:SPLIT], regime[:SPLIT], signal_mask[:SPLIT],
                             "atr_trail")
    te_trades = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                             c[SPLIT:], v[SPLIT:], regime[SPLIT:], signal_mask[SPLIT:],
                             "atr_trail")

    spot_tr_pnl = np.array([t.pnl_pct for t in tr_trades if t.pnl_pct is not None])
    spot_te_pnl = np.array([t.pnl_pct for t in te_trades if t.pnl_pct is not None])

    SPOT_FEE_RT = 0.0032   # 0.16%/side × 2
    PERP_FEE_RT = 0.0014   # 0.07%/side × 2
    FEE_SAVING  = SPOT_FEE_RT - PERP_FEE_RT  # +0.0018

    def _stats_from_pnl(pnl_arr):
        pnl = np.asarray(pnl_arr, dtype=float)
        n_t = len(pnl)
        if n_t == 0:
            return None
        wins   = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        wr   = len(wins) / n_t
        gw   = float(np.sum(wins))   if len(wins)   > 0 else 0.0
        gl   = float(np.sum(np.abs(losses))) if len(losses) > 0 else 0.0
        pf   = gw / gl if gl > 0 else float('inf')
        sharpe = ((np.mean(pnl) / np.std(pnl)) * np.sqrt(252)
                  if n_t > 1 and np.std(pnl) > 0 else 0.0)
        if n_t > 1:
            se = float(np.std(pnl, ddof=1)) / math.sqrt(n_t)
            t_s = float(np.mean(pnl)) / se if se > 0 else 0.0
            df  = n_t - 1
            z   = abs(t_s) * (1 - 1 / (4 * df)) if df > 0 else abs(t_s)
            p2  = math.erfc(z / math.sqrt(2))
            p   = p2 / 2 if t_s > 0 else 1 - p2 / 2
        else:
            t_s, p = 0.0, 1.0
        equity  = np.cumsum(pnl)
        rm      = np.maximum.accumulate(equity)
        max_dd  = float(np.max(rm - equity)) if len(equity) > 0 else 0.0
        return {"n": n_t, "wr": round(wr, 4), "pf": round(pf, 4),
                "sharpe": round(sharpe, 4), "dd": round(max_dd, 4),
                "p": round(p, 4)}

    results = {}
    print(f"\\n  {'Config':<28}  {'Ph':<5}  "
          f"{'n':>5}  {'WR':>7}  {'PF':>7}  {'Sharpe':>7}  {'MaxDD':>7}  {'p':>7}")
    print(f"  {'-'*28}  {'-'*5}  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}")

    for leverage in [1.0, 2.0, 3.0, 5.0]:
        # Post-scale: pnl_pct_perp = pnl_pct_spot * leverage + fee_savings
        perp_tr = spot_tr_pnl * leverage + FEE_SAVING
        perp_te = spot_te_pnl * leverage + FEE_SAVING

        tr_s = _stats_from_pnl(perp_tr)
        te_s = _stats_from_pnl(perp_te)

        lbl = f"{int(leverage)}x leverage (atr_trail)"
        for phase, s in [("TRAIN", tr_s), ("TEST", te_s)]:
            if s:
                star = "*" if (phase == "TEST" and s["p"] < 0.10) else " "
                print(f"  {lbl:<28}  {phase:<5}  "
                      f"{s['n']:5d}  {s['wr']:7.1%}  {s['pf']:7.3f}  "
                      f"{s['sharpe']:+7.3f}  {s['dd']:7.4f}  {s['p']:7.3f}{star}")
            else:
                print(f"  {lbl:<28}  {phase:<5}  "
                      f"{'0':>5}  {'---':>7}  {'---':>7}  {'---':>7}  {'---':>7}  {'---':>7}")
        results[f"{int(leverage)}x"] = {"train": tr_s, "test": te_s}

    print("\\n  Note: Excludes borrow fees (~0.01%/hr at normal utilisation).")
    print("  At 3x/24h avg hold: ~0.24% extra cost per trade (reduces PF significantly).")
    return results


# ---------------------------------------------------------------------------
# 3. Regime-conditional composite scanner config
# ---------------------------------------------------------------------------

def build_regime_conditional_config(btc_ts, btc_c):
    print("\n" + "=" * 72)
    print("REGIME-CONDITIONAL STRATEGY PERFORMANCE")
    print("=" * 72)

    sol_df = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    n = len(ts)
    SPLIT = int(n * 0.70)

    # Build fine-grained regime (3-state per bar)
    btc_ts_arr = btc_df_ts = btc_ts
    btc_closes = btc_c
    btc_daily_ts_arr = np.array(btc_ts)

    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    atr_v = ind.atr(h, l, c, 14)

    m_h3a, _ = signals_ichimoku_h3a(h, l, c)
    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    m_h3b = m_vol & m_rsi

    # Regime-conditional masks
    risk_on_mask  = np.array([r == RegimeState.RISK_ON  for r in regime])
    neutral_mask  = np.array([r == RegimeState.NEUTRAL  for r in regime])

    # H3-A in RISK_ON only
    m_h3a_ro = m_h3a & risk_on_mask
    # H3-B in NEUTRAL only
    m_h3b_neutral = m_h3b & neutral_mask
    # H3-B in any non-RISK_OFF
    m_h3b_any = m_h3b & (risk_on_mask | neutral_mask)

    print(f"\n  Regime distribution: RISK_ON={risk_on_mask.sum()/n:.1%}  "
          f"NEUTRAL={neutral_mask.sum()/n:.1%}  "
          f"RISK_OFF={(~(risk_on_mask|neutral_mask)).sum()/n:.1%}")

    bt = ExitResearchBacktester(10_000.0, 4.0)
    results = {}

    for name, mask, exit_m in [
        ("H3-A all regimes + atr_trail",   m_h3a,         "atr_trail"),
        ("H3-A RISK_ON + atr_trail",        m_h3a_ro,      "atr_trail"),
        ("H3-B all + atr_trail",            m_h3b_any,     "atr_trail"),
        ("H3-B neutral + atr_trail",        m_h3b_neutral, "atr_trail"),
        ("H3-A+H3-B combined + atr_trail",  m_h3a | m_h3b, "atr_trail"),
    ]:
        tr_trades = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                                 c[:SPLIT], v[:SPLIT], regime[:SPLIT], mask[:SPLIT], exit_m)
        te_trades = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                                 c[SPLIT:], v[SPLIT:], regime[SPLIT:], mask[SPLIT:], exit_m)

        def s(trades):
            if not trades: return None
            eng = BacktestEngine(10_000.0)
            eng.add_trades(trades)
            st = eng.compute_stats(venue=VENUE_SPOT)
            return {"n": st.n_trades, "wr": round(st.win_rate, 4),
                    "pf": round(st.profit_factor, 4),
                    "sharpe": round(st.sharpe_ratio, 4),
                    "dd": round(st.max_drawdown_pct, 4),
                    "p": round(st.p_value, 4)}

        tr = s(tr_trades); te = s(te_trades)
        star = "*" if (te and te["p"] < 0.10) else " "
        tr_s = f"n={tr['n']:3d} PF={tr['pf']:.3f}" if tr else "n=  0"
        te_s = (f"n={te['n']:3d} PF={te['pf']:.3f} Sh={te['sharpe']:+.3f} p={te['p']:.3f}{star}"
                if te else "n=  0")
        print(f"  {name:<40}  TRAIN:{tr_s}  TEST:{te_s}")
        results[name] = {"train": tr, "test": te}

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 72)
    print("REFINED STRATEGIES — Exit optimization + Perps + Regime-conditional")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    r1 = validate_exits(btc_ts, btc_c)
    r2 = test_h3b_perps(btc_ts, btc_c)
    r3 = build_regime_conditional_config(btc_ts, btc_c)

    # Save
    out_path = DATA_DIR / "refined_strategies_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "run_at":           datetime.now(timezone.utc).isoformat(),
            "exit_validation":  r1,
            "h3b_perps":        r2,
            "regime_conditional": r3,
        }, f, indent=2)
    print(f"\nSaved: {out_path}")
