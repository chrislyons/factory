#!/usr/bin/env python3
"""
ATR Breakout Paper Trading Scanner v2 (Regime-Gated)
Fetches live 1h candles from Binance, computes Donchian(20) + ATR(10),
SMA50/SMA200 regime filter, generates LONG/SHORT signals, manages paper positions.
Regime gate: Only take LONG entries in BULL (close>SMA200 && SMA50>SMA200).
Shorts unrestricted (confirmed profitable in all regimes).

v2 changes from v1:
- Added SMA200/SMA50 regime filter for long entries (+14% PF expected)
- Added SUI to SHORT_ASSETS (validated PF 2.14)
- Fetches 250 candles for SMA200 computation
"""

import json
import sys
import time
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
import numpy as np

# === CONFIG ===
BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")
DATA_DIR = BASE_DIR / "data" / "paper_trades"
STATE_FILE = DATA_DIR / "state.json"

ASSETS = ["FIL", "SUI", "AVAX", "NEAR", "RNDR", "WLD", "ETH", "LINK", "SOL"]
SHORT_ASSETS = {"ETH", "AVAX", "LINK", "SOL", "SUI"}

DONCHIAN_PERIOD = 20
ATR_PERIOD = 10
SMA_LONG = 50
SMA_SHORT = 200
ATR_MULT_ENTRY = 2.5    # SHORT Variant B: close < prev_lower - atr * 2.5
ATR_MULT_STOP = 2.0     # Initial stop: entry +/- ATR * 2
TRAIL_LONG = 0.02       # 2% trailing stop for longs
TRAIL_SHORT = 0.025     # 2.5% trailing stop for shorts
MAX_HOLD_LONG = 96      # hours
MAX_HOLD_SHORT = 48     # hours
REQUIRE_BULL = True     # Regime gate for longs

BINANCE_BASE = "https://api.binance.com"
CANDLE_LIMIT = 250      # Need 200+ for SMA200


# === BINANCE API ===
def fetch_klines(symbol: str, interval: str = "1h", limit: int = CANDLE_LIMIT):
    """Fetch OHLCV candles from Binance public API."""
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    candles = []
    for k in data:
        candles.append({
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "close_time": k[6],
        })
    return candles


def compute_indicators(candles):
    """
    Compute Donchian(20), ATR(10), SMA50, SMA200.
    SMA200 valid from index 199 onward; Donchian from 19 onward.
    We only generate signals from max(DONCHIAN_PERIOD, SMA_SHORT) onward.
    """
    n = len(candles)
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    closes = np.array([c["close"] for c in candles])

    # Donchian channels
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(DONCHIAN_PERIOD - 1, n):
        upper[i] = np.max(highs[i - DONCHIAN_PERIOD + 1: i + 1])
        lower[i] = np.min(lows[i - DONCHIAN_PERIOD + 1: i + 1])

    # True Range
    tr = np.zeros(n)
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    # ATR(10)
    atr = np.full(n, np.nan)
    for i in range(ATR_PERIOD, n):
        atr[i] = np.mean(tr[i - ATR_PERIOD + 1: i + 1])

    # SMA50 and SMA200
    sma50 = np.full(n, np.nan)
    sma200 = np.full(n, np.nan)
    for i in range(SMA_LONG - 1, n):
        sma50[i] = np.mean(closes[i - SMA_LONG + 1: i + 1])
    for i in range(SMA_SHORT - 1, n):
        sma200[i] = np.mean(closes[i - SMA_SHORT + 1: i + 1])

    # Regime classification
    regime = np.full(n, "UNKNOWN", dtype=object)
    for i in range(n):
        if np.isnan(sma200[i]) or np.isnan(sma50[i]):
            continue
        if closes[i] > sma200[i] and sma50[i] > sma200[i]:
            regime[i] = "BULL"
        elif closes[i] < sma200[i] and sma50[i] < sma200[i]:
            regime[i] = "BEAR"
        else:
            regime[i] = "SIDEWAYS"

    results = []
    for i in range(n):
        results.append({
            **candles[i],
            "upper": upper[i],
            "lower": lower[i],
            "atr": atr[i],
            "sma50": sma50[i],
            "sma200": sma200[i],
            "regime": regime[i],
        })
    return results


# === STATE MANAGEMENT ===
def load_state():
    """Load persisted state from disk."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"open_positions": [], "closed_trade_ids": [], "scan_count": 0}


def save_state(state):
    """Persist state to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(STATE_FILE)


# === TRADE LOGGING ===
def log_trade(trade):
    """Append a closed trade to today's JSONL log."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = DATA_DIR / f"paper_log_{date_str}.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(trade) + "\n")


# === SIGNAL GENERATION & POSITION MANAGEMENT ===
def process_asset(asset, indicators, state):
    """
    Check for new signals and manage existing positions for one asset.
    Returns (signals_found, updated_state).
    """
    signals = []
    open_positions = state.get("open_positions", [])
    closed_ids = set(state.get("closed_trade_ids", []))

    asset_positions = [p for p in open_positions if p["asset"] == asset]
    other_positions = [p for p in open_positions if p["asset"] != asset]

    min_bars = max(DONCHIAN_PERIOD + 2, SMA_SHORT + 1)
    if len(indicators) < min_bars:
        return signals, open_positions

    latest = indicators[-1]
    prev = indicators[-2]

    if np.isnan(latest["upper"]) or np.isnan(latest["lower"]) or np.isnan(latest["atr"]):
        return signals, open_positions

    current_close = latest["close"]
    current_time = latest["close_time"]
    current_atr = latest["atr"]
    current_regime = latest["regime"]

    # --- Manage existing positions ---
    still_open = []
    for pos in asset_positions:
        entry_time = pos["entry_time"]
        hours_held = (current_time - entry_time) / (1000 * 3600)
        direction = pos["direction"]
        max_hold = MAX_HOLD_LONG if direction == "LONG" else MAX_HOLD_SHORT
        trail_pct = TRAIL_LONG if direction == "LONG" else TRAIL_SHORT

        if direction == "LONG":
            new_trail = current_close * (1 - trail_pct)
            pos["stop_price"] = max(pos["stop_price"], new_trail)
            stop_hit = current_close <= pos["stop_price"]
        else:
            new_trail = current_close * (1 + trail_pct)
            pos["stop_price"] = min(pos["stop_price"], new_trail)
            stop_hit = current_close >= pos["stop_price"]

        time_exit = hours_held >= max_hold

        if stop_hit or time_exit:
            exit_price = pos["stop_price"] if stop_hit else current_close
            if direction == "LONG":
                pnl_pct = (exit_price - pos["entry_price"]) / pos["entry_price"]
            else:
                pnl_pct = (pos["entry_price"] - exit_price) / pos["entry_price"]

            trade_id = pos["trade_id"]
            if trade_id not in closed_ids:
                closed_trade = {
                    "trade_id": trade_id,
                    "asset": asset,
                    "direction": direction,
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_price,
                    "entry_time": entry_time,
                    "exit_time": current_time,
                    "pnl_pct": round(pnl_pct, 6),
                    "exit_reason": "stop" if stop_hit else "time",
                    "stop_at_exit": pos["stop_price"],
                    "hours_held": round(hours_held, 2),
                    "entry_regime": pos.get("regime", "UNKNOWN"),
                    "exit_regime": current_regime,
                }
                log_trade(closed_trade)
                closed_ids.add(trade_id)
                print(f"  EXIT {direction} {asset} @ {exit_price:.4f} | PnL: {pnl_pct*100:.2f}% | Reason: {'stop' if stop_hit else 'time'} | Held: {hours_held:.1f}h")
        else:
            still_open.append(pos)

    # --- Check for new signals ---
    has_long = any(p["direction"] == "LONG" for p in still_open)
    has_short = any(p["direction"] == "SHORT" for p in still_open)

    # LONG signal with regime gate
    if not has_long and current_close > prev["upper"]:
        # Regime gate: only enter longs in BULL
        is_bull = current_regime == "BULL"
        if REQUIRE_BULL and not is_bull:
            pass  # Suppressed by regime filter
        else:
            stop = current_close - ATR_MULT_STOP * current_atr
            trade_id = f"{asset}_LONG_{current_time}"
            sig = {
                "trade_id": trade_id,
                "asset": asset,
                "direction": "LONG",
                "entry_time": current_time,
                "entry_price": current_close,
                "stop_price": stop,
                "entry_atr": current_atr,
                "prev_upper": prev["upper"],
                "regime": current_regime,
            }
            signals.append(sig)
            still_open.append(sig)
            regime_tag = f" [REGIME: {current_regime}]" if not is_bull else ""
            print(f"  NEW LONG {asset} @ {current_close:.4f} | Stop: {stop:.4f} | ATR: {current_atr:.4f}{regime_tag}")

    # SHORT Variant B (no regime gate — profitable in all regimes)
    if not has_short and asset in SHORT_ASSETS:
        short_trigger = prev["lower"] - ATR_MULT_ENTRY * current_atr
        if current_close < short_trigger:
            stop = current_close + ATR_MULT_STOP * current_atr
            trade_id = f"{asset}_SHORT_{current_time}"
            sig = {
                "trade_id": trade_id,
                "asset": asset,
                "direction": "SHORT",
                "entry_time": current_time,
                "entry_price": current_close,
                "stop_price": stop,
                "entry_atr": current_atr,
                "prev_lower": prev["lower"],
                "short_trigger": short_trigger,
                "regime": current_regime,
            }
            signals.append(sig)
            still_open.append(sig)
            print(f"  NEW SHORT {asset} @ {current_close:.4f} | Stop: {stop:.4f} | Trigger: {short_trigger:.4f} [REGIME: {current_regime}]")

    state["open_positions"] = other_positions + still_open
    state["closed_trade_ids"] = list(closed_ids)
    return signals, state["open_positions"]


# === REGIME SUMMARY ===
def print_regime_summary(indicators_by_asset):
    """Print current regime for each asset."""
    print("\n--- REGIME STATUS ---")
    for asset, indicators in indicators_by_asset.items():
        if len(indicators) > 0:
            latest = indicators[-1]
            regime = latest.get("regime", "UNKNOWN")
            sma200 = latest.get("sma200", 0)
            close = latest["close"]
            above = "ABOVE" if close > sma200 else "BELOW"
            print(f"  {asset:5s}: {regime:8s} | close {above} SMA200 ({sma200:.4f})")
    print()


# === MAIN ===
def main():
    print(f"=== ATR BO Paper Trader v2 (Regime-Gated) | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ===")
    print(f"Assets: {', '.join(ASSETS)}")
    print(f"Short sleeve: {', '.join(sorted(SHORT_ASSETS))}")
    print(f"Regime gate: {'BULL ONLY (longs)' if REQUIRE_BULL else 'DISABLED'}")
    print()

    state = load_state()
    state["scan_count"] = state.get("scan_count", 0) + 1
    prev_open = len(state.get("open_positions", []))
    print(f"Loaded state: scan #{state['scan_count']} | {prev_open} open positions | {len(state.get('closed_trade_ids', []))} closed trades")
    print()

    all_signals = []
    fetch_errors = []
    indicators_by_asset = {}

    for asset in ASSETS:
        try:
            candles = fetch_klines(asset)
            if len(candles) < DONCHIAN_PERIOD + 2:
                print(f"  {asset}: insufficient candles ({len(candles)})")
                fetch_errors.append(asset)
                continue

            indicators = compute_indicators(candles)
            indicators_by_asset[asset] = indicators

            # Check regime
            latest = indicators[-1]
            print(f"  {asset:5s}: close={latest['close']:.4f} | regime={latest['regime']} | atr={latest['atr']:.4f}")

            signals, state["open_positions"] = process_asset(asset, indicators, state)
            all_signals.extend(signals)

        except Exception as e:
            print(f"  {asset}: ERROR - {e}")
            fetch_errors.append(asset)

    # Regime summary
    print_regime_summary(indicators_by_asset)

    # === SUMMARY ===
    print("=" * 60)
    print("OPEN POSITIONS:")
    open_pos = state.get("open_positions", [])
    if not open_pos:
        print("  (none)")
    else:
        for p in open_pos:
            direction = p["direction"]
            asset = p["asset"]
            age_h = (time.time() * 1000 - p["entry_time"]) / (1000 * 3600) if "entry_time" in p else 0
            max_h = MAX_HOLD_LONG if direction == "LONG" else MAX_HOLD_SHORT
            regime = p.get("regime", "?")
            print(f"  {direction:5s} {asset:5s} | Entry: {p['entry_price']:.4f} | Stop: {p['stop_price']:.4f} | Age: {age_h:.1f}h/{max_h}h | Regime: {regime}")

    print()
    print(f"NEW SIGNALS: {len(all_signals)}")
    if fetch_errors:
        print(f"FETCH ERRORS: {', '.join(fetch_errors)}")
    print(f"TOTAL OPEN: {len(open_pos)}")
    print()

    save_state(state)
    print(f"State saved to {STATE_FILE}")


if __name__ == "__main__":
    main()
