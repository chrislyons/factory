"""
run_backtests_expanded.py — H2/H3 backtests on expanded Binance historical data.

Now with sufficient sample sizes to begin statistical inference.
H3 success criterion: PF > 1.2 AND p < 0.10 (one-tailed, direction known)
H2 success criterion: Sharpe > 1.5 AND p < 0.10
"""

from __future__ import annotations

import sys, json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

from src.quant.spot_backtest import RegimeMomentumBacktester
from src.quant.perps_backtest import PerpsBacktester
from src.quant.backtest_engine import BacktestEngine
from src.quant.regime import RegimeState

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")


def load_binance(symbol: str, interval_min: int) -> pd.DataFrame:
    safe = symbol.replace("/", "_")
    p = DATA_DIR / f"binance_{safe}_{interval_min}m.parquet"
    if not p.exists():
        raise FileNotFoundError(f"No data: {p}")
    return pd.read_parquet(p)


def df_to_arrays(df: pd.DataFrame):
    ts = df.index.astype("int64").values / 1e9
    return (ts,
            df["open"].values.astype(float),
            df["high"].values.astype(float),
            df["low"].values.astype(float),
            df["close"].values.astype(float),
            df["volume"].values.astype(float))


def build_regime(closes: np.ndarray, sma_period: int = 20, threshold_pct: float = 2.0) -> np.ndarray:
    """Price-SMA regime proxy. Configurable period and threshold."""
    n = len(closes)
    regime = np.full(n, RegimeState.NEUTRAL, dtype=object)
    t = threshold_pct / 100.0
    for i in range(sma_period, n):
        sma = np.mean(closes[i - sma_period:i])
        if closes[i] > sma * (1 + t):
            regime[i] = RegimeState.RISK_ON
        elif closes[i] < sma * (1 - t):
            regime[i] = RegimeState.RISK_OFF
    return regime


def stats_row(stats, label: str, symbol: str, interval: str) -> dict:
    s = stats
    return {
        "label": label,
        "symbol": symbol,
        "interval": interval,
        "n_trades": s.n_trades,
        "win_rate": round(s.win_rate, 4),
        "profit_factor": round(s.profit_factor, 4),
        "sharpe": round(s.sharpe_ratio, 4),
        "sortino": round(s.sortino_ratio, 4),
        "max_dd_pct": round(s.max_drawdown_pct, 4),
        "total_pnl_pct": round(s.total_pnl_pct, 4),
        "expectancy_r": round(s.expectancy_r, 4),
        "p_value": round(s.p_value, 4),
        "t_stat": round(s.t_statistic, 4),
        "geometric_positive": s.geometric_positive,
    }


def run_h3_case(symbol: str, interval_min: int, bar_hours: float,
                sma_period: int = 20, threshold_pct: float = 2.0,
                capital: float = 10_000.0) -> dict | None:
    try:
        df = load_binance(symbol, interval_min)
    except FileNotFoundError as e:
        print(f"    [skip] {e}")
        return None

    ts, o, h, l, c, v = df_to_arrays(df)
    regime = build_regime(c, sma_period, threshold_pct)
    risk_on_pct = np.sum(regime == RegimeState.RISK_ON) / len(regime) * 100

    bt = RegimeMomentumBacktester(initial_capital=capital, bar_interval_hours=bar_hours)
    trades = bt.run(ts, o, h, l, c, v, pair=symbol, regime_states=regime)

    if not trades:
        print(f"    [0 trades] {symbol} {interval_min}m sma={sma_period} t={threshold_pct}%")
        return None

    engine = BacktestEngine(initial_capital=capital)
    engine.add_trades(trades)
    stats = engine.compute_stats(venue="kraken_spot")

    interval_label = f"{interval_min}m"
    label = f"H3_{symbol.replace('/','')}_{interval_label}_sma{sma_period}_t{threshold_pct}"
    row = stats_row(stats, label, symbol, interval_label)
    row["risk_on_pct"] = round(risk_on_pct, 1)
    row["n_bars"] = len(df)

    return row


def run_h2_case(symbol: str, interval_min: int, bar_hours: float,
                leverage: float = 3.0,
                sma_period: int = 20, threshold_pct: float = 2.0,
                capital: float = 5_000.0) -> dict | None:
    try:
        df = load_binance(symbol, interval_min)
    except FileNotFoundError as e:
        print(f"    [skip] {e}")
        return None

    ts, o, h, l, c, v = df_to_arrays(df)
    regime = build_regime(c, sma_period, threshold_pct)
    risk_on_pct = np.sum(regime == RegimeState.RISK_ON) / len(regime) * 100

    bt = PerpsBacktester(initial_capital=capital, leverage=leverage, bar_interval_hours=bar_hours)
    trades = bt.run(ts, o, h, l, c, v, regime_states=regime)

    if not trades:
        print(f"    [0 trades] {symbol} {interval_min}m sma={sma_period} t={threshold_pct}%")
        return None

    engine = BacktestEngine(initial_capital=capital)
    engine.add_trades(trades)
    stats = engine.compute_stats(venue="jupiter_perps")

    interval_label = f"{interval_min}m"
    label = f"H2_{symbol.replace('/','')}_{interval_label}_{leverage:.0f}x"
    row = stats_row(stats, label, symbol, interval_label)
    row["leverage"] = leverage
    row["risk_on_pct"] = round(risk_on_pct, 1)
    row["n_bars"] = len(df)

    return row


if __name__ == "__main__":
    print("=" * 70)
    print("EXPANDED BACKTESTS — H2 & H3 on Binance historical data")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    h3_results = []
    h2_results = []

    # -----------------------------------------------------------------------
    # H3: Regime Momentum — multiple symbols, intervals, regime thresholds
    # -----------------------------------------------------------------------
    print("\n[ H3: Regime Momentum (Kraken Spot) ]")

    h3_cases = [
        # (symbol, interval_min, bar_hours, sma_period, threshold_pct)
        # BTC daily — 8yr window
        ("BTC/USD",  1440, 24.0, 20, 1.0),
        ("BTC/USD",  1440, 24.0, 20, 2.0),
        ("BTC/USD",  1440, 24.0, 50, 2.0),
        # ETH daily
        ("ETH/USDT", 1440, 24.0, 20, 1.0),
        ("ETH/USDT", 1440, 24.0, 20, 2.0),
        # SOL daily — 5yr window
        ("SOL/USDT", 1440, 24.0, 20, 1.0),
        ("SOL/USDT", 1440, 24.0, 20, 2.0),
        # BTC 4h — 3yr window (6570 bars, expect 100+ trades)
        ("BTC/USD",  240,  4.0,  20, 1.0),
        ("BTC/USD",  240,  4.0,  20, 2.0),
        ("BTC/USD",  240,  4.0,  50, 1.0),
        # SOL 4h
        ("SOL/USDT", 240,  4.0,  20, 1.0),
        ("SOL/USDT", 240,  4.0,  20, 2.0),
        # BTC 1h — 1yr window
        ("BTC/USD",  60,   1.0,  20, 1.0),
        ("BTC/USD",  60,   1.0,  50, 1.0),
        # SOL 1h
        ("SOL/USDT", 60,   1.0,  20, 1.0),
    ]

    for sym, itvl, bh, sma, thr in h3_cases:
        r = run_h3_case(sym, itvl, bh, sma_period=sma, threshold_pct=thr)
        if r:
            h3_results.append(r)
            star = "*" if r["p_value"] < 0.10 else " "
            print(f"  {r['label']:<45} n={r['n_trades']:4d} WR={r['win_rate']:.1%} "
                  f"PF={r['profit_factor']:.3f} Sh={r['sharpe']:+.3f} "
                  f"p={r['p_value']:.3f}{star}")

    # -----------------------------------------------------------------------
    # H2: SOL-PERP Mean Reversion — multiple intervals and leverage
    # -----------------------------------------------------------------------
    print("\n[ H2: SOL-PERP Mean Reversion (Jupiter Perps) ]")

    h2_cases = [
        # (symbol, interval_min, bar_hours, leverage, sma_period, threshold_pct)
        ("SOL/USDT", 1440, 24.0, 3.0, 20, 1.0),
        ("SOL/USDT", 1440, 24.0, 3.0, 20, 2.0),
        ("SOL/USDT", 240,  4.0,  3.0, 20, 1.0),
        ("SOL/USDT", 240,  4.0,  3.0, 20, 2.0),
        ("SOL/USDT", 240,  4.0,  2.0, 20, 1.0),  # lower leverage
        ("SOL/USDT", 60,   1.0,  3.0, 20, 1.0),
        ("SOL/USDT", 60,   1.0,  2.0, 20, 1.0),
        ("BTC/USD",  240,  4.0,  3.0, 20, 1.0),  # BTC as comparison
        ("BTC/USD",  60,   1.0,  3.0, 20, 1.0),
    ]

    for sym, itvl, bh, lev, sma, thr in h2_cases:
        r = run_h2_case(sym, itvl, bh, leverage=lev, sma_period=sma, threshold_pct=thr)
        if r:
            h2_results.append(r)
            star = "*" if r["p_value"] < 0.10 else " "
            fail_dd = " [DD!]" if r["max_dd_pct"] > 15 else ""
            print(f"  {r['label']:<45} n={r['n_trades']:4d} WR={r['win_rate']:.1%} "
                  f"PF={r['profit_factor']:.3f} Sh={r['sharpe']:+.3f} "
                  f"p={r['p_value']:.3f}{star}{fail_dd}")

    # -----------------------------------------------------------------------
    # Summary tables
    # -----------------------------------------------------------------------
    all_results = h3_results + h2_results

    print("\n" + "=" * 70)
    print("STATISTICAL SIGNIFICANCE FILTER (p < 0.10, one-tailed)")
    print("=" * 70)

    significant = [r for r in all_results if r["p_value"] < 0.10]
    if significant:
        print(f"\n{'Label':<45} {'n':>5} {'WR':>6} {'PF':>7} {'Sh':>7} {'PnL%':>7} {'p':>7}")
        print("-" * 70)
        for r in sorted(significant, key=lambda x: x["p_value"]):
            print(f"{r['label']:<45} {r['n_trades']:>5} {r['win_rate']:>5.1%} "
                  f"{r['profit_factor']:>7.3f} {r['sharpe']:>7.3f} "
                  f"{r['total_pnl_pct']:>+6.2f}% {r['p_value']:>7.4f}")
    else:
        print("\n  No strategies reached p < 0.10")

    print("\n" + "=" * 70)
    print("FULL RESULTS — H3 (sorted by profit factor)")
    print("=" * 70)
    print(f"\n{'Label':<45} {'n':>5} {'WR':>6} {'PF':>7} {'Sh':>7} {'DD%':>6} {'p':>7}")
    print("-" * 70)
    for r in sorted(h3_results, key=lambda x: -x["profit_factor"]):
        star = "*" if r["p_value"] < 0.10 else " "
        print(f"{r['label']:<44}{star} {r['n_trades']:>5} {r['win_rate']:>5.1%} "
              f"{r['profit_factor']:>7.3f} {r['sharpe']:>7.3f} "
              f"{r['max_dd_pct']:>5.1f}% {r['p_value']:>7.4f}")

    print(f"\n{'Label':<45} {'n':>5} {'WR':>6} {'PF':>7} {'Sh':>7} {'DD%':>6} {'p':>7}")
    print("--- H2 ---")
    for r in sorted(h2_results, key=lambda x: -x["sharpe"]):
        star = "*" if r["p_value"] < 0.10 else " "
        dd_flag = " !" if r["max_dd_pct"] > 15 else "  "
        print(f"{r['label']:<44}{star} {r['n_trades']:>5} {r['win_rate']:>5.1%} "
              f"{r['profit_factor']:>7.3f} {r['sharpe']:>7.3f} "
              f"{r['max_dd_pct']:>5.1f}%{dd_flag} {r['p_value']:>7.4f}")

    # Save
    out = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "h3": h3_results,
        "h2": h2_results,
        "significant": significant,
    }
    out_path = DATA_DIR / "expanded_backtest_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nFull results saved: {out_path}")

    # Verdict
    print("\n" + "=" * 70)
    print("VERDICTS")
    print("=" * 70)

    h3_pass = [r for r in h3_results if r["profit_factor"] > 1.2 and r["p_value"] < 0.10]
    h2_pass = [r for r in h2_results if r["sharpe"] > 1.5 and r["p_value"] < 0.10 and r["max_dd_pct"] < 15]

    print(f"\nH3: {len(h3_pass)} variant(s) pass (PF>1.2 AND p<0.10)")
    for r in h3_pass:
        print(f"  -> {r['label']}  PF={r['profit_factor']:.3f}  p={r['p_value']:.4f}")

    print(f"\nH2: {len(h2_pass)} variant(s) pass (Sharpe>1.5 AND p<0.10 AND DD<15%)")
    for r in h2_pass:
        print(f"  -> {r['label']}  Sh={r['sharpe']:.3f}  p={r['p_value']:.4f}")

    if not h3_pass and not h2_pass:
        print("\nBoth null hypotheses hold. No statistically significant edge detected.")
        print("Next: investigate signal quality (Ichimoku vs price-SMA regime proxy).")
    else:
        print("\nEdge candidates confirmed. Proceed to paper trading on passing variants.")
