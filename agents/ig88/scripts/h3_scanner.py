#!/usr/bin/env python3
"""
h3_scanner.py — Live signal scanner for H3-A, H3-B, H3-C strategies.

Fetches latest 4h SOL/USDT data, evaluates all three strategies,
logs any active signals to data/paper_trades.jsonl, and prints a status report.

Designed to run every 4 hours (cron or timer).

Usage:
    python3 /Users/nesbitt/dev/factory/agents/ig88/scripts/h3_scanner.py
    python3 /Users/nesbitt/dev/factory/agents/ig88/scripts/h3_scanner.py --dry-run

H3-A: Ichimoku TK cross + above cloud + RSI > 55 + ichi_score >= 3 + not RISK_OFF
H3-B: Volume > 1.5× 20MA on +0.5% bar AND RSI crosses 50
H3-C: RSI crosses 50 AND price crosses above KAMA
"""

import sys, json, argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("/Users/nesbitt/dev/factory/agents/ig88")
sys.path.insert(0, str(ROOT))

import numpy as np
import src.quant.indicators as ind
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays
from src.quant.historical_fetcher import (
    fetch_binance_full, incremental_update, load_cached, save_cached, cache_path
)
from src.quant.regime import RegimeState

DATA_DIR = ROOT / "data"
PAPER_TRADES = DATA_DIR / "paper_trades.jsonl"
SCAN_LOG     = DATA_DIR / "scan_log.jsonl"


# ---------------------------------------------------------------------------
# Signal evaluation
# ---------------------------------------------------------------------------

def check_h3a(h, l, c, v, regime, i):
    """H3-A: Ichimoku convergence."""
    ichi  = ind.ichimoku(h, l, c)
    score = ind.ichimoku_composite_score(ichi, c)
    rsi_v = ind.rsi(c, 14)
    tk    = ichi.tk_cross_signals()

    cloud_top = max(
        ichi.senkou_span_a[i] if not np.isnan(ichi.senkou_span_a[i]) else -np.inf,
        ichi.senkou_span_b[i] if not np.isnan(ichi.senkou_span_b[i]) else -np.inf,
    )
    atr_v = ind.atr(h, l, c, 14)[i]

    conditions = {
        "tk_cross":     bool(tk[i] == 1),
        "above_cloud":  bool(not np.isnan(cloud_top) and c[i] > cloud_top),
        "rsi_55":       bool(not np.isnan(rsi_v[i]) and rsi_v[i] > 55),
        "ichi_score3":  bool(score[i] >= 3),
        "regime_ok":    bool(regime[i] != RegimeState.RISK_OFF),
    }
    active = all(conditions.values())

    return {
        "strategy": "H3-A",
        "active": active,
        "conditions": conditions,
        "diagnostics": {
            "close":      float(c[i]),
            "cloud_top":  float(cloud_top) if not np.isnan(cloud_top) else None,
            "rsi":        float(rsi_v[i]) if not np.isnan(rsi_v[i]) else None,
            "ichi_score": int(score[i]),
            "tenkan":     float(ichi.tenkan_sen[i]) if not np.isnan(ichi.tenkan_sen[i]) else None,
            "kijun":      float(ichi.kijun_sen[i]) if not np.isnan(ichi.kijun_sen[i]) else None,
            "atr":        float(atr_v) if not np.isnan(atr_v) else None,
        },
        "entry_price":  float(c[i]),
        "initial_stop": float(c[i] - 2.0 * atr_v) if not np.isnan(atr_v) else None,
        "target_cap":   float(c[i] + 5.0 * atr_v) if not np.isnan(atr_v) else None,
        "exit_method":  "atr_trail",  # trail stop upward each bar
    }


def check_h3b(h, l, c, v, regime, i):
    """H3-B: Volume ignition + RSI cross."""
    rsi_v  = ind.rsi(c, 14)
    vol_ma = ind.sma(v, 20)
    atr_v  = ind.atr(h, l, c, 14)[i]

    price_gain_pct = float((c[i] - c[i-1]) / c[i-1] * 100) if i > 0 else 0.0
    vol_mult       = float(v[i] / vol_ma[i]) if (not np.isnan(vol_ma[i]) and vol_ma[i] > 0) else 0.0
    rsi_cross      = (not np.isnan(rsi_v[i]) and not np.isnan(rsi_v[i-1])
                      and rsi_v[i] > 50 and rsi_v[i-1] <= 50)

    conditions = {
        "vol_spike_1_5x": bool(vol_mult >= 1.5),
        "price_gain_0_5": bool(price_gain_pct >= 0.5),
        "rsi_cross_50":   bool(rsi_cross),
        "regime_ok":      bool(regime[i] != RegimeState.RISK_OFF),
    }
    active = all(conditions.values())

    return {
        "strategy": "H3-B",
        "active": active,
        "conditions": conditions,
        "diagnostics": {
            "close":         float(c[i]),
            "vol_mult":      round(vol_mult, 2),
            "price_gain_pct": round(price_gain_pct, 3),
            "rsi":           float(rsi_v[i]) if not np.isnan(rsi_v[i]) else None,
            "rsi_prev":      float(rsi_v[i-1]) if not np.isnan(rsi_v[i-1]) else None,
            "atr":           float(atr_v) if not np.isnan(atr_v) else None,
        },
        "entry_price":  float(c[i]),
        "initial_stop": float(c[i] - 2.0 * atr_v) if not np.isnan(atr_v) else None,
        "target_cap":   float(c[i] + 5.0 * atr_v) if not np.isnan(atr_v) else None,
        "exit_method":  "atr_trail",   # upgraded from fixed 2x/3x
    }


def check_h3c(h, l, c, v, regime, i):
    """H3-C: RSI × KAMA cross."""
    rsi_v = ind.rsi(c, 14)
    kama  = ind.kama(c, period=6)
    atr_v = ind.atr(h, l, c, 14)[i]

    rsi_cross  = (not np.isnan(rsi_v[i]) and not np.isnan(rsi_v[i-1])
                  and rsi_v[i] > 50 and rsi_v[i-1] <= 50)
    kama_cross = (not np.isnan(kama[i]) and not np.isnan(kama[i-1])
                  and c[i] > kama[i] and c[i-1] <= kama[i-1])

    conditions = {
        "rsi_cross_50": bool(rsi_cross),
        "kama_cross":   bool(kama_cross),
        "regime_ok":    bool(regime[i] != RegimeState.RISK_OFF),
    }
    active = all(conditions.values())

    return {
        "strategy": "H3-C",
        "active": active,
        "conditions": conditions,
        "diagnostics": {
            "close":  float(c[i]),
            "kama":   float(kama[i]) if not np.isnan(kama[i]) else None,
            "rsi":    float(rsi_v[i]) if not np.isnan(rsi_v[i]) else None,
            "atr":    float(atr_v) if not np.isnan(atr_v) else None,
        },
        "entry_price":  float(c[i]),
        "stop":         float(c[i] - 2.0 * atr_v) if not np.isnan(atr_v) else None,
        "target":       float(c[i] + 3.0 * atr_v) if not np.isnan(atr_v) else None,
    }


# ---------------------------------------------------------------------------
# Regime assessment
# ---------------------------------------------------------------------------

def get_regime(btc_df, asset_ts):
    import pandas as pd
    btc_ts_arr = btc_df.index.astype("int64").values / 1e9
    _, _, _, _, btc_c, _ = df_to_arrays(btc_df)
    # BTC 20-bar rolling return at most recent BTC bar <= asset_ts[-1]
    idx = np.searchsorted(btc_ts_arr, asset_ts[-1], side="right") - 1
    if idx < 20:
        return RegimeState.NEUTRAL, 0.0
    ret = (btc_c[idx] - btc_c[idx - 20]) / btc_c[idx - 20] * 100
    if ret > 5.0:
        state = RegimeState.RISK_ON
    elif ret < -5.0:
        state = RegimeState.RISK_OFF
    else:
        state = RegimeState.NEUTRAL
    return state, round(float(ret), 2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Evaluate signals but don't log paper trades")
    parser.add_argument("--symbol", default="SOL/USDT",
                        help="Symbol to scan (default: SOL/USDT)")
    args = parser.parse_args()

    now_utc = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"H3 SCANNER — {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Symbol: {args.symbol} 4h  |  Dry run: {args.dry_run}")
    print(f"{'='*60}\n")

    # Refresh data
    print("Refreshing BTC/USD daily (regime)...")
    btc_df = None
    for sym, itvl in [("BTC/USD", 1440)]:
        p = cache_path("binance", sym, itvl)
        if p.exists():
            import pandas as pd
            btc_df = pd.read_parquet(p)
            print(f"  Loaded {sym} {itvl}m: {len(btc_df)} bars")

    print(f"Refreshing {args.symbol} 4h...")
    sol_df = None
    for sym, itvl in [(args.symbol, 240)]:
        p = cache_path("binance", sym, itvl)
        if p.exists():
            import pandas as pd
            sol_df = pd.read_parquet(p)
            print(f"  Loaded {sym} {itvl}m: {len(sol_df)} bars")

    if btc_df is None or sol_df is None:
        print("ERROR: Required data not available. Run historical_fetcher.py first.")
        sys.exit(1)

    # Convert to arrays
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    asset_ts = ts
    n = len(ts)
    i = n - 1  # latest complete bar

    bar_dt = datetime.utcfromtimestamp(ts[i]).strftime('%Y-%m-%d %H:%M UTC')
    print(f"\nLatest bar: {bar_dt}  Close: ${c[i]:,.2f}")

    # Macro regime
    regime_state, btc_20bar_ret = get_regime(btc_df, asset_ts)
    regime_arr = np.full(n, regime_state, dtype=object)
    print(f"Macro regime: {regime_state.value}  (BTC 20-bar: {btc_20bar_ret:+.1f}%)\n")

    # Evaluate all strategies on latest bar
    results = [
        check_h3a(h, l, c, v, regime_arr, i),
        check_h3b(h, l, c, v, regime_arr, i),
        check_h3c(h, l, c, v, regime_arr, i),
    ]

    signals_fired = [r for r in results if r["active"]]

    # Print status
    for r in results:
        status = "*** SIGNAL ***" if r["active"] else "no signal"
        print(f"[{r['strategy']}] {status}")
        for cname, cval in r["conditions"].items():
            tick = "✓" if cval else "✗"
            print(f"  {tick} {cname}")

        diag = r.get("diagnostics", {})
        if diag:
            diag_str = "  ".join(f"{k}={v}" for k, v in diag.items() if v is not None)
            print(f"  → {diag_str}")

        if r["active"]:
            print(f"  ENTRY: ${r['entry_price']:,.3f}  "
                  f"STOP: ${r['stop']:,.3f}  TARGET: ${r['target']:,.3f}")
        print()

    # Log signals
    if signals_fired and not args.dry_run:
        for r in signals_fired:
            record = {
                "timestamp":    now_utc.isoformat(),
                "bar_time":     bar_dt,
                "strategy":     r["strategy"],
                "symbol":       args.symbol,
                "interval":     "4h",
                "entry_price":  r["entry_price"],
                "stop":         r["stop"],
                "target":       r["target"],
                "regime":       regime_state.value,
                "btc_20bar_ret": btc_20bar_ret,
                "conditions":   r["conditions"],
                "diagnostics":  r["diagnostics"],
                "status":       "OPEN",
                "exit_price":   None,
                "exit_time":    None,
                "pnl_pct":      None,
            }
            with open(PAPER_TRADES, "a") as f:
                f.write(json.dumps(record) + "\n")
            print(f"*** LOGGED: {r['strategy']} signal at ${r['entry_price']:,.3f} ***")
    elif signals_fired and args.dry_run:
        print("(dry-run: signals not logged)")
    else:
        print("No signals active. Nothing logged.")

    # Log scan run
    scan_record = {
        "timestamp":     now_utc.isoformat(),
        "symbol":        args.symbol,
        "close":         float(c[i]),
        "regime":        regime_state.value,
        "btc_20bar_ret": btc_20bar_ret,
        "signals_fired": [r["strategy"] for r in signals_fired],
        "dry_run":       args.dry_run,
    }
    with open(SCAN_LOG, "a") as f:
        f.write(json.dumps(scan_record) + "\n")

    print(f"\nScan complete. Log: {SCAN_LOG}")

    # Summary
    if signals_fired:
        print(f"\n*** {len(signals_fired)} SIGNAL(S) ACTIVE: "
              f"{', '.join(r['strategy'] for r in signals_fired)} ***")
    else:
        print("\nAll clear. No active signals.")

    return len(signals_fired)


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 0)
