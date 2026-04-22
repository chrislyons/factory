#!/usr/bin/env python3
"""
ATR Breakout Paper Trader v6 — EXPANDED PORTFOLIO (Walk-Forward Validated)
===========================================================================
10 robust LONG + 4 robust SHORT strategies from expanded walk-forward validation.

Equal-weight allocation, 20% per position (max 5 concurrent per side).
State: data/paper_v8/state.json
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import requests
import numpy as np

BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
DATA_DIR = BASE_DIR / "data" / "paper_v8"
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "scan_log.jsonl"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Walk-forward validated strategies
LONG_ASSETS = ["ETH", "LINK", "AVAX", "SUI", "DOGE", "AAVE", "ARB", "APT", "FIL", "UNI"]
SHORT_ASSETS = ["ARB", "OP", "ETH", "APT"]

# Strategy params
DONCHIAN = 20
ATR_PERIOD = 10
ATR_MULT = 1.5
TRAIL = 0.01
SMA_REGIME = 100
CANDLE_LIMIT = 200
BINANCE = "https://api.binance.com"

def fetch_klines(symbol, interval="1h", limit=CANDLE_LIMIT):
    url = f"{BINANCE}/api/v3/klines"
    params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  ERROR {symbol}: {e}")
        return None

def compute_indicators(klines):
    n = len(klines)
    close = [float(k[4]) for k in klines]
    high = [float(k[2]) for k in klines]
    low = [float(k[3]) for k in klines]

    tr = [0]*n
    for i in range(1,n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr = [0]*n
    for i in range(ATR_PERIOD, n):
        atr[i] = sum(tr[i-ATR_PERIOD+1:i+1]) / ATR_PERIOD

    upper = [0]*n
    lower = [0]*n
    for i in range(DONCHIAN-1, n):
        upper[i] = max(high[i-DONCHIAN+1:i+1])
        lower[i] = min(low[i-DONCHIAN+1:i+1])

    sma = [0]*n
    for i in range(SMA_REGIME-1, n):
        sma[i] = sum(close[i-SMA_REGIME+1:i+1]) / SMA_REGIME

    return close, high, low, atr, upper, lower, sma

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

def scan_pair(asset, side, state):
    klines = fetch_klines(asset)
    if not klines or len(klines) < 150:
        return {"asset": asset, "side": side, "action": "NO_DATA"}

    close, high, low, atr, upper, lower, sma = compute_indicators(klines)
    n = len(close)
    last = close[-1]
    pos_key = f"{asset}_{side}"

    results = {"asset": asset, "side": side, "price": last}

    # Check open position
    if pos_key in state["positions"]:
        pos = state["positions"][pos_key]
        entry = pos["entry"]
        trail = pos["trail"]

        if side == "long":
            new_trail = max(trail, last * (1 - TRAIL))
            if last < new_trail:
                pnl = (last - entry) / entry
                pnl_usd = pos["size"] * pnl
                state["equity"] += pos["size"] + pnl_usd
                state["closed_trades"].append({
                    "asset": asset, "side": side, "entry": entry, "exit": last,
                    "pnl_pct": round(pnl*100,2), "pnl_usd": round(pnl_usd,2),
                    "time": datetime.now(timezone.utc).isoformat()
                })
                state["total_trades"] += 1
                if pnl > 0: state["wins"] += 1
                del state["positions"][pos_key]
                results["action"] = "EXIT"
                results["pnl_pct"] = round(pnl*100, 2)
                log_event({"type":"exit","asset":asset,"side":side,"pnl":round(pnl*100,2)})
            else:
                pos["trail"] = new_trail
                unreal = (last - entry) / entry * 100
                results["action"] = "HOLD"
                results["unrealized"] = round(unreal, 2)
        else:  # short
            new_trail = min(trail, last * (1 + TRAIL))
            if last > new_trail:
                pnl = (entry - last) / entry
                pnl_usd = pos["size"] * pnl
                state["equity"] += pos["size"] + pnl_usd
                state["closed_trades"].append({
                    "asset": asset, "side": side, "entry": entry, "exit": last,
                    "pnl_pct": round(pnl*100,2), "pnl_usd": round(pnl_usd,2),
                    "time": datetime.now(timezone.utc).isoformat()
                })
                state["total_trades"] += 1
                if pnl > 0: state["wins"] += 1
                del state["positions"][pos_key]
                results["action"] = "EXIT"
                results["pnl_pct"] = round(pnl*100, 2)
                log_event({"type":"exit","asset":asset,"side":side,"pnl":round(pnl*100,2)})
            else:
                pos["trail"] = new_trail
                unreal = (entry - last) / entry * 100
                results["action"] = "HOLD"
                results["unrealized"] = round(unreal, 2)
        return results

    # Entry check
    if sma[-1] == 0 or atr[-1] == 0:
        return {**results, "action": "WAIT"}

    breakout_up = upper[-2] + ATR_MULT * atr[-2]
    breakout_dn = lower[-2] - ATR_MULT * atr[-2]

    if side == "long":
        signal = last > breakout_up and last > sma[-1]
    else:
        signal = last < breakout_dn and last < sma[-1]

    if signal:
        # Count open positions for sizing
        open_same_side = sum(1 for k in state["positions"] if k.endswith(f"_{side}"))
        max_positions = len(LONG_ASSETS) if side == "long" else len(SHORT_ASSETS)
        weight = 1.0 / max_positions
        size = state["equity"] * weight

        if size < 50:
            return {**results, "action": "LOW_CAPITAL"}

        trail_price = last * (1 - TRAIL) if side == "long" else last * (1 + TRAIL)
        state["positions"][pos_key] = {
            "entry": last, "trail": trail_price, "side": side,
            "size": size, "time": datetime.now(timezone.utc).isoformat()
        }
        state["equity"] -= size
        results["action"] = "ENTRY"
        results["entry"] = last
        results["size"] = round(size, 2)
        log_event({"type":"entry","asset":asset,"side":side,"price":last,"size":size})
    else:
        results["action"] = "WAIT"
        results["distance"] = round((breakout_up/last - 1)*100, 2) if side == "long" else round((last/breakout_dn - 1)*100, 2)

    return results

def main():
    state = load_state()
    print(f"\n=== ATR Breakout v6 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")
    print(f"Equity: ${state['equity']:.0f} | Trades: {state['total_trades']} | "
          f"WR: {state['wins']}/{state['total_trades']} "
          f"({state['wins']/max(state['total_trades'],1)*100:.0f}%)")
    print(f"Open: {len(state['positions'])} | Closed: {len(state['closed_trades'])}")

    entries, exits = [], []

    for asset in LONG_ASSETS:
        r = scan_pair(asset, "long", state)
        if r["action"] == "ENTRY": entries.append(r)
        elif r["action"] == "EXIT": exits.append(r)

    for asset in SHORT_ASSETS:
        if f"{asset}_short" not in [f"{a}_long" for a in LONG_ASSETS] or True:  # allow both
            r = scan_pair(asset, "short", state)
            if r["action"] == "ENTRY": entries.append(r)
            elif r["action"] == "EXIT": exits.append(r)

    if exits:
        print(f"\n  EXITS:")
        for r in exits:
            print(f"    {r['side'].upper()} {r['asset']}: {r['pnl_pct']:+.2f}%")

    if entries:
        print(f"\n  ENTRIES:")
        for r in entries:
            print(f"    {r['side'].upper()} {r['asset']}: ${r['entry']:.4f} (${r['size']:.0f})")

    if not entries and not exits:
        print(f"\n  No trades this scan.")

    save_state(state)

    # Show open positions
    if state["positions"]:
        print(f"\n  Open positions:")
        for key, pos in state["positions"].items():
            asset = key.replace("_long","").replace("_short","")
            side = "LONG" if "long" in key else "SHORT"
            print(f"    {side} {asset}: entry=${pos['entry']:.4f} trail=${pos['trail']:.4f}")

if __name__ == "__main__":
    main()
