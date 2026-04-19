#!/usr/bin/env python3
"""
ATR Breakout Paper Trader v5 — Walk-Forward Validated Portfolio
================================================================
Based on walk-forward bootstrap validation (IG88080):
- ETH LONG with 50% ATR% vol filter (PF 1.93, avg 0.64%/trade)
- LINK LONG, no filter (PF 2.43, 4/4 WF splits profitable)

Only 2 strategies — honest assessment of what's actually robust.
Previous v4 ran 14 strategies, most of which fail walk-forward.

State file: data/paper_v5/state.json
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import numpy as np

# === CONFIG ===
BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
DATA_DIR = BASE_DIR / "data" / "paper_v7"
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "scan_log.jsonl"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Strategy config — pair-specific
STRATEGIES = {
    "ETH_LONG": {
        "symbol": "ETH",
        "side": "long",
        "donchian": 20,
        "atr_period": 10,
        "atr_mult": 1.5,
        "trail": 0.01,
        "sma_regime": 100,
        "vol_filter": 0.50,   # ATR% >= 50th percentile
        "vol_lookback": 500,
    },
    "LINK_LONG": {
        "symbol": "LINK",
        "side": "long",
        "donchian": 20,
        "atr_period": 10,
        "atr_mult": 1.5,
        "trail": 0.01,
        "sma_regime": 100,
        "vol_filter": None,   # No vol filter — robust without it
        "vol_lookback": 500,
    },
}

CANDLE_LIMIT = 600  # Need 500+ for vol lookback + SMA100
BINANCE = "https://api.binance.com"

def fetch_klines(symbol, interval="1h", limit=CANDLE_LIMIT):
    """Fetch OHLCV from Binance."""
    url = f"{BINANCE}/api/v3/klines"
    params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ERROR fetching {symbol}: {e}")
        return None

    candles = []
    for k in data:
        candles.append({
            "time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
        })
    return candles

def compute_indicators(candles, cfg):
    """Compute all indicators for a strategy config."""
    n = len(candles)
    close = [c["close"] for c in candles]
    high = [c["high"] for c in candles]
    low = [c["low"] for c in candles]

    # ATR
    tr = [0] * n
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))

    atr = [0] * n
    p = cfg["atr_period"]
    for i in range(p, n):
        atr[i] = sum(tr[i-p+1:i+1]) / p

    # Donchian channels
    don = cfg["donchian"]
    upper = [0] * n
    lower = [0] * n
    for i in range(don - 1, n):
        upper[i] = max(high[i-don+1:i+1])
        lower[i] = min(low[i-don+1:i+1])

    # SMA regime
    sma_period = cfg["sma_regime"]
    sma = [0] * n
    for i in range(sma_period - 1, n):
        sma[i] = sum(close[i-sma_period+1:i+1]) / sma_period

    # ATR% percentile rank (for vol filter)
    atr_pct_rank = [float('nan')] * n
    if cfg["vol_filter"] is not None:
        lookback = cfg["vol_lookback"]
        atr_pct = [atr[i] / close[i] if close[i] > 0 else 0 for i in range(n)]
        for i in range(lookback, n):
            window = sorted(atr_pct[i-lookback:i])
            rank = 0
            for j, v in enumerate(window):
                if v >= atr_pct[i]:
                    rank = j / lookback
                    break
            else:
                rank = 1.0
            atr_pct_rank[i] = rank

    return {
        "close": close, "high": high, "low": low,
        "atr": atr, "upper": upper, "lower": lower,
        "sma": sma, "atr_pct_rank": atr_pct_rank,
    }

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"positions": {}, "closed_trades": [], "equity": 100000.0,
            "last_scan": None, "total_trades": 0, "wins": 0}

def save_state(state):
    state["last_scan"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)

def log_event(event):
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")

def scan_strategy(name, cfg, state):
    """Run one scan cycle for a strategy."""
    candles = fetch_klines(cfg["symbol"])
    if candles is None or len(candles) < 200:
        return

    ind = compute_indicators(candles, cfg)
    n = len(candles)
    close = ind["close"]
    last_close = close[-1]

    results = {"strategy": name, "price": last_close}

    # Check open position
    if name in state["positions"]:
        pos = state["positions"][name]
        entry = pos["entry"]
        trail = pos["trail"]
        side = pos["side"]

        if side == "long":
            new_trail = max(trail, last_close * (1 - cfg["trail"]))
            if last_close < new_trail:
                # Exit
                pnl = (last_close - entry) / entry
                pnl_usd = pos["size"] * pnl
                state["equity"] += pnl_usd
                state["closed_trades"].append({
                    "strategy": name, "entry": entry, "exit": last_close,
                    "pnl_pct": round(pnl * 100, 2), "pnl_usd": round(pnl_usd, 2),
                    "bars_held": pos.get("bars", 0),
                    "time": datetime.now(timezone.utc).isoformat()
                })
                state["total_trades"] += 1
                if pnl > 0: state["wins"] += 1
                del state["positions"][name]
                results["action"] = "EXIT"
                results["pnl_pct"] = round(pnl * 100, 2)
                log_event({"type": "exit", "strategy": name, "pnl_pct": round(pnl*100, 2)})
            else:
                pos["trail"] = new_trail
                pos["bars"] = pos.get("bars", 0) + 1
                unrealized = (last_close - entry) / entry * 100
                results["action"] = "HOLD"
                results["unrealized_pct"] = round(unrealized, 2)
                results["trail"] = round(new_trail, 2)
        return results

    # Check entry conditions
    sma = ind["sma"][-1]
    if sma == 0:
        return results

    atr_val = ind["atr"][-1]
    if atr_val == 0:
        return results

    # Vol filter check
    if cfg["vol_filter"] is not None:
        vol_rank = ind["atr_pct_rank"][-1]
        if np.isnan(vol_rank) or vol_rank < cfg["vol_filter"]:
            results["action"] = "SKIP_VOL"
            results["vol_rank"] = round(vol_rank, 2) if not np.isnan(vol_rank) else "nan"
            return results

    mult = cfg["atr_mult"]
    if cfg["side"] == "long":
        breakout = ind["high"][-2] + mult * ind["atr"][-2]
        regime_ok = last_close > sma
        entry_signal = last_close > breakout
    else:
        breakout = ind["low"][-2] - mult * ind["atr"][-2]
        regime_ok = last_close < sma
        entry_signal = last_close < breakout

    if regime_ok and entry_signal:
        # Entry
        size = state["equity"] * 0.20  # 20% per position (equal weight 2 strategies)
        if size < 100:
            results["action"] = "SKIP_CAPITAL"
            return results

        trail = last_close * (1 - cfg["trail"]) if cfg["side"] == "long" else last_close * (1 + cfg["trail"])
        state["positions"][name] = {
            "entry": last_close,
            "trail": trail,
            "side": cfg["side"],
            "size": size,
            "bars": 0,
            "time": datetime.now(timezone.utc).isoformat()
        }
        state["equity"] -= size  # Reserve capital
        results["action"] = "ENTRY"
        results["entry_price"] = last_close
        results["trail"] = round(trail, 2)
        results["size"] = round(size, 2)
        log_event({"type": "entry", "strategy": name, "price": last_close, "size": size})
    else:
        results["action"] = "WAIT"
        results["regime_ok"] = regime_ok
        results["breakout"] = round(breakout, 2)
        results["distance_pct"] = round((breakout / last_close - 1) * 100, 2)

    return results

def main():
    state = load_state()
    print(f"\n=== ATR Breakout v5 Scan — {datetime.now(timezone.utc).isoformat()} ===")
    print(f"Equity: ${state['equity']:.2f} | Trades: {state['total_trades']} | "
          f"Win rate: {state['wins']}/{state['total_trades']}")

    for name, cfg in STRATEGIES.items():
        result = scan_strategy(name, cfg, state)
        if result:
            action = result.get("action", "?")
            print(f"\n  {name}: {action}")
            for k, v in result.items():
                if k not in ("strategy", "action"):
                    print(f"    {k}: {v}")

    save_state(state)

    # Summary
    if state["closed_trades"]:
        recent = state["closed_trades"][-5:]
        print(f"\n  Recent trades:")
        for t in recent:
            print(f"    {t['strategy']}: {t['pnl_pct']:+.2f}% (${t['pnl_usd']:+.2f})")

if __name__ == "__main__":
    main()
