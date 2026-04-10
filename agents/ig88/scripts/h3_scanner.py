#!/usr/bin/env python3
"""
h3_scanner.py — Live signal scanner for H3-A, H3-B, H3-C, H3-D strategies.

Runs every 4h via cron (job 656fd5138b85).
Fetches fresh Kraken SOL/USD 4h data, evaluates all strategies,
logs signals via paper_trader_live.py, monitors open positions for exits.

Requires: infisical secrets injected at runtime
  infisical run --token=<token> -- python3 scripts/h3_scanner.py

Paper trades logged to: data/paper_trades.jsonl
Scan log:               data/scan_log.jsonl
"""

import sys, json, argparse
from pathlib import Path
from datetime import datetime, timezone
import urllib.request

ROOT = Path("/Users/nesbitt/dev/factory/agents/ig88")
sys.path.insert(0, str(ROOT))

import numpy as np
import src.quant.indicators as ind
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays
from src.quant.historical_fetcher import fetch_binance_full, load_cached, save_cached
from src.quant.regime import RegimeState
from src.quant.paper_trader_live import (
    open_paper_trade, check_and_update_open_trades,
    get_trade_summary, print_open_positions
)

DATA_DIR  = ROOT / "data"
SCAN_LOG  = DATA_DIR / "scan_log.jsonl"


# ---------------------------------------------------------------------------
# Data fetching — Kraken for signals, Binance for history
# ---------------------------------------------------------------------------

def get_latest_sol_4h():
    """
    Load SOL/USDT 4h data. Refresh from Binance if stale.
    Returns DataFrame.
    """
    import pandas as pd
    import time
    cache_p = DATA_DIR / "binance_SOL_USDT_240m.parquet"

    if cache_p.exists():
        df = pd.read_parquet(cache_p)
        age_hours = (time.time() - cache_p.stat().st_mtime) / 3600
        if age_hours < 4.5:  # fresh enough
            return df

    # Refresh
    print("  Refreshing SOL/USDT 4h from Binance...")
    new_data = fetch_binance_full("SOLUSDT", 240)
    if not new_data.empty:
        old = pd.read_parquet(cache_p) if cache_p.exists() else pd.DataFrame()
        combined = pd.concat([old, new_data]).pipe(
            lambda df: df[~df.index.duplicated(keep="last")]).sort_index()
        combined.to_parquet(cache_p)
        return combined
    return df  # return stale if refresh fails


def get_btc_regime_data():
    """Load BTC daily data for regime detection."""
    import pandas as pd
    p = DATA_DIR / "binance_BTC_USD_1440m.parquet"
    df = pd.read_parquet(p)
    ts = df.index.astype("int64").values / 1e9
    c  = df["close"].values.astype(float)
    return ts, c


def get_current_btc_price() -> float:
    """Fetch current BTC price from CoinGecko (or cached)."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "IG-88/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return float(json.loads(r.read())["bitcoin"]["usd"])
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Signal evaluation — all strategies
# ---------------------------------------------------------------------------

def evaluate_all_signals(df, regime_arr, i: int) -> dict:
    """Evaluate all H3 strategy conditions at bar i. Returns dict of results."""
    ts, o, h, l, c, v = df_to_arrays(df)
    n = len(ts)
    if i >= n:
        return {}

    # Pre-compute indicators
    ichi    = ind.ichimoku(h, l, c)
    score   = ind.ichimoku_composite_score(ichi, c)
    rsi_v   = ind.rsi(c, 14)
    tk      = ichi.tk_cross_signals()
    atr_v   = ind.atr(h, l, c, 14)
    vol_ma  = ind.sma(v, 20)
    kama_v  = ind.kama(c, period=4)
    obv_v   = ind.obv(c, v)
    ema10   = ind.ema(obv_v, 10)

    regime_ok = regime_arr[i] != RegimeState.RISK_OFF
    cloud_top = max(
        ichi.senkou_span_a[i] if not np.isnan(ichi.senkou_span_a[i]) else -np.inf,
        ichi.senkou_span_b[i] if not np.isnan(ichi.senkou_span_b[i]) else -np.inf,
    )
    atr_now = atr_v[i] if not np.isnan(atr_v[i]) else 0.0

    results = {}

    # H3-A: Ichimoku convergence
    h3a_conds = {
        "tk_cross":    bool(tk[i] == 1),
        "above_cloud": bool(not np.isnan(cloud_top) and c[i] > cloud_top),
        "rsi_55":      bool(not np.isnan(rsi_v[i]) and rsi_v[i] > 55),
        "ichi_score3": bool(score[i] >= 3),
        "regime_ok":   bool(regime_ok),
    }
    results["H3-A"] = {
        "active":     all(h3a_conds.values()),
        "conditions": h3a_conds,
        "diagnostics": {
            "close": float(c[i]), "cloud_top": float(cloud_top) if not np.isnan(cloud_top) else None,
            "rsi": float(rsi_v[i]) if not np.isnan(rsi_v[i]) else None,
            "ichi_score": int(score[i]),
            "tenkan": float(ichi.tenkan_sen[i]) if not np.isnan(ichi.tenkan_sen[i]) else None,
            "kijun":  float(ichi.kijun_sen[i])  if not np.isnan(ichi.kijun_sen[i])  else None,
            "atr": float(atr_now),
        },
    }

    # H3-B: Volume ignition + RSI cross
    if i > 0 and not np.isnan(vol_ma[i]) and vol_ma[i] > 0:
        price_gain = (c[i] - c[i-1]) / c[i-1] if c[i-1] > 0 else 0.0
        h3b_conds = {
            "vol_1_5x":     bool(v[i] > 1.5 * vol_ma[i]),
            "price_gain":   bool(price_gain > 0.005),
            "rsi_cross_50": bool(not np.isnan(rsi_v[i]) and not np.isnan(rsi_v[i-1])
                                  and rsi_v[i] > 50 and rsi_v[i-1] <= 50),
            "regime_ok":    bool(regime_ok),
        }
        results["H3-B"] = {
            "active":     all(h3b_conds.values()),
            "conditions": h3b_conds,
            "diagnostics": {
                "close": float(c[i]), "vol_mult": round(v[i]/vol_ma[i], 2),
                "price_gain_pct": round(price_gain*100, 3),
                "rsi": float(rsi_v[i]) if not np.isnan(rsi_v[i]) else None,
                "atr": float(atr_now),
            },
        }

    # H3-C: RSI × KAMA cross
    if i > 0:
        h3c_conds = {
            "rsi_cross_52": bool(not np.isnan(rsi_v[i]) and not np.isnan(rsi_v[i-1])
                                  and rsi_v[i] > 52 and rsi_v[i-1] <= 52),
            "kama_cross":   bool(not np.isnan(kama_v[i]) and not np.isnan(kama_v[i-1])
                                  and c[i] > kama_v[i] and c[i-1] <= kama_v[i-1]),
            "regime_ok":    bool(regime_ok),
        }
        results["H3-C"] = {
            "active":     all(h3c_conds.values()),
            "conditions": h3c_conds,
            "diagnostics": {
                "close": float(c[i]),
                "kama": float(kama_v[i]) if not np.isnan(kama_v[i]) else None,
                "rsi":  float(rsi_v[i]) if not np.isnan(rsi_v[i]) else None,
                "atr":  float(atr_now),
            },
        }

    # H3-D: OBV EMA cross + RSI cross
    if i > 0:
        h3d_conds = {
            "obv_cross":    bool(not np.isnan(ema10[i]) and not np.isnan(ema10[i-1])
                                  and obv_v[i] > ema10[i] and obv_v[i-1] <= ema10[i-1]),
            "rsi_cross_50": bool(not np.isnan(rsi_v[i]) and not np.isnan(rsi_v[i-1])
                                  and rsi_v[i] > 50 and rsi_v[i-1] <= 50),
            "regime_ok":    bool(regime_ok),
        }
        results["H3-D"] = {
            "active":     all(h3d_conds.values()),
            "conditions": h3d_conds,
            "diagnostics": {
                "close": float(c[i]),
                "obv_above_ema10": bool(obv_v[i] > ema10[i]) if not np.isnan(ema10[i]) else None,
                "rsi":   float(rsi_v[i]) if not np.isnan(rsi_v[i]) else None,
                "atr":   float(atr_now),
            },
        }

    # Attach shared entry params to active signals
    for strat, res in results.items():
        if res["active"]:
            res["entry_price"]  = float(c[i])
            res["atr"]          = float(atr_now)
            res["initial_stop"] = float(c[i] - 2.0 * atr_now) if atr_now else None
            res["target_cap"]   = float(c[i] + 5.0 * atr_now) if atr_now else None
            res["kijun"]        = (float(ichi.kijun_sen[i])
                                   if not np.isnan(ichi.kijun_sen[i]) else None)

    return results


# ---------------------------------------------------------------------------
# Exit monitoring — check open positions
# ---------------------------------------------------------------------------

def monitor_open_positions(df, regime_arr) -> list[dict]:
    """Update trailing stops and close any triggered positions."""
    ts, o, h, l, c, v = df_to_arrays(df)
    i = len(ts) - 1  # latest bar
    atr_v  = ind.atr(h, l, c, 14)
    ichi   = ind.ichimoku(h, l, c)

    current_price  = float(c[i])
    current_atr    = float(atr_v[i]) if not np.isnan(atr_v[i]) else 0.0
    current_kijun  = float(ichi.kijun_sen[i]) if not np.isnan(ichi.kijun_sen[i]) else None

    closed = check_and_update_open_trades(
        current_prices={"SOL/USD": current_price, "SOL/USDT": current_price},
        current_atrs={"SOL/USD": current_atr, "SOL/USDT": current_atr},
        current_kijuns={"SOL/USD": current_kijun, "SOL/USDT": current_kijun} if current_kijun else None,
    )
    return closed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Evaluate signals but don't log paper trades")
    parser.add_argument("--symbol", default="SOL/USDT", help="Symbol to scan")
    parser.add_argument("--status", action="store_true", help="Show paper trading status and exit")
    args = parser.parse_args()

    now_utc = datetime.now(timezone.utc)
    print(f"\n{'='*60}")
    print(f"H3 SCANNER — {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Symbol: {args.symbol} 4h  |  Dry run: {args.dry_run}")
    print(f"{'='*60}")

    # Status-only mode
    if args.status:
        summary = get_trade_summary()
        print(f"\nPaper Trading Status:")
        print(f"  Closed trades: {summary['total_trades']}")
        if summary['total_trades'] > 0:
            print(f"  Win rate: {summary['win_rate']}%")
            print(f"  Profit factor: {summary['profit_factor']}")
            print(f"  Total net PnL: {summary['total_net_pnl_pct']:+.2f}%  "
                  f"(${summary['total_net_pnl_usd']:+.2f})")
        print(f"\n  Open positions: {summary['open_trades']}")
        print_open_positions()
        return 0

    # Load data
    print("\nLoading data...")
    try:
        df = get_latest_sol_4h()
        print(f"  SOL 4h: {len(df)} bars, latest: {df.index[-1]}")
    except Exception as e:
        print(f"  ERROR loading data: {e}")
        return 1

    btc_ts, btc_c = get_btc_regime_data()
    ts, o, h, l, c, v = df_to_arrays(df)
    regime_arr = build_btc_trend_regime(btc_c, ts, btc_ts)

    # Regime summary
    btc_price = get_current_btc_price()
    regime_state = regime_arr[-1].value if hasattr(regime_arr[-1], 'value') else str(regime_arr[-1])
    print(f"\nRegime: {regime_state}  |  BTC: ${btc_price:,.0f}  |  SOL: ${c[-1]:,.2f}")

    # Monitor open positions first
    print("\nMonitoring open positions...")
    closed_this_cycle = monitor_open_positions(df, regime_arr)
    if closed_this_cycle:
        print(f"  Closed {len(closed_this_cycle)} position(s) this cycle")
    else:
        open_trades = __import__('src.quant.paper_trader_live',
                                  fromlist=['get_open_trades']).get_open_trades()
        if open_trades:
            print(f"  {len(open_trades)} position(s) still open, trailing stops updated")
        else:
            print("  No open positions to monitor")

    # Evaluate signals on latest bar
    print("\nEvaluating signals...")
    i = len(ts) - 1
    signal_results = evaluate_all_signals(df, regime_arr, i)

    signals_fired = []
    for strat, res in signal_results.items():
        status = "*** SIGNAL ***" if res["active"] else "no signal"
        print(f"\n  [{strat}] {status}")
        for cname, cval in res.get("conditions", {}).items():
            tick = "✓" if cval else "✗"
            print(f"    {tick} {cname}")

        diag = res.get("diagnostics", {})
        if diag:
            diag_str = "  ".join(f"{k}={v}" for k, v in diag.items() if v is not None)
            print(f"    → {diag_str}")

        if res["active"]:
            ep = res.get("entry_price", c[i])
            print(f"    ENTRY: ${ep:,.3f}  STOP: ${res.get('initial_stop', 0):,.3f}  "
                  f"TARGET CAP: ${res.get('target_cap', 0):,.3f}")
            signals_fired.append((strat, res))

    # Log signals to paper trader
    if signals_fired and not args.dry_run:
        print(f"\n  Logging {len(signals_fired)} signal(s) as paper trades...")
        for strat, res in signals_fired:
            trade = open_paper_trade(
                strategy=strat,
                symbol=args.symbol,
                entry_price=res["entry_price"],
                atr_at_entry=res["atr"],
                regime=regime_state,
                btc_price=btc_price,
                signal_conditions=res["conditions"],
                venue="kraken_spot",
                notes=f"Scanner run {now_utc.strftime('%Y-%m-%d %H:%M UTC')}",
            )
            print(f"  *** LOGGED: {trade['id']} — {strat} entry ${trade['entry_price']:.3f} ***")
    elif signals_fired and args.dry_run:
        print("\n  (dry-run: signals not logged)")
    else:
        print("\n  No signals active. Nothing logged.")

    # Scan log entry
    scan_record = {
        "timestamp":     now_utc.isoformat(),
        "symbol":        args.symbol,
        "close":         float(c[i]),
        "btc_price":     btc_price,
        "regime":        regime_state,
        "signals_fired": [s for s, _ in signals_fired],
        "positions_closed": len(closed_this_cycle),
        "dry_run":       args.dry_run,
    }
    with open(SCAN_LOG, "a") as f:
        f.write(json.dumps(scan_record) + "\n")

    # Summary
    summary = get_trade_summary()
    print(f"\n{'='*60}")
    print(f"Paper Trading Summary: {summary['total_trades']} closed, "
          f"{summary['open_trades']} open")
    if summary['total_trades'] > 0:
        print(f"  WR={summary['win_rate']}%  PF={summary['profit_factor']}  "
              f"Net={summary['total_net_pnl_pct']:+.2f}%")

    if signals_fired:
        print(f"\n*** {len(signals_fired)} SIGNAL(S): {', '.join(s for s, _ in signals_fired)} ***")
    else:
        print(f"\nAll clear. Regime: {regime_state}. Watching.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
