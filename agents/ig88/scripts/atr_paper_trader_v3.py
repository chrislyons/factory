#!/usr/bin/env python3
"""
ATR Breakout Paper Trading Scanner v3 (Full 8-Asset Portfolio with Regime Filtering)
Backtests on local parquet data, computes Donchian + ATR, SMA100 regime filter,
generates LONG/SHORT signals, manages paper positions with portfolio-level tracking.

v3 changes from v2:
- Expanded to 8-asset portfolio: LONG (ETH, AVAX, SOL, LINK, NEAR, FIL, SUI, WLD)
- Added SHORT sleeve: ETH, LINK, AVAX, SOL, SUI (Variant B)
- SMA100 regime filter for LONG entries (replaces SMA50/SMA200)
- Trailing stop reduced to 1.0% (IG88077 confirmed optimal)
- Portfolio-level equal-weight tracking
- Enhanced logging with per-asset and portfolio metrics
- Reads from local parquet files (backtest mode)

Strategy Parameters (registry v5):
- LONG: lookback=20, atr_period=10, atr_mult=1.5, trail_pct=0.01, hold_hours=96
- SHORT: lookback=10, atr_period=10, atr_mult=2.5, trail_pct=0.025, hold_hours=48
- Entry LONG: close > high.rolling(lookback).max().shift(1)
- Entry SHORT: close < low.rolling(lookback).min().shift(1) - atr * atr_mult
- Friction: 0.0014 (Jupiter perps RT)
- Regime filter: SMA100 on close for LONG only
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

# === CONFIG ===
BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
DATA_DIR = BASE_DIR / "data" / "paper_v5"
OHLCV_DIR = BASE_DIR / "data" / "ohlcv" / "1h"
STATE_FILE = DATA_DIR / "state.json"
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"

# Asset definitions
LONG_ASSETS = ["ETH", "AVAX", "SOL", "LINK", "NEAR", "FIL", "SUI", "WLD"]
SHORT_ASSETS = ["ETH", "LINK", "AVAX", "SOL", "SUI"]
ALL_ASSETS = sorted(set(LONG_ASSETS + SHORT_ASSETS))

# Strategy parameters (from registry v5)
LONG_LOOKBACK = 20
LONG_ATR_PERIOD = 10
LONG_ATR_MULT_STOP = 1.5
LONG_TRAIL_PCT = 0.01
LONG_MAX_HOLD = 96

SHORT_LOOKBACK = 10
SHORT_ATR_PERIOD = 10
SHORT_ATR_MULT_ENTRY = 2.5
SHORT_ATR_MULT_STOP = 1.5
SHORT_TRAIL_PCT = 0.025
SHORT_MAX_HOLD = 48

FRICTION = 0.0014
SMA_REGIME_PERIOD = 100
STARTING_CAPITAL = 100000.0


@dataclass
class Position:
    trade_id: str
    asset: str
    direction: str  # LONG or SHORT
    entry_time: int  # ms timestamp
    entry_price: float
    stop_price: float
    entry_atr: float
    regime: str = "UNKNOWN"
    weight: float = 0.0


@dataclass
class ClosedTrade:
    trade_id: str
    asset: str
    direction: str
    entry_price: float
    exit_price: float
    entry_time: int
    exit_time: int
    pnl_pct: float
    net_pnl_pct: float
    exit_reason: str
    hours_held: float
    entry_regime: str
    exit_regime: str
    weight: float


# === DATA LOADING ===
def load_parquet(asset: str) -> pd.DataFrame:
    """Load 60m parquet data for an asset."""
    paths = [
        OHLCV_DIR / f"binance_{asset}USDT_60m.parquet",
        OHLCV_DIR / f"binance_{asset}_USDT_60m.parquet",
    ]
    for path in paths:
        if path.exists():
            df = pd.read_parquet(path)
            # Handle index - reset if it's a DatetimeIndex
            if isinstance(df.index, pd.DatetimeIndex):
                df = df.reset_index()
            # Find or create datetime column
            if "datetime" in df.columns:
                pass  # Already have it
            elif "timestamp" in df.columns:
                if df["timestamp"].dtype.kind in 'iuf':  # numeric
                    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
                else:
                    df["datetime"] = pd.to_datetime(df["timestamp"])
            elif "time" in df.columns:
                df["datetime"] = pd.to_datetime(df["time"], unit="s")
            else:
                # Try first column
                df["datetime"] = pd.to_datetime(df.iloc[:, 0], unit="s")
            df = df.sort_values("datetime").reset_index(drop=True)
            return df
    raise FileNotFoundError(f"No parquet found for {asset}")


def compute_indicators(df: pd.DataFrame, lookback: int, atr_period: int) -> pd.DataFrame:
    """Compute Donchian channels, ATR, and SMA100 regime filter."""
    df = df.copy()

    df["upper"] = df["high"].rolling(lookback).max()
    df["lower"] = df["low"].rolling(lookback).min()
    df["prev_upper"] = df["upper"].shift(1)
    df["prev_lower"] = df["lower"].shift(1)

    df["prev_close"] = df["close"].shift(1)
    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            abs(df["high"] - df["prev_close"]),
            abs(df["low"] - df["prev_close"])
        )
    )
    df["atr"] = df["tr"].rolling(atr_period).mean()
    df["sma100"] = df["close"].rolling(SMA_REGIME_PERIOD).mean()
    df["regime"] = "UNKNOWN"
    df.loc[df["sma100"].notna() & (df["close"] > df["sma100"]), "regime"] = "BULL"
    df.loc[df["sma100"].notna() & (df["close"] <= df["sma100"]), "regime"] = "BEAR"

    return df


# === VECTORIZED SIGNAL DETECTION ===
def detect_long_signals(df: pd.DataFrame, asset: str) -> pd.DataFrame:
    """Detect all LONG entry signals vectorized."""
    mask = (
        (df["close"] > df["prev_upper"]) &
        (df["regime"] == "BULL") &
        df["prev_upper"].notna() &
        df["atr"].notna() &
        df["sma100"].notna()
    )
    signals = df.loc[mask, ["datetime", "close", "atr", "sma100", "regime"]].copy()
    signals["asset"] = asset
    signals["direction"] = "LONG"
    signals["stop_price"] = signals["close"] - LONG_ATR_MULT_STOP * signals["atr"]
    signals["entry_time_ms"] = signals["datetime"].astype(np.int64) // 1_000_000
    return signals


def detect_short_signals(df: pd.DataFrame, asset: str) -> pd.DataFrame:
    """Detect all SHORT entry signals vectorized."""
    short_trigger = df["prev_lower"] - SHORT_ATR_MULT_ENTRY * df["atr"]
    mask = (
        (df["close"] < short_trigger) &
        df["prev_lower"].notna() &
        df["atr"].notna()
    )
    signals = df.loc[mask, ["datetime", "close", "atr", "regime"]].copy()
    signals["asset"] = asset
    signals["direction"] = "SHORT"
    signals["stop_price"] = signals["close"] + SHORT_ATR_MULT_STOP * signals["atr"]
    signals["entry_time_ms"] = signals["datetime"].astype(np.int64) // 1_000_000
    return signals


# === BACKTEST ENGINE ===
def run_backtest(
    long_data: dict,
    short_data: dict,
    all_closes: dict,
    all_regimes: dict,
) -> tuple:
    """
    Run the backtest processing signals chronologically.
    Returns (closed_trades, portfolio_snapshots).
    """
    # Collect all signals with timestamps
    all_signals = []

    for asset in LONG_ASSETS:
        if asset in long_data and long_data[asset] is not None:
            sigs = detect_long_signals(long_data[asset], asset)
            for _, row in sigs.iterrows():
                all_signals.append({
                    "time": row["entry_time_ms"],
                    "asset": asset,
                    "direction": "LONG",
                    "entry_price": row["close"],
                    "stop_price": row["stop_price"],
                    "atr": row["atr"],
                    "regime": row["regime"],
                    "datetime": row["datetime"],
                })

    for asset in SHORT_ASSETS:
        if asset in short_data and short_data[asset] is not None:
            sigs = detect_short_signals(short_data[asset], asset)
            for _, row in sigs.iterrows():
                all_signals.append({
                    "time": row["entry_time_ms"],
                    "asset": asset,
                    "direction": "SHORT",
                    "entry_price": row["close"],
                    "stop_price": row["stop_price"],
                    "atr": row["atr"],
                    "regime": row["regime"],
                    "datetime": row["datetime"],
                })

    # Sort signals by time
    all_signals.sort(key=lambda x: x["time"])
    print(f"Total signals detected: {len(all_signals)}")

    # Build close price lookup: {(asset, time_ms): close}
    # Also build sorted time arrays for each asset
    price_lookup = {}
    time_arrays = {}
    regime_arrays = {}

    for asset in ALL_ASSETS:
        df = long_data.get(asset)
        if df is None:
            df = short_data.get(asset)
        if df is None or len(df) == 0:
            continue
        times_ms = df["datetime"].astype(np.int64) // 1_000_000
        closes = df["close"].values
        regimes = df["regime"].values
        time_arrays[asset] = times_ms.values
        regime_arrays[asset] = regimes
        for t, c in zip(times_ms.values, closes):
            price_lookup[(asset, t)] = c

    # Process signals chronologically
    open_positions: list[Position] = []
    closed_trades: list[ClosedTrade] = []
    trade_counter = 0
    portfolio_snapshots = []

    # Track last snapshot time
    last_snapshot_time = 0
    snapshot_interval = 24 * 3600 * 1000  # 24 hours in ms

    for sig in all_signals:
        sig_time = sig["time"]
        sig_asset = sig["asset"]
        sig_dir = sig["direction"]

        # --- Check exits for all open positions up to this signal time ---
        still_open = []
        for pos in open_positions:
            pos_asset = pos.asset
            pos_dir = pos.direction
            trail_pct = LONG_TRAIL_PCT if pos_dir == "LONG" else SHORT_TRAIL_PCT
            max_hold_ms = (LONG_MAX_HOLD if pos_dir == "LONG" else SHORT_MAX_HOLD) * 3600 * 1000

            # Find current price at signal time
            times = time_arrays.get(pos_asset)
            if times is None:
                still_open.append(pos)
                continue

            # Find the bar at or just before sig_time
            idx = np.searchsorted(times, sig_time, side="right") - 1
            if idx < 0:
                still_open.append(pos)
                continue

            current_price = price_lookup.get((pos_asset, times[idx]))
            if current_price is None:
                still_open.append(pos)
                continue

            # Update trailing stop
            if pos_dir == "LONG":
                new_trail = current_price * (1 - trail_pct)
                pos.stop_price = max(pos.stop_price, new_trail)
                stop_hit = current_price <= pos.stop_price
            else:
                new_trail = current_price * (1 + trail_pct)
                pos.stop_price = min(pos.stop_price, new_trail)
                stop_hit = current_price >= pos.stop_price

            hours_held = (sig_time - pos.entry_time) / (3600 * 1000)
            time_exit = (sig_time - pos.entry_time) >= max_hold_ms

            if stop_hit or time_exit:
                exit_price = pos.stop_price if stop_hit else current_price
                if pos_dir == "LONG":
                    pnl_pct = (exit_price - pos.entry_price) / pos.entry_price
                else:
                    pnl_pct = (pos.entry_price - exit_price) / pos.entry_price

                net_pnl = pnl_pct - FRICTION
                exit_regime_idx = min(idx, len(regime_arrays.get(pos_asset, [])) - 1)
                exit_regime = regime_arrays.get(pos_asset, ["UNKNOWN"])[exit_regime_idx] if pos_asset in regime_arrays else "UNKNOWN"

                # Calculate weight at time of exit (equal weight among open positions at entry)
                n_open_at_entry = sum(1 for p in open_positions if p.entry_time <= pos.entry_time)
                pos_weight = 1.0 / max(n_open_at_entry, 1)

                trade = ClosedTrade(
                    trade_id=pos.trade_id,
                    asset=pos.asset,
                    direction=pos_dir,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    entry_time=pos.entry_time,
                    exit_time=int(times[idx]),
                    pnl_pct=round(pnl_pct, 6),
                    net_pnl_pct=round(net_pnl, 6),
                    exit_reason="stop" if stop_hit else "time",
                    hours_held=round(hours_held, 2),
                    entry_regime=pos.regime,
                    exit_regime=str(exit_regime),
                    weight=pos.weight if pos.weight > 0 else pos_weight,
                )
                closed_trades.append(trade)
            else:
                still_open.append(pos)

        # Re-weight remaining positions after exits
        if still_open:
            w = 1.0 / len(still_open)
            for p in still_open:
                p.weight = w
        open_positions = still_open

        # --- Check if we can enter this signal ---
        existing_same = [p for p in open_positions if p.asset == sig_asset and p.direction == sig_dir]
        if not existing_same:
            trade_counter += 1
            prefix = "L" if sig_dir == "LONG" else "S"
            trade_id = f"{prefix}{trade_counter:06d}"

            # Equal weight: 1 / (number of open positions + 1)
            n_after_entry = len(open_positions) + 1
            entry_weight = 1.0 / n_after_entry

            # Re-weight existing positions
            for p in open_positions:
                p.weight = entry_weight

            pos = Position(
                trade_id=trade_id,
                asset=sig_asset,
                direction=sig_dir,
                entry_time=sig["time"],
                entry_price=sig["entry_price"],
                stop_price=sig["stop_price"],
                entry_atr=sig["atr"],
                regime=sig["regime"],
                weight=entry_weight,
            )
            open_positions.append(pos)

        # --- Portfolio snapshot every 24h ---
        if sig_time - last_snapshot_time >= snapshot_interval:
            n = len(open_positions)
            if n > 0:
                weight = 1.0 / n
                for p in open_positions:
                    p.weight = weight

            unrealized = 0.0
            for p in open_positions:
                times = time_arrays.get(p.asset)
                if times is None:
                    continue
                idx = np.searchsorted(times, sig_time, side="right") - 1
                if idx < 0:
                    continue
                curr_price = price_lookup.get((p.asset, times[idx]))
                if curr_price is None:
                    continue
                if p.direction == "LONG":
                    unrealized += (curr_price - p.entry_price) / p.entry_price * p.weight
                else:
                    unrealized += (p.entry_price - curr_price) / p.entry_price * p.weight

            realized = sum(t.net_pnl_pct * t.weight for t in closed_trades)
            total_pnl = realized + unrealized
            equity = STARTING_CAPITAL * (1 + total_pnl)

            portfolio_snapshots.append({
                "time_ms": sig_time,
                "equity": round(equity, 2),
                "realized_pnl_pct": round(realized * 100, 4),
                "unrealized_pnl_pct": round(unrealized * 100, 4),
                "total_pnl_pct": round(total_pnl * 100, 4),
                "num_open": len(open_positions),
                "num_closed": len(closed_trades),
                "num_long": sum(1 for p in open_positions if p.direction == "LONG"),
                "num_short": sum(1 for p in open_positions if p.direction == "SHORT"),
            })
            last_snapshot_time = sig_time

    # Close remaining positions at last available price
    if open_positions:
        # Find the minimum common last time across all assets
        last_times = []
        for asset in set(p.asset for p in open_positions):
            if asset in time_arrays and len(time_arrays[asset]) > 0:
                last_times.append(time_arrays[asset][-1])
        if last_times:
            final_time = min(last_times)
            still_open_final = []
            for pos in open_positions:
                times = time_arrays.get(pos.asset)
                if times is None:
                    still_open_final.append(pos)
                    continue
                idx = np.searchsorted(times, final_time, side="right") - 1
                if idx < 0:
                    still_open_final.append(pos)
                    continue
                current_price = price_lookup.get((pos.asset, times[idx]))
                if current_price is None:
                    still_open_final.append(pos)
                    continue

                trail_pct = LONG_TRAIL_PCT if pos.direction == "LONG" else SHORT_TRAIL_PCT
                if pos.direction == "LONG":
                    new_trail = current_price * (1 - trail_pct)
                    pos.stop_price = max(pos.stop_price, new_trail)
                    pnl_pct = (current_price - pos.entry_price) / pos.entry_price
                else:
                    new_trail = current_price * (1 + trail_pct)
                    pos.stop_price = min(pos.stop_price, new_trail)
                    pnl_pct = (pos.entry_price - current_price) / pos.entry_price

                net_pnl = pnl_pct - FRICTION
                hours_held = (final_time - pos.entry_time) / (3600 * 1000)

                trade = ClosedTrade(
                    trade_id=pos.trade_id,
                    asset=pos.asset,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    exit_price=current_price,
                    entry_time=pos.entry_time,
                    exit_time=int(final_time),
                    pnl_pct=round(pnl_pct, 6),
                    net_pnl_pct=round(net_pnl, 6),
                    exit_reason="end_of_data",
                    hours_held=round(hours_held, 2),
                    entry_regime=pos.regime,
                    exit_regime="N/A",
                    weight=pos.weight if pos.weight > 0 else 1.0 / max(len(open_positions), 1),
                )
                closed_trades.append(trade)
            open_positions = still_open_final

    return closed_trades, portfolio_snapshots, open_positions


# === REGIME SUMMARY ===
def print_regime_summary(long_data: dict, short_data: dict):
    """Print current regime for each asset."""
    print("\n--- REGIME STATUS (SMA100) ---")
    for asset in ALL_ASSETS:
        df = long_data.get(asset)
        if df is None:
            df = short_data.get(asset)
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            regime = latest.get("regime", "UNKNOWN")
            sma100 = latest.get("sma100", np.nan)
            close = latest["close"]
            above = "ABOVE" if not np.isnan(sma100) and close > sma100 else "BELOW"
            sleeves = []
            if asset in LONG_ASSETS:
                sleeves.append("L")
            if asset in SHORT_ASSETS:
                sleeves.append("S")
            sma_str = f"{sma100:.4f}" if not np.isnan(sma100) else "N/A"
            print(f"  {asset:5s}: {regime:8s} | close {above:5s} SMA100 ({sma_str}) | [{','.join(sleeves)}]")
    print()


# === MAIN ===
def main():
    print(f"=== ATR Paper Trader v3 (8-Asset Portfolio) | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")
    print(f"LONG assets:  {', '.join(LONG_ASSETS)}")
    print(f"SHORT assets: {', '.join(SHORT_ASSETS)}")
    print(f"Regime filter: SMA{SMA_REGIME_PERIOD} (LONG only)")
    print(f"Trail stops: LONG={LONG_TRAIL_PCT*100:.1f}% | SHORT={SHORT_TRAIL_PCT*100:.1f}%")
    print(f"Friction: {FRICTION*100:.2f}% RT")
    print(f"Output: {DATA_DIR}")
    print()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load data and compute indicators
    long_data = {}
    short_data = {}
    all_closes = {}
    all_regimes = {}

    for asset in ALL_ASSETS:
        try:
            df = load_parquet(asset)
            print(f"  Loaded {asset}: {len(df)} bars ({df['datetime'].min()} to {df['datetime'].max()})")

            if asset in LONG_ASSETS:
                long_data[asset] = compute_indicators(df, LONG_LOOKBACK, LONG_ATR_PERIOD)
                all_closes[asset] = long_data[asset]["close"].values
                all_regimes[asset] = long_data[asset]["regime"].values
            if asset in SHORT_ASSETS:
                short_data[asset] = compute_indicators(df, SHORT_LOOKBACK, SHORT_ATR_PERIOD)
                if asset not in all_closes:
                    all_closes[asset] = short_data[asset]["close"].values
                    all_regimes[asset] = short_data[asset]["regime"].values
        except Exception as e:
            print(f"  ERROR loading {asset}: {e}")

    # Regime summary
    print_regime_summary(long_data, short_data)

    # Run backtest
    print("--- RUNNING BACKTEST ---\n")
    closed_trades, snapshots, open_positions = run_backtest(
        long_data, short_data, all_closes, all_regimes
    )

    # === RESULTS ===
    print("\n" + "=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)

    print(f"\nOPEN POSITIONS: {len(open_positions)}")
    if not open_positions:
        print("  (none)")
    else:
        for p in open_positions:
            print(f"  {p.direction:5s} {p.asset:5s} | Entry: {p.entry_price:.4f} | Stop: {p.stop_price:.4f}")

    print(f"\nCLOSED TRADES: {len(closed_trades)}")
    if closed_trades:
        long_trades = [t for t in closed_trades if t.direction == "LONG"]
        short_trades = [t for t in closed_trades if t.direction == "SHORT"]

        def trade_stats(trades, label):
            if not trades:
                return
            pnls = [t.net_pnl_pct for t in trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            total = sum(pnls)
            wr = len(wins) / len(trades) * 100 if trades else 0
            avg_win = sum(wins) / len(wins) if wins else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) < 0 else float('inf')
            print(f"\n  {label}:")
            print(f"    Count: {len(trades)} | Win Rate: {wr:.1f}%")
            print(f"    Total PnL: {total*100:+.2f}%")
            print(f"    Avg Win: {avg_win*100:+.2f}% | Avg Loss: {avg_loss*100:+.2f}%")
            print(f"    Profit Factor: {pf:.2f}")

        trade_stats(long_trades, "LONG")
        trade_stats(short_trades, "SHORT")

        # Per-asset breakdown
        print("\n  PER-ASSET BREAKDOWN:")
        for asset in ALL_ASSETS:
            asset_trades = [t for t in closed_trades if t.asset == asset]
            if asset_trades:
                pnls = [t.net_pnl_pct for t in asset_trades]
                total = sum(pnls)
                wins = sum(1 for p in pnls if p > 0)
                print(f"    {asset:5s}: {len(asset_trades):3d} trades | "
                      f"PnL: {total*100:+.2f}% | WR: {wins/len(asset_trades)*100:.0f}%")

    # Final portfolio metrics
    if closed_trades:
        # Calculate weighted portfolio return
        # Each trade contributes its net_pnl * weight to the portfolio
        # Since weights can change during the trade (rebalancing), we use the weight at exit
        total_weighted_pnl = sum(t.net_pnl_pct * t.weight for t in closed_trades)
        # Simple average for comparison
        avg_pnl = sum(t.net_pnl_pct for t in closed_trades) / len(closed_trades)
        equity = STARTING_CAPITAL * (1 + total_weighted_pnl)
        print(f"\nPORTFOLIO METRICS:")
        print(f"  Starting Capital: ${STARTING_CAPITAL:,.2f}")
        print(f"  Final Equity: ${equity:,.2f}")
        print(f"  Weighted Portfolio Return: {total_weighted_pnl*100:+.2f}%")
        print(f"  Average Trade PnL: {avg_pnl*100:+.2f}%")
        print(f"  Snapshots: {len(snapshots)}")

    # Save results
    trades_file = DATA_DIR / "closed_trades.jsonl"
    with open(trades_file, "w") as f:
        for t in closed_trades:
            f.write(json.dumps(asdict(t)) + "\n")
    print(f"\nTrades saved to {trades_file}")

    state = {
        "closed_trades": [asdict(t) for t in closed_trades],
        "open_positions": [asdict(p) for p in open_positions],
        "portfolio_snapshots": snapshots,
        "config": {
            "long_assets": LONG_ASSETS,
            "short_assets": SHORT_ASSETS,
            "long_lookback": LONG_LOOKBACK,
            "short_lookback": SHORT_LOOKBACK,
            "long_trail_pct": LONG_TRAIL_PCT,
            "short_trail_pct": SHORT_TRAIL_PCT,
            "sma_regime_period": SMA_REGIME_PERIOD,
            "friction": FRICTION,
        }
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)
    print(f"State saved to {STATE_FILE}")


if __name__ == "__main__":
    main()
