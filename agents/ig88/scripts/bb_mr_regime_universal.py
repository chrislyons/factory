#!/usr/bin/env python3
"""
BB Mean Reversion — Regime Universality Test
Does BB MR work outside CHOP? Or is it CHOP-only?
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
BB_PERIOD = 20
BB_STD = 2.0
MR_MAX_HOLD = 48
FRICTION = 0.0014


def load_pair(pair):
    for pat in [f"binance_{pair}_60m.parquet", f"binance_{pair}_1h.parquet"]:
        f = DATA_DIR / pat
        if f.exists():
            df = pd.read_parquet(f)
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df = df.set_index('time').sort_index()
                return df
    return None


def classify_regimes(btc_df):
    c = btc_df['close'].values
    sma50 = pd.Series(c).rolling(50).mean().values
    sma200 = pd.Series(c).rolling(200).mean().values
    regimes = pd.Series("UNKNOWN", index=btc_df.index)
    for i in range(200, len(c)):
        if c[i] > sma50[i] > sma200[i]:
            regimes.iloc[i] = "BULL"
        elif c[i] < sma50[i] < sma200[i]:
            regimes.iloc[i] = "BEAR"
        else:
            regimes.iloc[i] = "CHOP"
    return regimes


def run_bb_mr(df, regime_series, start_bar=0, end_bar=None, direction="long"):
    c, h, l = df['close'].values, df['high'].values, df['low'].values
    sma = pd.Series(c).rolling(BB_PERIOD).mean().values
    std = pd.Series(c).rolling(BB_PERIOD).std().values
    lower_bb = sma - BB_STD * std
    upper_bb = sma + BB_STD * std
    if end_bar is None:
        end_bar = len(c)

    trades, in_trade = [], False
    entry_price = entry_bar = 0
    entry_regime = ""
    for i in range(BB_PERIOD + 1, len(c)):
        if i < start_bar or i >= end_bar:
            continue
        regime = regime_series.iloc[i] if i < len(regime_series) else "UNKNOWN"
        if regime not in ["BULL", "BEAR", "CHOP"]:
            continue

        if in_trade:
            hours = i - entry_bar
            if direction == "long":
                if c[i] >= sma[i] or hours >= MR_MAX_HOLD:
                    exit_p = max(sma[i], c[i])
                    if c[i] >= upper_bb[i]:
                        exit_p = upper_bb[i]
                    pnl = (exit_p - entry_price) / entry_price - FRICTION
                    trades.append({"pnl": pnl, "regime": entry_regime})
                    in_trade = False
            else:
                if c[i] <= sma[i] or hours >= MR_MAX_HOLD:
                    exit_p = min(sma[i], c[i])
                    if c[i] <= lower_bb[i]:
                        exit_p = lower_bb[i]
                    pnl = (entry_price - exit_p) / entry_price - FRICTION
                    trades.append({"pnl": pnl, "regime": entry_regime})
                    in_trade = False

        if not in_trade:
            if direction == "long" and l[i] <= lower_bb[i]:
                in_trade = True
                entry_price = lower_bb[i]
                entry_bar = i
                entry_regime = regime
            elif direction == "short" and h[i] >= upper_bb[i]:
                in_trade = True
                entry_price = upper_bb[i]
                entry_bar = i
                entry_regime = regime

    return trades


def analyze_by_regime(trades, label):
    if not trades:
        return
    pnls = [t['pnl'] for t in trades]
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else float('inf')
    wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
    avg = np.mean(pnls) * 100
    print(f"  {label:20s} n={len(trades):4d}  PF={pf:5.2f}  WR={wr:5.1f}%  Avg={avg:+.2f}%")


# === MAIN ===
print("=" * 90)
print("BB MEAN REVERSION — REGIME UNIVERSALITY TEST")
print("=" * 90)

btc = load_pair("BTCUSDT")
regimes = classify_regimes(btc)

ASSETS = [
    "ETHUSDT", "AVAXUSDT", "LINKUSDT", "SOLUSDT",
    "DOGEUSDT", "LTCUSDT", "NEARUSDT", "ARBUSDT", "OPUSDT", "AAVEUSDT"
]

for pair in ASSETS:
    df = load_pair(pair)
    if df is None:
        continue

    regime_aligned = regimes.reindex(df.index, method='ffill')

    for direction in ["long", "short"]:
        trades = run_bb_mr(df, regime_aligned, direction=direction)
        if not trades:
            continue

        print(f"\n{pair} BB MR {direction.upper()}:")
        analyze_by_regime(trades, "ALL")

        for regime in ["BULL", "BEAR", "CHOP"]:
            r_trades = [t for t in trades if t['regime'] == regime]
            if r_trades:
                analyze_by_regime(r_trades, regime)
