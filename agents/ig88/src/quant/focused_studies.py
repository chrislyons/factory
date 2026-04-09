"""
focused_studies.py — Two focused backtesting studies for IG-88.

STUDY A: H3-C signal with ATR trailing stop exit vs fixed ATR 2x/3x exit
STUDY B: Confidence-weighted position sizing for H3-A using Ichimoku score
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88')

import numpy as np

import src.quant.indicators as ind
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.research_loop import ExitResearchBacktester
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade
from src.quant.regime import RegimeState

VENUE      = "kraken_spot"
MAKER_FEE  = 0.0016
CAPITAL    = 10_000.0
BAR_HOURS  = 4.0
SPLIT      = 0.70


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compute_stats(trades):
    """Compute stats dict from a list of Trade objects."""
    if not trades:
        return None
    eng = BacktestEngine(CAPITAL)
    eng.add_trades(trades)
    s = eng.compute_stats(venue=VENUE)
    total_pnl_usd = sum(t.pnl_usd for t in trades if t.pnl_usd is not None)
    return {
        "n":       s.n_trades,
        "wr":      s.win_rate,
        "pf":      s.profit_factor,
        "sharpe":  s.sharpe_ratio,
        "dd":      s.max_drawdown_pct,
        "pnl":     s.total_pnl_pct,
        "pnl_usd": total_pnl_usd,
        "pnl_pct_cap": total_pnl_usd / CAPITAL,  # dollar PnL as % of initial capital
        "p":       s.p_value,
    }


def print_result(label, tr, te, extra=""):
    star = "*" if (te and te["p"] < 0.10) else " "
    tr_s = (f"n={tr['n']:3d} WR={tr['wr']:.1%} PF={tr['pf']:.3f} Sh={tr['sharpe']:+.3f} p={tr['p']:.3f}"
            if tr else "n=  0")
    te_s = (f"n={te['n']:3d} WR={te['wr']:.1%} PF={te['pf']:.3f} Sh={te['sharpe']:+.3f} p={te['p']:.3f}"
            if te else "n=  0")
    print(f"  {label:<18}  TRAIN: {tr_s}")
    print(f"  {'':18}   TEST: {te_s}{star}  {extra}")


# ---------------------------------------------------------------------------
# STUDY A: H3-C signal with ATR fixed exit vs ATR trailing stop
# ---------------------------------------------------------------------------

def build_h3c_signal(h, l, c, v):
    """
    H3-C: RSI crosses above 52 AND price crosses above KAMA(period=4) from below.
    Returns boolean mask (n,).
    """
    n = len(c)
    rsi_v = ind.rsi(c, 14)
    # KAMA period=4 on close
    kama_v = ind.kama(c, period=4)

    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(rsi_v[i]) or np.isnan(rsi_v[i-1]):
            continue
        if np.isnan(kama_v[i]) or np.isnan(kama_v[i-1]):
            continue
        rsi_cross  = (rsi_v[i] > 52.0) and (rsi_v[i-1] <= 52.0)
        kama_cross = (c[i] > kama_v[i]) and (c[i-1] <= kama_v[i-1])
        mask[i] = rsi_cross and kama_cross
    return mask


def run_h3c_exit(ts, o, h, l, c, regime, signal_mask, exit_method,
                 atr_stop_mult=2.0, atr_target_mult=3.0):
    """
    Run H3-C backtest with specified exit method.
    exit_method: 'atr_fixed' or 'atr_trail'
    """
    n = len(ts)
    wallet = CAPITAL
    min_hold = 2
    cooldown = 2

    atr_v = ind.atr(h, l, c, 14)
    trades = []
    counter = 0
    last_exit = -999
    daily_pnl = 0.0
    halted = False
    cur_day = -1

    i = 60
    while i < n - min_hold - 2:
        day = int(ts[i] // 86400)
        if day != cur_day:
            cur_day = day
            daily_pnl = 0.0
            halted = False
        if halted:
            i += 1; continue
        if i - last_exit < cooldown:
            i += 1; continue
        if regime[i] == RegimeState.RISK_OFF:
            i += 1; continue
        if not signal_mask[i]:
            i += 1; continue

        av = atr_v[i]
        if np.isnan(av) or av <= 0:
            i += 1; continue

        eb = i + 1
        if eb >= n:
            break
        ep = o[eb]
        pos = wallet * 0.02
        if pos < 1.0:
            i += 1; continue

        stop_p   = ep - atr_stop_mult * av
        target_p = ep + atr_target_mult * av

        et = datetime.fromtimestamp(ts[eb], tz=timezone.utc)
        trade = Trade(
            trade_id=f"H3C-{exit_method[:5].upper()}-{counter:05d}",
            venue=VENUE, strategy=f"h3c_{exit_method}",
            pair="SOL/USDT", entry_timestamp=et, entry_price=ep,
            position_size_usd=pos, regime_state=regime[i],
            side="long", leverage=1.0,
            stop_level=stop_p, target_level=target_p,
            fees_paid=pos * MAKER_FEE,
        )
        counter += 1

        trail_stop = stop_p
        xb = eb; xp = ep; xr = ExitReason.TIME_STOP

        for j in range(1, n - eb):
            bar = eb + j
            if bar >= n:
                break
            cur_av = atr_v[bar] if not np.isnan(atr_v[bar]) else av

            if exit_method == "atr_trail":
                # Raise trail stop each bar: stop = max(prev_stop, close - 2*ATR)
                trail_stop = max(trail_stop, c[bar] - 2.0 * cur_av)
                if c[bar] < trail_stop and j >= min_hold:
                    xb = bar; xp = trail_stop; xr = ExitReason.STOP_HIT; break
                # Still check initial hard stop on lows
                if l[bar] <= stop_p and j < min_hold:
                    xb = bar; xp = stop_p; xr = ExitReason.STOP_HIT; break
            else:
                # Fixed ATR 2x stop / 3x target
                if l[bar] <= stop_p:
                    xb = bar; xp = stop_p; xr = ExitReason.STOP_HIT; break
                if h[bar] >= target_p:
                    xb = bar; xp = target_p; xr = ExitReason.TARGET_HIT; break

            if regime[bar] == RegimeState.RISK_OFF and j >= min_hold:
                xb = bar; xp = c[bar]; xr = ExitReason.REGIME_EXIT; break

        xt = datetime.fromtimestamp(ts[min(xb, n-1)], tz=timezone.utc)
        trade.close(xp, xt, xr, fees=pos * MAKER_FEE)
        if trade.pnl_usd is not None:
            wallet += trade.pnl_usd
            daily_pnl += trade.pnl_usd
            if daily_pnl < -(CAPITAL * 0.03):
                halted = True

        last_exit = xb
        trades.append(trade)
        i = xb + cooldown

    return trades


def study_a():
    print()
    print("=" * 72)
    print("STUDY A: H3-C Signal — Fixed ATR Exit vs ATR Trailing Stop")
    print("  Signal: RSI crosses above 52 AND price crosses above KAMA(4)")
    print("  Regime: not RISK_OFF | Asset: SOL/USDT 4h | Split: 70/30")
    print("=" * 72)

    # Load data
    sol_df  = load_binance("SOL/USDT", 240)
    btc_df  = load_binance("BTC/USD",  1440)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    N      = len(ts)
    SP     = int(N * SPLIT)

    print(f"\n  Total bars: {N}  Train: {SP}  Test: {N-SP}")

    # Build H3-C signal mask on FULL series (avoid lookahead)
    signal = build_h3c_signal(h, l, c, v)
    total_signals = int(np.sum(signal))
    tr_signals    = int(np.sum(signal[:SP]))
    te_signals    = int(np.sum(signal[SP:]))
    print(f"  H3-C signal fires: total={total_signals}  train={tr_signals}  test={te_signals}")

    regime_on_pct = np.sum(regime[:SP] != RegimeState.RISK_OFF) / SP * 100
    print(f"  Train regime (not RISK_OFF): {regime_on_pct:.1f}%")

    results = {}
    for method in ["atr_fixed", "atr_trail"]:
        tr_trades = run_h3c_exit(
            ts[:SP], o[:SP], h[:SP], l[:SP], c[:SP], regime[:SP], signal[:SP], method)
        te_trades = run_h3c_exit(
            ts[SP:], o[SP:], h[SP:], l[SP:], c[SP:], regime[SP:], signal[SP:], method)

        tr = compute_stats(tr_trades)
        te = compute_stats(te_trades)
        results[method] = {"train": tr, "test": te}
        label = "ATR 2x/3x (curr)" if method == "atr_fixed" else "ATR Trail 2x"
        print_result(label, tr, te)

    # Comparison summary
    print()
    fixed_te  = results["atr_fixed"]["test"]
    trail_te  = results["atr_trail"]["test"]
    if fixed_te and trail_te:
        pf_delta = (trail_te["pf"] - fixed_te["pf"]) if fixed_te["pf"] else 0
        sh_delta = trail_te["sharpe"] - fixed_te["sharpe"]
        dd_delta = trail_te["dd"] - fixed_te["dd"]
        print(f"  OOS delta (trail - fixed):  PF={pf_delta:+.3f}  Sh={sh_delta:+.3f}  DD={dd_delta:+.3f}")
        winner = "TRAIL" if (trail_te and trail_te["pf"] > fixed_te["pf"]) else "FIXED"
        print(f"  WINNER by OOS PF: {winner}")
        if trail_te["n"] >= 5 and trail_te["p"] < 0.10:
            print("  ATR trail exit: STATISTICALLY SIGNIFICANT (p < 0.10)")
        elif fixed_te["n"] >= 5 and fixed_te["p"] < 0.10:
            print("  ATR fixed exit: STATISTICALLY SIGNIFICANT (p < 0.10)")
        else:
            print("  Neither exit meets p < 0.10 on OOS set")

    return results


# ---------------------------------------------------------------------------
# STUDY B: Confidence-weighted position sizing for H3-A
# ---------------------------------------------------------------------------

def run_h3a_weighted(ts, o, h, l, c, h_arr, l_arr, regime, signal_mask,
                     ichi_score, use_weighted=False):
    """
    Run H3-A backtest with fixed vs confidence-weighted position sizing.

    Fixed:    always 2% of wallet
    Weighted: score 3 -> 2%, score 4 -> 3%, score 5+ -> 4%

    Returns (trades, wallet_curve) where wallet_curve tracks equity.
    """
    n = len(ts)
    wallet   = CAPITAL
    min_hold = 2
    cooldown = 2

    atr_v = ind.atr(h_arr, l_arr, c, 14)
    trades       = []
    wallet_curve = [CAPITAL]
    counter      = 0
    last_exit    = -999
    daily_pnl    = 0.0
    halted       = False
    cur_day      = -1

    strategy_label = "h3a_weighted" if use_weighted else "h3a_fixed"

    i = 60
    while i < n - min_hold - 2:
        day = int(ts[i] // 86400)
        if day != cur_day:
            cur_day   = day
            daily_pnl = 0.0
            halted    = False
        if halted:
            i += 1; continue
        if i - last_exit < cooldown:
            i += 1; continue
        if regime[i] == RegimeState.RISK_OFF:
            i += 1; continue
        if not signal_mask[i]:
            i += 1; continue

        av = atr_v[i]
        if np.isnan(av) or av <= 0:
            i += 1; continue

        eb = i + 1
        if eb >= n:
            break
        ep = o[eb]

        # Position sizing by Ichimoku score
        score_i = int(ichi_score[i])
        if use_weighted:
            if score_i >= 5:
                pct = 0.04
            elif score_i == 4:
                pct = 0.03
            else:  # score 3 or lower
                pct = 0.02
        else:
            pct = 0.02

        pos = wallet * pct
        if pos < 1.0:
            i += 1; continue

        stop_p   = ep - 2.0 * av
        target_p = ep + 3.0 * av

        et = datetime.fromtimestamp(ts[eb], tz=timezone.utc)
        trade = Trade(
            trade_id=f"H3A-{strategy_label[:5].upper()}-{counter:05d}",
            venue=VENUE, strategy=strategy_label,
            pair="SOL/USDT", entry_timestamp=et, entry_price=ep,
            position_size_usd=pos, regime_state=regime[i],
            side="long", leverage=1.0,
            stop_level=stop_p, target_level=target_p,
            fees_paid=pos * MAKER_FEE,
        )
        counter += 1

        xb = eb; xp = ep; xr = ExitReason.TIME_STOP
        for j in range(1, n - eb):
            bar = eb + j
            if bar >= n:
                break

            if l_arr[bar] <= stop_p:
                xb = bar; xp = stop_p; xr = ExitReason.STOP_HIT; break
            if h_arr[bar] >= target_p:
                xb = bar; xp = target_p; xr = ExitReason.TARGET_HIT; break
            if regime[bar] == RegimeState.RISK_OFF and j >= min_hold:
                xb = bar; xp = c[bar]; xr = ExitReason.REGIME_EXIT; break

        xt = datetime.fromtimestamp(ts[min(xb, n-1)], tz=timezone.utc)
        trade.close(xp, xt, xr, fees=pos * MAKER_FEE)
        if trade.pnl_usd is not None:
            wallet += trade.pnl_usd
            daily_pnl += trade.pnl_usd
            wallet_curve.append(wallet)
            if daily_pnl < -(CAPITAL * 0.03):
                halted = True

        last_exit = xb
        trades.append(trade)
        i = xb + cooldown

    # Compute wallet-level max drawdown
    wc = np.array(wallet_curve)
    peak = np.maximum.accumulate(wc)
    dd_series = (peak - wc) / peak
    wallet_max_dd = float(np.max(dd_series)) if len(dd_series) > 0 else 0.0
    final_wallet = wallet

    return trades, final_wallet, wallet_max_dd


def study_b():
    print()
    print("=" * 72)
    print("STUDY B: H3-A Confidence-Weighted Position Sizing")
    print("  Fixed: 2% per trade")
    print("  Weighted: score=3->2%, score=4->3%, score=5->4%")
    print("  Asset: SOL/USDT 4h | Split: 70/30 WF")
    print("=" * 72)

    # Load data
    sol_df  = load_binance("SOL/USDT", 240)
    btc_df  = load_binance("BTC/USD",  1440)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    N      = len(ts)
    SP     = int(N * SPLIT)

    # Build Ichimoku on full series
    ichi  = ind.ichimoku(h, l, c)
    score = ind.ichimoku_composite_score(ichi, c)

    # H3-A signal: TK cross + above cloud + RSI>55 + ichi_score>=3
    rsi_v = ind.rsi(c, 14)
    tk    = ichi.tk_cross_signals()

    n = len(c)
    h3a_mask = np.zeros(n, dtype=bool)
    for i in range(n):
        cloud_top = max(
            ichi.senkou_span_a[i] if not np.isnan(ichi.senkou_span_a[i]) else -np.inf,
            ichi.senkou_span_b[i] if not np.isnan(ichi.senkou_span_b[i]) else -np.inf,
        )
        h3a_mask[i] = (
            tk[i] == 1
            and c[i] > cloud_top
            and not np.isnan(rsi_v[i]) and rsi_v[i] > 55
            and score[i] >= 3
        )

    total_signals = int(np.sum(h3a_mask))
    tr_signals    = int(np.sum(h3a_mask[:SP]))
    te_signals    = int(np.sum(h3a_mask[SP:]))
    print(f"\n  Total bars: {N}  Train: {SP}  Test: {N-SP}")
    print(f"  H3-A signal fires: total={total_signals}  train={tr_signals}  test={te_signals}")

    # Score distribution at signal bars
    sig_bars = np.where(h3a_mask)[0]
    if len(sig_bars) > 0:
        sig_scores = score[sig_bars]
        for s_val in [3, 4, 5]:
            cnt = int(np.sum(sig_scores == s_val))
            pct = cnt / len(sig_bars) * 100
            print(f"  Score={s_val}: {cnt} trades ({pct:.1f}%)")

    results = {}
    for use_weighted in [False, True]:
        tr_trades, tr_wallet, tr_wdd = run_h3a_weighted(
            ts[:SP], o[:SP], h[:SP], l[:SP], c[:SP], h[:SP], l[:SP],
            regime[:SP], h3a_mask[:SP], score[:SP], use_weighted)
        te_trades, te_wallet, te_wdd = run_h3a_weighted(
            ts[SP:], o[SP:], h[SP:], l[SP:], c[SP:], h[SP:], l[SP:],
            regime[SP:], h3a_mask[SP:], score[SP:], use_weighted)

        tr = compute_stats(tr_trades)
        te = compute_stats(te_trades)
        label = "Weighted (conf)" if use_weighted else "Fixed 2%      "
        key   = "weighted" if use_weighted else "fixed"

        # Wallet-level P&L as % of initial capital
        tr_pnl_cap = (tr_wallet - CAPITAL) / CAPITAL
        te_pnl_cap = (te_wallet - CAPITAL) / CAPITAL

        results[key] = {
            "train": tr, "test": te,
            "tr_wallet": tr_wallet, "te_wallet": te_wallet,
            "tr_wdd": tr_wdd,       "te_wdd": te_wdd,
            "tr_pnl_cap": tr_pnl_cap,
            "te_pnl_cap": te_pnl_cap,
        }

        print()
        print(f"  [{label}]")
        if tr:
            print(f"    TRAIN: n={tr['n']}  WalletPnL={tr_pnl_cap:+.2%}  "
                  f"Sh={tr['sharpe']:+.3f}  WalletMaxDD={tr_wdd:.3f}  p={tr['p']:.3f}")
        else:
            print(f"    TRAIN: n=0")
        if te:
            star = "*" if te['p'] < 0.10 else ""
            print(f"    TEST:  n={te['n']}  WalletPnL={te_pnl_cap:+.2%}  "
                  f"Sh={te['sharpe']:+.3f}  WalletMaxDD={te_wdd:.3f}  p={te['p']:.3f}{star}")
        else:
            print(f"    TEST:  n=0")

        # Per-score breakdown if weighted
        if use_weighted:
            print(f"    Score sizing breakdown at signal bars:")
            te_sig_idx = np.where(h3a_mask[SP:])[0]
            if len(te_sig_idx) > 0:
                for sv, pct_label in [(3, "2%"), (4, "3%"), (5, "4%")]:
                    cnt = int(np.sum(score[SP:][te_sig_idx] == sv))
                    print(f"      score={sv} -> {pct_label}: {cnt} signals")

    # Comparison summary
    print()
    print(f"  Score distribution note: score=4 fires {int(np.sum(score[np.where(h3a_mask)[0]] == 4))} "
          f"times at H3-A bars vs score=3 ({int(np.sum(score[np.where(h3a_mask)[0]] == 3))}) "
          f"and score=5 ({int(np.sum(score[np.where(h3a_mask)[0]] == 5))})")

    fixed_r    = results.get("fixed",    {})
    weighted_r = results.get("weighted", {})
    fixed_te_pnl    = fixed_r.get("te_pnl_cap", 0)
    weighted_te_pnl = weighted_r.get("te_pnl_cap", 0)
    fixed_te    = fixed_r.get("test")
    weighted_te = weighted_r.get("test")

    print()
    if fixed_te and weighted_te:
        pnl_delta = weighted_te_pnl - fixed_te_pnl
        sh_delta  = weighted_te["sharpe"] - fixed_te["sharpe"]
        dd_delta  = weighted_r["te_wdd"]  - fixed_r["te_wdd"]
        print(f"  OOS delta (weighted - fixed):  WalletPnL={pnl_delta:+.2%}  "
              f"Sharpe={sh_delta:+.3f}  WalletMaxDD={dd_delta:+.3f}")
        winner = "WEIGHTED" if weighted_te_pnl > fixed_te_pnl else "FIXED"
        print(f"  WINNER by OOS wallet PnL: {winner}")
        if weighted_te["n"] >= 5 and weighted_te["p"] < 0.10:
            print("  Weighted sizing: STATISTICALLY SIGNIFICANT (p < 0.10)")
        elif fixed_te["n"] >= 5 and fixed_te["p"] < 0.10:
            print("  Fixed sizing: STATISTICALLY SIGNIFICANT (p < 0.10)")
        else:
            print("  Neither approach meets p < 0.10 on OOS set")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("=" * 72)
    print("IG-88 FOCUSED BACKTESTING STUDIES")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    res_a = study_a()
    res_b = study_b()

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)

    # Study A summary
    fixed_te  = res_a.get("atr_fixed",  {}).get("test")
    trail_te  = res_a.get("atr_trail",  {}).get("test")
    print("\nSTUDY A — H3-C Exit Comparison (SOL/USDT 4h OOS):")
    if fixed_te:
        star = "*" if fixed_te["p"] < 0.10 else ""
        print(f"  ATR Fixed 2x/3x : n={fixed_te['n']}  WR={fixed_te['wr']:.1%}  "
              f"PF={fixed_te['pf']:.3f}  Sh={fixed_te['sharpe']:+.3f}  p={fixed_te['p']:.3f}{star}")
    if trail_te:
        star = "*" if trail_te["p"] < 0.10 else ""
        print(f"  ATR Trail 2x    : n={trail_te['n']}  WR={trail_te['wr']:.1%}  "
              f"PF={trail_te['pf']:.3f}  Sh={trail_te['sharpe']:+.3f}  p={trail_te['p']:.3f}{star}")
    if fixed_te and trail_te:
        winner = "ATR TRAIL" if trail_te["pf"] > fixed_te["pf"] else "ATR FIXED"
        print(f"  --> Recommendation: {winner}")

    # Study B summary
    fixed_r    = res_b.get("fixed",    {})
    weighted_r = res_b.get("weighted", {})
    fixed_te    = fixed_r.get("test")
    weighted_te = weighted_r.get("test")
    fixed_te_pnl    = fixed_r.get("te_pnl_cap", 0)
    weighted_te_pnl = weighted_r.get("te_pnl_cap", 0)
    print("\nSTUDY B — H3-A Position Sizing (SOL/USDT 4h OOS):")
    if fixed_te:
        star = "*" if fixed_te["p"] < 0.10 else ""
        print(f"  Fixed 2%        : n={fixed_te['n']}  WalletPnL={fixed_te_pnl:+.2%}  "
              f"Sh={fixed_te['sharpe']:+.3f}  WDD={fixed_r['te_wdd']:.3f}  p={fixed_te['p']:.3f}{star}")
    if weighted_te:
        star = "*" if weighted_te["p"] < 0.10 else ""
        print(f"  Conf-Weighted   : n={weighted_te['n']}  WalletPnL={weighted_te_pnl:+.2%}  "
              f"Sh={weighted_te['sharpe']:+.3f}  WDD={weighted_r['te_wdd']:.3f}  p={weighted_te['p']:.3f}{star}")
    if fixed_te and weighted_te:
        winner = "CONF-WEIGHTED" if weighted_te_pnl > fixed_te_pnl else "FIXED 2%"
        print(f"  --> Recommendation: {winner}")

    print()
    print("Done.")
