#!/usr/bin/env python3
"""
ATR Breakout Paper Trader v4 — Full Portfolio, Optimized Params
================================================================
Live paper trading scanner with:
- LONG: 9 assets (ETH, AVAX, SOL, LINK, NEAR, FIL, SUI, WLD, RNDR)
- SHORT: 5 assets (ETH, LINK, AVAX, SOL, SUI) + funding bonus
- SMA100 regime filter (IG88077 confirmed PF improvement)
- 1.0% trailing stop for LONG (IG88077 confirmed optimal)
- 2.5% trailing stop for SHORT (Variant B)
- Equal-weight portfolio allocation

Fetches live 1h candles from Binance, manages paper positions via state file.
Runs as a cron job — each run checks for exits, then entries.

Changes from v3:
- Uses SMA100 (not SMA50/200) — confirmed better in IG88077
- 1.0% trail for LONG (was 2.0%) — confirmed optimal in IG88077
- Full 9-asset LONG + 5-asset SHORT
- Proper state management between cron runs
"""

import json
import sys
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests
import numpy as np

# === CONFIG ===
BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
DATA_DIR = BASE_DIR / "data" / "paper_v6"
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "scan_log.jsonl"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Assets
LONG_ASSETS = ["ETH", "AVAX", "SOL", "LINK", "NEAR", "FIL", "SUI", "WLD", "RNDR"]
SHORT_ASSETS = ["ETH", "LINK", "AVAX", "SOL", "SUI"]
ALL_ASSETS = sorted(set(LONG_ASSETS + SHORT_ASSETS))

# Strategy params (registry v5, IG88077 optimized)
DONCHIAN = 20
ATR_PERIOD = 10
ATR_MULT_ENTRY_SHORT = 2.5
ATR_MULT_STOP = 1.5
TRAIL_LONG = 0.01       # 1.0% — confirmed optimal
TRAIL_SHORT = 0.025     # 2.5%
MAX_HOLD_LONG = 96
MAX_HOLD_SHORT = 48
SMA_REGIME = 100        # SMA100 regime filter
FRICTION = 0.0014       # Jupiter perps RT

BINANCE = "https://api.binance.com"
CANDLE_LIMIT = 200      # Need 100+ for SMA100


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


def compute_indicators(candles):
    """Compute Donchian, ATR, SMA100."""
    n = len(candles)
    close = [c["close"] for c in candles]
    high = [c["high"] for c in candles]
    low = [c["low"] for c in candles]

    # ATR
    tr = [0] * n
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))

    atr = [0] * n
    for i in range(ATR_PERIOD, n):
        atr[i] = sum(tr[i-ATR_PERIOD+1:i+1]) / ATR_PERIOD

    # Donchian channels
    upper = [0] * n
    lower = [0] * n
    for i in range(DONCHIAN - 1, n):
        upper[i] = max(high[i-DONCHIAN+1:i+1])
        lower[i] = min(low[i-DONCHIAN+1:i+1])

    # SMA100
    sma = [0] * n
    for i in range(SMA_REGIME - 1, n):
        sma[i] = sum(close[i-SMA_REGIME+1:i+1]) / SMA_REGIME

    return {
        "close": close, "high": high, "low": low,
        "atr": atr, "upper": upper, "lower": lower, "sma": sma
    }


def load_state():
    """Load paper trading state."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "positions": [],
        "closed_trades": [],
        "equity": 100000.0,
        "last_scan": None,
        "total_trades": 0,
        "wins": 0,
    }


def save_state(state):
    """Save state."""
    state["last_scan"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def trade_id(asset, direction, entry_time):
    """Generate unique trade ID."""
    raw = f"{asset}_{direction}_{entry_time}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def check_exits(ind, state):
    """Check if any open positions should be closed."""
    closed = []
    remaining = []

    for pos in state["positions"]:
        asset = pos["asset"]
        direction = pos["direction"]
        entry_price = pos["entry_price"]
        trail_pct = TRAIL_LONG if direction == "LONG" else TRAIL_SHORT
        max_hold = MAX_HOLD_LONG if direction == "LONG" else MAX_HOLD_SHORT

        # Get current price from indicators
        if asset not in ind:
            remaining.append(pos)
            continue

        data = ind[asset]
        current_price = data["close"][-1]
        current_high = data["high"][-1]
        current_low = data["low"][-1]
        current_time = datetime.now(timezone.utc).isoformat()

        # Hours held
        entry_dt = datetime.fromisoformat(pos["entry_time"])
        hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600

        # Update trailing stop
        if direction == "LONG":
            highest = max(pos.get("highest_since_entry", entry_price), current_high)
            pos["highest_since_entry"] = highest
            trail_stop = highest * (1 - trail_pct)
            pos["stop_price"] = max(pos.get("stop_price", 0), trail_stop)

            # ATR-based initial stop
            atr_stop = entry_price - data["atr"][-1] * ATR_MULT_STOP if pos.get("entry_atr") else trail_stop
            if pos.get("use_atr_stop", True) and hours_held < 4:
                pos["stop_price"] = max(pos["stop_price"], atr_stop)

            # Check exit
            hit_stop = current_low <= pos["stop_price"]
            hit_hold = hours_held >= max_hold
            exit_price = pos["stop_price"] if hit_stop else current_price

        else:  # SHORT
            lowest = min(pos.get("lowest_since_entry", entry_price), current_low)
            pos["lowest_since_entry"] = lowest
            trail_stop = lowest * (1 + trail_pct)
            pos["stop_price"] = min(pos.get("stop_price", float("inf")), trail_stop)

            hit_stop = current_high >= pos["stop_price"]
            hit_hold = hours_held >= max_hold
            exit_price = pos["stop_price"] if hit_stop else current_price

        if hit_stop or hit_hold:
            # Compute PnL
            if direction == "LONG":
                pnl_pct = (exit_price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - exit_price) / entry_price
            net_pnl = pnl_pct - FRICTION

            reason = "STOP" if hit_stop else "TIME"
            is_win = net_pnl > 0

            trade = {
                "trade_id": pos["trade_id"],
                "asset": asset,
                "direction": direction,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_time": pos["entry_time"],
                "exit_time": current_time,
                "pnl_pct": round(pnl_pct * 100, 3),
                "net_pnl_pct": round(net_pnl * 100, 3),
                "exit_reason": reason,
                "hours_held": round(hours_held, 1),
            }
            closed.append(trade)
            state["closed_trades"].append(trade)
            state["total_trades"] += 1
            if is_win:
                state["wins"] += 1

            # Update equity
            state["equity"] *= (1 + net_pnl)

            wr = state["wins"] / state["total_trades"] * 100 if state["total_trades"] > 0 else 0
            print(f"  EXIT {direction} {asset}: {exit_price:.4f} | PnL: {net_pnl*100:+.2f}% | {reason} | {hours_held:.0f}h | WR: {wr:.1f}%")
        else:
            remaining.append(pos)

    state["positions"] = remaining
    return closed


def check_entries(ind, state):
    """Check for new entry signals."""
    existing = {(p["asset"], p["direction"]) for p in state["positions"]}
    entries = []

    for asset in LONG_ASSETS:
        if asset not in ind or (asset, "LONG") in existing:
            continue

        data = ind[asset]
        if data["upper"][-2] == 0 or data["atr"][-1] == 0:
            continue

        close = data["close"][-1]
        prev_upper = data["upper"][-2]
        sma = data["sma"][-1]

        # LONG entry: close > prev upper channel
        if close > prev_upper and sma > 0 and close > sma:  # SMA100 regime filter
            entry_price = close
            atr_stop = entry_price - data["atr"][-1] * ATR_MULT_STOP
            trail_stop = entry_price * (1 - TRAIL_LONG)
            stop = max(atr_stop, trail_stop)

            pos = {
                "trade_id": trade_id(asset, "LONG", datetime.now(timezone.utc).isoformat()),
                "asset": asset,
                "direction": "LONG",
                "entry_price": entry_price,
                "stop_price": stop,
                "entry_atr": data["atr"][-1],
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "highest_since_entry": entry_price,
                "use_atr_stop": True,
            }
            entries.append(pos)
            state["positions"].append(pos)
            print(f"  ENTRY LONG {asset}: {entry_price:.4f} | Stop: {stop:.4f} | SMA100: {sma:.4f}")

    for asset in SHORT_ASSETS:
        if asset not in ind or (asset, "SHORT") in existing:
            continue

        data = ind[asset]
        if data["lower"][-2] == 0 or data["atr"][-1] == 0:
            continue

        close = data["close"][-1]
        prev_lower = data["lower"][-2]
        atr = data["atr"][-1]

        # SHORT entry: close < prev lower - ATR * mult
        short_trigger = prev_lower - atr * ATR_MULT_ENTRY_SHORT
        if close < short_trigger:
            entry_price = close
            trail_stop = entry_price * (1 + TRAIL_SHORT)
            atr_stop = entry_price + atr * ATR_MULT_STOP
            stop = min(trail_stop, atr_stop)

            pos = {
                "trade_id": trade_id(asset, "SHORT", datetime.now(timezone.utc).isoformat()),
                "asset": asset,
                "direction": "SHORT",
                "entry_price": entry_price,
                "stop_price": stop,
                "entry_atr": atr,
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "lowest_since_entry": entry_price,
            }
            entries.append(pos)
            state["positions"].append(pos)
            print(f"  ENTRY SHORT {asset}: {entry_price:.4f} | Stop: {stop:.4f}")

    return entries


def main():
    print(f"=== ATR Paper Trader v4 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")

    state = load_state()
    print(f"Open positions: {len(state['positions'])} | Total trades: {state['total_trades']} | Equity: ${state['equity']:.2f}")

    # Fetch data for all assets
    ind = {}
    for asset in ALL_ASSETS:
        symbol = asset
        # Handle symbol mapping
        symbol_map = {"WLD": "WLD", "RNDR": "RNDR", "FIL": "FIL"}
        symbol = symbol_map.get(asset, asset)

        candles = fetch_klines(symbol)
        if candles and len(candles) >= 100:
            ind[asset] = compute_indicators(candles)
            print(f"  {asset}: {len(candles)} candles, close={ind[asset]['close'][-1]:.4f}, SMA100={ind[asset]['sma'][-1]:.4f}")
        else:
            print(f"  {asset}: insufficient data ({len(candles) if candles else 0} candles)")

    # Check exits first
    print("\n--- EXITS ---")
    check_exits(ind, state)

    # Check entries
    print("\n--- ENTRIES ---")
    check_entries(ind, state)

    # Summary
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

    # Log scan
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
