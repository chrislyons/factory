#!/usr/bin/env python3
"""Chandelier Exit backtest — compare against fixed ATR trailing on H3-A/B SOL 4h."""

import sys
from pathlib import Path

# Add project root to path (scripts/ -> project root)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

import src.quant.indicators as ind
from src.quant.indicator_research import (
    signals_ichimoku_h3a,
    signals_vol_spike_break,
    signals_rsi_momentum_cross,
)
from src.quant.ichimoku_backtest import load_binance, df_to_arrays, build_btc_trend_regime
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade
from src.quant.regime import RegimeState
from datetime import datetime, timezone

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"
MAKER_FEE = 0.0016


def run_backtest(ts, o, h, l, c, v, regime, signal_mask, exit_method, bar_hours=4.0):
    """Run backtest with specified exit method."""
    n = len(ts)
    wallet = 10_000.0
    atr_v = ind.atr(h, l, c, 14)
    ichi = ind.ichimoku(h, l, c)
    chan = ind.chandelier_exit(h, l, c, lookback=22, atr_mult=3.0)

    trades = []
    counter = 0
    last_exit = -999
    min_hold = max(1, int(2 / bar_hours))
    cooldown = max(1, int(2 / bar_hours))
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

        # Set initial stop based on method
        if exit_method == "atr_trail_2x":
            stop_p = ep - 2.0 * av
            target_p = ep + 3.0 * av
        elif exit_method == "chandelier_3x":
            # Use Chandelier long stop if available, else fallback
            cs = chan.long_stop[eb]
            if np.isnan(cs):
                cs = ep - 3.0 * av
            stop_p = cs
            target_p = ep + 4.0 * av  # Wider target for wider stop
        elif exit_method == "chandelier_2x":
            cs = chan.long_stop[eb]
            if np.isnan(cs):
                cs = ep - 2.0 * av
            # Recalculate with 2x mult
            lookback = 22
            atr_p = 14
            if eb >= lookback:
                highest = float(np.max(h[eb - lookback + 1:eb + 1]))
                atr_val = atr_v[eb] if not np.isnan(atr_v[eb]) else av
                cs = highest - 2.0 * atr_val
            stop_p = cs
            target_p = ep + 3.0 * av
        else:  # fixed atr 2x/3x
            stop_p = ep - 2.0 * av
            target_p = ep + 3.0 * av

        et = datetime.fromtimestamp(ts[eb], tz=timezone.utc)
        trade = Trade(
            trade_id=f"CHAN-{counter:05d}",
            venue=VENUE,
            strategy=exit_method,
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

        # Track highest high for trailing
        highest_since_entry = ep
        trail_stop = stop_p

        xb = eb
        xp = ep
        xr = ExitReason.TIME_STOP

        for j in range(1, n - eb):
            bar = eb + j
            if bar >= n:
                break

            cur_av = atr_v[bar] if not np.isnan(atr_v[bar]) else av

            # Update highest high for chandelier
            if h[bar] > highest_since_entry:
                highest_since_entry = h[bar]

            # Exit logic
            if exit_method.startswith("chandelier"):
                # Chandelier trailing: highest high - mult * ATR
                if exit_method == "chandelier_3x":
                    trail_stop = max(trail_stop, highest_since_entry - 3.0 * cur_av)
                else:  # chandelier_2x
                    trail_stop = max(trail_stop, highest_since_entry - 2.0 * cur_av)

                if l[bar] <= trail_stop and j >= min_hold:
                    xb = bar
                    xp = trail_stop
                    xr = ExitReason.STOP_HIT
                    break
            else:
                # Fixed ATR trailing
                trail_stop = max(trail_stop, c[bar] - 2.0 * cur_av)
                if c[bar] < trail_stop and j >= min_hold:
                    xb = bar
                    xp = trail_stop
                    xr = ExitReason.STOP_HIT
                    break

            # Target hit
            if h[bar] >= target_p:
                xb = bar
                xp = target_p
                xr = ExitReason.TARGET_HIT
                break

            # Time stop (20 bars = 80h)
            if j >= 20:
                xb = bar
                xp = c[bar]
                xr = ExitReason.TIME_STOP
                break

            # Regime exit
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


def main():
    print("=" * 80)
    print("CHANDELIER EXIT BACKTEST — H3-A/B on SOL 4h")
    print("=" * 80)

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

    # Align arrays (regime is 7 bars shorter due to BTC trend calc)
    min_len = min(len(ts), len(regime), len(m_h3a), len(m_h3b))
    ts, o, h, l, c, v = ts[:min_len], o[:min_len], h[:min_len], l[:min_len], c[:min_len], v[:min_len]
    regime = regime[:min_len]
    m_h3a = m_h3a[:min_len]
    m_h3b = m_h3b[:min_len]

    # Walk-forward split
    SPLIT = int(len(ts) * 0.70)

    exit_methods = ["atr_trail_2x", "chandelier_2x", "chandelier_3x"]

    for strategy_name, mask in [("H3-A", m_h3a), ("H3-B", m_h3b)]:
        print(f"\n{'─' * 80}")
        print(f"  {strategy_name} Strategy")
        print(f"{'─' * 80}")
        print(f"  {'Exit Method':<18} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-Sh':>7} "
              f"{'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7}")
        print(f"  {'─' * 18} {'─' * 5} {'─' * 7} {'─' * 7} "
              f"{'─' * 5} {'─' * 7} {'─' * 7} {'─' * 7}")

        results = {}
        for method in exit_methods:
            # Train
            tr_trades = run_backtest(
                ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                regime[:SPLIT], mask[:SPLIT], method
            )
            # Test
            te_trades = run_backtest(
                ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:], c[SPLIT:], v[SPLIT:],
                regime[SPLIT:], mask[SPLIT:], method
            )

            def stats(trades):
                if not trades:
                    return {"n": 0, "pf": 0, "sharpe": 0, "p": 1.0}
                eng = BacktestEngine(10_000.0)
                eng.add_trades(trades)
                s = eng.compute_stats(venue=VENUE)
                return {"n": s.n_trades, "pf": s.profit_factor, "sharpe": s.sharpe_ratio, "p": s.p_value}

            tr = stats(tr_trades)
            te = stats(te_trades)

            tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['sharpe']:7.3f}" if tr["n"] > 0 else "    0       -       -"
            te_s = f"{te['n']:5d} {te['pf']:7.3f} {te['sharpe']:7.3f} {te['p']:7.3f}" if te["n"] > 0 else "    0       -       -       -"

            note = ""
            if method == "atr_trail_2x":
                note = "(baseline)"
            elif te["n"] >= 5 and te["pf"] > 3.0:
                note = "✓ BETTER" if method.startswith("chandelier") else ""

            print(f"  {method:<18} {tr_s}  {te_s}  {note}")
            results[method] = {"train": tr, "test": te}

        # Best method
        best = max(
            [(k, v) for k, v in results.items() if v["test"]["n"] >= 5],
            key=lambda x: x[1]["test"]["pf"] * (1 - x[1]["test"]["p"]),
            default=(None, None)
        )
        if best[0]:
            te = best[1]["test"]
            print(f"\n  ➤ Best exit for {strategy_name}: {best[0]}  "
                  f"OOS PF={te['pf']:.3f} Sh={te['sharpe']:+.3f} p={te['p']:.3f}")

    print("\n" + "=" * 80)
    print("BACKTEST COMPLETE")


if __name__ == "__main__":
    main()
