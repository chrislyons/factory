"""
h3d_cross_asset.py — H3-D Cross-Asset Expansion

STEP 1: Fetch extended 1h OHLCV data for BTC/USD, ETH/USDT, SOL/USDT (2yr)
         and 4h data for LINK/USD, NEAR/USD, AVAX/USD, XRP/USD (2yr)

STEP 2: H3-D Signal Test
  Signal: OBV crosses above EMA(10) AND RSI crosses above 50 simultaneously
  Exit:   ATR trailing stop (2x ATR stop, 3x ATR target)
  Regime: BTC 20-bar trend proxy
  Split:  70/30 walk-forward
  Assets: ETH daily, NEAR daily, LINK daily, AVAX daily

Reports: OOS PF, p-value, n for each asset.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

from src.quant.historical_fetcher import (
    fetch_binance_full,
    incremental_update,
    save_cached,
    load_cached,
    BINANCE_SYMBOL_MAP,
    BINANCE_LISTING_DATES,
    DATA_DIR,
)
import src.quant.indicators as ind
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.indicator_research import backtest_signal
from src.quant.regime import RegimeState


# ---------------------------------------------------------------------------
# STEP 1: Fetch extended historical data
# ---------------------------------------------------------------------------

def fetch_extended_data():
    """Fetch 2yr 1h data for BTC/ETH/SOL and 2yr 4h data for LINK/NEAR/AVAX/XRP."""

    now = datetime.now(timezone.utc)
    two_yr_ago = now - timedelta(days=2 * 365)

    fetch_targets = [
        # (ig88_symbol, interval_min, start_dt, label)
        ("BTC/USD",  60,   two_yr_ago, "BTC 1h  2yr"),
        ("ETH/USDT", 60,   two_yr_ago, "ETH 1h  2yr"),
        ("SOL/USDT", 60,   two_yr_ago, "SOL 1h  2yr"),
        ("LINK/USD", 240,  two_yr_ago, "LINK 4h 2yr"),
        ("NEAR/USD", 240,  two_yr_ago, "NEAR 4h 2yr"),
        ("AVAX/USD", 240,  two_yr_ago, "AVAX 4h 2yr"),
        ("XRP/USD",  240,  two_yr_ago, "XRP 4h  2yr"),
    ]

    print("\n" + "=" * 70)
    print("STEP 1: Fetching Extended Historical OHLCV Data")
    print(f"Target: 2yr history  Start: {two_yr_ago.strftime('%Y-%m-%d')}")
    print("=" * 70)

    fetched_files = []

    for ig88_sym, interval_min, start_dt, label in fetch_targets:
        binance_sym = BINANCE_SYMBOL_MAP.get(ig88_sym)
        if not binance_sym:
            print(f"  [skip] {label} — no Binance mapping")
            continue

        # Respect listing date floor
        listing_dt = BINANCE_LISTING_DATES.get(binance_sym, datetime(2019, 1, 1, tzinfo=timezone.utc))
        effective_start = max(start_dt, listing_dt)

        print(f"\n  {label}  ({binance_sym})  from {effective_start.strftime('%Y-%m-%d')}")

        # Check existing cache
        existing = load_cached("binance", ig88_sym, interval_min)

        if existing is not None and not existing.empty:
            earliest_cached = existing.index[0]
            latest_cached   = existing.index[-1]

            # Normalize to UTC-aware pandas Timestamps
            if earliest_cached.tzinfo is None:
                earliest_cached = earliest_cached.tz_localize("UTC")
            if latest_cached.tzinfo is None:
                latest_cached = latest_cached.tz_localize("UTC")

            cached_start_ts = earliest_cached

            # Need earlier data than what we have?
            effective_start_ts = pd.Timestamp(effective_start)
            if effective_start_ts.tzinfo is None:
                effective_start_ts = effective_start_ts.tz_localize("UTC")
            needs_backfill = cached_start_ts > effective_start_ts + pd.Timedelta(days=5)

            delta = timedelta(hours=interval_min * 2)
            threshold_dt = now - delta
            threshold_ts = pd.Timestamp(threshold_dt).tz_localize("UTC") if threshold_dt.tzinfo is None else pd.Timestamp(threshold_dt)
            needs_tail = latest_cached < threshold_ts

            if not needs_backfill and not needs_tail:
                span = f"{existing.index[0].date()} -> {existing.index[-1].date()}"
                print(f"  [current] {len(existing)} bars  {span}")
                fetched_files.append((ig88_sym, interval_min))
                continue

            if needs_backfill:
                print(f"  [backfill] cached starts {cached_start_ts.date()}, need {effective_start.date()} — fetching gap...")
                # Fetch missing earlier portion
                backfill_end = cached_start_ts - timedelta(minutes=interval_min)
                new_early = fetch_binance_full(binance_sym, interval_min,
                                               start_dt=effective_start,
                                               end_dt=backfill_end)
                if not new_early.empty:
                    combined = pd.concat([new_early, existing])
                    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                    existing = combined

            if needs_tail:
                gap_start = existing.index[-1].to_pydatetime()
                if gap_start.tzinfo is None:
                    gap_start = gap_start.replace(tzinfo=timezone.utc)
                gap_start = gap_start + timedelta(minutes=interval_min)
                print(f"  [tail]    fetching from {gap_start.strftime('%Y-%m-%d')} to now...")
                new_tail = fetch_binance_full(binance_sym, interval_min, start_dt=gap_start)
                if not new_tail.empty:
                    combined = pd.concat([existing, new_tail])
                    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                    existing = combined

            p = save_cached(existing, "binance", ig88_sym, interval_min)
            span = f"{existing.index[0].date()} -> {existing.index[-1].date()}"
            print(f"  [saved]   {len(existing)} bars  {span}  -> {p.name}")

        else:
            print(f"  [full]    no cache found, fetching full 2yr history...")
            df = fetch_binance_full(binance_sym, interval_min, start_dt=effective_start)
            if df.empty:
                print(f"  [warn]    No data returned for {ig88_sym} {interval_min}m")
                continue
            p = save_cached(df, "binance", ig88_sym, interval_min)
            span = f"{df.index[0].date()} -> {df.index[-1].date()}"
            print(f"  [saved]   {len(df)} bars  {span}  -> {p.name}")

        fetched_files.append((ig88_sym, interval_min))

    print(f"\n  Fetch complete. {len(fetched_files)} datasets ready.")
    return fetched_files


# ---------------------------------------------------------------------------
# STEP 2: H3-D Signal — OBV cross EMA10 + RSI cross 50
# ---------------------------------------------------------------------------

def build_h3d_signal(c: np.ndarray, v: np.ndarray) -> np.ndarray:
    """
    H3-D Entry Signal:
    OBV crosses above EMA(10) of OBV  AND  RSI(14) crosses above 50 simultaneously.

    Both conditions must trigger on the same bar.
    """
    n = len(c)

    # Compute OBV
    obv_vals = ind.obv(c, v)

    # EMA(10) of OBV
    obv_ema10 = ind.ema(obv_vals, 10)

    # RSI(14)
    rsi_vals = ind.rsi(c, 14)

    mask = np.zeros(n, dtype=bool)

    for i in range(1, n):
        if np.isnan(obv_ema10[i]) or np.isnan(obv_ema10[i-1]):
            continue
        if np.isnan(rsi_vals[i]) or np.isnan(rsi_vals[i-1]):
            continue

        # OBV crosses above its EMA10
        obv_cross = (obv_vals[i] > obv_ema10[i]) and (obv_vals[i-1] <= obv_ema10[i-1])

        # RSI crosses above 50
        rsi_cross = (rsi_vals[i] > 50.0) and (rsi_vals[i-1] <= 50.0)

        mask[i] = obv_cross and rsi_cross

    return mask


def run_h3d_backtest():
    """
    Run H3-D cross-asset expansion on ETH, NEAR, LINK, AVAX daily data.
    70/30 walk-forward. ATR trailing stop (2x/3x ATR via backtest_signal).
    Reports OOS PF, p-value, n for each asset.
    """

    print("\n" + "=" * 70)
    print("STEP 2: H3-D Cross-Asset Expansion")
    print("Signal: OBV > EMA(10) cross  AND  RSI cross above 50")
    print("Exit:   2x ATR stop / 3x ATR target")
    print("Regime: BTC 20-bar trend proxy")
    print("Split:  70% train / 30% OOS")
    print("=" * 70)

    # Load BTC daily for regime
    try:
        btc_df = load_binance("BTC/USD", 1440)
    except FileNotFoundError:
        print("  [ERROR] BTC daily data not found. Run fetch first.")
        return []

    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    # Assets to test
    test_assets = [
        ("ETH/USDT", 1440, 24.0, "ETH daily"),
        ("NEAR/USD",  1440, 24.0, "NEAR daily"),
        ("LINK/USD",  1440, 24.0, "LINK daily"),
        ("AVAX/USD",  1440, 24.0, "AVAX daily"),
    ]

    results = []

    print(f"\n  {'Asset':<14} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  "
          f"{'OOS-n':>6} {'OOS-PF':>7} {'OOS-Sh':>7} {'OOS-p':>7}  flag")
    print(f"  {'-'*14} {'-'*5} {'-'*7} {'-'*7}  "
          f"{'-'*6} {'-'*7} {'-'*7} {'-'*7}  ----")

    for sym, itvl, bar_hours, label in test_assets:
        try:
            df = load_binance(sym, itvl)
        except FileNotFoundError:
            print(f"  {label:<14} [no data — skipping]")
            continue

        if len(df) < 200:
            print(f"  {label:<14} [insufficient data: {len(df)} bars]")
            continue

        ts, o, h, l, c, v = df_to_arrays(df)

        # Build BTC-based regime
        regime = build_btc_trend_regime(btc_c, ts, btc_ts,
                                        trend_period=20,
                                        bull_threshold=0.05,
                                        bear_threshold=-0.05)

        # Compute ATR
        atr_vals = ind.atr(h, l, c, 14)

        # Build H3-D signal
        signal_mask = build_h3d_signal(c, v)

        # 70/30 split
        N = len(ts)
        SPLIT = int(N * 0.70)

        # Train set
        tr = backtest_signal(
            ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
            c[:SPLIT], v[:SPLIT],
            signal_mask[:SPLIT], regime[:SPLIT], atr_vals[:SPLIT],
            None, 10_000.0, bar_hours
        )

        # OOS test set
        te = backtest_signal(
            ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
            c[SPLIT:], v[SPLIT:],
            signal_mask[SPLIT:], regime[SPLIT:], atr_vals[SPLIT:],
            None, 10_000.0, bar_hours
        )

        # Flag
        flag = ""
        if te and te["n"] >= 5:
            if te["pf"] > 2.0 and te["p"] < 0.10:
                flag = "STRONG*"
            elif te["pf"] > 1.5:
                flag = "pass"
            elif te["pf"] < 0.8:
                flag = "fail"
        elif te and te["n"] < 5:
            flag = "low-n"

        tr_s = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['p']:7.3f}" if tr else "    0       -       -"
        te_s = (f"{te['n']:6d} {te['pf']:7.3f} {te['sharpe']:7.3f} {te['p']:7.3f}"
                if te else "     0       -       -       -")
        star = "*" if (te and te["p"] < 0.10) else " "
        print(f"  {label:<14} {tr_s}  {te_s}{star}  {flag}")

        results.append({
            "asset":     label,
            "symbol":    sym,
            "interval":  itvl,
            "train":     tr,
            "oos":       te,
            "n_total":   N,
            "n_train":   SPLIT,
            "n_oos":     N - SPLIT,
            "signal_fires_total": int(np.sum(signal_mask)),
            "signal_fires_oos":   int(np.sum(signal_mask[SPLIT:])),
        })

    # Summary table
    print("\n" + "=" * 70)
    print("H3-D OOS SUMMARY")
    print("=" * 70)
    print(f"  {'Asset':<14} {'OOS-n':>6} {'OOS-PF':>8} {'OOS-p':>8}  {'Status'}")
    print(f"  {'-'*14} {'-'*6} {'-'*8} {'-'*8}  {'-'*15}")

    significant = []
    for r in results:
        te = r["oos"]
        if te:
            oos_pf = te["pf"]
            oos_p  = te["p"]
            oos_n  = te["n"]
            status = ""
            if oos_n >= 5:
                if oos_pf > 2.0 and oos_p < 0.10:
                    status = "STRONG EDGE *"
                    significant.append(r)
                elif oos_pf > 1.5 and oos_p < 0.20:
                    status = "weak edge"
                elif oos_pf < 1.0:
                    status = "no edge"
                else:
                    status = "marginal"
            else:
                status = f"low-n ({oos_n})"
            print(f"  {r['asset']:<14} {oos_n:>6} {oos_pf:>8.3f} {oos_p:>8.3f}  {status}")
        else:
            print(f"  {r['asset']:<14}      0        -        -  no trades")

    if significant:
        print(f"\n  Assets with OOS PF > 2.0 AND p < 0.10: {[r['asset'] for r in significant]}")
    else:
        print(f"\n  No assets met STRONG EDGE criteria (PF > 2.0, p < 0.10)")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("H3-D CROSS-ASSET EXPANSION RUN")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    # Step 1: Fetch extended data
    fetch_extended_data()

    # Step 2: Run H3-D backtest
    results = run_h3d_backtest()

    # Final printout
    print("\n" + "=" * 70)
    print("FINAL RESULTS — H3-D OBV-EMA10 + RSI Cross Signal")
    print("=" * 70)

    for r in results:
        te = r["oos"]
        if te:
            star = " *" if te["p"] < 0.10 else "  "
            print(f"  {r['asset']:<14}  OOS PF={te['pf']:.3f}  p={te['p']:.3f}  n={te['n']}{star}")
        else:
            print(f"  {r['asset']:<14}  OOS: no trades")

    print("\nDone.")
