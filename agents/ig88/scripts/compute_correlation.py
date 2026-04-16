#!/usr/bin/env python3
"""
Compute pairwise return correlation matrix for 10 ATR BO LONG assets.
- Pearson correlation on hourly returns
- Correlation on daily returns
- Rolling 90-day correlation
- Correlation of ATR BO signals (do assets fire signals at the same time?)
"""

import pandas as pd
import numpy as np
import json
import os
from datetime import datetime

# --- Config ---
DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"
OUTPUT_PATH = "/Users/nesbitt/dev/factory/agents/ig88/data/correlation_matrix.json"
SYMBOLS = ["FIL", "SUI", "AVAX", "NEAR", "RNDR", "WLD", "ETH", "LINK", "SOL", "BTC"]

# ATR Breakout LONG parameters (standard)
ATR_PERIOD = 14
BREAKOUT_PERIOD = 20
ATR_MULTIPLIER = 1.5  # Entry when price > highest_high + ATR * multiplier


def load_ohlcv(symbol):
    """Load OHLCV data for a symbol, trying both filename formats."""
    # Try binance_{SYMBOL}USDT_60m.parquet first
    path = os.path.join(DATA_DIR, f"binance_{symbol}USDT_60m.parquet")
    if not os.path.exists(path):
        # Try with underscore: binance_{SYMBOL}_USDT_60m.parquet
        path = os.path.join(DATA_DIR, f"binance_{symbol}_USDT_60m.parquet")
        if not os.path.exists(path):
            print(f"WARNING: No file found for {symbol}")
            return None
    
    df = pd.read_parquet(path)
    # Ensure datetime index
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
    elif isinstance(df.index, pd.DatetimeIndex):
        # Normalize existing index to UTC
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
    else:
        # Try common column names
        for col in ["date", "datetime", "open_time"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True)
                df = df.set_index(col)
                break
    
    # Standardize column names to lowercase
    df.columns = [c.lower() for c in df.columns]
    
    # Keep only standard OHLCV columns
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    
    print(f"  {symbol}: {len(df)} rows, {df.index.min()} to {df.index.max()}")
    return df


def compute_atr_bo_signals(df):
    """
    Compute ATR Breakout LONG signals.
    Signal = 1 when close > highest_high(BREAKOUT_PERIOD) + ATR * ATR_MULTIPLIER
    This is a channel breakout with ATR filter.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    # ATR (Wilder's method)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1/ATR_PERIOD, min_periods=ATR_PERIOD).mean()
    
    # Highest high over breakout period
    highest_high = high.rolling(BREAKOUT_PERIOD).max()
    
    # Breakout level
    breakout_level = highest_high.shift(1) + atr * ATR_MULTIPLIER
    
    # Signal: close breaks above the level
    signal = (close > breakout_level).astype(int)
    
    return signal


def main():
    print("=" * 60)
    print("ATR BO LONG Correlation Matrix Analysis")
    print("=" * 60)
    
    # --- Load all data ---
    print("\nLoading OHLCV data...")
    data = {}
    for sym in SYMBOLS:
        df = load_ohlcv(sym)
        if df is not None:
            data[sym] = df
    
    loaded_symbols = list(data.keys())
    print(f"\nLoaded {len(loaded_symbols)}/{len(SYMBOLS)} symbols: {loaded_symbols}")
    
    # --- Find overlapping period ---
    starts = [data[s].index.min() for s in loaded_symbols]
    ends = [data[s].index.max() for s in loaded_symbols]
    overlap_start = max(starts)
    overlap_end = min(ends)
    print(f"\nOverlapping period: {overlap_start} to {overlap_end}")
    
    # Trim to overlap
    for sym in loaded_symbols:
        data[sym] = data[sym][(data[sym].index >= overlap_start) & (data[sym].index <= overlap_end)]
        print(f"  {sym} after trim: {len(data[sym])} rows")
    
    # --- Compute hourly returns ---
    print("\nComputing hourly returns...")
    hourly_returns = {}
    for sym in loaded_symbols:
        hourly_returns[sym] = data[sym]["close"].pct_change()
    
    hourly_ret_df = pd.DataFrame(hourly_returns)
    hourly_ret_df = hourly_ret_df.dropna(how="all")
    
    # === (1) Hourly Pearson Correlation ===
    print("\n=== HOURLY RETURN PEARSON CORRELATION ===")
    hourly_corr = hourly_ret_df.corr(method="pearson")
    print(hourly_corr.round(4).to_string())
    
    # --- Compute daily returns ---
    print("\nComputing daily returns...")
    daily_closes = {}
    for sym in loaded_symbols:
        daily = data[sym]["close"].resample("1D").last()
        daily_closes[sym] = daily
    
    daily_close_df = pd.DataFrame(daily_closes)
    daily_ret_df = daily_close_df.pct_change().dropna(how="all")
    
    # === (2) Daily Pearson Correlation ===
    print("\n=== DAILY RETURN PEARSON CORRELATION ===")
    daily_corr = daily_ret_df.corr(method="pearson")
    print(daily_corr.round(4).to_string())
    
    # === (3) Rolling 90-day correlation (on daily returns) ===
    print("\nComputing rolling 90-day correlations (daily returns)...")
    rolling_90d_corr = {}
    pairs = []
    for i, s1 in enumerate(loaded_symbols):
        for j, s2 in enumerate(loaded_symbols):
            if j <= i:
                continue
            pair_name = f"{s1}-{s2}"
            pairs.append(pair_name)
            # Rolling 90-day Pearson correlation
            rolling = daily_ret_df[s1].rolling(90).corr(daily_ret_df[s2])
            rolling_90d_corr[pair_name] = rolling.dropna()
    
    rolling_df = pd.DataFrame(rolling_90d_corr)
    
    # Summary stats for rolling correlations
    print("\nRolling 90-day correlation stats (mean, min, max):")
    rolling_stats = {}
    for pair in pairs:
        if pair in rolling_df.columns:
            vals = rolling_df[pair].dropna()
            if len(vals) > 0:
                stats = {
                    "mean": round(float(vals.mean()), 4),
                    "min": round(float(vals.min()), 4),
                    "max": round(float(vals.max()), 4),
                    "std": round(float(vals.std()), 4),
                    "latest": round(float(vals.iloc[-1]), 4),
                    "n_obs": len(vals)
                }
                rolling_stats[pair] = stats
                print(f"  {pair}: mean={stats['mean']:.4f} min={stats['min']:.4f} max={stats['max']:.4f} latest={stats['latest']:.4f}")
    
    # === (4) ATR BO Signal Correlation ===
    print("\nComputing ATR Breakout signals...")
    signals = {}
    signal_counts = {}
    for sym in loaded_symbols:
        sig = compute_atr_bo_signals(data[sym])
        signals[sym] = sig
        n_signals = int(sig.sum())
        signal_counts[sym] = n_signals
        print(f"  {sym}: {n_signals} signals ({n_signals/len(sig)*100:.1f}% of bars)")
    
    signals_df = pd.DataFrame(signals)
    signals_df = signals_df.reindex(hourly_ret_df.index)
    
    # Binary signal correlation (point-biserial / Pearson on binary)
    print("\n=== ATR BO SIGNAL CORRELATION (binary: 0/1) ===")
    signal_corr = signals_df.corr(method="pearson")
    print(signal_corr.round(4).to_string())
    
    # Signal coincidence analysis
    print("\n=== SIGNAL COINCIDENCE ANALYSIS ===")
    # How often do multiple assets fire on the same bar?
    signals_df_clean = signals_df.dropna()
    if len(signals_df_clean) > 0:
        signals_per_bar = signals_df_clean.sum(axis=1)
        print(f"  Bars with 0 signals: {(signals_per_bar == 0).sum()}")
        print(f"  Bars with 1 signal:  {(signals_per_bar == 1).sum()}")
        print(f"  Bars with 2+ signals: {(signals_per_bar >= 2).sum()}")
        print(f"  Bars with 3+ signals: {(signals_per_bar >= 3).sum()}")
        print(f"  Max simultaneous signals: {int(signals_per_bar.max())}")
        print(f"  Mean signals per bar: {signals_per_bar.mean():.4f}")
    
    # Pairwise signal overlap (Jaccard-like: both fire / either fires)
    print("\nPairwise signal overlap (P(both fire) / P(either fires)):")
    signal_overlap = {}
    for i, s1 in enumerate(loaded_symbols):
        for j, s2 in enumerate(loaded_symbols):
            if j <= i:
                continue
            both = int(((signals_df_clean[s1] == 1) & (signals_df_clean[s2] == 1)).sum())
            either = int(((signals_df_clean[s1] == 1) | (signals_df_clean[s2] == 1)).sum())
            overlap = both / either if either > 0 else 0.0
            pair_key = f"{s1}-{s2}"
            signal_overlap[pair_key] = round(overlap, 4)
            print(f"  {pair_key}: overlap={overlap:.4f} (both={both}, either={either})")
    
    # --- Build output JSON ---
    output = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "symbols": loaded_symbols,
            "overlap_start": str(overlap_start),
            "overlap_end": str(overlap_end),
            "n_hourly_bars": len(hourly_ret_df),
            "n_daily_bars": len(daily_ret_df),
            "atr_params": {
                "atr_period": ATR_PERIOD,
                "breakout_period": BREAKOUT_PERIOD,
                "atr_multiplier": ATR_MULTIPLIER
            }
        },
        "signal_counts": signal_counts,
        "hourly_return_correlation": {
            sym: {sym2: round(float(hourly_corr.loc[sym, sym2]), 6) 
                  for sym2 in loaded_symbols}
            for sym in loaded_symbols
        },
        "daily_return_correlation": {
            sym: {sym2: round(float(daily_corr.loc[sym, sym2]), 6)
                  for sym2 in loaded_symbols}
            for sym in loaded_symbols
        },
        "rolling_90d_correlation_stats": rolling_stats,
        "atr_bo_signal_correlation": {
            sym: {sym2: round(float(signal_corr.loc[sym, sym2]), 6)
                  for sym2 in loaded_symbols}
            for sym in loaded_symbols
        },
        "atr_bo_signal_overlap": signal_overlap,
        "signal_coincidence": {
            "bars_with_0_signals": int((signals_per_bar == 0).sum()) if len(signals_df_clean) > 0 else 0,
            "bars_with_1_signal": int((signals_per_bar == 1).sum()) if len(signals_df_clean) > 0 else 0,
            "bars_with_2plus_signals": int((signals_per_bar >= 2).sum()) if len(signals_df_clean) > 0 else 0,
            "bars_with_3plus_signals": int((signals_per_bar >= 3).sum()) if len(signals_df_clean) > 0 else 0,
            "max_simultaneous": int(signals_per_bar.max()) if len(signals_df_clean) > 0 else 0,
            "mean_per_bar": round(float(signals_per_bar.mean()), 6) if len(signals_df_clean) > 0 else 0,
        }
    }
    
    # --- Save ---
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nResults saved to {OUTPUT_PATH}")
    
    # --- Summary ---
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("\nDaily return correlation highlights:")
    for i, s1 in enumerate(loaded_symbols):
        for j, s2 in enumerate(loaded_symbols):
            if j <= i:
                continue
            val = daily_corr.loc[s1, s2]
            if val > 0.7:
                print(f"  HIGH: {s1}-{s2} = {val:.4f}")
            elif val < 0.3:
                print(f"  LOW:  {s1}-{s2} = {val:.4f}")
    
    print("\nDone!")


if __name__ == "__main__":
    main()
