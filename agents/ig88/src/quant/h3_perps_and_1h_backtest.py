"""
h3_perps_and_1h_backtest.py

1. FIX: Corrected Jupiter Perps H3-B simulation
   - Bug was dividing ATR by leverage making stops impossibly tight
   - Fix: use normal ATR stops, then POST-PROCESS trade pnl_pct by leverage
   - Perp fee: 0.07%/side = 0.14% RT vs spot 0.16%/side = 0.32% RT
     => perps is CHEAPER by 0.18% RT, adds to pnl
   - Borrow fees (~0.01%/hr) NOT modeled -- stated clearly

2. H3-A and H3-B on SOL/USDT 1h (8760 bars, 1yr) with 70/30 walk-forward
"""

from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np
import pandas as pd

from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.research_loop import ExitResearchBacktester
from src.quant.indicator_research import (
    signals_ichimoku_h3a, signals_vol_spike_break, signals_rsi_momentum_cross
)
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade, TradeOutcome
import src.quant.indicators as ind
from src.quant.regime import RegimeState

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE_SPOT = "kraken_spot"
VENUE_PERP = "jupiter_perps"
SPOT_FEE_RT = 0.0032    # 0.16% per side × 2 = 0.32% round trip
PERP_FEE_RT = 0.0014    # 0.07% per side × 2 = 0.14% round trip
FEE_SAVING   = SPOT_FEE_RT - PERP_FEE_RT  # +0.0018 in favor of perps


# ---------------------------------------------------------------------------
# Helper: compute stats from a list of (pnl_pct, win_bool) tuples
# ---------------------------------------------------------------------------

def compute_stats_from_pnl_array(pnl_arr: np.ndarray, capital: float = 5_000.0) -> dict | None:
    """Compute WR, PF, Sharpe, p from an array of pnl_pct values."""
    from src.quant.backtest_engine import _ttest_1samp
    import math

    pnl = np.asarray(pnl_arr, dtype=float)
    n = len(pnl)
    if n == 0:
        return None

    wins  = pnl[pnl > 0]
    losses= pnl[pnl < 0]
    wr    = len(wins) / n
    gross_w = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_l = float(np.sum(np.abs(losses))) if len(losses) > 0 else 0.0
    pf    = gross_w / gross_l if gross_l > 0 else float('inf')

    # Sharpe (annualised, using n as proxy for time normalisation via sqrt(252))
    if n > 1 and np.std(pnl) > 0:
        sharpe = (np.mean(pnl) / np.std(pnl)) * np.sqrt(252)
    else:
        sharpe = 0.0

    # t-test
    if n > 1:
        mean = float(np.mean(pnl))
        se   = float(np.std(pnl, ddof=1)) / math.sqrt(n)
        t    = mean / se if se > 0 else 0.0
        df   = n - 1
        if df > 30:
            p = math.erfc(abs(t) / math.sqrt(2))
        else:
            x = df / (df + t * t)
            z = abs(t) * (1 - 1 / (4 * df))
            p = math.erfc(z / math.sqrt(2))
        p_one = p / 2 if t > 0 else 1 - p / 2
    else:
        t, p_one = 0.0, 1.0

    total_pnl = float(np.sum(pnl))
    max_dd = 0.0
    equity = np.cumsum(pnl)
    running_max = np.maximum.accumulate(equity)
    dd = running_max - equity
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    return {
        "n": n,
        "wr": round(wr, 4),
        "pf": round(pf, 4),
        "sharpe": round(sharpe, 4),
        "dd": round(max_dd, 4),
        "pnl_pct": round(total_pnl, 4),
        "p": round(p_one, 4),
    }


# ---------------------------------------------------------------------------
# Corrected Perps simulation
# ---------------------------------------------------------------------------

def run_h3b_perps_corrected(btc_ts, btc_c):
    print()
    print("=" * 72)
    print("H3-B ON JUPITER PERPS — CORRECTED SIMULATION")
    print("=" * 72)
    print()
    print("  Methodology:")
    print("  1. Run ExitResearchBacktester with NORMAL ATR stops (no leverage division)")
    print("  2. Collect spot-equivalent trades")
    print("  3. For each trade: pnl_pct_perp = pnl_pct_spot * leverage + fee_savings")
    print(f"     fee_savings per trade = {FEE_SAVING:.4f} ({FEE_SAVING*100:.2f}%)")
    print(f"     (spot RT fee={SPOT_FEE_RT:.4f}, perp RT fee={PERP_FEE_RT:.4f})")
    print("  4. Borrow fees (~0.01%/hr) NOT modeled -- live trades must account for this")
    print()

    sol_df = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    n = len(ts)
    SPLIT = int(n * 0.70)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)

    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    signal_mask = m_vol & m_rsi

    bt = ExitResearchBacktester(initial_capital=5_000.0, bar_hours=4.0)

    # Run spot backtests for train/test slices
    tr_trades = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                             c[:SPLIT], v[:SPLIT], regime[:SPLIT], signal_mask[:SPLIT],
                             "atr_trail")
    te_trades = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                             c[SPLIT:], v[SPLIT:], regime[SPLIT:], signal_mask[SPLIT:],
                             "atr_trail")

    spot_tr_pnl = np.array([t.pnl_pct for t in tr_trades if t.pnl_pct is not None])
    spot_te_pnl = np.array([t.pnl_pct for t in te_trades if t.pnl_pct is not None])

    print(f"  Spot baseline (1x, atr_trail, 4h, 70/30 split):")
    sp_tr = compute_stats_from_pnl_array(spot_tr_pnl)
    sp_te = compute_stats_from_pnl_array(spot_te_pnl)
    if sp_tr:
        print(f"    TRAIN  n={sp_tr['n']:3d}  WR={sp_tr['wr']:.1%}  PF={sp_tr['pf']:.3f}  "
              f"Sh={sp_tr['sharpe']:+.3f}  p={sp_tr['p']:.3f}")
    if sp_te:
        star = "*" if sp_te['p'] < 0.10 else " "
        print(f"    TEST   n={sp_te['n']:3d}  WR={sp_te['wr']:.1%}  PF={sp_te['pf']:.3f}  "
              f"Sh={sp_te['sharpe']:+.3f}  p={sp_te['p']:.3f}{star}")
    print()

    print(f"  Leveraged perps results (scale pnl_pct * leverage + fee_savings):")
    print()
    print(f"  {'Config':<28}  {'Phase':<6}  "
          f"{'n':>5}  {'WR':>7}  {'PF':>7}  {'Sharpe':>7}  {'MaxDD':>7}  {'p':>7}")
    print(f"  {'-'*28}  {'-'*6}  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}")

    results = {}
    for leverage in [1.0, 2.0, 3.0, 5.0]:
        # Perp pnl = spot_pnl * leverage + fee_savings_per_trade
        # fee_savings is a one-time per-trade benefit (perp cheaper than spot)
        perp_tr = spot_tr_pnl * leverage + FEE_SAVING
        perp_te = spot_te_pnl * leverage + FEE_SAVING

        tr_s = compute_stats_from_pnl_array(perp_tr)
        te_s = compute_stats_from_pnl_array(perp_te)

        lbl = f"{int(leverage)}x leverage"
        for phase, s in [("TRAIN", tr_s), ("TEST", te_s)]:
            if s:
                star = "*" if (phase == "TEST" and s['p'] < 0.10) else " "
                print(f"  {lbl:<28}  {phase:<6}  "
                      f"{s['n']:5d}  {s['wr']:7.1%}  {s['pf']:7.3f}  "
                      f"{s['sharpe']:+7.3f}  {s['dd']:7.4f}  {s['p']:7.3f}{star}")
            else:
                print(f"  {lbl:<28}  {phase:<6}  {'0':>5}  {'---':>7}  {'---':>7}  "
                      f"{'---':>7}  {'---':>7}  {'---':>7}")

        results[f"{int(leverage)}x"] = {"train": tr_s, "test": te_s}

    print()
    print("  NOTE: Borrow fees (~0.01%/hr at normal utilization) are NOT modeled.")
    print("  At 3x leverage and ~24h avg hold per trade, cost ~0.24% extra per trade.")
    print("  At 5x leverage, significantly erodes edge -- use position sizing carefully.")
    return results


# ---------------------------------------------------------------------------
# 1H backtest helpers
# ---------------------------------------------------------------------------

def run_wf_1h(ts, o, h, l, c, v, regime, signal_mask, exit_method, capital=10_000.0,
              bar_hours=1.0, split=0.70):
    """Walk-forward backtest for 1h data using ExitResearchBacktester."""
    SPLIT = int(len(ts) * split)
    bt = ExitResearchBacktester(initial_capital=capital, bar_hours=bar_hours)

    tr_trades = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                             c[:SPLIT], v[:SPLIT], regime[:SPLIT], signal_mask[:SPLIT],
                             exit_method)
    te_trades = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                             c[SPLIT:], v[SPLIT:], regime[SPLIT:], signal_mask[SPLIT:],
                             exit_method)

    def stats(trades):
        if not trades:
            return None
        eng = BacktestEngine(capital)
        eng.add_trades(trades)
        s = eng.compute_stats(venue=VENUE_SPOT)
        return {
            "n": s.n_trades,
            "wr": round(s.win_rate, 4),
            "pf": round(s.profit_factor, 4),
            "sharpe": round(s.sharpe_ratio, 4),
            "dd": round(s.max_drawdown_pct, 4),
            "pnl_pct": round(s.total_pnl_pct, 4),
            "p": round(s.p_value, 4),
        }

    return stats(tr_trades), stats(te_trades)


def run_h3_1h_backtest(btc_ts, btc_c):
    print()
    print("=" * 72)
    print("H3-A AND H3-B ON SOL/USDT 1H DATA (8760 bars, 1yr)")
    print("=" * 72)

    sol_df = load_binance("SOL/USDT", 60)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    n = len(ts)
    SPLIT = int(n * 0.70)

    dt_start = datetime.fromtimestamp(ts[0], tz=timezone.utc).strftime('%Y-%m-%d')
    dt_split = datetime.fromtimestamp(ts[SPLIT], tz=timezone.utc).strftime('%Y-%m-%d')
    dt_end   = datetime.fromtimestamp(ts[-1], tz=timezone.utc).strftime('%Y-%m-%d')

    print(f"\n  Data: {n} bars | {dt_start} -> {dt_end}")
    print(f"  Train: {SPLIT} bars ({dt_start} -> {dt_split})")
    print(f"  Test:  {n - SPLIT} bars ({dt_split} -> {dt_end})")

    # Build regime from BTC daily
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)

    # Signal masks on 1h data
    m_h3a, _ = signals_ichimoku_h3a(h, l, c)
    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    m_h3b = m_vol & m_rsi

    regime_dist = {
        "risk_on":  sum(1 for r in regime if r == RegimeState.RISK_ON) / n,
        "neutral":  sum(1 for r in regime if r == RegimeState.NEUTRAL) / n,
        "risk_off": sum(1 for r in regime if r == RegimeState.RISK_OFF) / n,
    }
    print(f"\n  Regime dist: RISK_ON={regime_dist['risk_on']:.1%}  "
          f"NEUTRAL={regime_dist['neutral']:.1%}  RISK_OFF={regime_dist['risk_off']:.1%}")
    print(f"  H3-A signals: {m_h3a.sum()} bars  |  H3-B signals: {m_h3b.sum()} bars")

    print()
    print(f"  {'Strategy':<30}  {'Phase':<6}  "
          f"{'n':>5}  {'WR':>7}  {'PF':>7}  {'Sharpe':>8}  {'p':>7}")
    print(f"  {'-'*30}  {'-'*6}  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*8}  {'-'*7}")

    results = {}
    for name, mask in [("H3-A (Ichimoku+RSI+score)", m_h3a),
                       ("H3-B (vol+rsi_cross)", m_h3b)]:
        tr, te = run_wf_1h(ts, o, h, l, c, v, regime, mask, "atr_trail",
                            capital=10_000.0, bar_hours=1.0)
        for phase, s in [("TRAIN", tr), ("TEST", te)]:
            if s:
                star = "*" if (phase == "TEST" and s['p'] < 0.10) else " "
                print(f"  {name:<30}  {phase:<6}  "
                      f"{s['n']:5d}  {s['wr']:7.1%}  {s['pf']:7.3f}  "
                      f"{s['sharpe']:+8.3f}  {s['p']:7.3f}{star}")
            else:
                print(f"  {name:<30}  {phase:<6}  "
                      f"{'0':>5}  {'---':>7}  {'---':>7}  {'---':>8}  {'---':>7}")
        results[name] = {"train": tr, "test": te}

    return results


# ---------------------------------------------------------------------------
# 4H reference for comparison
# ---------------------------------------------------------------------------

def run_h3_4h_reference(btc_ts, btc_c):
    print()
    print("=" * 72)
    print("H3-A AND H3-B ON SOL/USDT 4H DATA (reference/comparison)")
    print("=" * 72)

    sol_df = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    n = len(ts)
    SPLIT = int(n * 0.70)

    dt_start = datetime.fromtimestamp(ts[0], tz=timezone.utc).strftime('%Y-%m-%d')
    dt_split = datetime.fromtimestamp(ts[SPLIT], tz=timezone.utc).strftime('%Y-%m-%d')
    dt_end   = datetime.fromtimestamp(ts[-1], tz=timezone.utc).strftime('%Y-%m-%d')

    print(f"\n  Data: {n} bars | {dt_start} -> {dt_end}")
    print(f"  Train: {SPLIT} bars  |  Test: {n - SPLIT} bars")

    regime = build_btc_trend_regime(btc_c, ts, btc_ts)

    m_h3a, _ = signals_ichimoku_h3a(h, l, c)
    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    m_h3b = m_vol & m_rsi

    print(f"\n  H3-A signals: {m_h3a.sum()} bars  |  H3-B signals: {m_h3b.sum()} bars")
    print()
    print(f"  {'Strategy':<30}  {'Phase':<6}  "
          f"{'n':>5}  {'WR':>7}  {'PF':>7}  {'Sharpe':>8}  {'p':>7}")
    print(f"  {'-'*30}  {'-'*6}  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*8}  {'-'*7}")

    results = {}
    for name, mask in [("H3-A (Ichimoku+RSI+score)", m_h3a),
                       ("H3-B (vol+rsi_cross)", m_h3b)]:
        SPLIT4 = int(n * 0.70)
        bt = ExitResearchBacktester(initial_capital=10_000.0, bar_hours=4.0)
        tr_trades = bt.run_exit(ts[:SPLIT4], o[:SPLIT4], h[:SPLIT4], l[:SPLIT4],
                                 c[:SPLIT4], v[:SPLIT4], regime[:SPLIT4], mask[:SPLIT4],
                                 "atr_trail")
        te_trades = bt.run_exit(ts[SPLIT4:], o[SPLIT4:], h[SPLIT4:], l[SPLIT4:],
                                 c[SPLIT4:], v[SPLIT4:], regime[SPLIT4:], mask[SPLIT4:],
                                 "atr_trail")

        def stats(trades):
            if not trades:
                return None
            eng = BacktestEngine(10_000.0)
            eng.add_trades(trades)
            s = eng.compute_stats(venue=VENUE_SPOT)
            return {"n": s.n_trades, "wr": round(s.win_rate, 4),
                    "pf": round(s.profit_factor, 4), "sharpe": round(s.sharpe_ratio, 4),
                    "dd": round(s.max_drawdown_pct, 4), "p": round(s.p_value, 4)}

        tr = stats(tr_trades)
        te = stats(te_trades)

        for phase, s in [("TRAIN", tr), ("TEST", te)]:
            if s:
                star = "*" if (phase == "TEST" and s['p'] < 0.10) else " "
                print(f"  {name:<30}  {phase:<6}  "
                      f"{s['n']:5d}  {s['wr']:7.1%}  {s['pf']:7.3f}  "
                      f"{s['sharpe']:+8.3f}  {s['p']:7.3f}{star}")
            else:
                print(f"  {name:<30}  {phase:<6}  "
                      f"{'0':>5}  {'---':>7}  {'---':>7}  {'---':>8}  {'---':>7}")
        results[name] = {"train": tr, "test": te}

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 72)
    print("H3 PERPS FIX + 1H BACKTEST")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    # Load BTC daily for regime
    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    # 1. Corrected perps backtest
    r_perps = run_h3b_perps_corrected(btc_ts, btc_c)

    # 2. 1H backtest
    r_1h = run_h3_1h_backtest(btc_ts, btc_c)

    # 3. 4H reference
    r_4h = run_h3_4h_reference(btc_ts, btc_c)

    # 4. Comparison summary
    print()
    print("=" * 72)
    print("COMPARISON: 1H vs 4H (TEST SET, atr_trail exit)")
    print("=" * 72)
    print()
    print(f"  {'Config':<35}  {'n':>5}  {'WR':>7}  {'PF':>7}  {'Sharpe':>8}  {'p':>7}")
    print(f"  {'-'*35}  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*8}  {'-'*7}")

    for label, r in [("H3-A 1h TEST", r_1h.get("H3-A (Ichimoku+RSI+score)", {}).get("test")),
                     ("H3-A 4h TEST", r_4h.get("H3-A (Ichimoku+RSI+score)", {}).get("test")),
                     ("H3-B 1h TEST", r_1h.get("H3-B (vol+rsi_cross)", {}).get("test")),
                     ("H3-B 4h TEST", r_4h.get("H3-B (vol+rsi_cross)", {}).get("test"))]:
        if r:
            star = "*" if r['p'] < 0.10 else " "
            print(f"  {label:<35}  {r['n']:5d}  {r['wr']:7.1%}  {r['pf']:7.3f}  "
                  f"{r['sharpe']:+8.3f}  {r['p']:7.3f}{star}")
        else:
            print(f"  {label:<35}  {'0':>5}  {'---':>7}  {'---':>7}  {'---':>8}  {'---':>7}")

    print()
    print("* = p < 0.10 (one-tailed t-test vs mean return = 0)")
    print()
    print("Done.")
