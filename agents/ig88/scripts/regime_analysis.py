#!/usr/bin/env python3
"""
Regime analysis: characterize the profitable vs unprofitable walk-forward windows
for ETHUSDT and SOLUSDT to understand what drives edge.
"""
import pandas as pd
import numpy as np
import os

DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"

def load_60m(sym):
    for prefix in ["binance_", ""]:
        for suffix in [f"{sym}_60m.parquet", f"{sym}_1h.parquet"]:
            path = os.path.join(DATA_DIR, f"{prefix}{suffix}")
            if os.path.exists(path):
                df = pd.read_parquet(path)
                if 'time' in df.columns:
                    df.index = pd.to_datetime(df['time'], unit='s')
                df = df.sort_index()
                if len(df) > 1000:
                    return df
    return None

for sym, splits in [
    ("ETHUSDT", [
        ("2024-10-12", "2025-01-29", 1.62, "OK"),
        ("2025-01-29", "2025-05-19", 9.71, "GREAT"),
        ("2025-05-19", "2025-09-05", 1.63, "OK"),
        ("2025-09-05", "2025-12-24", 1.81, "OK"),
        ("2025-12-24", "2026-04-12", 0.23, "BAD"),
    ]),
    ("SOLUSDT", [
        ("2024-10-12", "2025-01-29", 0.38, "BAD"),
        ("2025-01-29", "2025-05-19", 0.15, "BAD"),
        ("2025-05-19", "2025-09-05", 0.10, "BAD"),
        ("2025-09-05", "2025-12-24", 2.57, "GREAT"),
        ("2025-12-24", "2026-04-12", 2.14, "GREAT"),
    ]),
]:
    df = load_60m(sym)
    if df is None:
        print(f"{sym}: no data")
        continue

    print(f"\n{'='*60}")
    print(f"  {sym} — REGIME ANALYSIS")
    print(f"{'='*60}")

    for start, end, pf, label in splits:
        window = df.loc[start:end]
        if len(window) < 100:
            continue

        close = window['close']
        returns = close.pct_change().dropna()

        # Regime stats
        sma100 = close.rolling(100).mean()
        above_sma = (close > sma100).mean() * 100  # % bars above SMA100

        # Trend: linear regression slope
        x = np.arange(len(close))
        slope = np.polyfit(x, close.values, 1)[0]
        trend_pct = (slope * len(close)) / close.iloc[0] * 100

        # Volatility
        hourly_vol = returns.std() * np.sqrt(8760) * 100  # annualized
        # ATR ratio (vs recent)
        h, l, c = window['high'], window['low'], window['close']
        tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        atr_pct = (atr / close).mean() * 100

        # Ranging vs trending: autocorrelation of returns
        autocorr = returns.autocorr(lag=1) if len(returns) > 2 else 0

        # Max drawdown in window
        peak = close.expanding().max()
        dd = ((close - peak) / peak).min() * 100

        print(f"\n  {start} to {end} — PF={pf:.2f} [{label}]")
        print(f"    Bars: {len(window)}")
        print(f"    Price range: ${close.min():.2f} - ${close.max():.2f}")
        print(f"    Trend: {trend_pct:+.1f}% over window")
        print(f"    % bars above SMA100: {above_sma:.0f}%")
        print(f"    Annualized vol: {hourly_vol:.0f}%")
        print(f"    ATR% (avg): {atr_pct:.2f}%")
        print(f"    Return autocorrelation: {autocorr:.3f}")
        print(f"    Max drawdown: {dd:.1f}%")

print("\n\nKEY INSIGHT:")
print("ATR Breakout needs TRENDING regime with momentum.")
print("Range-bound / choppy regimes destroy the strategy.")
print("Next step: add regime filter to only trade in trending conditions.")
