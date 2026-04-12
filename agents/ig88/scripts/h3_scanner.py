#!/usr/bin/env python3
"""
h3_scanner.py — Live signal scanner for H3 strategies.
Now expanded to multi-asset parallel scanning and integrated with KrakenExecutor.
"""

import sys, json, argparse
from pathlib import Path
from datetime import datetime, timezone
import urllib.request
import numpy as np

ROOT = Path("/Users/nesbitt/dev/factory/agents/ig88")
sys.path.insert(0, str(ROOT))

import pandas as pd
import src.quant.indicators as ind
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays
from src.quant.historical_fetcher import fetch_binance_full, load_cached, save_cached
from src.quant.regime import RegimeState
from src.quant.paper_trader_live import (
    open_paper_trade, check_and_update_open_trades,
    get_trade_summary, print_open_positions
)
from src.trading.kraken_executor import KrakenExecutor

DATA_DIR  = ROOT / "data"
SCAN_LOG  = DATA_DIR / "scan_log.jsonl"

# Validated assets for H3 logic
VALID_ASSETS = {
    "SOL": {"pair": "SOL/USDT", "kraken": "SOLUSD"},
    "BTC": {"pair": "BTC/USDT", "kraken": "BTCUSD"},
    "ETH": {"pair": "ETH/USDT", "kraken": "ETHUSD"},
    "LINK": {"pair": "LINK/USDT", "kraken": "LINKUSD"},
    "AVAX": {"pair": "AVAX/USDT", "kraken": "AVAXUSD"},
    "NEAR": {"pair": "NEAR/USDT", "kraken": "NEARUSD"},
}

def get_asset_4h_data(symbol: str):
    """Fetch/Load 4h data for a specific symbol."""
    cache_p = DATA_DIR / f"binance_{symbol.replace('/', '_')}_240m.parquet"
    if cache_p.exists():
        df = pd.read_parquet(cache_p)
        import time
        if (time.time() - cache_p.stat().st_mtime) / 3600 < 4.5:
            return df
    
    print(f"  Refreshing {symbol} 4h from Binance...")
    new_data = fetch_binance_full(symbol.replace('/', ''), 240)
    if not new_data.empty:
        old = pd.read_parquet(cache_p) if cache_p.exists() else pd.DataFrame()
        combined = pd.concat([old, new_data]).pipe(
            lambda df: df[~df.index.duplicated(keep="last")]).sort_index()
        combined.to_parquet(cache_p)
        return combined
    return df if 'df' in locals() else pd.DataFrame()

def get_btc_regime_data():
    p = DATA_DIR / "binance_BTC_USD_1440m.parquet"
    df = pd.read_parquet(p)
    ts = df.index.astype("int64").values / 1e9
    c  = df["close"].values.astype(float)
    return ts, c

def get_current_btc_price() -> float:
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        req = urllib.request.Request(url, headers={"User-Agent": "IG-88/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return float(json.loads(r.read())["bitcoin"]["usd"])
    except Exception:
        return 0.0

def evaluate_all_signals(df, regime_arr, i: int) -> dict:
    ts, o, h, l, c, v = df_to_arrays(df)
    n = len(ts)
    if i >= n: return {}

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
    cloud_top = max(ichi.senkou_span_a[i] if not np.isnan(ichi.senkou_span_a[i]) else -np.inf,
                    ichi.senkou_span_b[i] if not np.isnan(ichi.senkou_span_b[i]) else -np.inf)
    atr_now = atr_v[i] if not np.isnan(atr_v[i]) else 0.0

    results = {}
    # H3-A
    h3a_conds = {
        "tk_cross": bool(tk[i] == 1),
        "above_cloud": bool(not np.isnan(cloud_top) and c[i] > cloud_top),
        "rsi_55": bool(not np.isnan(rsi_v[i]) and rsi_v[i] > 55),
        "ichi_score3": bool(score[i] >= 3),
        "regime_ok": bool(regime_ok),
    }
    results["H3-A"] = {"active": all(h3a_conds.values()), "conditions": h3a_conds, "diagnostics": {"close": float(c[i]), "atr": float(atr_now)}}

    # H3-B
    if i > 0 and not np.isnan(vol_ma[i]) and vol_ma[i] > 0:
        price_gain = (c[i] - c[i-1]) / c[i-1] if c[i-1] > 0 else 0.0
        h3b_conds = {
            "vol_1_5x": bool(v[i] > 1.5 * vol_ma[i]),
            "price_gain": bool(price_gain > 0.005),
            "rsi_cross_50": bool(not np.isnan(rsi_v[i]) and not np.isnan(rsi_v[i-1]) and rsi_v[i] > 50 and rsi_v[i-1] <= 50),
            "regime_ok": bool(regime_ok),
        }
        results["H3-B"] = {"active": all(h3b_conds.values()), "conditions": h3b_conds, "diagnostics": {"close": float(c[i]), "atr": float(atr_now)}}

    for strat, res in results.items():
        if res["active"]:
            res["entry_price"] = float(c[i])
            res["atr"] = float(atr_now)
            res["initial_stop"] = float(c[i] - 2.0 * atr_now) if atr_now else None
            res["target_cap"] = float(c[i] + 5.0 * atr_now) if atr_now else None

    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live-mode", action="store_true", help="Enable live execution via KrakenExecutor")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.status:
        summary = get_trade_summary()
        print(f"Paper Trading Summary: {summary['total_trades']} closed, {summary['open_trades']} open")
        print_open_positions()
        return 0

    executor = None
    if args.live_mode:
        try:
            executor = KrakenExecutor()
            print("  LIVE MODE ENABLED: KrakenExecutor initialized.")
        except Exception as e:
            print(f"  Error initializing executor: {e}. Falling back to paper only.")

    btc_ts, btc_c = get_btc_regime_data()
    btc_price = get_current_btc_price()
    now_utc = datetime.now(timezone.utc)
    
    print(f"\\n{'='*60}\\nH3 MULTI-ASSET SCANNER — {now_utc.strftime('%Y-%m-%d %H:%M UTC')}\\n{'='*60}")
    print(f"Regime: {build_btc_trend_regime(btc_c, btc_ts, btc_ts)[-1]} | BTC: ${btc_price:,.0f}")

    for asset, info in VALID_ASSETS.items():
        print(f"\\nScanning {asset} ({info['pair']})...")
        try:
            df = get_asset_4h_data(info['pair'])
            ts, o, h, l, c, v = df_to_arrays(df)
            regime_arr = build_btc_trend_regime(btc_c, ts, btc_ts)
            i = len(ts) - 1
            
            # Monitor exits for this asset
            closed = check_and_update_open_trades(
                current_prices={info['pair']: float(c[i])},
                current_atrs={info['pair']: float(ind.atr(h, l, c, 14)[i])},
                current_kijuns=None
            )
            if closed: print(f"  Closed {len(closed)} positions for {asset}")

            signal_results = evaluate_all_signals(df, regime_arr, i)
            
            for strat, res in signal_results.items():
                if res["active"]:
                    print(f"  *** {strat} SIGNAL for {asset} at ${res['entry_price']:.3f} ***")
                    
                    # 1. Paper Trade Log (Shadow)
                    open_paper_trade(
                        strategy=strat, symbol=info['pair'], entry_price=res["entry_price"],
                        atr_at_entry=res["atr"], regime=regime_arr[-1], btc_price=btc_price,
                        signal_conditions=res["conditions"], venue="kraken_spot"
                    )
                    
                    # 2. Live Execution
                    if args.live_mode and executor:
                        try:
                            # Min lot for validation: approx 0.1 SOL, etc. 
                            # For simplification, we use a small USD notional converted to volume
                            notional_usd = 10.0 
                            volume = notional_usd / res["entry_price"]
                            print(f"  Executing live market buy: {volume:.4f} {asset}...")
                            executor.execute_trade(info['kraken'], 'buy', volume)
                        except Exception as e:
                            print(f"  Live execution failed: {e}")
                            
        except Exception as e:
            print(f"  Error scanning {asset}: {e}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
