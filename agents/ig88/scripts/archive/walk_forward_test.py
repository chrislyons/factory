#!/usr/bin/env python3
"""Walk-Forward Validation: Rolling window edge decay detection.

Rolls a 6-month window (1095 bars of 4h) across the full SOL 4h history.
Each window is split 70/30 (train/validation). Tracks PF, Sharpe, n trades
across windows to detect edge decay or regime-dependent performance.

Goal: Answer "Is the H3 edge stable, decaying, or regime-dependent?"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import json
from datetime import datetime, timezone

import src.quant.indicators as ind
from src.quant.indicator_research import (
    signals_ichimoku_h3a,
    signals_vol_spike_break,
    signals_rsi_momentum_cross,
)
from src.quant.ichimoku_backtest import load_binance, df_to_arrays, build_btc_trend_regime
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade
from src.quant.regime import RegimeState

VENUE = "kraken_spot"
MAKER_FEE = 0.0016
WINDOW_BARS = 1095  # ~6 months of 4h bars (182.5 days * 6 bars/day)
TRAIN_SPLIT = 0.70


def run_window_backtest(ts, o, h, l, c, v, regime, signal_mask, bar_hours=4.0):
    """Backtest a single window with ATR trailing stop."""
    n = len(ts)
    wallet = 10_000.0
    atr_v = ind.atr(h, l, c, 14)

    trades = []
    counter = 0
    last_exit = -999
    min_hold = max(1, int(2 / bar_hours))
    cooldown = max(1, int(2 / bar_hours))
    daily_pnl = 0.0
    halted = False
    cur_day = -1

    i = 60  # warmup for Ichimoku
    while i < n - min_hold - 2:
        day = int(ts[i] // 86400)
        if day != cur_day:
            cur_day = day
            daily_pnl = 0.0
            halted = False
        if halted:
            i += 1
            continue
        if i - last_exit < cooldown:
            i += 1
            continue
        if regime[i] == RegimeState.RISK_OFF:
            i += 1
            continue
        if not signal_mask[i]:
            i += 1
            continue

        av = atr_v[i]
        if np.isnan(av) or av <= 0:
            i += 1
            continue

        eb = i + 1
        if eb >= n:
            break

        ep = o[eb]
        pos = wallet * 0.02
        if pos < 1.0:
            i += 1
            continue

        stop_p = ep - 2.0 * av
        target_p = ep + 3.0 * av

        et = datetime.fromtimestamp(ts[eb], tz=timezone.utc)
        trade = Trade(
            trade_id=f"WF-{counter:05d}",
            venue=VENUE,
            strategy="walk_forward",
            pair="SOL/USDT",
            entry_timestamp=et,
            entry_price=ep,
            position_size_usd=pos,
            regime_state=regime[i],
            side="long",
            leverage=1.0,
            stop_level=stop_p,
            target_level=target_p,
            fees_paid=pos * MAKER_FEE,
        )
        counter += 1

        trail_stop = stop_p
        xb = eb
        xp = ep
        xr = ExitReason.TIME_STOP

        for j in range(1, n - eb):
            bar = eb + j
            if bar >= n:
                break

            cur_av = atr_v[bar] if not np.isnan(atr_v[bar]) else av
            trail_stop = max(trail_stop, c[bar] - 2.0 * cur_av)

            if c[bar] < trail_stop and j >= min_hold:
                xb = bar
                xp = trail_stop
                xr = ExitReason.STOP_HIT
                break

            if h[bar] >= target_p:
                xb = bar
                xp = target_p
                xr = ExitReason.TARGET_HIT
                break

            if j >= 20:
                xb = bar
                xp = c[bar]
                xr = ExitReason.TIME_STOP
                break

            if regime[bar] == RegimeState.RISK_OFF and j >= min_hold:
                xb = bar
                xp = c[bar]
                xr = ExitReason.REGIME_EXIT
                break

        xt = datetime.fromtimestamp(ts[min(xb, n - 1)], tz=timezone.utc)
        trade.close(xp, xt, xr, fees=pos * MAKER_FEE)
        if trade.pnl_usd is not None:
            wallet += trade.pnl_usd
            daily_pnl += trade.pnl_usd
            if daily_pnl < -(10_000.0 * 0.03):
                halted = True

        last_exit = xb
        trades.append(trade)
        i = xb + cooldown

    return trades


def compute_window_stats(trades):
    """Compute stats for a list of trades."""
    if not trades:
        return {"n": 0, "wr": 0.0, "pf": 0.0, "sharpe": 0.0, "dd": 0.0, "p": 1.0, "expectancy": 0.0}
    eng = BacktestEngine(10_000.0)
    eng.add_trades(trades)
    s = eng.compute_stats(venue=VENUE)
    return {
        "n": s.n_trades,
        "wr": s.win_rate,
        "pf": s.profit_factor,
        "sharpe": s.sharpe_ratio,
        "dd": s.max_drawdown_pct,
        "p": s.p_value,
        "expectancy": s.expectancy_per_trade,
    }


def main():
    print("=" * 100)
    print("WALK-FORWARD VALIDATION: 6-month rolling windows, H3-A/B on SOL 4h")
    print("=" * 100)

    # Load data
    df = load_binance("SOL/USDT", 240)
    btc_df = load_binance("BTC/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(df)
    btc_ts, btc_o, btc_h, btc_l, btc_c, btc_v = df_to_arrays(btc_df)
    regime = build_btc_trend_regime(btc_c, btc_ts, ts)

    # Generate signals
    m_h3a, _ = signals_ichimoku_h3a(h, l, c)
    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    m_h3b = m_vol & m_rsi

    # Align arrays
    min_len = min(len(ts), len(regime), len(m_h3a), len(m_h3b))
    ts, o, h, l, c, v = ts[:min_len], o[:min_len], h[:min_len], l[:min_len], c[:min_len], v[:min_len]
    regime = regime[:min_len]
    m_h3a = m_h3a[:min_len]
    m_h3b = m_h3b[:min_len]

    N = len(ts)
    step = WINDOW_BARS // 3  # 1/3 window overlap for smoother tracking
    INNER_SPLIT = int(WINDOW_BARS * TRAIN_SPLIT)

    print(f"\n  Total bars: {N}")
    print(f"  Window: {WINDOW_BARS} bars (~{WINDOW_BARS/6:.0f} days = ~{WINDOW_BARS/6/30:.1f} months)")
    print(f"  Step: {step} bars ({step/6:.0f} days)")
    print(f"  Inner split: {INNER_SPLIT} train / {WINDOW_BARS - INNER_SPLIT} validation")
    print(f"  Estimated windows: {(N - WINDOW_BARS) // step + 1}")

    results_all = {}

    for strategy_name, mask in [("H3-A", m_h3a), ("H3-B", m_h3b)]:
        print(f"\n{'─' * 100}")
        print(f"  {strategy_name} Strategy")
        print(f"{'─' * 100}")
        print(f"  {'Window Start':<16} {'Window End':<16} {'Tr-n':>4} {'Tr-PF':>7} {'Tr-Sh':>7} "
              f"{'Te-n':>4} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>6} {'Te-DD':>7} {'Decay':>7}")
        print(f"  {'─' * 16} {'─' * 16} {'─' * 4} {'─' * 7} {'─' * 7} "
              f"{'─' * 4} {'─' * 7} {'─' * 7} {'─' * 6} {'─' * 7} {'─' * 7}")

        window_results = []
        start = 0
        window_idx = 0

        while start + WINDOW_BARS <= N:
            end = start + WINDOW_BARS
            inner_train = start + INNER_SPLIT

            w_ts = ts[start:end]
            w_o = o[start:end]
            w_h = h[start:end]
            w_l = l[start:end]
            w_c = c[start:end]
            w_v = v[start:end]
            w_regime = regime[start:end]
            w_mask = mask[start:end]

            # Training
            tr_trades = run_window_backtest(
                w_ts[:INNER_SPLIT], w_o[:INNER_SPLIT], w_h[:INNER_SPLIT],
                w_l[:INNER_SPLIT], w_c[:INNER_SPLIT], w_v[:INNER_SPLIT],
                w_regime[:INNER_SPLIT], w_mask[:INNER_SPLIT]
            )

            # Validation (OOS)
            te_trades = run_window_backtest(
                w_ts[INNER_SPLIT:], w_o[INNER_SPLIT:], w_h[INNER_SPLIT:],
                w_l[INNER_SPLIT:], w_c[INNER_SPLIT:], w_v[INNER_SPLIT:],
                w_regime[INNER_SPLIT:], w_mask[INNER_SPLIT:]
            )

            tr_stats = compute_window_stats(tr_trades)
            te_stats = compute_window_stats(te_trades)

            # Decode dates
            start_ts = w_ts[0]
            end_ts = w_ts[-1]
            start_date = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            end_date = datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime("%Y-%m-%d")

            # Decay metric: train PF - test PF (positive = decay)
            decay = tr_stats["pf"] - te_stats["pf"] if tr_stats["n"] > 0 and te_stats["n"] > 0 else 0.0

            tr_n = f"{tr_stats['n']:4d}" if tr_stats["n"] > 0 else "   0"
            tr_pf = f"{tr_stats['pf']:7.3f}" if tr_stats["n"] > 0 else "      -"
            tr_sh = f"{tr_stats['sharpe']:7.3f}" if tr_stats["n"] > 0 else "      -"
            te_n = f"{te_stats['n']:4d}" if te_stats["n"] > 0 else "   0"
            te_pf = f"{te_stats['pf']:7.3f}" if te_stats["n"] > 0 else "      -"
            te_sh = f"{te_stats['sharpe']:7.3f}" if te_stats["n"] > 0 else "      -"
            te_p = f"{te_stats['p']:6.3f}" if te_stats["n"] > 0 else "     -"
            te_dd = f"{te_stats['dd']:7.2%}" if te_stats["n"] > 0 else "      -"
            decay_str = f"{decay:7.3f}" if te_stats["n"] > 0 else "      -"

            # Flag
            flag = ""
            if te_stats["n"] > 0:
                if te_stats["pf"] > 4.0:
                    flag = " ★"
                elif te_stats["pf"] < 1.0:
                    flag = " ✗"
                elif decay > 5.0:
                    flag = " ⚠"

            print(f"  {start_date:<16} {end_date:<16} {tr_n} {tr_pf} {tr_sh} "
                  f"{te_n} {te_pf} {te_sh} {te_p} {te_dd} {decay_str}{flag}")

            window_results.append({
                "window_idx": window_idx,
                "start_date": start_date,
                "end_date": end_date,
                "train": tr_stats,
                "test": te_stats,
                "decay": decay,
            })

            window_idx += 1
            start += step

        results_all[strategy_name] = window_results

        # Summary statistics
        valid_windows = [w for w in window_results if w["test"]["n"] >= 5]
        if valid_windows:
            te_pfs = [w["test"]["pf"] for w in valid_windows]
            te_sharpes = [w["test"]["sharpe"] for w in valid_windows]
            decays = [w["decay"] for w in valid_windows]

            print(f"\n  --- {strategy_name} Summary ({len(valid_windows)} valid windows) ---")
            print(f"  OOS PF:   mean={np.mean(te_pfs):.3f}  median={np.median(te_pfs):.3f}  "
                  f"std={np.std(te_pfs):.3f}  min={np.min(te_pfs):.3f}  max={np.max(te_pfs):.3f}")
            print(f"  OOS Sharpe: mean={np.mean(te_sharpes):.3f}  median={np.median(te_sharpes):.3f}")
            print(f"  Decay (Tr-PF - Te-PF): mean={np.mean(decays):.3f}  "
                  f"positive={sum(1 for d in decays if d > 0)}/{len(decays)}")

            # Trend analysis: is PF declining over time?
            if len(valid_windows) >= 5:
                x = np.arange(len(valid_windows))
                y = np.array(te_pfs)
                slope = np.polyfit(x, y, 1)[0]
                trend = "DECLINING ↓" if slope < -0.5 else "STABLE →" if slope < 0.5 else "IMPROVING ↑"
                print(f"  PF Trend: {trend} (slope={slope:.3f} per window)")
        else:
            print(f"\n  --- {strategy_name}: No valid windows (n>=5) ---")

    # Save results
    output_path = Path("/Users/nesbitt/dev/factory/agents/ig88/data/walk_forward_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results_all, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")

    print("\n" + "=" * 100)
    print("WALK-FORWARD VALIDATION COMPLETE")


if __name__ == "__main__":
    main()
