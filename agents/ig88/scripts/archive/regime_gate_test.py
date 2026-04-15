#!/usr/bin/env python3
"""Regime Gate: Composite score filtering H3-A/B entries by market regime.

Tests whether filtering entries using Squeeze + %B + ADX reduces losing trades
without killing winners. Goal: improve PF by avoiding choppy/range-bound regimes.

Components:
1. Squeeze active = low vol compression (wait for release before momentum entries)
2. %B extreme (>0.9 or <0.1) = overbought/oversold (avoid chasing)
3. ADX < 20 = no trend (filter range-bound chop)

Composite gate: PASS if NOT in squeeze AND NOT in %B extreme AND ADX > 20
"""

import sys
from pathlib import Path

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


def compute_regime_gate(h, l, c, v):
    """Compute composite regime gate. True = favorable regime for momentum entries."""
    n = len(c)

    # 1. Squeeze: active squeeze = low vol, wait for release
    squeeze_result = ind.squeeze(h, l, c)
    squeeze_active = squeeze_result.squeeze

    # 2. %B extremes: overbought/oversold
    bb = ind.bollinger_bands(c)
    pct_b_extreme = (bb.percent_b > 0.9) | (bb.percent_b < 0.1)

    # 3. ADX: weak trend
    adx_result = ind.adx(h, l, c, 14)
    adx_weak = adx_result.adx < 20.0

    # Gate: PASS if all conditions favorable
    # NOT in squeeze AND NOT in %B extreme AND ADX > 20
    gate = (~squeeze_active) & (~pct_b_extreme) & (~adx_weak)

    return gate, squeeze_active, pct_b_extreme, adx_weak


def run_backtest(ts, o, h, l, c, v, regime, signal_mask, regime_gate=None, bar_hours=4.0):
    """Run backtest with optional regime gate filter."""
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

        # Apply regime gate if provided
        if regime_gate is not None and not regime_gate[i]:
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
            trade_id=f"GATE-{counter:05d}",
            venue=VENUE,
            strategy="gated",
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


def main():
    print("=" * 90)
    print("REGIME GATE TEST — Composite filter (Squeeze + %B + ADX) on H3-A/B SOL 4h")
    print("=" * 90)

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

    # Compute regime gate
    gate, squeeze_active, pct_b_extreme, adx_weak = compute_regime_gate(h, l, c, v)

    # Align arrays
    min_len = min(len(ts), len(regime), len(m_h3a), len(m_h3b), len(gate))
    ts, o, h, l, c, v = ts[:min_len], o[:min_len], h[:min_len], l[:min_len], c[:min_len], v[:min_len]
    regime = regime[:min_len]
    m_h3a = m_h3a[:min_len]
    m_h3b = m_h3b[:min_len]
    gate = gate[:min_len]

    # Walk-forward split
    SPLIT = int(len(ts) * 0.70)

    # Gate statistics
    start = 60  # warmup
    print(f"\n--- Regime Gate Statistics (bars {start} to {min_len}) ---")
    active = gate[start:]
    print(f"  Total bars: {len(active)}")
    print(f"  Gate PASS: {np.sum(active)} ({np.mean(active)*100:.1f}%)")
    print(f"  Gate BLOCK: {np.sum(~active)} ({np.mean(~active)*100:.1f}%)")
    print(f"  Squeeze active: {np.sum(squeeze_active[start:])} ({np.mean(squeeze_active[start:])*100:.1f}%)")
    print(f"  %B extreme: {np.sum(pct_b_extreme[start:])} ({np.mean(pct_b_extreme[start:])*100:.1f}%)")
    print(f"  ADX < 20: {np.sum(adx_weak[start:])} ({np.mean(adx_weak[start:])*100:.1f}%)")

    for strategy_name, mask in [("H3-A", m_h3a), ("H3-B", m_h3b)]:
        print(f"\n{'─' * 90}")
        print(f"  {strategy_name} Strategy")
        print(f"{'─' * 90}")
        print(f"  {'Config':<25} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-Sh':>7} "
              f"{'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7} {'Gate%':>7}")
        print(f"  {'─' * 25} {'─' * 5} {'─' * 7} {'─' * 7} "
              f"{'─' * 5} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 7}")

        results = {}

        # Baseline: no gate
        for label, g in [("No gate (baseline)", None), ("Regime gate ON", gate)]:
            tr_trades = run_backtest(
                ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                regime[:SPLIT], mask[:SPLIT], g
            )
            te_trades = run_backtest(
                ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:], c[SPLIT:], v[SPLIT:],
                regime[SPLIT:], mask[SPLIT:], g
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
            gate_pct = f"{np.mean(gate[SPLIT:])*100:.1f}%" if g is not None else "100%"

            tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['sharpe']:7.3f}" if tr["n"] > 0 else "    0       -       -"
            te_s = f"{te['n']:5d} {te['pf']:7.3f} {te['sharpe']:7.3f} {te['p']:7.3f}" if te["n"] > 0 else "    0       -       -       -"

            note = ""
            if label == "Regime gate ON" and te["n"] > 0:
                base_te = results.get("No gate (baseline)", {}).get("test", {})
                if base_te and te.get("pf", 0) > base_te.get("pf", 0):
                    note = "✓ IMPROVED"

            print(f"  {label:<25} {tr_s}  {te_s} {gate_pct:>7}  {note}")
            results[label] = {"train": tr, "test": te}

        # Best
        best = max(
            [(k, v) for k, v in results.items() if v["test"]["n"] >= 5],
            key=lambda x: x[1]["test"]["pf"] * (1 - x[1]["test"]["p"]),
            default=(None, None)
        )
        if best[0]:
            te = best[1]["test"]
            print(f"\n  ➤ Best config for {strategy_name}: {best[0]}  "
                  f"OOS PF={te['pf']:.3f} Sh={te['sharpe']:+.3f} p={te['p']:.3f}")

    print("\n" + "=" * 90)
    print("REGIME GATE TEST COMPLETE")


if __name__ == "__main__":
    main()
