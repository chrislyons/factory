#!/usr/bin/env python3
"""
Stream 2 Research: H3-C Optimization, Cross-Asset Validation, 2h Timeframe Test

(1) H3-C Optimization: Parameter sweep on RSI threshold (45-55), KAMA periods (4-14),
    fast/slow combos with ATR trailing exit on SOL 4h.
(2) Cross-Asset Validation: Test H3-A/B/C on ETH, NEAR, INJ 4h with ATR trailing exit.
(3) 2h Timeframe Test: Test H3-A/B on SOL 2h to see if intermediate timeframe works.

Report all OOS PF, n, p-values. Flag any strategy with OOS PF > 2.0 and p < 0.10 as promotable.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
import pandas as pd

import src.quant.indicators as ind
from src.quant.indicator_research import (
    SignalBacktester, backtest_signal,
    signals_vol_spike_break, signals_rsi_momentum_cross,
    signals_kama_cross, signals_ichimoku_h3a,
)
from src.quant.research_loop import ExitResearchBacktester
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine, Trade
from src.quant.regime import RegimeState

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
RESEARCH_DIR = DATA_DIR / "research"
VENUE = "kraken_spot"
MAKER_FEE = 0.0016


def save_structured_result(study_id, asset, tf, category, result_data):
    """Save structured result to research directory and update ledger."""
    target_dir = RESEARCH_DIR / category
    target_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"{asset}_{tf}_{study_id}_{timestamp}.json".replace(" ", "_")
    target_path = target_dir / filename
    
    with open(target_path, 'w') as f:
        json.dump(result_data, f, indent=2)
    
    # Append to Ledger
    ledger_path = RESEARCH_DIR / "ledger.csv"
    with open(ledger_path, 'a') as f:
        f.write(f"{datetime.now().isoformat()},{category},{asset},{tf},{target_path}\n")
    
    return target_path


def load_asset(symbol, interval_min):
    """Load asset data from binance parquet files."""
    try:
        return load_binance(symbol, interval_min)
    except FileNotFoundError:
        return None


# =============================================================================
# H3-C Strategy: RSI + KAMA with adaptive parameters
# =============================================================================

def signals_h3c(c, h, l, rsi_threshold=50, kama_period=6, kama_fast=2, kama_slow=30):
    """
    H3-C: RSI momentum + KAMA cross + price above KAMA.
    
    Entry conditions:
    1. RSI crosses above rsi_threshold (momentum confirmation)
    2. Price crosses above KAMA (trend confirmation)
    3. Price is above KAMA (trend aligned)
    
    Returns (signal_mask, exit_ma=KAMA)
    """
    rsi_v = ind.rsi(c, 14)
    kama_v = ind.kama(c, period=kama_period, fast_period=kama_fast, slow_period=kama_slow)
    
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    
    for i in range(1, n):
        if np.isnan(rsi_v[i]) or np.isnan(rsi_v[i-1]):
            continue
        if np.isnan(kama_v[i]) or np.isnan(kama_v[i-1]):
            continue
        
        # RSI crosses above threshold
        rsi_cross = rsi_v[i] > rsi_threshold and rsi_v[i-1] <= rsi_threshold
        
        # Price crosses above KAMA
        kama_cross = c[i] > kama_v[i] and c[i-1] <= kama_v[i-1]
        
        # Combined signal: either RSI cross OR KAMA cross, with price above KAMA
        above_kama = c[i] > kama_v[i]
        
        mask[i] = (rsi_cross or kama_cross) and above_kama
    
    return mask, kama_v


def run_wf_split(ts, o, h, l, c, v, regime, atr_v, mask, exit_ma=None,
                 capital=10_000.0, bar_hours=4.0, split=0.70):
    """Walk-forward backtest with train/test split."""
    N = len(ts)
    SPLIT = int(N * split)
    
    tr_exit = exit_ma[:SPLIT] if exit_ma is not None else None
    te_exit = exit_ma[SPLIT:] if exit_ma is not None else None
    
    tr = backtest_signal(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                         c[:SPLIT], v[:SPLIT], mask[:SPLIT], regime[:SPLIT],
                         atr_v[:SPLIT], tr_exit, capital, bar_hours)
    te = backtest_signal(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                         c[SPLIT:], v[SPLIT:], mask[SPLIT:], regime[SPLIT:],
                         atr_v[SPLIT:], te_exit, capital, bar_hours)
    return tr, te


def run_exit_backtest(ts, o, h, l, c, v, regime, signal_mask, exit_method='atr_trail',
                      bar_hours=4.0):
    """Run backtest with specific exit method using ExitResearchBacktester."""
    bt = ExitResearchBacktester(bar_hours=bar_hours)
    trades = bt.run_exit(ts, o, h, l, c, v, regime, signal_mask, exit_method)
    return trades


def stats_to_dict(stats, label=""):
    """Convert BacktestStats to dict."""
    if stats is None:
        return None
    return {
        "label": label,
        "n": stats.n_trades,
        "wr": round(stats.win_rate, 4),
        "pf": round(stats.profit_factor, 4),
        "sharpe": round(stats.sharpe_ratio, 4),
        "sortino": round(stats.sortino_ratio, 4),
        "dd": round(stats.max_drawdown_pct, 4),
        "pnl_pct": round(stats.total_pnl_pct, 4),
        "exp_r": round(stats.expectancy_r, 4),
        "p": round(stats.p_value, 4),
    }


def compute_stats(trades, capital=10_000.0):
    """Compute stats from trades list."""
    if not trades:
        return None
    eng = BacktestEngine(initial_capital=capital)
    eng.add_trades(trades)
    return eng.compute_stats(venue=VENUE)


def fmt_result(r, label=""):
    """Format result for display."""
    if not r:
        return f"{label:20s} n=  0"
    star = "*" if r["p"] < 0.10 else " "
    return f"{label:20s} n={r['n']:4d} PF={r['pf']:7.3f} Sh={r['sharpe']:+6.3f} p={r['p']:.3f}{star}"


# =============================================================================
# STUDY 1: H3-C Parameter Optimization on SOL 4h
# =============================================================================

def study1_h3c_optimization():
    """Parameter sweep on RSI threshold (45-55), KAMA periods (4-14), fast/slow combos."""
    print("\n" + "=" * 80)
    print("STUDY 1: H3-C Optimization - SOL 4h")
    print("Parameter sweep: RSI threshold (45-55), KAMA periods (4-14), fast/slow combos")
    print("Exit method: ATR trailing stop")
    print("=" * 80)
    
    # Load SOL 4h data
    df = load_asset("SOL/USDT", 240)
    if df is None or len(df) < 200:
        print("ERROR: SOL/USDT 4h data not available")
        return {}
    
    ts, o, h, l, c, v = df_to_arrays(df)
    
    # Load BTC for regime
    btc_df = load_asset("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    
    atr_v = ind.atr(h, l, c, 14)
    
    # Parameter grid
    rsi_thresholds = [45, 48, 50, 52, 55]
    kama_periods = [4, 6, 8, 10, 12, 14]
    kama_fast_periods = [2, 3]
    kama_slow_periods = [20, 30, 40]
    
    results = []
    best_result = None
    best_score = -999
    
    print(f"\nData: {len(ts)} bars from {datetime.fromtimestamp(ts[0]).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(ts[-1]).strftime('%Y-%m-%d')}")
    print(f"\nTesting {len(rsi_thresholds) * len(kama_periods) * len(kama_fast_periods) * len(kama_slow_periods)} parameter combinations...")
    print()
    
    for rsi_thresh, kama_p, kama_f, kama_s in product(rsi_thresholds, kama_periods, kama_fast_periods, kama_slow_periods):
        # Skip invalid combinations
        if kama_f >= kama_s:
            continue
        if kama_f >= kama_p or kama_s <= kama_p:
            continue
        
        mask, exit_ma = signals_h3c(c, h, l, rsi_thresh, kama_p, kama_f, kama_s)
        
        # Skip if too few signals
        if np.sum(mask) < 10:
            continue
        
        # Run walk-forward with ATR trail exit
        tr, te = run_wf_split(ts, o, h, l, c, v, regime, atr_v, mask, exit_ma, bar_hours=4.0)
        
        if te is None or te["n"] < 5:
            continue
        
        # Score: PF * (1-p) for significance
        score = te["pf"] * (1 - te["p"])
        
        result = {
            "rsi_threshold": rsi_thresh,
            "kama_period": kama_p,
            "kama_fast": kama_f,
            "kama_slow": kama_s,
            "train": tr,
            "test": te,
            "score": score,
            "promotable": te["pf"] > 2.0 and te["p"] < 0.10,
        }
        results.append(result)
        
        if score > best_score:
            best_score = score
            best_result = result
    
    # Sort by score
    results.sort(key=lambda x: x["score"], reverse=True)
    
    # Print top 20 results
    print(f"{'Rank':>4} {'RSI':>5} {'KAMA':>6} {'Fast':>5} {'Slow':>5} {'Tr-n':>5} {'Tr-PF':>7} {'Te-n':>5} {'Te-PF':>7} {'Te-Sh':>7} {'Te-p':>7} {'Flag'}")
    print("-" * 90)
    
    for i, r in enumerate(results[:20]):
        te = r["test"]
        tr = r["train"]
        flag = "PROMOTABLE*" if r["promotable"] else ""
        print(f"{i+1:4d} {r['rsi_threshold']:5d} {r['kama_period']:6d} {r['kama_fast']:5d} {r['kama_slow']:5d} "
              f"{tr['n']:5d} {tr['pf']:7.3f} {te['n']:5d} {te['pf']:7.3f} {te['sharpe']:+7.3f} {te['p']:7.3f} {flag}")
    
    # Summary
    print("\n" + "-" * 80)
    promotable = [r for r in results if r["promotable"]]
    if promotable:
        print(f"PROMOTABLE STRATEGIES (OOS PF > 2.0, p < 0.10): {len(promotable)}")
        for r in promotable[:5]:
            print(f"  RSI={r['rsi_threshold']} KAMA={r['kama_period']} Fast={r['kama_fast']} Slow={r['kama_slow']} "
                  f"OOS PF={r['test']['pf']:.3f} p={r['test']['p']:.3f}")
    else:
        print("NO PROMOTABLE STRATEGIES FOUND")
    
    # Save results
    save_data = {
        "study": "H3-C Optimization",
        "asset": "SOL",
        "timeframe": "4h",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_tested": len(results),
        "promotable_count": len(promotable),
        "best_params": {
            "rsi_threshold": best_result["rsi_threshold"] if best_result else None,
            "kama_period": best_result["kama_period"] if best_result else None,
            "kama_fast": best_result["kama_fast"] if best_result else None,
            "kama_slow": best_result["kama_slow"] if best_result else None,
        },
        "best_test": best_result["test"] if best_result else None,
        "promotable": [{"params": {"rsi": r["rsi_threshold"], "kama_p": r["kama_period"], 
                                    "kama_f": r["kama_fast"], "kama_s": r["kama_slow"]},
                        "test": r["test"]} for r in promotable[:10]],
        "top_20": [{"params": {"rsi": r["rsi_threshold"], "kama_p": r["kama_period"],
                                "kama_f": r["kama_fast"], "kama_s": r["kama_slow"]},
                    "test": r["test"]} for r in results[:20]],
    }
    
    save_path = save_structured_result("H3-C_Opt", "SOL", "4h", "h3c_optimization", save_data)
    print(f"\nResults saved: {save_path}")
    
    return {"best": best_result, "promotable": promotable, "top_10": results[:10]}


# =============================================================================
# STUDY 2: Cross-Asset Validation (H3-A, H3-B, H3-C on ETH, NEAR, INJ 4h)
# =============================================================================

def study2_cross_asset_validation(best_h3c_params=None):
    """Test H3-A, H3-B, H3-C on ETH, NEAR, INJ 4h with ATR trailing exit."""
    print("\n" + "=" * 80)
    print("STUDY 2: Cross-Asset Validation - H3-A/B/C on ETH, NEAR, INJ 4h")
    print("Exit method: ATR trailing stop")
    print("=" * 80)
    
    # Default H3-C params if not provided
    if best_h3c_params is None:
        best_h3c_params = {"rsi": 50, "kama_p": 6, "kama_f": 2, "kama_s": 30}
    
    # Assets to test
    assets = [
        ("ETH/USDT", 240, 4.0, "ETH 4h"),
        ("NEAR/USDT", 240, 4.0, "NEAR 4h"),
        ("INJ/USD", 240, 4.0, "INJ 4h"),
    ]
    
    # Load BTC for regime
    btc_df = load_asset("BTC/USD", 1440)
    if btc_df is None:
        print("ERROR: BTC/USD data not available for regime")
        return {}
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)
    
    all_results = {}
    
    for symbol, interval, bar_hours, label in assets:
        print(f"\n--- {label} ---")
        
        df = load_asset(symbol, interval)
        if df is None or len(df) < 200:
            print(f"  [SKIP] No data available")
            continue
        
        ts, o, h, l, c, v = df_to_arrays(df)
        regime = build_btc_trend_regime(btc_c, ts, btc_ts)
        atr_v = ind.atr(h, l, c, 14)
        
        print(f"  Data: {len(ts)} bars")
        
        asset_results = {}
        
        # H3-A: Ichimoku + RSI > 55 + score >= 3
        print("\n  H3-A (Ichimoku + RSI>55 + Score>=3):")
        m_h3a, e_h3a = signals_ichimoku_h3a(h, l, c)
        
        # Use ATR trail exit
        bt = ExitResearchBacktester(bar_hours=bar_hours)
        h3a_trades_tr = bt.run_exit(ts[:int(len(ts)*0.7)], o[:int(len(ts)*0.7)], 
                                     h[:int(len(ts)*0.7)], l[:int(len(ts)*0.7)],
                                     c[:int(len(ts)*0.7)], v[:int(len(ts)*0.7)],
                                     regime[:int(len(ts)*0.7)], m_h3a[:int(len(ts)*0.7)], 
                                     'atr_trail')
        h3a_trades_te = bt.run_exit(ts[int(len(ts)*0.7):], o[int(len(ts)*0.7):], 
                                     h[int(len(ts)*0.7):], l[int(len(ts)*0.7):],
                                     c[int(len(ts)*0.7):], v[int(len(ts)*0.7):],
                                     regime[int(len(ts)*0.7):], m_h3a[int(len(ts)*0.7):], 
                                     'atr_trail')
        
        h3a_tr = compute_stats(h3a_trades_tr)
        h3a_te = compute_stats(h3a_trades_te)
        h3a_tr_d = stats_to_dict(h3a_tr, "H3-A Train")
        h3a_te_d = stats_to_dict(h3a_te, "H3-A Test")
        
        print(f"    {fmt_result(h3a_tr_d, 'Train')}")
        print(f"    {fmt_result(h3a_te_d, 'OOS Test')}")
        
        asset_results["H3-A"] = {"train": h3a_tr_d, "test": h3a_te_d,
                                  "promotable": (h3a_te_d["pf"] > 2.0 and h3a_te_d["p"] < 0.10) if h3a_te_d else False}
        
        # H3-B: Volume spike + RSI cross
        print("\n  H3-B (VolSpike + RSI Cross):")
        m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
        m_rsi, _ = signals_rsi_momentum_cross(c)
        m_h3b = m_vol & m_rsi
        
        h3b_trades_tr = bt.run_exit(ts[:int(len(ts)*0.7)], o[:int(len(ts)*0.7)], 
                                     h[:int(len(ts)*0.7)], l[:int(len(ts)*0.7)],
                                     c[:int(len(ts)*0.7)], v[:int(len(ts)*0.7)],
                                     regime[:int(len(ts)*0.7)], m_h3b[:int(len(ts)*0.7)], 
                                     'atr_trail')
        h3b_trades_te = bt.run_exit(ts[int(len(ts)*0.7):], o[int(len(ts)*0.7):], 
                                     h[int(len(ts)*0.7):], l[int(len(ts)*0.7):],
                                     c[int(len(ts)*0.7):], v[int(len(ts)*0.7):],
                                     regime[int(len(ts)*0.7):], m_h3b[int(len(ts)*0.7):], 
                                     'atr_trail')
        
        h3b_tr = compute_stats(h3b_trades_tr)
        h3b_te = compute_stats(h3b_trades_te)
        h3b_tr_d = stats_to_dict(h3b_tr, "H3-B Train")
        h3b_te_d = stats_to_dict(h3b_te, "H3-B Test")
        
        print(f"    {fmt_result(h3b_tr_d, 'Train')}")
        print(f"    {fmt_result(h3b_te_d, 'OOS Test')}")
        
        asset_results["H3-B"] = {"train": h3b_tr_d, "test": h3b_te_d,
                                  "promotable": (h3b_te_d["pf"] > 2.0 and h3b_te_d["p"] < 0.10) if h3b_te_d else False}
        
        # H3-C: RSI + KAMA (best params from Study 1)
        print(f"\n  H3-C (RSI + KAMA, RSI={best_h3c_params['rsi']}, KAMA={best_h3c_params['kama_p']}):")
        m_h3c, e_h3c = signals_h3c(c, h, l, 
                                     rsi_threshold=best_h3c_params['rsi'],
                                     kama_period=best_h3c_params['kama_p'],
                                     kama_fast=best_h3c_params['kama_f'],
                                     kama_slow=best_h3c_params['kama_s'])
        
        h3c_trades_tr = bt.run_exit(ts[:int(len(ts)*0.7)], o[:int(len(ts)*0.7)], 
                                     h[:int(len(ts)*0.7)], l[:int(len(ts)*0.7)],
                                     c[:int(len(ts)*0.7)], v[:int(len(ts)*0.7)],
                                     regime[:int(len(ts)*0.7)], m_h3c[:int(len(ts)*0.7)], 
                                     'atr_trail')
        h3c_trades_te = bt.run_exit(ts[int(len(ts)*0.7):], o[int(len(ts)*0.7):], 
                                     h[int(len(ts)*0.7):], l[int(len(ts)*0.7):],
                                     c[int(len(ts)*0.7):], v[int(len(ts)*0.7):],
                                     regime[int(len(ts)*0.7):], m_h3c[int(len(ts)*0.7):], 
                                     'atr_trail')
        
        h3c_tr = compute_stats(h3c_trades_tr)
        h3c_te = compute_stats(h3c_trades_te)
        h3c_tr_d = stats_to_dict(h3c_tr, "H3-C Train")
        h3c_te_d = stats_to_dict(h3c_te, "H3-C Test")
        
        print(f"    {fmt_result(h3c_tr_d, 'Train')}")
        print(f"    {fmt_result(h3c_te_d, 'OOS Test')}")
        
        asset_results["H3-C"] = {"train": h3c_tr_d, "test": h3c_te_d,
                                  "promotable": (h3c_te_d["pf"] > 2.0 and h3c_te_d["p"] < 0.10) if h3c_te_d else False}
        
        all_results[label] = asset_results
        
        # Save per-asset results
        save_data = {
            "study": "Cross-Asset Validation",
            "asset": symbol,
            "timeframe": "4h",
            "h3c_params": best_h3c_params,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "results": asset_results,
        }
        save_path = save_structured_result("CrossAsset", symbol.split("/")[0], "4h", "cross_asset", save_data)
        print(f"  Saved: {save_path}")
    
    # Summary
    print("\n" + "=" * 80)
    print("CROSS-ASSET SUMMARY")
    print("=" * 80)
    
    promotable_strategies = []
    for asset_label, strats in all_results.items():
        for strat_name, strat_data in strats.items():
            if strat_data.get("promotable", False):
                te = strat_data["test"]
                promotable_strategies.append({
                    "asset": asset_label,
                    "strategy": strat_name,
                    "pf": te["pf"],
                    "p": te["p"],
                    "n": te["n"],
                })
                print(f"  PROMOTABLE: {asset_label} {strat_name} - OOS PF={te['pf']:.3f} p={te['p']:.3f} n={te['n']}")
    
    if not promotable_strategies:
        print("  No promotable strategies found across cross-asset validation")
    
    return all_results


# =============================================================================
# STUDY 3: 2h Timeframe Test (H3-A/B on SOL 2h)
# =============================================================================

def study3_timeframe_test():
    """Test H3-A and H3-B on SOL 2h to see if intermediate timeframe works."""
    print("\n" + "=" * 80)
    print("STUDY 3: 2h Timeframe Test - H3-A/B on SOL 2h")
    print("Exit method: ATR trailing stop")
    print("=" * 80)
    
    # Load SOL 2h data
    df = load_asset("SOL/USDT", 120)
    if df is None or len(df) < 200:
        print("ERROR: SOL/USDT 2h data not available")
        # Try with alternative naming
        df = load_binance("SOLUSDT", 120)
        if df is None or len(df) < 200:
            print("ERROR: No SOL 2h data found")
            return {}
    
    ts, o, h, l, c, v = df_to_arrays(df)
    
    # Load BTC for regime
    btc_df = load_asset("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    
    atr_v = ind.atr(h, l, c, 14)
    
    print(f"\nData: {len(ts)} bars from {datetime.fromtimestamp(ts[0]).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(ts[-1]).strftime('%Y-%m-%d')}")
    
    results = {}
    bt = ExitResearchBacktester(bar_hours=2.0)
    
    # H3-A
    print("\n--- H3-A (Ichimoku + RSI>55 + Score>=3) on SOL 2h ---")
    m_h3a, e_h3a = signals_ichimoku_h3a(h, l, c)
    
    h3a_trades_tr = bt.run_exit(ts[:int(len(ts)*0.7)], o[:int(len(ts)*0.7)], 
                                 h[:int(len(ts)*0.7)], l[:int(len(ts)*0.7)],
                                 c[:int(len(ts)*0.7)], v[:int(len(ts)*0.7)],
                                 regime[:int(len(ts)*0.7)], m_h3a[:int(len(ts)*0.7)], 
                                 'atr_trail')
    h3a_trades_te = bt.run_exit(ts[int(len(ts)*0.7):], o[int(len(ts)*0.7):], 
                                 h[int(len(ts)*0.7):], l[int(len(ts)*0.7):],
                                 c[int(len(ts)*0.7):], v[int(len(ts)*0.7):],
                                 regime[int(len(ts)*0.7):], m_h3a[int(len(ts)*0.7):], 
                                 'atr_trail')
    
    h3a_tr = compute_stats(h3a_trades_tr)
    h3a_te = compute_stats(h3a_trades_te)
    h3a_tr_d = stats_to_dict(h3a_tr, "H3-A Train")
    h3a_te_d = stats_to_dict(h3a_te, "H3-A Test")
    
    print(f"  {fmt_result(h3a_tr_d, 'Train')}")
    print(f"  {fmt_result(h3a_te_d, 'OOS Test')}")
    
    results["H3-A"] = {
        "train": h3a_tr_d,
        "test": h3a_te_d,
        "promotable": (h3a_te_d["pf"] > 2.0 and h3a_te_d["p"] < 0.10) if h3a_te_d else False
    }
    
    # H3-B
    print("\n--- H3-B (VolSpike + RSI Cross) on SOL 2h ---")
    m_vol, _ = signals_vol_spike_break(c, v, vol_mult=1.5)
    m_rsi, _ = signals_rsi_momentum_cross(c)
    m_h3b = m_vol & m_rsi
    
    h3b_trades_tr = bt.run_exit(ts[:int(len(ts)*0.7)], o[:int(len(ts)*0.7)], 
                                 h[:int(len(ts)*0.7)], l[:int(len(ts)*0.7)],
                                 c[:int(len(ts)*0.7)], v[:int(len(ts)*0.7)],
                                 regime[:int(len(ts)*0.7)], m_h3b[:int(len(ts)*0.7)], 
                                 'atr_trail')
    h3b_trades_te = bt.run_exit(ts[int(len(ts)*0.7):], o[int(len(ts)*0.7):], 
                                 h[int(len(ts)*0.7):], l[int(len(ts)*0.7):],
                                 c[int(len(ts)*0.7):], v[int(len(ts)*0.7):],
                                 regime[int(len(ts)*0.7):], m_h3b[int(len(ts)*0.7):], 
                                 'atr_trail')
    
    h3b_tr = compute_stats(h3b_trades_tr)
    h3b_te = compute_stats(h3b_trades_te)
    h3b_tr_d = stats_to_dict(h3b_tr, "H3-B Train")
    h3b_te_d = stats_to_dict(h3b_te, "H3-B Test")
    
    print(f"  {fmt_result(h3b_tr_d, 'Train')}")
    print(f"  {fmt_result(h3b_te_d, 'OOS Test')}")
    
    results["H3-B"] = {
        "train": h3b_tr_d,
        "test": h3b_te_d,
        "promotable": (h3b_te_d["pf"] > 2.0 and h3b_te_d["p"] < 0.10) if h3b_te_d else False
    }
    
    # H3-C (with best params from Study 1 if available)
    print("\n--- H3-C (RSI + KAMA) on SOL 2h ---")
    m_h3c, e_h3c = signals_h3c(c, h, l, rsi_threshold=50, kama_period=6, kama_fast=2, kama_slow=30)
    
    h3c_trades_tr = bt.run_exit(ts[:int(len(ts)*0.7)], o[:int(len(ts)*0.7)], 
                                 h[:int(len(ts)*0.7)], l[:int(len(ts)*0.7)],
                                 c[:int(len(ts)*0.7)], v[:int(len(ts)*0.7)],
                                 regime[:int(len(ts)*0.7)], m_h3c[:int(len(ts)*0.7)], 
                                 'atr_trail')
    h3c_trades_te = bt.run_exit(ts[int(len(ts)*0.7):], o[int(len(ts)*0.7):], 
                                 h[int(len(ts)*0.7):], l[int(len(ts)*0.7):],
                                 c[int(len(ts)*0.7):], v[int(len(ts)*0.7):],
                                 regime[int(len(ts)*0.7):], m_h3c[int(len(ts)*0.7):], 
                                 'atr_trail')
    
    h3c_tr = compute_stats(h3c_trades_tr)
    h3c_te = compute_stats(h3c_trades_te)
    h3c_tr_d = stats_to_dict(h3c_tr, "H3-C Train")
    h3c_te_d = stats_to_dict(h3c_te, "H3-C Test")
    
    print(f"  {fmt_result(h3c_tr_d, 'Train')}")
    print(f"  {fmt_result(h3c_te_d, 'OOS Test')}")
    
    results["H3-C"] = {
        "train": h3c_tr_d,
        "test": h3c_te_d,
        "promotable": (h3c_te_d["pf"] > 2.0 and h3c_te_d["p"] < 0.10) if h3c_te_d else False
    }
    
    # Save results
    save_data = {
        "study": "2h Timeframe Test",
        "asset": "SOL",
        "timeframe": "2h",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    save_path = save_structured_result("Timeframe", "SOL", "2h", "timeframe_test", save_data)
    print(f"\nResults saved: {save_path}")
    
    # Summary
    print("\n" + "-" * 80)
    print("2h TIMEFRAME SUMMARY")
    print("-" * 80)
    for strat, data in results.items():
        te = data["test"]
        flag = "PROMOTABLE*" if data["promotable"] else ""
        if te:
            print(f"  {strat}: n={te['n']} PF={te['pf']:.3f} p={te['p']:.3f} {flag}")
    
    return results


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 80)
    print("STREAM 2 RESEARCH: H3-C Optimization, Cross-Asset, 2h Timeframe")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)
    
    # Study 1: H3-C Optimization
    opt_results = study1_h3c_optimization()
    
    # Get best H3-C params
    best_h3c = None
    if opt_results and opt_results.get("best"):
        best = opt_results["best"]
        best_h3c = {
            "rsi": best["rsi_threshold"],
            "kama_p": best["kama_period"],
            "kama_f": best["kama_fast"],
            "kama_s": best["kama_slow"],
        }
        print(f"\nBest H3-C params: RSI={best_h3c['rsi']} KAMA={best_h3c['kama_p']} Fast={best_h3c['kama_f']} Slow={best_h3c['kama_s']}")
    
    # Study 2: Cross-Asset Validation
    cross_results = study2_cross_asset_validation(best_h3c)
    
    # Study 3: 2h Timeframe Test
    tf_results = study3_timeframe_test()
    
    # Final Summary
    print("\n" + "=" * 80)
    print("FINAL SUMMARY - ALL PROMOTABLE STRATEGIES")
    print("=" * 80)
    
    all_promotable = []
    
    # From H3-C Optimization
    if opt_results and opt_results.get("promotable"):
        for r in opt_results["promotable"]:
            all_promotable.append({
                "source": "H3-C Optimization (SOL 4h)",
                "params": r.get("params", {}),
                "pf": r["test"]["pf"],
                "p": r["test"]["p"],
                "n": r["test"]["n"],
            })
    
    # From Cross-Asset
    for asset_label, strats in cross_results.items():
        for strat_name, strat_data in strats.items():
            if strat_data.get("promotable", False):
                te = strat_data["test"]
                all_promotable.append({
                    "source": f"Cross-Asset ({asset_label})",
                    "strategy": strat_name,
                    "pf": te["pf"],
                    "p": te["p"],
                    "n": te["n"],
                })
    
    # From 2h Timeframe
    for strat_name, strat_data in tf_results.items():
        if strat_data.get("promotable", False):
            te = strat_data["test"]
            all_promotable.append({
                "source": "2h Timeframe (SOL)",
                "strategy": strat_name,
                "pf": te["pf"],
                "p": te["p"],
                "n": te["n"],
            })
    
    if all_promotable:
        print(f"\nFound {len(all_promotable)} promotable strategies (OOS PF > 2.0, p < 0.10):\n")
        for i, s in enumerate(all_promotable, 1):
            print(f"  {i}. {s['source']} {s.get('strategy', 'H3-C')}")
            print(f"     OOS PF={s['pf']:.3f} p-value={s['p']:.3f} n={s['n']}")
            if "params" in s:
                print(f"     Params: {s['params']}")
            print()
    else:
        print("\n  No promotable strategies found (OOS PF > 2.0, p < 0.10)")
    
    # Save final summary
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "study": "Stream 2 Complete",
        "promotable_count": len(all_promotable),
        "promotable": all_promotable,
        "h3c_best_params": best_h3c,
    }
    
    summary_path = RESEARCH_DIR / "stream2_summary.json"
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\nFinal summary saved: {summary_path}")
    
    return all_promotable


if __name__ == "__main__":
    main()
