#!/usr/bin/env python3
"""
Jupiter Perps Short Paper Trader — IG88063

Short-side strategies for Jupiter Perps (BTC/ETH/SOL on Solana).
Ontario-compliant venue for short selling.

Strategies (all daily timeframe):
  S1: ETH Daily Break EMA50 (30% allocation, 2.0x ATR trail) — PRIMARY
      PF: 2.05 | OOS PF: 2.119 | n=20 | WR 45%
      Entry: Close < EMA50 + prev close >= EMA50 + Volume > 1.2x SMA20
      Exit: 2.0x ATR trailing stop (tracks lowest low)

  S2: ETH Daily Break 20-Low (15% allocation, 2.0x ATR trail) — TERTIARY
      PF: 1.65 | n=19 | WR 53%
      Entry: Close < 20-bar low (excl current) + Volume > 1.5x SMA20
      Exit: 2.0x ATR trailing stop

Regime Gate: BTC Daily SMA50
  RISK_OFF (<SMA50): Full allocation to short edges
  RISK_ON  (>SMA50): Halve short allocation (trend may reverse)

Usage:
  python3 scripts/jupiter_shorts.py           # Check signals
  python3 scripts/jupiter_shorts.py --summary  # Daily summary
  python3 scripts/jupiter_shorts.py --reset    # Reset all
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

AGENT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = AGENT_ROOT / "data" / "jupiter_shorts"
STATE_FILE = DATA_DIR / "state.json"
TRADES_LOG = DATA_DIR / "trades.jsonl"

STARTING_CAPITAL = 1000.0  # USD (for paper)
FRICTION = 0.0010  # Jupiter Perps fee (~0.1%)
MAX_HOLD_BARS = 30  # daily bars = 30 days max hold


def fetch_binance_daily(pair: str, limit: int = 500) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": pair, "interval": "1d", "limit": limit}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df.set_index('open_time')[['open', 'high', 'low', 'close', 'volume']]


def detect_regime() -> str:
    """BTC Daily SMA50 regime detection."""
    try:
        btc = fetch_binance_daily("BTCUSDT", limit=100)
        close = btc['close'].values
        sma50 = pd.Series(close).rolling(50).mean().values
        if len(close) < 51:
            return "UNKNOWN"
        return "RISK_ON" if close[-1] > sma50[-1] else "RISK_OFF"
    except Exception:
        return "UNKNOWN"


def compute_atr(high, low, close, period=14):
    tr = np.maximum(high[1:]-low[1:], np.maximum(np.abs(high[1:]-close[:-1]), np.abs(low[1:]-close[:-1])))
    tr = np.concatenate([[0], tr])
    return pd.Series(tr).rolling(period).mean().values


def load_state() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "portfolio_value": STARTING_CAPITAL,
        "positions": {},
        "last_bar_time": {},
        "total_trades": 0,
        "wins": 0,
        "total_pnl": 0.0,
    }


def save_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def log_trade(trade: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    trade["logged_at"] = datetime.now(tz=timezone.utc).isoformat()
    with open(TRADES_LOG, "a") as f:
        f.write(json.dumps(trade, default=str) + "\n")


def check_exit_short(position: dict, df: pd.DataFrame) -> dict | None:
    """Check if a short position should exit.

    For shorts:
    - Track lowest low since entry
    - Trail stop = lowest + ATR * trail_mult
    - Exit when close > trail stop (price rising past stop)
    - PnL = (entry - exit) / entry - friction (positive when price drops)
    """
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = compute_atr(high, low, close)
    i = len(close) - 1

    lowest = min(position["lowest_since_entry"], low[i])
    trail_stop = lowest + position["trail_atr_mult"] * atr[i]

    ret = (position["entry_price"] - close[i]) / position["entry_price"] - FRICTION
    bars_held = i - position["signal_bar"]

    if close[i] > trail_stop:
        return {"exit_price": close[i], "exit_reason": "trailing_stop", "pnl_pct": ret, "bars_held": bars_held}
    if bars_held >= MAX_HOLD_BARS:
        return {"exit_price": close[i], "exit_reason": "time_stop", "pnl_pct": ret, "bars_held": bars_held}

    position["lowest_since_entry"] = lowest
    return None


# ---------------------------------------------------------------------------
# S1: ETH Daily Break EMA50 Short (PF 2.05, OOS PF 2.119)
# Entry: next-bar-open
# ---------------------------------------------------------------------------
def eth_short_ema50_signal(df: pd.DataFrame) -> dict | None:
    close = df['close'].values; high = df['high'].values; low = df['low'].values
    volume = df['volume'].values
    atr = compute_atr(high, low, close)
    ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().values
    vol_sma = pd.Series(volume).rolling(20).mean().values
    i = len(close) - 2
    if i < 52: return None
    if (close[i] < ema50[i] and close[i-1] >= ema50[i-1] and volume[i] > 1.2 * vol_sma[i]):
        return {
            "strategy": "eth_short_ema50", "pair": "ETHUSDT", "side": "short",
            "entry_price": df['open'].values[i+1],
            "trail_atr_mult": 2.0,
            "lowest_since_entry": df['open'].values[i+1],
            "signal_bar": i,
            "allocation": 0.30, "leverage": 1.0,
        }
    return None


# ---------------------------------------------------------------------------
# S2: ETH Daily Break 20-Low Short (PF 1.65)
# Entry: next-bar-open
# ---------------------------------------------------------------------------
def eth_short_20low_signal(df: pd.DataFrame) -> dict | None:
    close = df['close'].values; high = df['high'].values; low = df['low'].values
    volume = df['volume'].values
    atr = compute_atr(high, low, close)
    low20 = pd.Series(low[:-1]).rolling(20).max().values  # 20-bar HIGH of lows (for break below)
    # Actually: we want 20-bar LOW. When price closes below the 20-bar low, it's a breakdown.
    # The 20-bar low is the MINIMUM of the last 20 lows (excluding current bar).
    low20 = pd.Series(low[:-1]).rolling(20).min().values
    vol_sma = pd.Series(volume).rolling(20).mean().values
    i = len(close) - 2
    if i < 22: return None
    # Check if close breaks below 20-bar low
    if close[i] < low20[i-1] and volume[i] > 1.5 * vol_sma[i]:
        return {
            "strategy": "eth_short_20low", "pair": "ETHUSDT", "side": "short",
            "entry_price": df['open'].values[i+1],
            "trail_atr_mult": 2.0,
            "lowest_since_entry": df['open'].values[i+1],
            "signal_bar": i,
            "allocation": 0.15, "leverage": 1.0,
        }
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run_scan():
    state = load_state()

    strategies = {
        "eth_short_ema50": {"signal_fn": eth_short_ema50_signal, "pair": "ETHUSDT"},
        "eth_short_20low": {"signal_fn": eth_short_20low_signal, "pair": "ETHUSDT"},
    }

    # Detect regime
    regime = detect_regime()
    state["regime"] = regime
    regime_mult = 1.0 if regime == "RISK_OFF" else 0.5  # Halve shorts in uptrend
    print(f"Regime: {regime} (short multiplier: {regime_mult:.0%})")

    # Fetch daily data
    data = {}
    for pair in set(s["pair"] for s in strategies.values()):
        try:
            data[pair] = fetch_binance_daily(pair, limit=300)
        except Exception as e:
            print(f"ERROR fetching {pair}: {e}")
            return

    # Check exits
    for strat_name, strat in strategies.items():
        if strat_name in state["positions"]:
            pos = state["positions"][strat_name]
            exit_info = check_exit_short(pos, data[strat["pair"]])
            if exit_info:
                pnl_usd = exit_info["pnl_pct"] * pos["position_size_usd"] * pos.get("leverage", 1.0)
                trade_record = {
                    "strategy": strat_name, "pair": strat["pair"], "side": "short",
                    "entry_price": pos["entry_price"], "exit_price": exit_info["exit_price"],
                    "position_size_usd": pos["position_size_usd"],
                    "pnl_pct": exit_info["pnl_pct"], "pnl_usd": pnl_usd,
                    "exit_reason": exit_info["exit_reason"], "bars_held": exit_info["bars_held"],
                    "exit_time": datetime.now(tz=timezone.utc).isoformat(),
                }
                log_trade(trade_record)
                state["portfolio_value"] += pnl_usd
                state["total_trades"] += 1
                state["total_pnl"] += pnl_usd
                if pnl_usd > 0: state["wins"] += 1
                del state["positions"][strat_name]
                print(f"EXIT {strat_name}: {exit_info['exit_reason']} | PnL: {pnl_usd:+.2f} ({exit_info['pnl_pct']:+.2%})")

    # Check entries
    for strat_name, strat in strategies.items():
        if strat_name in state["positions"]:
            continue
        df = data[strat["pair"]]
        last_bar = str(df.index[-2])
        if state.get("last_bar_time", {}).get(strat_name) == last_bar:
            continue
        signal = strat["signal_fn"](df)
        if signal:
            # Apply regime multiplier
            alloc = signal["allocation"] * regime_mult
            position_size = state["portfolio_value"] * alloc
            signal["position_size_usd"] = position_size
            signal["allocation"] = alloc
            signal["entry_time"] = datetime.now(tz=timezone.utc).isoformat()
            state["positions"][strat_name] = signal
            print(f"ENTRY {strat_name}: SHORT {signal['pair']} @ ${signal['entry_price']:.4f} | Size: ${position_size:.2f}")
        else:
            print(f"NO SIGNAL {strat_name}")
        state.setdefault("last_bar_time", {})[strat_name] = last_bar

    save_state(state)
    wr = state['wins'] / max(state['total_trades'], 1)
    print(f"\nPortfolio: ${state['portfolio_value']:.2f} | Trades: {state['total_trades']} | WR: {wr:.0%}")


def show_summary():
    state = load_state()
    regime = state.get("regime", "UNKNOWN")
    print("=" * 60)
    print("JUPITER SHORTS — Portfolio Short-Side (IG88063)")
    print("=" * 60)
    print(f"Portfolio: ${state['portfolio_value']:.2f} | Capital: ${STARTING_CAPITAL:.2f}")
    print(f"Regime: {regime}")
    pnl_pct = (state['portfolio_value'] / STARTING_CAPITAL - 1) * 100
    print(f"PnL: ${state['total_pnl']:+.2f} ({pnl_pct:+.1f}%) | Trades: {state['total_trades']}")
    if state['total_trades'] > 0:
        print(f"Win Rate: {state['wins']/state['total_trades']:.0%}")
    if state['positions']:
        print("\nOPEN SHORT POSITIONS:")
        for s, p in state['positions'].items():
            print(f"  {s}: SHORT {p['pair']} @ ${p['entry_price']:.4f} | ${p.get('position_size_usd',0):.2f} | {p.get('leverage',1)}x")
    else:
        print("\nNo open short positions.")
    if TRADES_LOG.exists():
        print(f"\nRECENT TRADES:")
        with open(TRADES_LOG) as f:
            for line in f.readlines()[-10:]:
                t = json.loads(line)
                side = t.get('side', 'long').upper()
                print(f"  {t['strategy']}: {side} {t['pnl_pct']:+.2%} (${t['pnl_usd']:+.2f}) — {t['exit_reason']}")


def reset_positions():
    state = {
        "portfolio_value": STARTING_CAPITAL, "positions": {}, "last_bar_time": {},
        "total_trades": 0, "wins": 0, "total_pnl": 0.0,
    }
    save_state(state)
    print(f"Reset. Starting capital: ${STARTING_CAPITAL}")


if __name__ == "__main__":
    if "--summary" in sys.argv:
        show_summary()
    elif "--reset" in sys.argv:
        reset_positions()
    else:
        run_scan()
