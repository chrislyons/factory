"""
run_h2_backtest.py — H2: SOL-PERP Mean Reversion (Jupiter Perps) on real OHLCV data.

Runs PerpsBacktester with RSI + Ichimoku signals on:
  - SOL/USDT 4h data (Jupiter's core timeframe)
  - SOL/USDT 1h data (higher frequency test)

Success metric: Sharpe > 1.5 over the test window.
Failure criterion: Drawdown > 15% of strategy allocation.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np

from src.quant.data_fetcher import fetch_and_cache_ohlcv
from src.quant.perps_backtest import PerpsBacktester
from src.quant.backtest_engine import BacktestEngine
from src.quant.regime import RegimeState


def df_to_arrays(df):
    ts = df.index.astype("int64").values / 1e9
    o  = df["open"].values.astype(float)
    h  = df["high"].values.astype(float)
    l  = df["low"].values.astype(float)
    c  = df["close"].values.astype(float)
    v  = df["volume"].values.astype(float)
    return ts, o, h, l, c, v


def build_regime_from_prices(closes: np.ndarray, lookback: int = 20) -> np.ndarray:
    """Price-derived regime: above SMA = RISK_ON, below = NEUTRAL."""
    n = len(closes)
    regime = np.full(n, RegimeState.NEUTRAL, dtype=object)
    for i in range(lookback, n):
        sma = np.mean(closes[i - lookback:i])
        if closes[i] > sma * 1.02:
            regime[i] = RegimeState.RISK_ON
        elif closes[i] < sma * 0.98:
            regime[i] = RegimeState.RISK_OFF
        else:
            regime[i] = RegimeState.NEUTRAL
    return regime


def print_stats(stats, label: str):
    s = stats
    print(f"\n  --- {label} ---")
    print(f"  Trades:         {s.n_trades}  (W:{s.n_wins} L:{s.n_losses})")
    print(f"  Win rate:       {s.win_rate:.1%}")
    print(f"  Profit factor:  {s.profit_factor:.3f}")
    print(f"  Sharpe:         {s.sharpe_ratio:.3f}")
    print(f"  Max drawdown:   {s.max_drawdown_pct:.1f}%")
    print(f"  Total PnL:      ${s.total_pnl_usd:+,.2f}  ({s.total_pnl_pct:+.2f}%)")
    print(f"  Avg win%:       {s.avg_win_pct:+.3f}%  |  Avg loss%: {s.avg_loss_pct:+.3f}%")
    print(f"  Expectancy/R:   {s.expectancy_r:+.4f}")
    print(f"  p-value:        {s.p_value:.4f}  (t={s.t_statistic:.3f})")


def stats_to_dict(stats, label: str) -> dict:
    s = stats
    return {
        "label": label,
        "total_trades": s.n_trades,
        "win_rate": round(s.win_rate, 4),
        "profit_factor": round(s.profit_factor, 4),
        "sharpe_ratio": round(s.sharpe_ratio, 4),
        "max_drawdown_pct": round(s.max_drawdown_pct, 4),
        "total_pnl_usd": round(s.total_pnl_usd, 4),
        "total_pnl_pct": round(s.total_pnl_pct, 4),
        "expectancy_r": round(s.expectancy_r, 6),
        "p_value": round(s.p_value, 6),
    }


if __name__ == "__main__":
    INITIAL_CAPITAL = 5_000.0

    print("=" * 60)
    print("H2: SOL-PERP MEAN REVERSION BACKTEST — Real OHLCV Data")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    results = {}

    # -----------------------------------------------------------------------
    # Test 1: 4h bars — primary timeframe for perps
    # -----------------------------------------------------------------------
    print("\n[ Test 1: SOL/USDT 4h — primary perps timeframe ]")

    df_4h = fetch_and_cache_ohlcv("SOL/USDT", interval_min=240)
    ts, o, h, l, c, v = df_to_arrays(df_4h)
    regime = build_regime_from_prices(c)
    risk_on_pct = np.sum(regime == RegimeState.RISK_ON) / len(regime) * 100
    print(f"  Bars: {len(ts)}  |  RISK_ON: {risk_on_pct:.1f}%  |  Range: {df_4h.index[0].date()} -> {df_4h.index[-1].date()}")

    bt_4h = PerpsBacktester(
        initial_capital=INITIAL_CAPITAL,
        leverage=3.0,
        bar_interval_hours=4.0,
    )
    trades_4h = bt_4h.run(
        timestamps=ts,
        opens=o,
        highs=h,
        lows=l,
        closes=c,
        volumes=v,
        regime_states=regime,
    )

    if trades_4h:
        engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
        engine.add_trades(trades_4h)
        stats_4h = engine.compute_stats(venue="jupiter_perps")
        label = "PerpsH2_SOL_4h_3x"
        print_stats(stats_4h, label)
        results[label] = stats_to_dict(stats_4h, label)
    else:
        print("  No trades generated on 4h data")

    # -----------------------------------------------------------------------
    # Test 2: Daily bars — trend confirmation
    # -----------------------------------------------------------------------
    print("\n[ Test 2: SOL/USDT daily — trend confirmation ]")

    df_d = fetch_and_cache_ohlcv("SOL/USDT", interval_min=1440)
    ts, o, h, l, c, v = df_to_arrays(df_d)
    regime = build_regime_from_prices(c)
    risk_on_pct = np.sum(regime == RegimeState.RISK_ON) / len(regime) * 100
    print(f"  Bars: {len(ts)}  |  RISK_ON: {risk_on_pct:.1f}%  |  Range: {df_d.index[0].date()} -> {df_d.index[-1].date()}")

    bt_d = PerpsBacktester(
        initial_capital=INITIAL_CAPITAL,
        leverage=3.0,
        bar_interval_hours=24.0,
    )
    trades_d = bt_d.run(
        timestamps=ts,
        opens=o,
        highs=h,
        lows=l,
        closes=c,
        volumes=v,
        regime_states=regime,
    )

    if trades_d:
        engine = BacktestEngine(initial_capital=INITIAL_CAPITAL)
        engine.add_trades(trades_d)
        stats_d = engine.compute_stats(venue="jupiter_perps")
        label = "PerpsH2_SOL_daily_3x"
        print_stats(stats_d, label)
        results[label] = stats_to_dict(stats_d, label)
    else:
        print("  No trades generated on daily data")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("SUMMARY TABLE")
    print("=" * 60)
    print(f"{'Strategy':<30} {'Trades':>7} {'WR':>7} {'PF':>7} {'Sharpe':>8} {'DD%':>6} {'PnL%':>8}")
    print("-" * 60)
    for k, v in results.items():
        short = k[:29]
        pval_star = "*" if v["p_value"] < 0.05 else " "
        print(f"{short:<30} {v['total_trades']:>7} {v['win_rate']:>6.1%} "
              f"{v['profit_factor']:>7.3f} {v['sharpe_ratio']:>8.3f} "
              f"{v['max_drawdown_pct']:>5.1f}% {v['total_pnl_pct']:>+7.2f}%  p={v['p_value']:.3f}{pval_star}")

    # Save
    out_path = Path("/Users/nesbitt/dev/factory/agents/ig88/data/h2_backtest_results.json")
    with open(out_path, "w") as f:
        json.dump({
            "run_at": datetime.now(timezone.utc).isoformat(),
            "initial_capital": INITIAL_CAPITAL,
            "results": results,
        }, f, indent=2)
    print(f"\nResults saved: {out_path}")

    # H2 verdict
    print("\n" + "=" * 60)
    print("H2 VERDICT")
    print("=" * 60)

    success_metric_pass = [k for k, v in results.items() if v["sharpe_ratio"] > 1.5]
    failure_criterion   = [k for k, v in results.items() if v["max_drawdown_pct"] > 15.0]

    if failure_criterion:
        print(f"FAIL (DD > 15%): {', '.join(failure_criterion)}")

    if success_metric_pass:
        print(f"PASS (Sharpe > 1.5): {', '.join(success_metric_pass)}")
        print("\nH2 STATUS: EDGE CANDIDATE — proceed to paper trading")
    else:
        print("\nH2 STATUS: NULL HYPOTHESIS HOLDS — Sharpe < 1.5 across all variants")
        if results:
            best = max(results.items(), key=lambda x: x[1]["sharpe_ratio"])
            print(f"Best variant: {best[0]}  Sharpe={best[1]['sharpe_ratio']:.3f}")
        print("Next step: review signal parameters, try RSI threshold sensitivity")
