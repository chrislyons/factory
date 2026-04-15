#!/usr/bin/env python3
"""
Walk-Forward OOS Validation for Momentum Breakout Strategy
Expanding window, 5 splits, bootstrap CIs, two friction scenarios.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

# ─── Configuration ───────────────────────────────────────────────────────────
DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
OUTPUT_PATH = DATA_DIR / "edge_discovery" / "momentum_oos_validation.json"

PAIRS = {
    "BTC/USDT": DATA_DIR / "binance_BTCUSDT_60m.parquet",
    "ETH/USDT": DATA_DIR / "binance_ETHUSDT_60m.parquet",
    "SOL/USDT": DATA_DIR / "binance_SOLUSDT_60m.parquet",
    "LINK/USDT": DATA_DIR / "binance_LINKUSDT_60m.parquet",
    "AVAX/USDT": DATA_DIR / "binance_AVAXUSDT_60m.parquet",
}

FRICTION = {
    "jupiter_perps": 0.0014,   # 0.14% round-trip
    "kraken_maker": 0.0050,    # 0.50% round-trip
}

# Walk-forward splits (IS%, OOS%)
SPLITS = [
    (0.50, 0.50),
    (0.60, 0.40),
    (0.70, 0.30),
    (0.80, 0.20),
    (0.90, 0.10),
]

N_BOOTSTRAP = 5000
BOOTSTRAP_CI = 0.90
SEED = 42


def resample_to_4h(df_60m: pd.DataFrame) -> pd.DataFrame:
    """Resample 60m OHLCV to 240m (4h)."""
    df = df_60m.copy()
    # Ensure datetime index
    if "timestamp" in df.columns:
        df = df.set_index("timestamp")
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    # Only aggregate columns that exist
    agg = {k: v for k, v in agg.items() if k in df.columns}
    df_4h = df.resample("240min").agg(agg).dropna()
    return df_4h


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all indicators for Momentum Breakout strategy."""
    df = df.copy()

    # HH20: 20-bar highest high
    df["hh20"] = df["high"].rolling(20).max()

    # SMA20 of volume
    df["vol_sma20"] = df["volume"].rolling(20).mean()

    # SMA10 of close (exit signal)
    df["sma10"] = df["close"].rolling(10).mean()

    # ATR14
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14).mean()

    # ADX14
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[(plus_dm < 0) | (plus_dm < minus_dm)] = 0
    minus_dm[(minus_dm < 0) | (minus_dm < plus_dm)] = 0

    atr_smooth = tr.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr_smooth)
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr_smooth)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx14"] = dx.rolling(14).mean()

    return df


def run_backtest(df: pd.DataFrame, friction_pct: float) -> list[dict]:
    """
    Run Momentum Breakout backtest on a dataframe with indicators.
    Returns list of trade dicts.
    """
    trades = []
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    highest_since_entry = 0.0
    trade_returns = []

    for i in range(30, len(df)):  # Skip first 30 bars for indicator warmup
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if not in_position:
            # Entry conditions (using previous bar's signals, execute at current bar's open)
            # Close > HH20 (prev bar's HH20 computed on bars up to prev)
            # Volume > 2.0x SMA20 volume
            # ADX > 30
            hh20_prev = prev.get("hh20", np.nan)
            vol_sma20_prev = prev.get("vol_sma20", np.nan)
            adx14_prev = prev.get("adx14", np.nan)

            if (not np.isnan(hh20_prev) and not np.isnan(vol_sma20_prev)
                    and not np.isnan(adx14_prev)):
                if (prev["close"] > hh20_prev
                        and prev["volume"] > 2.0 * vol_sma20_prev
                        and adx14_prev > 30):
                    # Enter at current bar's open
                    in_position = True
                    entry_price = row["open"]
                    entry_idx = i
                    highest_since_entry = entry_price

        else:
            # Track highest price for trailing stop
            if row["high"] > highest_since_entry:
                highest_since_entry = row["high"]

            # Exit conditions
            sma10 = row.get("sma10", np.nan)
            atr14 = row.get("atr14", np.nan)
            exit_signal = False
            exit_reason = ""

            # Exit 1: Close < SMA10
            if not np.isnan(sma10) and row["close"] < sma10:
                exit_signal = True
                exit_reason = "sma10_cross"

            # Exit 2: Trailing stop at 1.0x ATR below highest
            if not np.isnan(atr14):
                trailing_stop = highest_since_entry - 1.0 * atr14
                if row["low"] <= trailing_stop:
                    exit_signal = True
                    exit_reason = "trailing_stop"

            if exit_signal:
                # Exit at close (or trailing stop level for realism)
                if exit_reason == "trailing_stop":
                    exit_price = max(row["open"], trailing_stop)  # Can't exit below open gap
                else:
                    exit_price = row["close"]

                # Apply friction
                gross_return = (exit_price / entry_price) - 1.0
                net_return = gross_return - friction_pct

                trade = {
                    "entry_bar": entry_idx,
                    "exit_bar": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "gross_return": gross_return,
                    "net_return": net_return,
                    "exit_reason": exit_reason,
                    "bars_held": i - entry_idx,
                }
                trades.append(trade)
                trade_returns.append(net_return)

                in_position = False

    return trades, trade_returns


def compute_metrics(trade_returns: list[float]) -> dict:
    """Compute PF, WR, n_trades, total_return from a list of trade returns."""
    if not trade_returns:
        return {"pf": 0.0, "wr": 0.0, "n_trades": 0, "total_return": 0.0,
                "avg_return": 0.0, "max_dd": 0.0}

    returns = np.array(trade_returns)
    wins = returns[returns > 0]
    losses = returns[returns < 0]

    gross_profit = wins.sum() if len(wins) > 0 else 0.0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)

    wr = len(wins) / len(returns) if len(returns) > 0 else 0.0
    total_return = float(returns.sum())
    avg_return = float(returns.mean())

    # Max drawdown on cumulative equity curve
    equity = np.cumsum(returns)
    running_max = np.maximum.accumulate(equity)
    drawdowns = running_max - equity
    max_dd = float(drawdowns.max()) if len(drawdowns) > 0 else 0.0

    return {
        "pf": round(pf, 4),
        "wr": round(wr, 4),
        "n_trades": len(returns),
        "total_return": round(total_return, 6),
        "avg_return": round(avg_return, 6),
        "max_dd": round(max_dd, 6),
    }


def bootstrap_ci(trade_returns: list[float], n_iter: int = 5000,
                 ci: float = 0.90, seed: int = 42) -> dict:
    """Compute bootstrap CI on profit factor."""
    if len(trade_returns) < 2:
        return {"pf_mean": 0.0, "pf_lower": 0.0, "pf_upper": 0.0,
                "wr_mean": 0.0, "wr_lower": 0.0, "wr_upper": 0.0}

    rng = np.random.RandomState(seed)
    returns = np.array(trade_returns)
    n = len(returns)

    pf_samples = []
    wr_samples = []

    for _ in range(n_iter):
        sample = rng.choice(returns, size=n, replace=True)
        wins = sample[sample > 0]
        losses = sample[sample < 0]
        gp = wins.sum() if len(wins) > 0 else 0.0
        gl = abs(losses.sum()) if len(losses) > 0 else 0.0
        pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)
        pf_samples.append(min(pf, 999.0))  # Cap for stats
        wr_samples.append(len(wins) / n if n > 0 else 0.0)

    pf_arr = np.array(pf_samples)
    wr_arr = np.array(wr_samples)

    alpha = 1 - ci
    lower_q = alpha / 2
    upper_q = 1 - alpha / 2

    return {
        "pf_mean": round(float(pf_arr.mean()), 4),
        "pf_lower": round(float(np.percentile(pf_arr, lower_q * 100)), 4),
        "pf_upper": round(float(np.percentile(pf_arr, upper_q * 100)), 4),
        "wr_mean": round(float(wr_arr.mean()), 4),
        "wr_lower": round(float(np.percentile(wr_arr, lower_q * 100)), 4),
        "wr_upper": round(float(np.percentile(wr_arr, upper_q * 100)), 4),
        "pct_profitable": round(float((pf_arr > 1.0).mean()), 4),
    }


def walk_forward_for_pair(df_4h: pd.DataFrame, friction_pct: float) -> dict:
    """Run expanding-window walk-forward for one pair/friction combo."""
    results = {}
    n_total = len(df_4h)

    for split_name, (is_pct, oos_pct) in zip(
            ["50_50", "60_40", "70_30", "80_20", "90_10"], SPLITS):

        is_end = int(n_total * is_pct)
        is_data = df_4h.iloc[:is_end].copy()
        oos_data = df_4h.iloc[is_end:].copy()

        # Run backtest on IS period (for reference)
        is_trades, is_returns = run_backtest(is_data, friction_pct)
        is_metrics = compute_metrics(is_returns)

        # Run backtest on OOS period
        oos_trades, oos_returns = run_backtest(oos_data, friction_pct)
        oos_metrics = compute_metrics(oos_returns)

        # Bootstrap CI on OOS
        oos_ci = bootstrap_ci(oos_returns, N_BOOTSTRAP, BOOTSTRAP_CI, SEED)

        results[split_name] = {
            "is_bars": len(is_data),
            "oos_bars": len(oos_data),
            "is_metrics": is_metrics,
            "oos_metrics": oos_metrics,
            "oos_bootstrap_ci": oos_ci,
        }

    return results


def aggregate_oos(all_results: dict, friction_name: str) -> dict:
    """Aggregate OOS metrics across all pairs for each split."""
    agg = {}

    for split_name in ["50_50", "60_40", "70_30", "80_20", "90_10"]:
        all_returns = []
        all_trades = []

        for pair_name, pair_results in all_results.items():
            if friction_name in pair_results:
                split_data = pair_results[friction_name].get(split_name, {})
                oos_metrics = split_data.get("oos_metrics", {})
                n = oos_metrics.get("n_trades", 0)
                tr = oos_metrics.get("total_return", 0)
                # Approximate individual returns from aggregate
                if n > 0:
                    avg_ret = tr / n
                    all_returns.extend([avg_ret] * n)
                    all_trades.append(n)

        if all_returns:
            returns = np.array(all_returns)
            wins = returns[returns > 0]
            losses = returns[returns < 0]
            gp = wins.sum() if len(wins) > 0 else 0.0
            gl = abs(losses.sum()) if len(losses) > 0 else 0.0
            pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)
            wr = len(wins) / len(returns) if len(returns) > 0 else 0.0

            agg[split_name] = {
                "aggregate_pf": round(min(pf, 999.0), 4),
                "aggregate_wr": round(wr, 4),
                "total_trades": int(sum(all_trades)),
                "total_return": round(float(returns.sum()), 6),
            }
        else:
            agg[split_name] = {
                "aggregate_pf": 0.0,
                "aggregate_wr": 0.0,
                "total_trades": 0,
                "total_return": 0.0,
            }

    return agg


def main():
    print("=" * 70)
    print("MOMENTUM BREAKOUT - WALK-FORWARD OOS VALIDATION")
    print("=" * 70)
    print(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    all_results = {}

    for pair_name, data_path in PAIRS.items():
        print(f"\n{'─' * 60}")
        print(f"Processing: {pair_name}")
        print(f"{'─' * 60}")

        # Load and resample
        print(f"  Loading {data_path.name}...")
        df_60m = pd.read_parquet(data_path)
        df_4h = resample_to_4h(df_60m)
        print(f"  Resampled: {len(df_4h)} 4h bars "
              f"({df_4h.index[0]} to {df_4h.index[-1]})")

        # Compute indicators on full dataset
        df_4h = compute_indicators(df_4h)

        pair_results = {}

        for friction_name, friction_pct in FRICTION.items():
            print(f"\n  Friction: {friction_name} ({friction_pct*100:.2f}%)")
            wf_results = walk_forward_for_pair(df_4h, friction_pct)
            pair_results[friction_name] = wf_results

            for split_name, split_data in wf_results.items():
                oos = split_data["oos_metrics"]
                ci = split_data["oos_bootstrap_ci"]
                print(f"    {split_name}: OOS PF={oos['pf']:.2f} "
                      f"WR={oos['wr']:.1%} trades={oos['n_trades']} "
                      f"ret={oos['total_return']:.2%} "
                      f"[CI: {ci['pf_lower']:.2f}-{ci['pf_upper']:.2f}]")

        all_results[pair_name] = pair_results

    # Aggregate across pairs
    print(f"\n{'=' * 70}")
    print("AGGREGATE OOS RESULTS")
    print(f"{'=' * 70}")

    aggregated = {}
    for friction_name in FRICTION:
        agg = aggregate_oos(all_results, friction_name)
        aggregated[friction_name] = agg
        print(f"\n  {friction_name}:")
        for split_name, metrics in agg.items():
            print(f"    {split_name}: PF={metrics['aggregate_pf']:.2f} "
                  f"WR={metrics['aggregate_wr']:.1%} "
                  f"trades={metrics['total_trades']} "
                  f"ret={metrics['total_return']:.2%}")

    # Survival analysis
    print(f"\n{'=' * 70}")
    print("EDGE SURVIVAL ANALYSIS")
    print(f"{'=' * 70}")

    survival = {}
    for friction_name, label in [("jupiter_perps", "Jupiter (0.14%)"),
                                  ("kraken_maker", "Kraken (0.50%)")]:
        agg = aggregated[friction_name]
        splits_profitable = sum(1 for s in agg.values() if s["aggregate_pf"] > 1.0)
        total_splits = len(agg)
        avg_pf = np.mean([s["aggregate_pf"] for s in agg.values()])
        all_positive_ci = True

        for pair_name in PAIRS:
            for split_name in agg:
                ci_data = all_results[pair_name][friction_name][split_name]["oos_bootstrap_ci"]
                if ci_data["pf_lower"] <= 1.0:
                    all_positive_ci = False
                    break

        survives = splits_profitable >= 3 and avg_pf > 1.1
        survival[friction_name] = {
            "label": label,
            "splits_profitable": splits_profitable,
            "total_splits": total_splits,
            "avg_pf": round(avg_pf, 4),
            "all_ci_lower_above_1": all_positive_ci,
            "survives": survives,
        }
        status = "YES - EDGE SURVIVES" if survives else "NO - EDGE DOES NOT SURVIVE"
        print(f"\n  {label}: {status}")
        print(f"    Profitable splits: {splits_profitable}/{total_splits}")
        print(f"    Avg PF: {avg_pf:.2f}")
        print(f"    All CIs lower bound > 1.0: {all_positive_ci}")

    # Build final output
    output = {
        "metadata": {
            "strategy": "Momentum Breakout",
            "description": (
                "Entry: Close > HH20 + Volume > 2.0x SMA(20) + ADX(14) > 30. "
                "Exit: Close < SMA(10) OR Trailing Stop at 1.0x ATR(14). T1 entry."
            ),
            "timeframe": "240m (resampled from 60m)",
            "walk_forward_type": "expanding_window",
            "n_splits": len(SPLITS),
            "n_bootstrap": N_BOOTSTRAP,
            "bootstrap_ci": BOOTSTRAP_CI,
            "pairs": list(PAIRS.keys()),
            "generated_at": datetime.now().isoformat(),
        },
        "per_pair_results": {},
        "aggregated_oos": aggregated,
        "survival_analysis": survival,
    }

    # Reformat per-pair results for JSON
    for pair_name, pair_data in all_results.items():
        output["per_pair_results"][pair_name] = {}
        for friction_name, wf_data in pair_data.items():
            output["per_pair_results"][pair_name][friction_name] = {}
            for split_name, split_data in wf_data.items():
                output["per_pair_results"][pair_name][friction_name][split_name] = {
                    "is_bars": split_data["is_bars"],
                    "oos_bars": split_data["oos_bars"],
                    "is_metrics": split_data["is_metrics"],
                    "oos_metrics": split_data["oos_metrics"],
                    "oos_bootstrap_ci": split_data["oos_bootstrap_ci"],
                }

    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n\nResults saved to: {OUTPUT_PATH}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
