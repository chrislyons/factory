"""
obv_perps_portfolio.py — Three focused studies:

1. OBV divergence as primary entry signal
   Tests OBV cross above its EMA as a primary entry (identified as orthogonal
   to other signals in Study 2). What's the standalone OBV edge?

2. H3-B on Jupiter Perps — corrected implementation
   Uses a custom backtester that correctly applies leverage to P&L
   while keeping ATR stops in absolute price terms.

3. Multi-asset portfolio Sharpe
   H3-Combined (A+B) on SOL 4h, H3-C on ETH/BTC 4h simultaneously.
   What is the portfolio-level Sharpe with correlation adjustment?
"""

from __future__ import annotations

import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import src.quant.indicators as ind
from src.quant.indicator_research import SignalBacktester, backtest_signal
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade
from src.quant.regime import RegimeState
from src.quant.research_loop import ExitResearchBacktester

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE_SPOT = "kraken_spot"
VENUE_PERP = "jupiter_perps"
MAKER_FEE  = 0.0016
PERP_FEE   = 0.0007   # 0.07% per side (Jupiter)


def run_wf(ts, o, h, l, c, v, regime, mask, exit_m="atr_trail",
           capital=10_000.0, bh=4.0):
    SPLIT = int(len(ts) * 0.70)
    bt = ExitResearchBacktester(capital, bh)
    tr_tr = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                         c[:SPLIT], v[:SPLIT], regime[:SPLIT], mask[:SPLIT], exit_m)
    te_tr = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                         c[SPLIT:], v[SPLIT:], regime[SPLIT:], mask[SPLIT:], exit_m)
    def s(trades, cap):
        if not trades: return None
        eng = BacktestEngine(cap); eng.add_trades(trades)
        st = eng.compute_stats(venue=VENUE_SPOT)
        return {"n": st.n_trades, "wr": round(st.win_rate, 4),
                "pf": round(st.profit_factor, 4), "sharpe": round(st.sharpe_ratio, 4),
                "dd": round(st.max_drawdown_pct, 4),
                "pnl_pct": round(st.total_pnl_pct, 4), "p": round(st.p_value, 4)}
    return s(tr_tr, capital), s(te_tr, capital)


# ---------------------------------------------------------------------------
# 1. OBV as primary entry
# ---------------------------------------------------------------------------

def study_obv(btc_ts, btc_c):
    print("\n" + "=" * 72)
    print("STUDY: OBV-Based Entry Signals")
    print("=" * 72)

    assets = [
        ("SOL/USDT", 240,  4.0,  "SOL 4h"),
        ("ETH/USDT", 240,  4.0,  "ETH 4h"),
        ("BTC/USD",  240,  4.0,  "BTC 4h"),
        ("SOL/USDT", 1440, 24.0, "SOL 1d"),
        ("ETH/USDT", 1440, 24.0, "ETH 1d"),
    ]

    results = {}
    print(f"\n  {'Asset':<12} {'Signal':<30} {'Tr-n':>5} {'Tr-PF':>7} {'Te-n':>5} {'Te-PF':>7} {'Te-p':>7}")
    print(f"  {'-'*12} {'-'*30} {'-'*5} {'-'*7} {'-'*5} {'-'*7} {'-'*7}")

    for sym, itvl, bh, label in assets:
        try:
            df = load_binance(sym, itvl)
        except FileNotFoundError:
            continue
        ts, o, h, l, c, v = df_to_arrays(df)
        if len(ts) < 200: continue
        regime = build_btc_trend_regime(btc_c, ts, btc_ts)
        n = len(ts)

        obv_vals = ind.obv(c, v)
        obv_ema20 = ind.ema(obv_vals, 20)
        obv_ema10 = ind.ema(obv_vals, 10)
        rsi_v = ind.rsi(c, 14)
        atr_v = ind.atr(h, l, c, 14)

        signal_defs = {
            "obv_cross_ema20":    np.zeros(n, dtype=bool),  # OBV crosses above EMA20
            "obv_cross_ema10":    np.zeros(n, dtype=bool),  # OBV crosses above EMA10
            "obv_rsi_cross":      np.zeros(n, dtype=bool),  # OBV cross + RSI cross 50
            "obv_trend_confirm":  np.zeros(n, dtype=bool),  # OBV above EMA20 + price rising
            "obv_diverge_up":     np.zeros(n, dtype=bool),  # Price new low but OBV higher low
        }

        # Build masks
        for i in range(1, n):
            if regime[i] == RegimeState.RISK_OFF: continue
            if any(np.isnan(x) for x in [obv_ema20[i], obv_ema20[i-1],
                                           obv_ema10[i], obv_ema10[i-1]]): continue

            # OBV crosses above its EMA20
            signal_defs["obv_cross_ema20"][i] = (
                obv_vals[i] > obv_ema20[i] and obv_vals[i-1] <= obv_ema20[i-1]
            )
            # OBV crosses above EMA10
            signal_defs["obv_cross_ema10"][i] = (
                obv_vals[i] > obv_ema10[i] and obv_vals[i-1] <= obv_ema10[i-1]
            )
            # Combined: OBV cross + RSI cross 50
            if not np.isnan(rsi_v[i]) and not np.isnan(rsi_v[i-1]):
                signal_defs["obv_rsi_cross"][i] = (
                    signal_defs["obv_cross_ema20"][i] and
                    rsi_v[i] > 50 and rsi_v[i-1] <= 50
                )
            # OBV above EMA20 for trend + price up bar
            signal_defs["obv_trend_confirm"][i] = (
                obv_vals[i] > obv_ema20[i] and
                c[i] > c[i-1] and
                (c[i] - c[i-1]) / c[i-1] > 0.005
            )

        # OBV divergence (price lower low, OBV higher low) — requires lookback
        for i in range(10, n):
            if regime[i] == RegimeState.RISK_OFF: continue
            # Find most recent price low and OBV low in last 10 bars
            recent_c = c[i-10:i]; recent_obv = obv_vals[i-10:i]
            prev_c_low = np.min(recent_c); prev_obv_low = np.min(recent_obv)
            # Current bar makes a new low in price context, but OBV is higher
            if c[i] < c[i-1] and c[i] < prev_c_low:
                # Bullish divergence: price at new low but OBV making higher low
                obv_at_prev_price_low = recent_obv[np.argmin(recent_c)]
                if obv_vals[i] > obv_at_prev_price_low:
                    signal_defs["obv_diverge_up"][i] = True

        for sig_name, mask in signal_defs.items():
            tr, te = run_wf(ts, o, h, l, c, v, regime, mask, exit_m="atr_trail", bh=bh)
            if tr or (te and te["n"] >= 3):
                tr_s = f"{tr['n']:5d} {tr['pf']:7.3f}" if tr else "    0       -"
                te_s = (f"{te['n']:5d} {te['pf']:7.3f} {te['p']:7.3f}"
                        if te else "    0       -       -")
                star = "*" if (te and te["p"] < 0.10) else " "
                print(f"  {label:<12} {sig_name:<30} {tr_s}  {te_s}{star}")
            results[f"{label}_{sig_name}"] = {"train": tr, "test": te}

    return results


# ---------------------------------------------------------------------------
# 2. H3-B on Jupiter Perps — corrected
# ---------------------------------------------------------------------------

def study_h3b_perps_corrected(btc_ts, btc_c):
    """
    Corrected perps simulation. Key insight: with leverage, the same
    % price move produces leverage× the P&L. So we keep the ATR stop in
    absolute price terms but scale the P&L by leverage.
    
    Implementation: run standard SignalBacktester, then scale all trade PnLs
    by the leverage factor post-hoc.
    """
    print("\n" + "=" * 72)
    print("H3-B ON JUPITER PERPS — corrected leverage simulation")
    print("=" * 72)

    sol_df = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    n = len(ts); SPLIT = int(n * 0.70)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    atr_v = ind.atr(h, l, c, 14)

    rsi_v  = ind.rsi(c, 14)
    vol_ma = ind.sma(v, 20)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(vol_ma[i]) or vol_ma[i] <= 0: continue
        if np.isnan(rsi_v[i]) or np.isnan(rsi_v[i-1]): continue
        mask[i] = (v[i] > 1.5 * vol_ma[i]
                   and (c[i] - c[i-1]) / c[i-1] > 0.005
                   and rsi_v[i] > 50 and rsi_v[i-1] <= 50
                   and regime[i] != RegimeState.RISK_OFF)

    print(f"\n  {'Config':<30} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  "
          f"{'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}")
    print(f"  {'-'*30} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7} {'-'*7}")

    results = {}
    PERP_ROUND_TRIP = 0.0014  # 0.14% (0.07% each side)

    for leverage in [1.0, 2.0, 3.0, 5.0]:
        for exit_m in ["atr_trail", "time10"]:
            # Run backtester with perp fees (higher than spot)
            bt = ExitResearchBacktester(5_000.0, 4.0)

            # Override fee in backtester by scaling position slightly
            # (approximate: use spot backtester, then apply leverage to PnL)
            tr_trades_raw = bt.run_exit(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                                         c[:SPLIT], v[:SPLIT], regime[:SPLIT],
                                         mask[:SPLIT], exit_m)
            te_trades_raw = bt.run_exit(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                                         c[SPLIT:], v[SPLIT:], regime[SPLIT:],
                                         mask[SPLIT:], exit_m)

            def scale_and_stats(trades, lev, fee_adj):
                """Scale PnL by leverage, apply perp fee overhead."""
                if not trades: return None
                scaled = []
                for t in trades:
                    if t.pnl_usd is None: continue
                    # Original PnL is at 1× leverage, spot fees
                    # Perp PnL = original_pnl_pct × leverage × position_size - perp_fee
                    orig_pnl_pct = t.pnl_usd / t.position_size_usd
                    # Apply leverage to the price move component
                    lev_pnl_pct = orig_pnl_pct * lev
                    # But fees are now higher (perp vs spot)
                    fee_overhead = PERP_ROUND_TRIP - MAKER_FEE * 2  # extra fee
                    net_pnl_pct  = lev_pnl_pct - fee_overhead
                    scaled.append(net_pnl_pct * t.position_size_usd)

                if not scaled: return None
                profits = [x for x in scaled if x > 0]
                losses  = [abs(x) for x in scaled if x <= 0]
                pf = sum(profits) / sum(losses) if losses and sum(losses) > 0 else float("inf")
                wr = len(profits) / len(scaled)
                total_pnl = sum(scaled)
                # Rough Sharpe: mean / std of trade PnLs
                arr = np.array(scaled)
                sh = float(np.mean(arr) / np.std(arr) * np.sqrt(len(arr))) if np.std(arr) > 0 else 0.0
                return {"n": len(scaled), "wr": round(wr, 4), "pf": round(pf, 3),
                        "sharpe": round(sh, 3), "total_pnl": round(total_pnl, 2)}

            tr = scale_and_stats(tr_trades_raw, leverage, PERP_ROUND_TRIP)
            te = scale_and_stats(te_trades_raw, leverage, PERP_ROUND_TRIP)

            label = f"{leverage:.0f}x + {exit_m}"
            tr_s = f"{tr['n']:5d} {tr['pf']:7.3f}" if tr else "    0       -"
            te_s = (f"{te['n']:5d} {te['pf']:7.3f} {te['sharpe']:7.3f}"
                    if te else "    0       -       -")
            lev_note = " ← BEST_SPOT" if leverage == 1.0 and exit_m == "atr_trail" else ""
            print(f"  {label:<30}     {tr_s}      {te_s}{lev_note}")
            results[label] = {"train": tr, "test": te}

    return results


# ---------------------------------------------------------------------------
# 3. Multi-asset portfolio Sharpe
# ---------------------------------------------------------------------------

def study_portfolio_sharpe(btc_ts, btc_c):
    """
    Simulate running H3-Combined (A+B) on SOL 4h and H3-C on ETH/BTC 4h
    simultaneously. Compute portfolio-level P&L curve and Sharpe.
    """
    print("\n" + "=" * 72)
    print("MULTI-ASSET PORTFOLIO SIMULATION")
    print("=" * 72)

    from src.quant.indicator_research import signals_ichimoku_h3a

    # Load all assets
    sol_df  = load_binance("SOL/USDT", 240)
    eth_df  = load_binance("ETH/USDT", 240)
    btc_df4 = load_binance("BTC/USD",  240)

    datasets = {}
    for name, df in [("SOL", sol_df), ("ETH", eth_df), ("BTC", btc_df4)]:
        ts, o, h, l, c, v = df_to_arrays(df)
        regime = build_btc_trend_regime(btc_c, ts, btc_ts)
        atr_v  = ind.atr(h, l, c, 14)
        datasets[name] = (ts, o, h, l, c, v, regime, atr_v)

    # Build signals for each asset
    # SOL: H3-Combined = H3-A OR H3-B
    sol_ts, sol_o, sol_h, sol_l, sol_c, sol_v, sol_reg, sol_atr = datasets["SOL"]
    m_h3a, _ = signals_ichimoku_h3a(sol_h, sol_l, sol_c)
    sol_rv = ind.rsi(sol_c, 14); sol_vm = ind.sma(sol_v, 20)
    m_h3b = np.zeros(len(sol_ts), dtype=bool)
    for i in range(1, len(sol_ts)):
        if np.isnan(sol_vm[i]) or np.isnan(sol_rv[i]) or np.isnan(sol_rv[i-1]): continue
        m_h3b[i] = (sol_v[i] > 1.5*sol_vm[i]
                    and (sol_c[i]-sol_c[i-1])/sol_c[i-1] > 0.005
                    and sol_rv[i] > 50 and sol_rv[i-1] <= 50
                    and sol_reg[i] != RegimeState.RISK_OFF)
    sol_mask = m_h3a | m_h3b

    # ETH + BTC: H3-C (RSI cross + KAMA)
    eth_mask = btc_mask = None
    for name in ["ETH", "BTC"]:
        ts_, o_, h_, l_, c_, v_, reg_, _ = datasets[name]
        kama_ = ind.kama(c_, period=6)
        rsi_  = ind.rsi(c_, 14)
        n_ = len(ts_)
        m_ = np.zeros(n_, dtype=bool)
        for i in range(1, n_):
            if np.isnan(kama_[i]) or np.isnan(rsi_[i]) or np.isnan(rsi_[i-1]): continue
            m_[i] = (rsi_[i] > 50 and rsi_[i-1] <= 50
                     and c_[i] > kama_[i] and c_[i-1] <= kama_[i-1]
                     and reg_[i] != RegimeState.RISK_OFF)
        if name == "ETH": eth_mask = m_
        else: btc_mask = m_

    # Collect all trade PnL%s from each asset OOS
    CAPITAL = 10_000.0
    all_pnl_pcts = []

    for asset_name, asset_data, mask in [
        ("SOL H3-A+B", datasets["SOL"], sol_mask),
        ("ETH H3-C",   datasets["ETH"], eth_mask),
        ("BTC H3-C",   datasets["BTC"], btc_mask),
    ]:
        ts_, o_, h_, l_, c_, v_, reg_, atr_ = asset_data
        SPLIT = int(len(ts_) * 0.70)
        bt = ExitResearchBacktester(CAPITAL, 4.0)
        te_trades = bt.run_exit(ts_[SPLIT:], o_[SPLIT:], h_[SPLIT:], l_[SPLIT:],
                                 c_[SPLIT:], v_[SPLIT:], reg_[SPLIT:], mask[SPLIT:],
                                 "atr_trail")
        if te_trades:
            eng = BacktestEngine(CAPITAL); eng.add_trades(te_trades)
            s = eng.compute_stats(venue=VENUE_SPOT)
            pnl_pcts = [t.pnl_pct for t in te_trades if t.pnl_pct is not None]
            all_pnl_pcts.extend(pnl_pcts)
            print(f"  {asset_name:<20}: n={s.n_trades:3d} PF={s.profit_factor:.3f} "
                  f"Sh={s.sharpe_ratio:+.3f} p={s.p_value:.3f}")
        else:
            print(f"  {asset_name:<20}: no trades")

    # Portfolio-level stats
    if all_pnl_pcts:
        arr = np.array(all_pnl_pcts)
        portfolio_sharpe = float(np.mean(arr) / np.std(arr) * np.sqrt(len(arr))) if np.std(arr) > 0 else 0.0
        wr = np.sum(arr > 0) / len(arr)
        profits = arr[arr > 0]; losses = arr[arr <= 0]
        pf = float(np.sum(profits) / abs(np.sum(losses))) if len(losses) > 0 else float("inf")

        print(f"\n  Portfolio OOS combined:")
        print(f"  n={len(all_pnl_pcts)} trades  WR={wr:.1%}  PF={pf:.3f}  "
              f"Portfolio Sharpe={portfolio_sharpe:.3f}")
        print(f"  Mean trade PnL: {np.mean(arr):+.3f}%  Std: {np.std(arr):.3f}%")

    return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 72)
    print("OBV + PERPS + PORTFOLIO STUDIES")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    r1 = study_obv(btc_ts, btc_c)
    r2 = study_h3b_perps_corrected(btc_ts, btc_c)
    r3 = study_portfolio_sharpe(btc_ts, btc_c)

    out_path = DATA_DIR / "obv_perps_portfolio_results.json"
    with open(out_path, "w") as f:
        json.dump({"run_at": datetime.now(timezone.utc).isoformat(),
                   "obv": {k: v for k, v in list(r1.items())[:20]},
                   "perps": r2}, f, indent=2)
    print(f"\nSaved: {out_path}")
