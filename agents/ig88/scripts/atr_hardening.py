#!/usr/bin/env python3
"""
ATR Breakout Strategy — Comprehensive Robustness Hardening
============================================================
Tests: Walk-forward, parameter sensitivity, slippage, regime dependency,
       extended symbol universe, MACD combo filter, leverage simulation.

SHORT when price breaks above upper ATR channel:
  signal_short = close > close.shift(1) + atr * mult
Trailing stop: 3% default
Max hold: 48h default
"""

import json
import os
import sys
import warnings
import time
import itertools
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
MANIFEST = Path("/Users/nesbitt/dev/factory/agents/ig88/data/manifest.json")
OUTPUT   = Path("/Users/nesbitt/dev/factory/agents/ig88/data/atr_hardening.json")

# Default strategy params
ATR_PERIOD    = 14
ATR_MULT      = 2.0
LOOKBACK      = 10
TRAIL_STOP    = 0.03     # 3%
MAX_HOLD_H    = 48       # hours

# Hyperliquid fee structure
TAKER_FEE = 0.00045  # 0.045%

# ─── DATA LOADING ─────────────────────────────────────────────────────────────

def load_manifest_symbols():
    """Load 1h symbols with >= 10000 rows, prefer _1h files for consistency."""
    with open(MANIFEST) as f:
        m = json.load(f)

    seen = set()
    symbols = []
    for item in m["data"]["1h"]:
        if item["rows"] < 5000:
            continue
        fname = item["file"]
        # prefer _1h files (18000 rows) over 60m duplicates
        if "_1440m" in fname or "_120m" in fname:
            continue
        base = Path(fname).stem.replace("binance_", "").replace("_1h", "").replace("_60m", "")
        if base in seen:
            continue
        seen.add(base)
        symbols.append({
            "file": Path("/Users/nesbitt/dev/factory/agents/ig88/data") / fname,
            "symbol": base,
            "rows": item["rows"],
        })
    return symbols


def load_price_data(filepath):
    """Load parquet, return DataFrame with OHLCV."""
    df = pd.read_parquet(filepath)
    df = df.sort_index()
    # Ensure standard columns
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            raise ValueError(f"Missing column {col}")
    return df


# ─── INDICATORS ───────────────────────────────────────────────────────────────

def calc_atr(df, period=14):
    """True Range based ATR."""
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period, min_periods=period).mean()
    return atr


def calc_macd(df, fast=12, slow=26, signal=9):
    """MACD line, signal line, histogram."""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist


def classify_regime(df, lookback=100):
    """Classify each bar into bull/bear/sideways based on 100-bar return & vol."""
    returns = df["close"].pct_change(lookback)
    vol = df["close"].pct_change().rolling(lookback).std()

    med_vol = vol.median()
    regime = pd.Series("sideways", index=df.index)
    regime[returns > 0.02] = "bull"
    regime[returns < -0.02] = "bear"
    # override high-vol sideways as "volatile"
    regime[(regime == "sideways") & (vol > med_vol * 1.5)] = "volatile"
    return regime


# ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────

def backtest_atr_short(df, atr_period=ATR_PERIOD, atr_mult=ATR_MULT,
                       lookback=LOOKBACK, trail_stop=TRAIL_STOP,
                       max_hold_h=MAX_HOLD_H, slippage=0.0,
                       leverage=1.0, fee_rate=TAKER_FEE,
                       macd_filter=False):
    """
    Core backtest for ATR Breakout SHORT strategy.

    Entry: short when close > close.shift(1) + atr * mult  (breakout above channel)
    Exit:  trailing stop (3%) or max hold (48h)

    Returns dict of performance metrics.
    """
    n = len(df)
    if n < atr_period + lookback + 10:
        return None

    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values

    # ATR
    atr = calc_atr(df, atr_period).values

    # MACD if filtering
    if macd_filter:
        _, _, macd_hist = calc_macd(df)
        macd_h = macd_hist.values
    else:
        macd_h = None

    # Entry signals: short when close > prev_close + atr * mult
    signals = np.zeros(n, dtype=bool)
    prev_close = np.roll(closes, 1)
    prev_close[0] = closes[0]
    signals = closes > (prev_close + atr * atr_mult)

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_idx = 0
    stop_price = 0.0

    for i in range(atr_period + 5, n):
        if not in_trade:
            if signals[i] and not np.isnan(atr[i]):
                # MACD filter: only short if MACD hist is negative (bearish momentum)
                if macd_filter and macd_h is not None:
                    if np.isnan(macd_h[i]) or macd_h[i] >= 0:
                        continue

                # Entry at next open (bar close) — use close as proxy
                entry_price = closes[i] * (1 - slippage)  # slippage on entry
                entry_idx = i
                stop_price = entry_price * (1 + trail_stop)
                in_trade = True
        else:
            # Check exit conditions
            elapsed = i - entry_idx
            # Update trailing stop: if price goes lower, tighten stop
            current_low = lows[i]
            if current_low < entry_price * (1 - trail_stop):
                # Price moved in our favor, trail stop down
                new_stop = current_low * (1 + trail_stop * 0.5)
                stop_price = min(stop_price, new_stop)

            # Hit stop? (high touches stop)
            exit_price = None
            exit_reason = None

            if highs[i] >= stop_price:
                exit_price = stop_price * (1 + slippage)  # slippage on exit
                exit_reason = "stop"
            elif elapsed >= max_hold_h:
                exit_price = closes[i] * (1 + slippage)
                exit_reason = "max_hold"

            if exit_price is not None:
                # SHORT PnL: profit when price drops
                raw_return = (entry_price - exit_price) / entry_price
                leveraged_return = raw_return * leverage - (fee_rate * 2)  # entry + exit fees
                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return": leveraged_return,
                    "bars_held": elapsed,
                    "exit_reason": exit_reason,
                })
                in_trade = False

    # Close any open trade at last bar
    if in_trade:
        exit_price = closes[-1] * (1 + slippage)
        raw_return = (entry_price - exit_price) / entry_price
        leveraged_return = raw_return * leverage - (fee_rate * 2)
        trades.append({
            "entry_idx": entry_idx,
            "exit_idx": n - 1,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "return": leveraged_return,
            "bars_held": n - 1 - entry_idx,
            "exit_reason": "eod",
        })

    return compute_metrics(trades)


def compute_metrics(trades):
    """Compute strategy performance metrics from trade list."""
    if not trades:
        return {
            "total_trades": 0, "win_rate": 0, "profit_factor": 0,
            "avg_return": 0, "total_return": 0, "max_dd": 0,
            "sharpe": 0, "avg_win": 0, "avg_loss": 0,
            "best_trade": 0, "worst_trade": 0,
            "avg_bars_held": 0, "expectancy": 0,
        }

    rets = np.array([t["return"] for t in trades])
    n = len(rets)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]

    win_rate = len(wins) / n if n > 0 else 0
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.0001
    profit_factor = (wins.sum() / abs(losses.sum())) if len(losses) > 0 and losses.sum() != 0 else float("inf") if len(wins) > 0 else 0

    total_return = np.prod(1 + rets) - 1

    # Max drawdown
    equity = np.cumprod(1 + rets)
    running_max = np.maximum.accumulate(equity)
    drawdowns = (equity - running_max) / running_max
    max_dd = abs(drawdowns.min()) if len(drawdowns) > 0 else 0

    # Sharpe (per trade)
    sharpe = (rets.mean() / (rets.std() + 1e-10)) * np.sqrt(n) if rets.std() > 0 else 0

    expectancy = rets.mean()

    bars_held = [t["bars_held"] for t in trades]

    return {
        "total_trades": n,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "avg_return": round(rets.mean(), 6),
        "total_return": round(total_return, 6),
        "max_dd": round(max_dd, 6),
        "sharpe": round(sharpe, 4),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "best_trade": round(rets.max(), 6),
        "worst_trade": round(rets.min(), 6),
        "avg_bars_held": round(np.mean(bars_held), 1),
        "expectancy": round(expectancy, 6),
    }


# ─── TEST SUITES ──────────────────────────────────────────────────────────────

def test_1_walk_forward(df, symbol, splits=[0.5, 0.6, 0.7]):
    """Walk-forward with 3 splits."""
    results = {}
    n = len(df)

    for split in splits:
        train_end = int(n * split)
        train_df = df.iloc[:train_end]
        test_df = df.iloc[train_end:]

        train_result = backtest_atr_short(train_df)
        test_result = backtest_atr_short(test_df)

        results[f"split_{int(split*100)}"] = {
            "train_rows": len(train_df),
            "test_rows": len(test_df),
            "train": train_result,
            "test": test_result,
        }

    return results


def test_2_parameter_sensitivity(df):
    """Vary ATR period (±4), ATR multiplier (±0.5), lookback (±5)."""
    results = []

    atr_periods = [ATR_PERIOD - 4, ATR_PERIOD, ATR_PERIOD + 4]
    atr_mults   = [ATR_MULT - 0.5, ATR_MULT - 0.25, ATR_MULT, ATR_MULT + 0.25, ATR_MULT + 0.5]
    lookbacks   = [LOOKBACK - 5, LOOKBACK - 2, LOOKBACK, LOOKBACK + 2, LOOKBACK + 5]

    for ap in atr_periods:
        for am in atr_mults:
            for lb in lookbacks:
                if ap < 5 or am < 0.5 or lb < 3:
                    continue
                res = backtest_atr_short(df, atr_period=ap, atr_mult=am, lookback=lb)
                if res:
                    results.append({
                        "atr_period": ap, "atr_mult": am, "lookback": lb,
                        **res
                    })

    # Compute sensitivity stats
    pfs = [r["profit_factor"] for r in results if r["total_trades"] >= 5]
    if pfs:
        summary = {
            "mean_pf": round(np.mean(pfs), 4),
            "median_pf": round(np.median(pfs), 4),
            "min_pf": round(min(pfs), 4),
            "max_pf": round(max(pfs), 4),
            "std_pf": round(np.std(pfs), 4),
            "pct_profitable": round(sum(1 for p in pfs if p > 1) / len(pfs), 4),
        }
    else:
        summary = {}

    return {"grid": results, "sensitivity_summary": summary}


def test_3_slippage(df):
    """Test with 0.05% slippage."""
    base = backtest_atr_short(df, slippage=0.0)
    with_slip = backtest_atr_short(df, slippage=0.0005)
    with_hl_fees = backtest_atr_short(df, slippage=0.0005, fee_rate=TAKER_FEE)

    return {
        "no_slippage_no_fee": base,
        "with_0.05pct_slippage": with_slip,
        "with_slippage_plus_hl_fees": with_hl_fees,
        "pf_degradation": round(
            (base["profit_factor"] - with_hl_fees["profit_factor"]) / base["profit_factor"], 4
        ) if base and with_hl_fees and base["profit_factor"] > 0 else None,
    }


def test_4_regime_dependency(df):
    """Split into bull/bear/sideways."""
    regime = classify_regime(df, lookback=100)
    results = {}

    for rtype in ["bull", "bear", "sideways", "volatile"]:
        mask = regime == rtype
        sub = df[mask]
        if len(sub) > 100:
            res = backtest_atr_short(sub)
            results[rtype] = {
                "bars": len(sub),
                **res
            }
        else:
            results[rtype] = {"bars": len(sub), "total_trades": 0, "note": "insufficient data"}

    return results


def test_5_extended_universe(symbol_files):
    """Test on all symbols."""
    results = {}
    for sym_info in symbol_files:
        try:
            df = load_price_data(sym_info["file"])
            res = backtest_atr_short(df)
            results[sym_info["symbol"]] = res
        except Exception as e:
            results[sym_info["symbol"]] = {"error": str(e)}

    # Aggregate
    pfs = [r["profit_factor"] for r in results.values()
           if isinstance(r, dict) and "profit_factor" in r and r.get("total_trades", 0) >= 5]

    agg = {
        "symbols_tested": len(results),
        "symbols_with_trades": len(pfs),
        "mean_pf": round(np.mean(pfs), 4) if pfs else 0,
        "median_pf": round(np.median(pfs), 4) if pfs else 0,
        "pct_profitable": round(sum(1 for p in pfs if p > 1) / len(pfs), 4) if pfs else 0,
        "min_pf": round(min(pfs), 4) if pfs else 0,
        "max_pf": round(max(pfs), 4) if pfs else 0,
    }

    return {"per_symbol": results, "aggregate": agg}


def test_6_macd_combo(symbol_files):
    """ATR Breakout + MACD filter."""
    results = {}
    for sym_info in symbol_files:
        try:
            df = load_price_data(sym_info["file"])
            base = backtest_atr_short(df, macd_filter=False)
            combo = backtest_atr_short(df, macd_filter=True)
            results[sym_info["symbol"]] = {
                "atr_only": base,
                "atr_macd_combo": combo,
            }
        except Exception as e:
            results[sym_info["symbol"]] = {"error": str(e)}

    return results


def test_7_leverage(symbol_files, leverages=[1, 3, 5, 7, 10]):
    """Leverage simulation with Hyperliquid fees."""
    results = {}
    for sym_info in symbol_files:
        try:
            df = load_price_data(sym_info["file"])
            sym_results = {}
            for lev in leverages:
                res = backtest_atr_short(df, leverage=lev, fee_rate=TAKER_FEE, slippage=0.0)
                sym_results[f"{lev}x"] = res
            results[sym_info["symbol"]] = sym_results
        except Exception as e:
            results[sym_info["symbol"]] = {"error": str(e)}

    return results


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    print("=" * 70)
    print("ATR BREAKOUT STRATEGY — ROBUSTNESS HARDENING")
    print("=" * 70)

    # Load symbols
    symbol_files = load_manifest_symbols()
    print(f"\nLoaded {len(symbol_files)} symbols from manifest")
    for s in symbol_files:
        print(f"  {s['symbol']:15s}  {s['rows']:>6d} rows  {s['file'].name}")

    # ─── Run baseline on key symbols first ───
    print("\n" + "=" * 70)
    print("BASELINE BACKTESTS (default params)")
    print("=" * 70)
    for sym_info in symbol_files:
        if sym_info["symbol"] in ["SOLUSDT", "LINKUSDT", "BTCUSDT", "ETHUSDT"]:
            try:
                df = load_price_data(sym_info["file"])
                res = backtest_atr_short(df)
                print(f"\n  {sym_info['symbol']}:")
                print(f"    Trades: {res['total_trades']}  Win%: {res['win_rate']:.1%}  PF: {res['profit_factor']:.2f}  "
                      f"Return: {res['total_return']:.2%}  Sharpe: {res['sharpe']:.2f}  MaxDD: {res['max_dd']:.2%}")
            except Exception as e:
                print(f"  {sym_info['symbol']}: ERROR - {e}")

    # ─── Test 1: Walk-Forward ───
    print("\n" + "=" * 70)
    print("TEST 1: WALK-FORWARD ANALYSIS")
    print("=" * 70)
    wf_results = {}
    for sym_info in symbol_files:
        try:
            df = load_price_data(sym_info["file"])
            wf_results[sym_info["symbol"]] = test_1_walk_forward(df, sym_info["symbol"])
            r = wf_results[sym_info["symbol"]]
            splits_summary = []
            for k, v in r.items():
                t_pf = v["test"]["profit_factor"] if v["test"] else 0
                splits_summary.append(f"{k}: testPF={t_pf:.2f}")
            print(f"  {sym_info['symbol']:15s}  {'  '.join(splits_summary)}")
        except Exception as e:
            wf_results[sym_info["symbol"]] = {"error": str(e)}
            print(f"  {sym_info['symbol']:15s}  ERROR: {e}")

    # ─── Test 2: Parameter Sensitivity ───
    print("\n" + "=" * 70)
    print("TEST 2: PARAMETER SENSITIVITY")
    print("=" * 70)
    param_results = {}
    for sym_info in symbol_files:
        if sym_info["symbol"] in ["SOLUSDT", "LINKUSDT", "BTCUSDT", "ETHUSDT"]:
            try:
                df = load_price_data(sym_info["file"])
                param_results[sym_info["symbol"]] = test_2_parameter_sensitivity(df)
                s = param_results[sym_info["symbol"]]["sensitivity_summary"]
                print(f"  {sym_info['symbol']:15s}  meanPF={s.get('mean_pf',0):.2f}  "
                      f"medPF={s.get('median_pf',0):.2f}  "
                      f"%profitable={s.get('pct_profitable',0):.1%}  "
                      f"stdPF={s.get('std_pf',0):.2f}")
            except Exception as e:
                param_results[sym_info["symbol"]] = {"error": str(e)}
                print(f"  {sym_info['symbol']:15s}  ERROR: {e}")

    # ─── Test 3: Slippage ───
    print("\n" + "=" * 70)
    print("TEST 3: SLIPPAGE IMPACT (0.05% + Hyperliquid fees)")
    print("=" * 70)
    slippage_results = {}
    for sym_info in symbol_files:
        try:
            df = load_price_data(sym_info["file"])
            slippage_results[sym_info["symbol"]] = test_3_slippage(df)
            r = slippage_results[sym_info["symbol"]]
            base_pf = r["no_slippage_no_fee"]["profit_factor"] if r["no_slippage_no_fee"] else 0
            slip_pf = r["with_slippage_plus_hl_fees"]["profit_factor"] if r["with_slippage_plus_hl_fees"] else 0
            degrad = r["pf_degradation"]
            print(f"  {sym_info['symbol']:15s}  basePF={base_pf:.2f}  slipPF={slip_pf:.2f}  "
                  f"degradation={degrad}")
        except Exception as e:
            slippage_results[sym_info["symbol"]] = {"error": str(e)}
            print(f"  {sym_info['symbol']:15s}  ERROR: {e}")

    # ─── Test 4: Regime Dependency ───
    print("\n" + "=" * 70)
    print("TEST 4: REGIME DEPENDENCY")
    print("=" * 70)
    regime_results = {}
    for sym_info in symbol_files:
        if sym_info["symbol"] in ["SOLUSDT", "LINKUSDT", "BTCUSDT", "ETHUSDT"]:
            try:
                df = load_price_data(sym_info["file"])
                regime_results[sym_info["symbol"]] = test_4_regime_dependency(df)
                r = regime_results[sym_info["symbol"]]
                parts = []
                for regime, v in r.items():
                    pf = v.get("profit_factor", 0) if "profit_factor" in v else 0
                    nt = v.get("total_trades", 0)
                    parts.append(f"{regime}:trades={nt},pf={pf:.2f}")
                print(f"  {sym_info['symbol']:15s}  {'  '.join(parts)}")
            except Exception as e:
                regime_results[sym_info["symbol"]] = {"error": str(e)}
                print(f"  {sym_info['symbol']:15s}  ERROR: {e}")

    # ─── Test 5: Extended Universe ───
    print("\n" + "=" * 70)
    print("TEST 5: EXTENDED SYMBOL UNIVERSE")
    print("=" * 70)
    universe_results = test_5_extended_universe(symbol_files)
    agg = universe_results["aggregate"]
    print(f"  Symbols tested: {agg['symbols_tested']}")
    print(f"  Symbols with trades: {agg['symbols_with_trades']}")
    print(f"  Mean PF: {agg['mean_pf']:.2f}")
    print(f"  Median PF: {agg['median_pf']:.2f}")
    print(f"  % Profitable: {agg['pct_profitable']:.1%}")
    print(f"  PF range: {agg['min_pf']:.2f} - {agg['max_pf']:.2f}")
    for sym, r in universe_results["per_symbol"].items():
        if isinstance(r, dict) and "profit_factor" in r:
            print(f"    {sym:15s}  trades={r['total_trades']:3d}  PF={r['profit_factor']:.2f}  "
                  f"ret={r['total_return']:.2%}  sharpe={r['sharpe']:.2f}")

    # ─── Test 6: MACD Combo ───
    print("\n" + "=" * 70)
    print("TEST 6: ATR + MACD COMBO FILTER")
    print("=" * 70)
    macd_results = test_6_macd_combo(symbol_files)
    for sym, r in macd_results.items():
        if "atr_only" in r and "atr_macd_combo" in r:
            base = r["atr_only"]
            combo = r["atr_macd_combo"]
            if base and combo:
                print(f"  {sym:15s}  ATR_only: tr={base['total_trades']} PF={base['profit_factor']:.2f}  "
                      f"Combo: tr={combo['total_trades']} PF={combo['profit_factor']:.2f}")

    # ─── Test 7: Leverage ───
    print("\n" + "=" * 70)
    print("TEST 7: LEVERAGE SIMULATION (Hyperliquid fees)")
    print("=" * 70)
    leverage_results = test_7_leverage(symbol_files)
    for sym in ["SOLUSDT", "LINKUSDT", "BTCUSDT", "ETHUSDT"]:
        if sym in leverage_results and "error" not in leverage_results[sym]:
            r = leverage_results[sym]
            parts = []
            for lev_key in ["1x", "3x", "5x", "7x", "10x"]:
                if lev_key in r:
                    pf = r[lev_key]["profit_factor"] if r[lev_key] else 0
                    ret = r[lev_key]["total_return"] if r[lev_key] else 0
                    dd = r[lev_key]["max_dd"] if r[lev_key] else 0
                    parts.append(f"{lev_key}:PF={pf:.1f},ret={ret:.1%},dd={dd:.1%}")
            print(f"  {sym:15s}  {'  '.join(parts)}")

    # ─── SAVE RESULTS ───
    all_results = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "strategy": "ATR Breakout SHORT",
            "default_params": {
                "atr_period": ATR_PERIOD,
                "atr_mult": ATR_MULT,
                "lookback": LOOKBACK,
                "trail_stop": TRAIL_STOP,
                "max_hold_h": MAX_HOLD_H,
            },
            "slippage_test": 0.0005,
            "hyperliquid_taker_fee": TAKER_FEE,
        },
        "test_1_walk_forward": wf_results,
        "test_2_parameter_sensitivity": param_results,
        "test_3_slippage": slippage_results,
        "test_4_regime_dependency": regime_results,
        "test_5_extended_universe": universe_results,
        "test_6_macd_combo": macd_results,
        "test_7_leverage": leverage_results,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print(f"Results saved to {OUTPUT}")
    print(f"Total time: {elapsed:.1f}s")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
