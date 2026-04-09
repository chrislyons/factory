"""
run_h3_backtest.py — H3: Regime-Based Momentum (Kraken Spot) on real OHLCV data.

Runs both EventDriven and RegimeMomentum strategies on:
  - BTC/USD  (Tier 1 — 2 years daily)
  - ETH/USDT (Tier 1 — 2 years daily)
  - SOL/USDT (Tier 1 — 2 years daily)

Then also runs on 4-hour data for BTC/USD to capture intraday momentum.

Outputs a full BacktestStats report and updates the strategy registry.
"""

from __future__ import annotations

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np

from src.quant.data_fetcher import fetch_and_cache_ohlcv
from src.quant.spot_backtest import EventDrivenBacktester, RegimeMomentumBacktester
from src.quant.backtest_engine import BacktestEngine
from src.quant.regime import RegimeState


def df_to_arrays(df):
    """Convert OHLCV DataFrame to numpy arrays expected by backtester."""
    ts = df.index.astype("int64").values / 1e9  # pandas UTC ns -> epoch seconds
    o  = df["open"].values.astype(float)
    h  = df["high"].values.astype(float)
    l  = df["low"].values.astype(float)
    c  = df["close"].values.astype(float)
    v  = df["volume"].values.astype(float)
    return ts, o, h, l, c, v


def build_regime_series_from_prices(closes: np.ndarray, lookback: int = 20) -> np.ndarray:
    """
    Build a deterministic regime series from price data.
    Uses simple momentum: price above 20-period SMA -> RISK_ON, below -> NEUTRAL.
    This replaces the synthetic random regime generator for backtesting on real data.
    """
    n = len(closes)
    regime = np.full(n, RegimeState.NEUTRAL, dtype=object)

    for i in range(lookback, n):
        sma = np.mean(closes[i - lookback:i])
        if closes[i] > sma * 1.02:   # 2% above SMA -> RISK_ON
            regime[i] = RegimeState.RISK_ON
        elif closes[i] < sma * 0.98:  # 2% below SMA -> RISK_OFF
            regime[i] = RegimeState.RISK_OFF
        else:
            regime[i] = RegimeState.NEUTRAL

    return regime


def run_strategy(name: str, backtester, symbol: str, interval_min: int, bar_hours: float):
    """Fetch data, run backtest, return stats dict."""
    print(f"\n  [{name}] {symbol} {interval_min}m ...")
    df = fetch_and_cache_ohlcv(symbol, interval_min=interval_min)

    ts, o, h, l, c, v = df_to_arrays(df)
    regime = build_regime_series_from_prices(c)

    risk_on_pct = np.sum(regime == RegimeState.RISK_ON) / len(regime) * 100
    print(f"    Bars: {len(ts)}  |  RISK_ON: {risk_on_pct:.1f}%  |  Range: {df.index[0].date()} -> {df.index[-1].date()}")

    trades = backtester.run(
        timestamps=ts,
        opens=o,
        highs=h,
        lows=l,
        closes=c,
        volumes=v,
        pair=symbol,
        regime_states=regime,
    )

    if not trades:
        print(f"    No trades generated")
        return None

    engine = BacktestEngine(initial_capital=backtester.initial_capital)
    engine.add_trades(trades)
    stats = engine.compute_stats(venue="kraken_spot")

    return stats


def print_stats(stats, label: str):
    """Pretty-print BacktestStats."""
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
    print(f"  Geometric PnL:  {s.geometric_return:+.4f}  (positive={s.geometric_positive})")


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
        "avg_win_pct": round(s.avg_win_pct, 4),
        "avg_loss_pct": round(s.avg_loss_pct, 4),
        "expectancy_r": round(s.expectancy_r, 6),
        "p_value": round(s.p_value, 6),
    }


if __name__ == "__main__":
    INITIAL_CAPITAL = 10_000.0

    print("=" * 60)
    print("H3: REGIME MOMENTUM BACKTEST — Real OHLCV Data")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    results = {}

    # -----------------------------------------------------------------------
    # Strategy A: RegimeMomentum on daily data for Tier 1 assets
    # -----------------------------------------------------------------------
    print("\n[ Strategy A: RegimeMomentum — Daily bars ]")

    symbols_daily = [
        ("BTC/USD",  1440),
        ("SOL/USDT", 1440),
    ]

    for symbol, interval in symbols_daily:
        bt = RegimeMomentumBacktester(
            initial_capital=INITIAL_CAPITAL,
            bar_interval_hours=24.0,
        )
        stats = run_strategy("RegimeMomentum", bt, symbol, interval, bar_hours=24.0)
        if stats:
            label = f"RegimeMomentum_{symbol}_daily"
            print_stats(stats, label)
            results[label] = stats_to_dict(stats, label)

    # -----------------------------------------------------------------------
    # Strategy B: RegimeMomentum on 4-hour data for BTC/USD
    # -----------------------------------------------------------------------
    print("\n[ Strategy B: RegimeMomentum — 4h bars (BTC/USD) ]")

    bt_4h = RegimeMomentumBacktester(
        initial_capital=INITIAL_CAPITAL,
        bar_interval_hours=4.0,
    )
    stats_4h = run_strategy("RegimeMomentum_4h", bt_4h, "BTC/USD", 240, bar_hours=4.0)
    if stats_4h:
        label = "RegimeMomentum_BTC_4h"
        print_stats(stats_4h, label)
        results[label] = stats_to_dict(stats_4h, label)

    # -----------------------------------------------------------------------
    # Strategy C: EventDriven on daily data (baseline comparison)
    # -----------------------------------------------------------------------
    print("\n[ Strategy C: EventDriven — Daily bars (BTC/USD baseline) ]")

    bt_evt = EventDrivenBacktester(
        initial_capital=INITIAL_CAPITAL,
        event_hit_rate=0.05,
        event_win_rate=0.55,
        event_avg_gain_pct=2.5,
        event_avg_loss_pct=1.5,
        bar_interval_hours=24.0,
    )
    stats_evt = run_strategy("EventDriven", bt_evt, "BTC/USD", 1440, bar_hours=24.0)
    if stats_evt:
        label = "EventDriven_BTC_daily"
        print_stats(stats_evt, label)
        results[label] = stats_to_dict(stats_evt, label)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("SUMMARY TABLE")
    print("=" * 60)
    print(f"{'Strategy':<35} {'Trades':>7} {'WR':>7} {'PF':>7} {'Sharpe':>8} {'PnL%':>8}")
    print("-" * 60)
    for k, v in results.items():
        short = k[:34]
        pval_star = "*" if v["p_value"] < 0.05 else " "
        print(f"{short:<35} {v['total_trades']:>7} {v['win_rate']:>6.1%} "
              f"{v['profit_factor']:>7.3f} {v['sharpe_ratio']:>8.3f} "
              f"{v['total_pnl_pct']:>+7.2f}%  p={v['p_value']:.3f}{pval_star}")

    # Save results
    out_path = Path("/Users/nesbitt/dev/factory/agents/ig88/data/h3_backtest_results.json")
    with open(out_path, "w") as f:
        json.dump({
            "run_at": datetime.now(timezone.utc).isoformat(),
            "initial_capital": INITIAL_CAPITAL,
            "results": results,
        }, f, indent=2)
    print(f"\nResults saved: {out_path}")

    # H3 verdict
    print("\n" + "=" * 60)
    print("H3 VERDICT")
    print("=" * 60)

    passing = [k for k, v in results.items() if v["profit_factor"] > 1.2]
    failing = [k for k, v in results.items() if v["profit_factor"] <= 1.2]

    if passing:
        print(f"PASS (PF > 1.2): {', '.join(passing)}")
    if failing:
        print(f"FAIL (PF <= 1.2): {', '.join(failing)}")

    if not passing:
        print("\nH3 STATUS: NULL HYPOTHESIS HOLDS — no regime momentum edge detected")
        print("Next step: investigate H3 parameter sensitivity / shorter timeframes")
    else:
        best = max(results.items(), key=lambda x: x[1]["profit_factor"])
        print(f"\nH3 STATUS: EDGE CANDIDATE — best: {best[0]} (PF={best[1]['profit_factor']:.3f})")
        print("Next step: paper trade the passing variants for 30 days")
