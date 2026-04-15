#!/usr/bin/env python3
"""Multi-timeframe Mean Reversion Backtest with Walk-Forward Analysis."""

import json
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────────────────
DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
OUTPUT_PATH = DATA_DIR / "edge_discovery" / "mr_multitimeframe.json"
PAIRS = ["SOLUSDT", "AVAXUSDT", "ETHUSDT", "LINKUSDT", "BTCUSDT"]
TIMEFRAMES = {
    "1h": {"file_suffix": "60m", "resample_from": None},
    "2h": {"file_suffix": "60m", "resample_from": "2h"},
    "4h": {"file_suffix": "240m", "resample_from": None},
    "8h": {"file_suffix": "240m", "resample_from": "8h"},
    "1d": {"file_suffix": "1440m", "resample_from": None},
}
FRICTION = 0.005  # 0.50% round-trip
WALK_FORWARD_SPLITS = 5


# ── Data Loading ───────────────────────────────────────────────────────────────
def load_data(pair: str, tf_config: dict) -> pd.DataFrame:
    """Load OHLCV data from parquet, optionally resample."""
    file_path = DATA_DIR / f"binance_{pair}_{tf_config['file_suffix']}.parquet"
    if not file_path.exists():
        raise FileNotFoundError(f"Data file not found: {file_path}")

    df = pd.read_parquet(file_path)
    # Ensure columns are lowercase
    df.columns = [c.lower() for c in df.columns]

    # Ensure we have a datetime index
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
    elif "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
        df = df.set_index("datetime")

    # Keep only OHLCV
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df = df.sort_index()

    # Resample if needed
    if tf_config["resample_from"]:
        df = df.resample(tf_config["resample_from"]).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })
        df = df.dropna()

    return df


# ── Indicator Calculation ──────────────────────────────────────────────────────
def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_bollinger(series: pd.Series, period: int = 20, num_std: float = 1.0):
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    lower = sma - num_std * std
    upper = sma + num_std * std
    return sma, lower, upper


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close).abs(),
        (low - close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def is_bullish_reversal(df: pd.DataFrame) -> pd.Series:
    """Detect bullish reversal candles: hammer, bullish engulfing, or pin bar."""
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]

    body = (c - o).abs()
    candle_range = h - l
    upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
    lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l

    # Hammer / pin bar: small body, long lower wick, small upper wick
    is_hammer = (
        (body < 0.3 * candle_range) &
        (lower_wick > 2 * body) &
        (upper_wick < 0.3 * candle_range)
    )

    # Bullish engulfing: prev bearish, current bullish and engulfs
    prev_bearish = o.shift(1) > c.shift(1)
    cur_bullish = c > o
    engulfs = (c >= o.shift(1)) & (o <= c.shift(1))
    is_engulfing = prev_bearish & cur_bullish & engulfs

    return is_hammer | is_engulfing


# ── Strategy Signals ───────────────────────────────────────────────────────────
def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all MR signals and indicators."""
    df = df.copy()

    # Indicators
    df["rsi"] = compute_rsi(df["close"], 14)
    df["bb_sma"], df["bb_lower"], df["bb_upper"] = compute_bollinger(df["close"], 20, 1.0)
    df["atr"] = compute_atr(df, 14)
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    df["bullish_reversal"] = is_bullish_reversal(df)

    # Signal conditions
    df["rsi_oversold"] = df["rsi"] < 35
    df["below_bb_lower"] = df["close"] < df["bb_lower"]
    df["vol_spike"] = df["volume"] > 1.2 * df["vol_sma20"]

    # Combined entry signal (T1: on close of signal bar)
    df["entry_signal"] = (
        df["rsi_oversold"] &
        df["below_bb_lower"] &
        df["bullish_reversal"] &
        df["vol_spike"]
    )

    # ATR as percentage of close for adaptive stops
    df["atr_pct"] = df["atr"] / df["close"] * 100

    return df


def get_stop_target(atr_pct: float):
    """Adaptive stops based on ATR% regime."""
    if atr_pct < 2.0:  # LOW volatility
        return 0.015, 0.030
    elif atr_pct < 4.0:  # MID volatility
        return 0.010, 0.075
    else:  # HIGH volatility
        return 0.005, 0.075


# ── Backtest Engine ────────────────────────────────────────────────────────────
def backtest_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Run backtest and return trade log."""
    trades = []
    position = False
    entry_price = 0.0
    entry_idx = 0
    stop_pct = 0.0
    target_pct = 0.0

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]

        # Check if we should enter
        if not position and prev_row["entry_signal"]:
            # Enter at open of next bar (T1)
            entry_price = row["open"]
            entry_idx = i
            atr_pct = prev_row["atr_pct"]
            stop_pct, target_pct = get_stop_target(atr_pct)
            position = True
            continue

        if position:
            # Check stop loss
            stop_hit = row["low"] <= entry_price * (1 - stop_pct)
            # Check target
            target_hit = row["high"] >= entry_price * (1 + target_pct)

            if stop_hit or target_hit:
                # Determine exit price
                if stop_hit and target_hit:
                    # Whichever was hit first (assume stop first for conservatism)
                    exit_price = entry_price * (1 - stop_pct)
                    exit_reason = "stop"
                elif stop_hit:
                    exit_price = entry_price * (1 - stop_pct)
                    exit_reason = "stop"
                else:
                    exit_price = entry_price * (1 + target_pct)
                    exit_reason = "target"

                # Apply friction
                gross_return = (exit_price / entry_price) - 1
                net_return = gross_return - FRICTION

                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return": net_return,
                    "exit_reason": exit_reason,
                    "hold_bars": i - entry_idx,
                    "atr_pct": df.iloc[entry_idx - 1]["atr_pct"] if entry_idx > 0 else 0,
                })

                position = False

            # Max hold timeout: exit after 20 bars if no stop/target
            elif (i - entry_idx) >= 20:
                exit_price = row["close"]
                gross_return = (exit_price / entry_price) - 1
                net_return = gross_return - FRICTION

                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return": net_return,
                    "exit_reason": "timeout",
                    "hold_bars": i - entry_idx,
                    "atr_pct": df.iloc[entry_idx - 1]["atr_pct"] if entry_idx > 0 else 0,
                })
                position = False

    return pd.DataFrame(trades)


# ── Walk-Forward Analysis ─────────────────────────────────────────────────────
def walk_forward_test(df: pd.DataFrame, n_splits: int = 5) -> dict:
    """Run walk-forward OOS testing with n_splits."""
    n = len(df)
    fold_size = n // (n_splits + 1)  # each IS fold is 1 chunk, OOS is next chunk

    oos_results = []

    for split in range(n_splits):
        # In-sample: cumulative from start up to split point
        is_end = fold_size * (split + 1)
        # Out-of-sample: next fold
        oos_start = is_end
        oos_end = min(is_end + fold_size, n)

        if oos_end - oos_start < 50:  # skip tiny folds
            continue

        oos_df = df.iloc[oos_start:oos_end].copy()
        oos_trades = backtest_trades(oos_df)

        if len(oos_trades) > 0:
            wins = (oos_trades["return"] > 0).sum()
            total = len(oos_trades)
            gross_profit = oos_trades.loc[oos_trades["return"] > 0, "return"].sum()
            gross_loss = abs(oos_trades.loc[oos_trades["return"] < 0, "return"].sum())
            pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
            wr = wins / total * 100
        else:
            pf = 0.0
            wr = 0.0
            total = 0

        oos_results.append({
            "split": split + 1,
            "pf": round(pf, 3),
            "wr": round(wr, 1),
            "trades": total,
        })

    # Aggregate OOS
    if oos_results:
        avg_pf = np.mean([r["pf"] for r in oos_results])
        avg_wr = np.mean([r["wr"] for r in oos_results])
        total_trades = sum(r["trades"] for r in oos_results)
    else:
        avg_pf = 0.0
        avg_wr = 0.0
        total_trades = 0

    return {
        "splits": oos_results,
        "avg_pf": round(avg_pf, 3),
        "avg_wr": round(avg_wr, 1),
        "total_oos_trades": total_trades,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    results = {}
    summary_rows = []

    for pair in PAIRS:
        results[pair] = {}

        for tf_name, tf_config in TIMEFRAMES.items():
            print(f"Processing {pair} @ {tf_name}...")

            try:
                df = load_data(pair, tf_config)
            except FileNotFoundError as e:
                print(f"  SKIP: {e}")
                results[pair][tf_name] = {"error": str(e)}
                continue

            # Need enough data
            if len(df) < 200:
                print(f"  SKIP: insufficient data ({len(df)} bars)")
                results[pair][tf_name] = {"error": "insufficient data"}
                continue

            # Compute signals
            df = compute_signals(df)

            # Walk-forward test
            wf = walk_forward_test(df, WALK_FORWARD_SPLITS)

            results[pair][tf_name] = wf

            summary_rows.append({
                "pair": pair,
                "timeframe": tf_name,
                "avg_pf": wf["avg_pf"],
                "avg_wr": wf["avg_wr"],
                "total_oos_trades": wf["total_oos_trades"],
            })

            print(f"  OOS PF={wf['avg_pf']:.3f}  WR={wf['avg_wr']:.1f}%  Trades={wf['total_oos_trades']}")

    # Save results
    output = {
        "strategy": "MR Long Only",
        "params": {
            "rsi_period": 14,
            "rsi_threshold": 35,
            "bb_period": 20,
            "bb_std": 1.0,
            "volume_mult": 1.2,
            "friction": FRICTION,
            "adaptive_stops": {
                "low_atr": {"stop": 1.5, "target": 3.0},
                "mid_atr": {"stop": 1.0, "target": 7.5},
                "high_atr": {"stop": 0.5, "target": 7.5},
            },
            "max_hold_bars": 20,
            "walk_forward_splits": WALK_FORWARD_SPLITS,
        },
        "results": results,
        "timestamp": datetime.utcnow().isoformat(),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to {OUTPUT_PATH}")

    # Print summary table
    print("\n" + "=" * 75)
    print(f"{'PAIR':<12} {'TF':<6} {'OOS PF':>10} {'OOS WR':>10} {'Trades':>10}")
    print("-" * 75)
    for row in sorted(summary_rows, key=lambda x: (-x["avg_pf"], x["pair"])):
        print(f"{row['pair']:<12} {row['timeframe']:<6} {row['avg_pf']:>10.3f} {row['avg_wr']:>9.1f}% {row['total_oos_trades']:>10}")
    print("=" * 75)

    # Find best per pair
    print("\nBest timeframe per pair (by OOS PF):")
    for pair in PAIRS:
        pair_rows = [r for r in summary_rows if r["pair"] == pair]
        if pair_rows:
            best = max(pair_rows, key=lambda x: x["avg_pf"])
            print(f"  {pair}: {best['timeframe']} (PF={best['avg_pf']:.3f}, WR={best['avg_wr']:.1f}%, Trades={best['total_oos_trades']})")


if __name__ == "__main__":
    main()
