"""
momentum_breakout_backtest.py — Strategy #3: Momentum Breakout with Regime Filter

TRENDING regime complement to our MR (Mean Reversion) strategy.

Regime filter: ADX(14) > 25 AND price > SMA(200) for uptrend
Entry: Close > N-period high AND Volume > Mx SMA(20) AND RSI(14) in [50, RSI_MAX]
Exit: Chandelier trailing stop (ATR(22) * K from highest high since entry) OR time exit (T bars)
Direction: LONG only

Grid search over 5 params, 5-split walk-forward, OOS-only reporting.
Friction: Kraken 0.32% round-trip (maker).

Key question: Can momentum complement MR (different regimes = different signals)?
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

import src.quant.indicators as ind
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade
from src.quant.ichimoku_backtest import df_to_arrays, load_binance
from src.quant.regime import RegimeState

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"
KRAKEN_RT_FEE = 0.0032  # 0.32% round-trip maker fee
BAR_HOURS = 4.0
INITIAL_CAPITAL = 10_000.0
WARMUP = 220  # Need 200 for SMA(200) + extra for ADX

# Pairs to test (same as MR strategy)
PAIRS = [
    ("SOL/USDT", 240),
    ("AVAX/USDT", 240),
    ("ETH/USDT", 240),
    ("LINK/USDT", 240),
    ("BTC/USDT", 240),
]


# ---------------------------------------------------------------------------
# Regime detection: ADX trend filter
# ---------------------------------------------------------------------------

def build_adx_trend_regime(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    adx_period: int = 14,
    sma_period: int = 200,
    adx_threshold: float = 25.0,
) -> np.ndarray:
    """
    TRENDING regime filter: ADX(14) > 25 AND price > SMA(200) for uptrend.
    Returns boolean array: True = trending regime (tradeable).
    """
    n = len(close)
    adx_result = ind.adx(high, low, close, period=adx_period)
    sma_200 = ind.sma(close, sma_period)

    trending = np.zeros(n, dtype=bool)
    for i in range(n):
        if np.isnan(adx_result.adx[i]) or np.isnan(sma_200[i]):
            continue
        # TRENDING = ADX > threshold AND price above SMA(200)
        if adx_result.adx[i] > adx_threshold and close[i] > sma_200[i]:
            trending[i] = True
    return trending


# ---------------------------------------------------------------------------
# Momentum breakout entry signals
# ---------------------------------------------------------------------------

def generate_entry_signals(
    high: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    breakout_lookback: int = 20,
    volume_mult: float = 2.0,
    rsi_upper: float = 70.0,
    rsi_period: int = 14,
) -> np.ndarray:
    """
    Entry: Close > N-period high AND Volume > Mx SMA(20) AND RSI(14) in [50, RSI_MAX].

    Returns boolean signal mask.
    """
    n = len(close)
    rsi_vals = ind.rsi(close, rsi_period)
    vol_sma = ind.sma(volume, 20)

    signals = np.zeros(n, dtype=bool)

    for i in range(max(breakout_lookback, 20, rsi_period + 1), n):
        # Breakout: close above N-period highest high
        period_high = np.max(high[i - breakout_lookback:i])  # highest high BEFORE this bar
        if close[i] <= period_high:
            continue

        # Volume filter: volume > Mx SMA(20)
        if np.isnan(vol_sma[i]) or vol_sma[i] <= 0:
            continue
        if volume[i] <= volume_mult * vol_sma[i]:
            continue

        # RSI filter: 50 <= RSI <= RSI_UPPER (momentum but not overbought)
        if np.isnan(rsi_vals[i]):
            continue
        if rsi_vals[i] < 50 or rsi_vals[i] > rsi_upper:
            continue

        signals[i] = True

    return signals


# ---------------------------------------------------------------------------
# Chandelier trailing stop backtester
# ---------------------------------------------------------------------------

class MomentumBreakoutBacktester:
    """
    Backtest momentum breakout with Chandelier trailing stop.

    Entry: signal bar -> enter at next bar's open
    Exit: Chandelier stop (highest high since entry - ATR * K) OR time exit (T bars)
    """

    def __init__(
        self,
        initial_capital: float = INITIAL_CAPITAL,
        bar_hours: float = BAR_HOURS,
        atr_period: int = 22,
        atr_trail_mult: float = 3.0,
        time_exit_bars: int = 10,
        cooldown_bars: int = 2,
    ):
        self.initial_capital = initial_capital
        self.bar_hours = bar_hours
        self.atr_period = atr_period
        self.atr_trail_mult = atr_trail_mult
        self.time_exit_bars = time_exit_bars
        self.cooldown_bars = cooldown_bars

    def run(
        self,
        ts: np.ndarray,
        o: np.ndarray,
        h: np.ndarray,
        l: np.ndarray,
        c: np.ndarray,
        v: np.ndarray,
        signal_mask: np.ndarray,
        trending_regime: np.ndarray,
        atr_vals: np.ndarray,
    ) -> list[Trade]:
        n = len(ts)
        trades = []
        wallet = self.initial_capital
        counter = 0
        last_exit = -999
        daily_pnl = 0.0
        halted = False
        current_day = -1

        i = WARMUP

        while i < n - 2:
            # Daily halt check
            day = int(ts[i] // 86400)
            if day != current_day:
                current_day = day
                daily_pnl = 0.0
                halted = False
            if halted:
                i += 1
                continue

            # Cooldown
            if i - last_exit < self.cooldown_bars:
                i += 1
                continue

            # TRENDING regime gate
            if not trending_regime[i]:
                i += 1
                continue

            # Signal check
            if not signal_mask[i]:
                i += 1
                continue

            # ATR check
            atr_v = atr_vals[i]
            if np.isnan(atr_v) or atr_v <= 0:
                i += 1
                continue

            # Entry at next bar's open
            entry_bar = i + 1
            if entry_bar >= n:
                break

            entry_price = o[entry_bar]
            entry_time = datetime.fromtimestamp(ts[entry_bar], tz=timezone.utc)
            pos_size = wallet * 0.02  # 2% risk sizing
            if pos_size < 1.0:
                i += 1
                continue

            counter += 1
            trade = Trade(
                trade_id=f"MOM-{counter:05d}",
                venue=VENUE,
                strategy="momentum_breakout",
                pair="",
                entry_timestamp=entry_time,
                entry_price=entry_price,
                position_size_usd=pos_size,
                regime_state=RegimeState.RISK_ON,
                side="long",
                leverage=1.0,
                fees_paid=pos_size * KRAKEN_RT_FEE * 0.5,  # entry fee only
            )

            # Track for Chandelier
            highest_high = h[entry_bar]
            exit_bar = entry_bar
            exit_price = entry_price
            exit_reason = ExitReason.TIME_STOP

            for j in range(1, n - entry_bar):
                bar = entry_bar + j
                if bar >= n:
                    break

                # Update highest high
                if h[bar] > highest_high:
                    highest_high = h[bar]

                # Chandelier trailing stop
                cur_atr = atr_vals[bar] if not np.isnan(atr_vals[bar]) else atr_v
                trail_stop = highest_high - self.atr_trail_mult * cur_atr

                # Check stop hit
                if l[bar] <= trail_stop:
                    exit_bar = bar
                    exit_price = trail_stop
                    exit_reason = ExitReason.STOP_HIT
                    break

                # Time exit
                if j >= self.time_exit_bars:
                    exit_bar = bar
                    exit_price = c[bar]
                    exit_reason = ExitReason.TIME_STOP
                    break

            exit_time = datetime.fromtimestamp(ts[min(exit_bar, n - 1)], tz=timezone.utc)
            trade.close(exit_price, exit_time, exit_reason, fees=pos_size * KRAKEN_RT_FEE * 0.5)

            if trade.pnl_usd is not None:
                wallet += trade.pnl_usd
                daily_pnl += trade.pnl_usd
                if daily_pnl < -(self.initial_capital * 0.03):
                    halted = True

            last_exit = exit_bar
            trades.append(trade)
            i = exit_bar + self.cooldown_bars

        return trades


def backtest_momentum_breakout(
    ts, o, h, l, c, v, trending_regime, atr_vals,
    breakout_lookback=20, volume_mult=2.0, rsi_upper=70.0,
    atr_trail_mult=3.0, time_exit_bars=10,
    capital=INITIAL_CAPITAL, bar_hours=BAR_HOURS,
) -> dict | None:
    """Run a single parameter set and return stats dict."""

    signal_mask = generate_entry_signals(
        h, c, v,
        breakout_lookback=breakout_lookback,
        volume_mult=volume_mult,
        rsi_upper=rsi_upper,
    )

    bt = MomentumBreakoutBacktester(
        initial_capital=capital,
        bar_hours=bar_hours,
        atr_trail_mult=atr_trail_mult,
        time_exit_bars=time_exit_bars,
    )
    trades = bt.run(ts, o, h, l, c, v, signal_mask, trending_regime, atr_vals)

    if not trades:
        return None

    eng = BacktestEngine(initial_capital=capital)
    eng.add_trades(trades)
    s = eng.compute_stats(venue=VENUE)

    return {
        "n": s.n_trades,
        "wr": round(s.win_rate, 4),
        "pf": round(s.profit_factor, 4),
        "sharpe": round(s.sharpe_ratio, 4),
        "sortino": round(s.sortino_ratio, 4),
        "dd": round(s.max_drawdown_pct, 4),
        "pnl_pct": round(s.total_pnl_pct, 4),
        "exp_r": round(s.expectancy_r, 4),
        "p": round(s.p_value, 4),
    }


# ---------------------------------------------------------------------------
# Walk-forward with grid search
# ---------------------------------------------------------------------------

def walk_forward_5split(
    ts, o, h, l, c, v, trending_regime, atr_vals,
    n_splits: int = 5,
) -> list[dict]:
    """
    5-split walk-forward validation.
    Each split: train on first portion, test on next portion.
    We only report OOS (test) results.
    """
    N = len(ts)
    # Split into n_splits+1 segments, use first for warmup, rest for train/test pairs
    # Simple approach: divide into n_splits equal segments, each is a test window
    segment_size = N // (n_splits + 1)

    oos_results = []

    for split in range(n_splits):
        # Test window is segment [split+1], train is everything before
        test_start = (split + 1) * segment_size
        test_end = min((split + 2) * segment_size, N)
        train_start = 0
        train_end = test_start

        if test_end - test_start < 50 or train_end - train_start < WARMUP + 100:
            continue

        # Grid search on train set
        best_params = None
        best_train_pf = 0.0

        for params in PARAM_GRID:
            bl, vm, ru, tm, te = params
            tr_result = backtest_momentum_breakout(
                ts[:train_end], o[:train_end], h[:train_end],
                l[:train_end], c[:train_end], v[:train_end],
                trending_regime[:train_end], atr_vals[:train_end],
                breakout_lookback=bl, volume_mult=vm, rsi_upper=ru,
                atr_trail_mult=tm, time_exit_bars=te,
            )
            if tr_result and tr_result["n"] >= 5 and tr_result["pf"] > best_train_pf:
                best_train_pf = tr_result["pf"]
                best_params = params

        if best_params is None:
            # No valid params found, skip this split
            oos_results.append({
                "split": split + 1,
                "test_bars": test_end - test_start,
                "params": None,
                "oos_stats": None,
            })
            continue

        # Test on OOS with best params
        bl, vm, ru, tm, te = best_params
        te_result = backtest_momentum_breakout(
            ts[test_start:test_end], o[test_start:test_end],
            h[test_start:test_end], l[test_start:test_end],
            c[test_start:test_end], v[test_start:test_end],
            trending_regime[test_start:test_end],
            atr_vals[test_start:test_end],
            breakout_lookback=bl, volume_mult=vm, rsi_upper=ru,
            atr_trail_mult=tm, time_exit_bars=te,
        )

        oos_results.append({
            "split": split + 1,
            "test_bars": test_end - test_start,
            "params": {"lookback": bl, "vol_mult": vm, "rsi_max": ru,
                       "trail_mult": tm, "time_exit": te},
            "train_pf": round(best_train_pf, 3),
            "oos_stats": te_result,
        })

    return oos_results


# ---------------------------------------------------------------------------
# Grid definition
# ---------------------------------------------------------------------------

LOOKBACKS = [10, 15, 20, 30]
VOL_MULTS = [1.5, 2.0, 2.5]
RSI_UPPERS = [65, 70, 75]
TRAIL_MULTS = [2.0, 2.5, 3.0, 3.5]
TIME_EXITS = [5, 10, 15, 20]

PARAM_GRID = list(product(LOOKBACKS, VOL_MULTS, RSI_UPPERS, TRAIL_MULTS, TIME_EXITS))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 78)
    print("MOMENTUM BREAKOUT WITH REGIME FILTER — Strategy #3")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 78)
    print(f"Pairs: {', '.join(p[0] for p in PAIRS)}")
    print(f"Grid: {len(PARAM_GRID)} param combos ("
          f"{len(LOOKBACKS)} lookback x {len(VOL_MULTS)} vol x "
          f"{len(RSI_UPPERS)} RSI x {len(TRAIL_MULTS)} trail x "
          f"{len(TIME_EXITS)} time)")
    print(f"Walk-forward: 5 splits, OOS only")
    print(f"Friction: Kraken {KRAKEN_RT_FEE*100:.2f}% round-trip")
    print()

    all_pair_results = {}
    total_oos_pfs = []

    for symbol, interval_min in PAIRS:
        label = symbol.replace("/", "_")
        print(f"\n{'='*78}")
        print(f"PAIR: {symbol} ({interval_min}m)")
        print(f"{'='*78}")

        # Load data
        try:
            df = load_binance(symbol, interval_min)
        except FileNotFoundError:
            print(f"  [SKIP] Data not found for {symbol}")
            continue

        ts, o, h, l, c, v = df_to_arrays(df)
        print(f"  Bars: {len(ts)}  ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

        # Pre-compute indicators
        print("  Computing indicators...")
        atr_vals = ind.atr(h, l, c, period=22)
        trending_regime = build_adx_trend_regime(h, l, c)

        trend_pct = np.sum(trending_regime) / len(trending_regime) * 100
        print(f"  TRENDING regime: {trend_pct:.1f}% of bars (ADX>25 & price>SMA200)")

        # Walk-forward grid search
        t0 = time.time()
        wf_results = walk_forward_5split(ts, o, h, l, c, v, trending_regime, atr_vals)
        elapsed = time.time() - t0

        # Report OOS results
        pair_oos_pfs = []
        print(f"\n  Walk-Forward Results ({elapsed:.1f}s):")
        print(f"  {'Split':>5} {'Look':>4} {'Vol':>4} {'RSI':>4} {'Trail':>5} {'Time':>4} "
              f"{'Tr-PF':>7} {'Te-n':>5} {'Te-PF':>7} {'Te-WR':>6} {'Te-DD':>7} {'Te-p':>7}")
        print(f"  {'-'*5} {'-'*4} {'-'*4} {'-'*4} {'-'*5} {'-'*4} "
              f"{'-'*7} {'-'*5} {'-'*7} {'-'*6} {'-'*7} {'-'*7}")

        for wr in wf_results:
            if wr["params"] is None or wr["oos_stats"] is None:
                print(f"  {wr['split']:>5} {'--- no valid params ---':>40}")
                continue

            p = wr["params"]
            oos = wr["oos_stats"]
            te_pf = oos["pf"] if oos else 0
            te_n = oos["n"] if oos else 0
            te_wr = oos["wr"] if oos else 0
            te_dd = oos["dd"] if oos else 0
            te_p = oos["p"] if oos else 1.0

            if te_n >= 3:
                pair_oos_pfs.append(te_pf)
                total_oos_pfs.append(te_pf)

            star = "*" if (oos and te_p < 0.10) else " "
            print(f"  {wr['split']:>5} {p['lookback']:>4} {p['vol_mult']:>4.1f} "
                  f"{p['rsi_max']:>4.0f} {p['trail_mult']:>5.1f} {p['time_exit']:>4} "
                  f"{wr['train_pf']:>7.2f} {te_n:>5} {te_pf:>7.3f} "
                  f"{te_wr:>6.1%} {te_dd:>7.2%} {te_p:>7.3f}{star}")

        if pair_oos_pfs:
            avg_pf = np.mean(pair_oos_pfs)
            med_pf = np.median(pair_oos_pfs)
            print(f"\n  Avg OOS PF: {avg_pf:.3f}  Median: {med_pf:.3f}  "
                  f"Min: {min(pair_oos_pfs):.3f}  Max: {max(pair_oos_pfs):.3f}")
        else:
            avg_pf = 0.0
            print(f"\n  No valid OOS trades")

        all_pair_results[symbol] = {
            "avg_oos_pf": round(avg_pf, 3) if pair_oos_pfs else 0,
            "median_oos_pf": round(med_pf, 3) if pair_oos_pfs else 0,
            "oos_pfs": [round(x, 3) for x in pair_oos_pfs],
            "splits": wr,
            "wf_results": wf_results,
        }

    # Final summary
    print(f"\n{'='*78}")
    print("FINAL SUMMARY — Momentum Breakout with Regime Filter")
    print(f"{'='*78}")

    print(f"\n  {'Pair':<12} {'Avg OOS PF':>10} {'Median PF':>10} {'Splits':>6} {'Verdict':<20}")
    print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*6} {'-'*20}")

    for symbol, _ in PAIRS:
        if symbol not in all_pair_results:
            continue
        r = all_pair_results[symbol]
        n_splits = len(r["oos_pfs"])
        avg = r["avg_oos_pf"]
        if avg > 2.0:
            verdict = "VALIDATED EDGE"
        elif avg > 1.5:
            verdict = "PROMISING"
        elif avg > 1.0:
            verdict = "MARGINAL"
        else:
            verdict = "NO EDGE"
        print(f"  {symbol:<12} {avg:>10.3f} {r['median_oos_pf']:>10.3f} {n_splits:>6} {verdict:<20}")

    # Global verdict
    if total_oos_pfs:
        global_avg = np.mean(total_oos_pfs)
        global_med = np.median(total_oos_pfs)
        print(f"\n  GLOBAL: Avg OOS PF = {global_avg:.3f}, Median = {global_med:.3f}")

        if global_avg > 2.0:
            print(f"\n  >>> VALIDATED EDGE: Momentum breakout complements MR in TRENDING regime <<<")
            print(f"  >>> Global OOS PF {global_avg:.3f} > 2.0 threshold <<<")
        else:
            print(f"\n  >>> NOT VALIDATED: Global OOS PF {global_avg:.3f} < 2.0 threshold <<<")
            print(f"  >>> Momentum breakout does NOT demonstrate consistent edge <<<")
    else:
        global_avg = 0.0
        global_med = 0.0
        print(f"\n  >>> INSUFFICIENT DATA: No OOS trades generated <<<")

    # Save results
    output_dir = DATA_DIR / "edge_discovery"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "momentum_breakout.json"

    result = {
        "strategy": "momentum_breakout_regime_filter",
        "description": "Momentum Breakout with ADX/SMA200 regime filter for TRENDING conditions",
        "complements": "MR (mean_reversion) which works in RANGING regime",
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "friction_model": f"Kraken {KRAKEN_RT_FEE*100:.2f}% round-trip maker",
        "walk_forward_splits": 5,
        "grid_size": len(PARAM_GRID),
        "global_avg_oos_pf": round(global_avg, 3),
        "global_median_oos_pf": round(global_med, 3),
        "validated": global_avg > 2.0,
        "pairs": all_pair_results,
        "grid_params": {
            "breakout_lookback": LOOKBACKS,
            "volume_mult": VOL_MULTS,
            "rsi_upper": RSI_UPPERS,
            "trail_atr_mult": TRAIL_MULTS,
            "time_exit_bars": TIME_EXITS,
        },
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n  Results saved: {output_path}")


if __name__ == "__main__":
    main()
