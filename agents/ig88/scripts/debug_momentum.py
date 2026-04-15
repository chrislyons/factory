#!/usr/bin/env python3
"""Debug momentum breakout entry conditions."""

import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")

# Load BTC
df = pd.read_parquet(DATA_DIR / "binance_BTCUSDT_60m.parquet")
if "timestamp" in df.columns:
    df = df.set_index("timestamp")
df_4h = df.resample("240min").agg({
    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
}).dropna()

print(f"4h bars: {len(df_4h)}")
print(f"Columns: {df_4h.columns.tolist()}")
print(f"Date range: {df_4h.index[0]} to {df_4h.index[-1]}")

# Compute indicators
df = df_4h.copy()
df["hh20"] = df["high"].rolling(20).max()
df["vol_sma20"] = df["volume"].rolling(20).mean()
df["vol_ratio"] = df["volume"] / df["vol_sma20"]
df["sma10"] = df["close"].rolling(10).mean()

# ATR14
high, low, close = df["high"], df["low"], df["close"]
prev_close = close.shift(1)
tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
df["atr14"] = tr.rolling(14).mean()

# ADX14
plus_dm = high.diff()
minus_dm = -low.diff()
plus_dm_orig = plus_dm.copy()
minus_dm_orig = minus_dm.copy()
plus_dm[(plus_dm < 0) | (plus_dm < minus_dm)] = 0
minus_dm[(minus_dm < 0) | (minus_dm < plus_dm)] = 0
atr_smooth = tr.rolling(14).mean()
plus_di = 100 * (plus_dm.rolling(14).mean() / atr_smooth)
minus_di = 100 * (minus_dm.rolling(14).mean() / atr_smooth)
dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
df["adx14"] = dx.rolling(14).mean()
df["plus_di"] = plus_di
df["minus_di"] = minus_di

# Check entry conditions on each bar (bar i uses bar i's indicators)
df["close_gt_hh20"] = df["close"] > df["hh20"]
df["vol_gt_2x"] = df["volume"] > 2.0 * df["vol_sma20"]
df["adx_gt_30"] = df["adx14"] > 30
df["entry_signal"] = df["close_gt_hh20"] & df["vol_gt_2x"] & df["adx_gt_30"]

# Stats
print(f"\nIndicator stats (last 500 bars):")
subset = df.iloc[-5000:]
print(f"  close > HH20: {subset['close_gt_hh20'].sum()} / {len(subset)} ({subset['close_gt_hh20'].mean():.1%})")
print(f"  volume > 2x SMA20: {subset['vol_gt_2x'].sum()} / {len(subset)} ({subset['vol_gt_2x'].mean():.1%})")
print(f"  ADX > 30: {subset['adx_gt_30'].sum()} / {len(subset)} ({subset['adx_gt_30'].mean():.1%})")
print(f"  All 3 combined: {subset['entry_signal'].sum()} / {len(subset)} ({subset['entry_signal'].mean():.1%})")

# Show some entry signal bars
entries = df[df["entry_signal"]].copy()
print(f"\nTotal entry signals across full dataset: {len(entries)}")
if len(entries) > 0:
    print("\nSample entries:")
    for idx, row in entries.head(20).iterrows():
        print(f"  {idx}: close={row['close']:.2f} HH20={row['hh20']:.2f} "
              f"vol_ratio={row['vol_ratio']:.2f} ADX={row['adx14']:.1f}")

# Check individual conditions breakdown
print(f"\nCondition breakdown (full dataset):")
print(f"  close > HH20: {df['close_gt_hh20'].sum()} ({df['close_gt_hh20'].mean():.2%})")
print(f"  vol > 2x: {df['vol_gt_2x'].sum()} ({df['vol_gt_2x'].mean():.2%})")
print(f"  ADX > 30: {df['adx_gt_30'].sum()} ({df['adx_gt_30'].mean():.2%})")
print(f"  Combined: {df['entry_signal'].sum()} ({df['entry_signal'].mean():.2%})")

# Maybe the issue is using prev bar - let's check if prev bar condition also triggers
# The issue: we check prev bar's close > prev bar's hh20
# But HH20 at bar i uses bars [i-19, i] including bar i itself
# So close > HH20 is very rare since HH20 includes current high

# Let's check: close > prev bar's HH20 (shifted)
df["prev_hh20"] = df["hh20"].shift(1)
df["close_gt_prev_hh20"] = df["close"] > df["prev_hh20"]
print(f"\nUsing prev bar's HH20 (shifted):")
print(f"  close > prev_HH20: {df['close_gt_prev_hh20'].sum()} ({df['close_gt_prev_hh20'].mean():.2%})")

df["prev_vol_sma20"] = df["vol_sma20"].shift(1)
df["prev_adx14"] = df["adx14"].shift(1)
df["prev_vol_ratio"] = df["vol_ratio"].shift(1)
df["entry_signal_prev"] = df["close_gt_prev_hh20"] & (df["volume"] > 2.0 * df["prev_vol_sma20"]) & (df["prev_adx14"] > 30)
print(f"  Combined (using prev bar signals): {df['entry_signal_prev'].sum()} ({df['entry_signal_prev'].mean():.2%})")

entries_prev = df[df["entry_signal_prev"]]
print(f"\nTotal prev-bar entry signals: {len(entries_prev)}")
if len(entries_prev) > 0:
    print("\nSample prev-bar entries:")
    for idx, row in entries_prev.head(20).iterrows():
        print(f"  {idx}: close={row['close']:.2f} prev_HH20={row['prev_hh20']:.2f} "
              f"prev_vol_ratio={row['prev_vol_ratio']:.2f} prev_ADX={row['prev_adx14']:.1f}")

# Also check ADX distribution
print(f"\nADX distribution:")
print(f"  ADX > 20: {(df['adx14'] > 20).sum()} ({(df['adx14'] > 20).mean():.2%})")
print(f"  ADX > 25: {(df['adx14'] > 25).sum()} ({(df['adx14'] > 25).mean():.2%})")
print(f"  ADX > 30: {(df['adx14'] > 30).sum()} ({(df['adx14'] > 30).mean():.2%})")
print(f"  ADX > 35: {(df['adx14'] > 35).sum()} ({(df['adx14'] > 35).mean():.2%})")
print(f"  ADX mean: {df['adx14'].mean():.1f}, median: {df['adx14'].median():.1f}")
print(f"  ADX min: {df['adx14'].min():.1f}, max: {df['adx14'].max():.1f}")
