#!/usr/bin/env python3
"""
ATR Breakout Paper Trader v5 — Regime-Agnostic Portfolio
=========================================================
Key change from v4: SHORT entries fire when assets are BELOW SMA100.
This prevents the strategy from sitting idle during bearish regimes.

LONG (above SMA100):
  - 12 assets: ETH, AVAX, SOL, LINK, NEAR, FIL, SUI, RNDR, DOGE, LTC, AAVE, OP
  - Entry: close > prev Donchian(20) upper
  - 1.0% trailing stop, 96h max hold

SHORT (below SMA100):
  - 4 assets: ARB, OP, ETH, APT (WF-validated: PF 4.14, 2.57, 1.85, 1.76)
  - Entry: close < prev Donchian(20) lower - ATR * 2.5
  - 2.5% trailing stop, 48h max hold
  - Funding rate bonus: +11-22% ann in bull markets

Regime gate: SMA100 per-asset
  - close > SMA100 → LONG eligible, SHORT blocked
  - close < SMA100 → SHORT eligible, LONG blocked
"""
import json
import hashlib
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

# Assets — regime-agnostic
LONG_ASSETS = ["ETH", "AVAX", "SOL", "LINK", "NEAR", "FIL", "SUI", "RNDR",
               "DOGE", "LTC", "AAVE", "OP"]
SHORT_ASSETS = ["ARB", "OP", "ETH", "APT"]  # WF-validated robust shorts
ALL_ASSETS = sorted(set(LONG_ASSETS + SHORT_ASSETS))

# Strategy params
DONCHIAN = 20
ATR_PERIOD = 10
ATR_MULT_ENTRY_SHORT = 1.5  # IG88081: 1.5x optimal (PF 2.95, 345 trades vs 2.67/68 at 2.5x)
ATR_MULT_STOP = 1.5
TRAIL_LONG = 0.01       # 1.0%
TRAIL_SHORT = 0.025     # 2.5%
MAX_HOLD_LONG = 96
MAX_HOLD_SHORT = 48
SMA_REGIME = 100
FRICTION = 0.0014       # Jupiter perps RT

BINANCE = "https://api.binance.com"
CANDLE_LIMIT = 200

# Symbol mapping (Binance uses different symbols for some assets)
SYMBOL_MAP = {
    "ARB": "ARBUSDT",
    "OP": "OPUSDT",
    "ETH": "ETHUSDT",
    "APT": "APTUSDT",
    "AVAX": "AVAXUSDT",
    "SOL": "SOLUSDT",
    "LINK": "LINKUSDT",
    "NEAR": "NEARUSDT",
    "FIL": "FILUSDT",
    "SUI": "SUIUSDT",
    "RNDR": "RNDRUSDT",
    "DOGE": "DOGEUSDT",
    "LTC": "LTCUSDT",
    "AAVE": "AAVEUSDT",
}


def fetch_klines(asset, interval="1h", limit=CANDLE_LIMIT):
    symbol = SYMBOL_MAP.get(asset, f"{asset}USDT")
    url = f"{BINANCE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ERROR fetching {asset} ({symbol}): {e}")
        return None

    candles = []
    for k in data:
        candles.append({
            "time": k[0], "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]),
        })
    return candles


def compute_indicators(candles):
    n = len(candles)
    close = [c["close"] for c in candles]
    high = [c["high"] for c in candles]
    low = [c["low"] for c in candles]

    tr = [0] * n
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))

    atr = [0] * n
    for i in range(ATR_PERIOD, n):
        atr[i] = sum(tr[i-ATR_PERIOD+1:i+1]) / ATR_PERIOD

    upper = [0] * n
    lower = [0] * n
    for i in range(DONCHIAN - 1, n):
        upper[i] = max(high[i-DONCHIAN+1:i+1])
        lower[i] = min(low[i-DONCHIAN+1:i+1])

    sma = [0] * n
    for i in range(SMA_REGIME - 1, n):
        sma[i] = sum(close[i-SMA_REGIME+1:i+1]) / SMA_REGIME

    return {
        "close": close, "high": high, "low": low,
        "atr": atr, "upper": upper, "lower": lower, "sma": sma
    }


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "positions": [], "closed_trades": [], "equity": 100000.0,
        "last_scan": None, "total_trades": 0, "wins": 0,
    }


def save_state(state):
    state["last_scan"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def trade_id(asset, direction, entry_time):
    raw = f"{asset}_{direction}_{entry_time}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def check_exits(ind, state):
    closed = []
    remaining = []

    for pos in state["positions"]:
        asset = pos["asset"]
        direction = pos["direction"]
        entry_price = pos["entry_price"]
        trail_pct = TRAIL_LONG if direction == "LONG" else TRAIL_SHORT
        max_hold = MAX_HOLD_LONG if direction == "LONG" else MAX_HOLD_SHORT

        if asset not in ind:
            remaining.append(pos)
            continue

        data = ind[asset]
        current_price = data["close"][-1]
        current_high = data["high"][-1]
        current_low = data["low"][-1]
        current_time = datetime.now(timezone.utc).isoformat()

        entry_dt = datetime.fromisoformat(pos["entry_time"])
        hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600

        if direction == "LONG":
            highest = max(pos.get("highest_since_entry", entry_price), current_high)
            pos["highest_since_entry"] = highest
            trail_stop = highest * (1 - trail_pct)
            pos["stop_price"] = max(pos.get("stop_price", 0), trail_stop)

            if pos.get("use_atr_stop", True) and hours_held < 4:
                atr_stop = entry_price - data["atr"][-1] * ATR_MULT_STOP
                pos["stop_price"] = max(pos["stop_price"], atr_stop)

            hit_stop = current_low <= pos["stop_price"]
            hit_hold = hours_held >= max_hold
            exit_price = pos["stop_price"] if hit_stop else current_price
        else:
            lowest = min(pos.get("lowest_since_entry", entry_price), current_low)
            pos["lowest_since_entry"] = lowest
            trail_stop = lowest * (1 + trail_pct)
            pos["stop_price"] = min(pos.get("stop_price", float("inf")), trail_stop)

            hit_stop = current_high >= pos["stop_price"]
            hit_hold = hours_held >= max_hold
            exit_price = pos["stop_price"] if hit_stop else current_price

        if hit_stop or hit_hold:
            if direction == "LONG":
                pnl_pct = (exit_price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - exit_price) / entry_price
            net_pnl = pnl_pct - FRICTION

            reason = "STOP" if hit_stop else "TIME"
            is_win = net_pnl > 0

            trade = {
                "trade_id": pos["trade_id"], "asset": asset,
                "direction": direction, "entry_price": entry_price,
                "exit_price": exit_price, "entry_time": pos["entry_time"],
                "exit_time": current_time,
                "pnl_pct": round(pnl_pct * 100, 3),
                "net_pnl_pct": round(net_pnl * 100, 3),
                "exit_reason": reason, "hours_held": round(hours_held, 1),
            }
            closed.append(trade)
            state["closed_trades"].append(trade)
            state["total_trades"] += 1
            if is_win:
                state["wins"] += 1

            state["equity"] *= (1 + net_pnl)
            wr = state["wins"] / state["total_trades"] * 100 if state["total_trades"] > 0 else 0
            print(f"  EXIT {direction} {asset}: {exit_price:.4f} | PnL: {net_pnl*100:+.2f}% | {reason} | {hours_held:.0f}h | WR: {wr:.1f}%")
        else:
            remaining.append(pos)

    state["positions"] = remaining
    return closed


def check_entries(ind, state):
    existing = {(p["asset"], p["direction"]) for p in state["positions"]}
    entries = []

    # LONG entries: only when above SMA100
    for asset in LONG_ASSETS:
        if asset not in ind or (asset, "LONG") in existing:
            continue
        data = ind[asset]
        if data["upper"][-2] == 0 or data["atr"][-1] == 0 or data["sma"][-1] == 0:
            continue

        close = data["close"][-1]
        sma = data["sma"][-1]

        # SMA100 regime gate
        if close <= sma:
            continue

        prev_upper = data["upper"][-2]
        if close > prev_upper:
            entry_price = close
            atr_stop = entry_price - data["atr"][-1] * ATR_MULT_STOP
            trail_stop = entry_price * (1 - TRAIL_LONG)
            stop = max(atr_stop, trail_stop)

            pos = {
                "trade_id": trade_id(asset, "LONG", datetime.now(timezone.utc).isoformat()),
                "asset": asset, "direction": "LONG",
                "entry_price": entry_price, "stop_price": stop,
                "entry_atr": data["atr"][-1],
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "highest_since_entry": entry_price,
                "use_atr_stop": True,
            }
            entries.append(pos)
            state["positions"].append(pos)
            print(f"  ENTRY LONG {asset}: {entry_price:.4f} | Stop: {stop:.4f} | SMA100: {sma:.4f}")

    # SHORT entries: only when below SMA100
    for asset in SHORT_ASSETS:
        if asset not in ind or (asset, "SHORT") in existing:
            continue
        data = ind[asset]
        if data["lower"][-2] == 0 or data["atr"][-1] == 0 or data["sma"][-1] == 0:
            continue

        close = data["close"][-1]
        sma = data["sma"][-1]

        # SMA100 regime gate — SHORT below SMA100
        if close >= sma:
            continue

        prev_lower = data["lower"][-2]
        atr = data["atr"][-1]
        short_trigger = prev_lower - atr * ATR_MULT_ENTRY_SHORT

        if close < short_trigger:
            entry_price = close
            trail_stop = entry_price * (1 + TRAIL_SHORT)
            atr_stop = entry_price + atr * ATR_MULT_STOP
            stop = min(trail_stop, atr_stop)

            pos = {
                "trade_id": trade_id(asset, "SHORT", datetime.now(timezone.utc).isoformat()),
                "asset": asset, "direction": "SHORT",
                "entry_price": entry_price, "stop_price": stop,
                "entry_atr": atr,
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "lowest_since_entry": entry_price,
            }
            entries.append(pos)
            state["positions"].append(pos)
            print(f"  ENTRY SHORT {asset}: {entry_price:.4f} | Stop: {stop:.4f} | SMA100: {sma:.4f}")

    return entries


def main():
    print(f"=== ATR Paper Trader v5 (Regime-Agnostic) — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")

    state = load_state()
    print(f"Open positions: {len(state['positions'])} | Total trades: {state['total_trades']} | Equity: ${state['equity']:.2f}")

    ind = {}
    for asset in ALL_ASSETS:
        candles = fetch_klines(asset)
        if candles and len(candles) >= 100:
            ind[asset] = compute_indicators(candles)
            regime = "ABOVE" if ind[asset]["close"][-1] > ind[asset]["sma"][-1] else "BELOW"
            print(f"  {asset}: {len(candles)} candles, close={ind[asset]['close'][-1]:.4f}, SMA100={ind[asset]['sma'][-1]:.4f} ({regime})")
        else:
            print(f"  {asset}: insufficient data ({len(candles) if candles else 0} candles)")

    print("\n--- EXITS ---")
    check_exits(ind, state)

    print("\n--- ENTRIES ---")
    check_entries(ind, state)

    print(f"\n--- SUMMARY ---")
    print(f"Open positions: {len(state['positions'])}")
    for pos in state["positions"]:
        direction = pos["direction"]
        asset = pos["asset"]
        entry = pos["entry_price"]
        stop = pos["stop_price"]
        current = ind.get(asset, {}).get("close", [0])[-1]
        if current > 0:
            if direction == "LONG":
                unrealized = (current - entry) / entry * 100
            else:
                unrealized = (entry - current) / entry * 100
            print(f"  {direction} {asset}: entry={entry:.4f} current={current:.4f} PnL={unrealized:+.2f}% stop={stop:.4f}")

    wr = state["wins"] / state["total_trades"] * 100 if state["total_trades"] > 0 else 0
    print(f"\nTotal closed: {state['total_trades']} | Wins: {state['wins']} | WR: {wr:.1f}% | Equity: ${state['equity']:.2f}")

    save_state(state)

    log_entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "open_positions": len(state["positions"]),
        "total_trades": state["total_trades"],
        "equity": round(state["equity"], 2),
        "win_rate": round(wr, 1),
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    print("\nDone.")


if __name__ == "__main__":
    main()
