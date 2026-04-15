#!/usr/bin/env python3
"""
Paper Trading Engine v2 — ETH Momentum Asia + ETH Vol Breakout (IG88056)

Runs signal generation on live 4h Binance data. Tracks positions and P&L
in a dedicated JSONL log. Designed to run every 4 hours via cron.

Strategies:
  1. ETH Momentum 4h (Asia hours) — 2.5x ATR trailing stop (40% allocation)
  2. ETH Vol Breakout 4h — 4.0x ATR trailing stop (60% allocation)

  Optimized: Vol Breakout wider stops capture bigger winners. Walk-forward test 4.31x (IG88058).

Usage:
  python3 scripts/paper_trader_v2.py           # Check signals
  python3 scripts/paper_trader_v2.py --summary  # Daily summary
  python3 scripts/paper_trader_v2.py --reset    # Reset all positions
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

AGENT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = AGENT_ROOT / "data" / "paper_v2"
STATE_FILE = DATA_DIR / "state.json"
TRADES_LOG = DATA_DIR / "trades.jsonl"
SUMMARY_LOG = DATA_DIR / "daily_summaries.jsonl"

STARTING_CAPITAL = 1000.0  # CAD
FRICTION = 0.0050  # Kraken maker round-trip
POSITION_SIZE = 0.50  # 50% of capital per strategy (total 100%)
MAX_HOLD_BARS = 30  # 4h bars = 5 days max hold


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_binance_4h(pair: str, limit: int = 500) -> pd.DataFrame:
    """Fetch 4h candles from Binance."""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": pair, "interval": "4h", "limit": limit}
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
    df = df.set_index('open_time')
    return df[['open', 'high', 'low', 'close', 'volume']]


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def compute_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    diff = np.diff(close)
    gains = np.maximum(diff, 0)
    losses = np.abs(np.minimum(diff, 0))
    ag = pd.Series(gains).rolling(period).mean().values
    al = pd.Series(losses).rolling(period).mean().values
    rs = np.where(al > 0, ag / al, 0)
    r = 100 - 100 / (1 + rs)
    return np.concatenate([[50], r])


def compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    tr = np.concatenate([[0], tr])
    return pd.Series(tr).rolling(period).mean().values


def compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    tr = np.concatenate([[0], tr])
    atr = pd.Series(tr).rolling(period).mean().values
    
    plus_dm = np.where(
        (high[1:] - high[:-1]) > (low[:-1] - low[1:]),
        np.maximum(high[1:] - high[:-1], 0), 0
    )
    plus_dm = np.concatenate([[0], plus_dm])
    
    minus_dm = np.where(
        (low[:-1] - low[1:]) > (high[1:] - high[:-1]),
        np.maximum(low[:-1] - low[1:], 0), 0
    )
    minus_dm = np.concatenate([[0], minus_dm])
    
    plus_di = 100 * pd.Series(plus_dm).rolling(period).mean().values / np.where(atr > 0, atr, 1)
    minus_di = 100 * pd.Series(minus_dm).rolling(period).mean().values / np.where(atr > 0, atr, 1)
    dx = 100 * np.abs(plus_di - minus_di) / np.where(plus_di + minus_di > 0, plus_di + minus_di, 1)
    return pd.Series(dx).rolling(period).mean().values


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ETH Momentum Strategy
# ---------------------------------------------------------------------------

def eth_momentum_signal(df: pd.DataFrame) -> dict | None:
    """Generate ETH momentum signal. Returns trade dict or None.
    
    Upgraded with Asia hours filter (IG88055):
    - Only trade during 00:00-08:00 UTC (Asia session)
    - PF improves from 1.65-2.25 to 2.1-2.99 across all splits
    """
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values
    
    atr = compute_atr(high, low, close)
    adx = compute_adx(high, low, close)
    adx_change = np.diff(adx, prepend=adx[0])
    hh20 = pd.Series(high).rolling(20).max().values
    vol_sma = pd.Series(volume).rolling(20).mean().values
    
    i = len(close) - 2  # Previous completed bar
    
    if i < 25:
        return None
    
    # Asia hours filter (00:00-08:00 UTC)
    hour = df.index[i].hour
    asia_hours = hour in range(0, 9)
    
    # ADX accelerating filter (trend strengthening)
    adx_rising = adx_change[i] > 0 and adx_change[i-1] > 0
    
    signal = (close[i] > hh20[i-1] and 
              volume[i] > 1.5 * vol_sma[i] and 
              adx[i] > 25 and 
              asia_hours)
    
    if signal:
        entry_price = close[-1]  # Current bar close
        trail_stop = entry_price - 2.5 * atr[i]
        return {
            "strategy": "eth_momentum_4h",
            "pair": "ETHUSDT",
            "asset": "ETH",
            "entry_price": entry_price,
            "trail_atr_mult": 2.5,
            "atr_at_entry": float(atr[i]),
            "stop_price": trail_stop,
            "highest_since_entry": entry_price,
            "signal_bar": i,
        }
    return None


def eth_momentum_check_exit(position: dict, df: pd.DataFrame) -> dict | None:
    """Check if ETH momentum position should be exited."""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    
    atr = compute_atr(high, low, close)
    i = len(close) - 1  # Current bar
    
    highest = max(position["highest_since_entry"], close[i])
    trail_stop = highest - position["trail_atr_mult"] * atr[i]
    
    ret = (close[i] - position["entry_price"]) / position["entry_price"] - FRICTION
    bars_held = i - position["signal_bar"]
    
    if close[i] < trail_stop:
        return {"exit_price": close[i], "exit_reason": "trailing_stop", "pnl_pct": ret, "bars_held": bars_held}
    if bars_held >= MAX_HOLD_BARS:
        return {"exit_price": close[i], "exit_reason": "time_stop", "pnl_pct": ret, "bars_held": bars_held}
    
    # Update highest for next check
    position["highest_since_entry"] = highest
    return None


# ---------------------------------------------------------------------------
# ETH Volatility Breakout Strategy (IG88056)
# ---------------------------------------------------------------------------

def eth_vol_breakout_signal(df: pd.DataFrame) -> dict | None:
    """Generate ETH volatility breakout signal. Returns trade dict or None.
    
    IG88056: Third confirmed edge.
    - PF 2.39-2.84 across all walk-forward splits
    - Only 12.8% overlap with ETH Momentum (mostly independent)
    - Fires during ALL hours (not restricted to Asia)
    
    Entry: ATR > 1.5x ATR SMA(50) + Close > SMA(20) + Volume > 1.5x SMA
    Exit: 3.0x ATR trailing stop
    """
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values
    
    atr = compute_atr(high, low, close)
    atr_sma = pd.Series(atr).rolling(50).mean().values
    sma20 = pd.Series(close).rolling(20).mean().values
    vol_sma = pd.Series(volume).rolling(20).mean().values
    
    i = len(close) - 2
    
    if i < 50:
        return None
    
    vol_expansion = atr[i] > 1.5 * atr_sma[i]
    price_up = close[i] > sma20[i]
    volume_spike = volume[i] > 1.5 * vol_sma[i]
    
    if vol_expansion and price_up and volume_spike:
        entry_price = close[-1]
        trail_stop = entry_price - 4.0 * atr[i]
        return {
            "strategy": "eth_vol_breakout_4h",
            "pair": "ETHUSDT",
            "asset": "ETH",
            "entry_price": entry_price,
            "trail_atr_mult": 4.0,
            "atr_at_entry": float(atr[i]),
            "stop_price": trail_stop,
            "highest_since_entry": entry_price,
            "signal_bar": i,
        }
    return None


def eth_vol_breakout_check_exit(position: dict, df: pd.DataFrame) -> dict | None:
    """Check if ETH vol breakout position should be exited."""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    
    atr = compute_atr(high, low, close)
    i = len(close) - 1
    
    highest = max(position["highest_since_entry"], close[i])
    trail_stop = highest - position["trail_atr_mult"] * atr[i]
    
    ret = (close[i] - position["entry_price"]) / position["entry_price"] - FRICTION
    bars_held = i - position["signal_bar"]
    
    if close[i] < trail_stop:
        return {"exit_price": close[i], "exit_reason": "trailing_stop", "pnl_pct": ret, "bars_held": bars_held}
    if bars_held >= MAX_HOLD_BARS:
        return {"exit_price": close[i], "exit_reason": "time_stop", "pnl_pct": ret, "bars_held": bars_held}
    
    position["highest_since_entry"] = highest
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_scan():
    """Main scan cycle. Check for signals and exits."""
    state = load_state()
    
    strategies = {
        "eth_momentum_4h": {
            "signal_fn": eth_momentum_signal,
            "exit_fn": eth_momentum_check_exit,
            "allocation": 0.40,
        },
        "eth_vol_breakout_4h": {
            "signal_fn": eth_vol_breakout_signal,
            "exit_fn": eth_vol_breakout_check_exit,
            "allocation": 0.60,
        },
    }
    
    pair_map = {
        "eth_momentum_4h": "ETHUSDT",
        "eth_vol_breakout_4h": "ETHUSDT",
    }
    
    # Fetch data
    data = {}
    for strat_name, pair in pair_map.items():
        try:
            data[pair] = fetch_binance_4h(pair)
        except Exception as e:
            print(f"ERROR fetching {pair}: {e}")
            return
    
    # Check exits first
    for strat_name, strat in strategies.items():
        pair = pair_map[strat_name]
        if strat_name in state["positions"]:
            pos = state["positions"][strat_name]
            exit_info = strat["exit_fn"](pos, data[pair])
            if exit_info:
                pnl_usd = exit_info["pnl_pct"] * pos["position_size_usd"]
                trade_record = {
                    "strategy": strat_name,
                    "pair": pair,
                    "side": "long",
                    "entry_price": pos["entry_price"],
                    "exit_price": exit_info["exit_price"],
                    "position_size_usd": pos["position_size_usd"],
                    "pnl_pct": exit_info["pnl_pct"],
                    "pnl_usd": pnl_usd,
                    "exit_reason": exit_info["exit_reason"],
                    "bars_held": exit_info["bars_held"],
                    "entry_time": pos.get("entry_time", "unknown"),
                    "exit_time": datetime.now(tz=timezone.utc).isoformat(),
                }
                log_trade(trade_record)
                
                state["portfolio_value"] += pnl_usd
                state["total_trades"] += 1
                state["total_pnl"] += pnl_usd
                if pnl_usd > 0:
                    state["wins"] += 1
                
                del state["positions"][strat_name]
                print(f"EXIT {strat_name}: {exit_info['exit_reason']} | PnL: {pnl_usd:+.2f} USD ({exit_info['pnl_pct']:+.2%})")
    
    # Check entries
    now = datetime.now(tz=timezone.utc)
    for strat_name, strat in strategies.items():
        if strat_name in state["positions"]:
            continue  # Already have position
        
        pair = pair_map[strat_name]
        df = data[pair]
        
        # Check if we already processed this bar
        last_bar = str(df.index[-2])  # Second to last (last completed bar)
        if state.get("last_bar_time", {}).get(strat_name) == last_bar:
            continue
        
        signal = strat["signal_fn"](df)
        if signal:
            position_size = state["portfolio_value"] * POSITION_SIZE * strat["allocation"]
            signal["position_size_usd"] = position_size
            signal["entry_time"] = now.isoformat()
            signal["signal_bar"] = len(df) - 2
            
            state["positions"][strat_name] = signal
            print(f"ENTRY {strat_name}: {signal['pair']} @ ${signal['entry_price']:.4f} | Size: ${position_size:.2f}")
        else:
            print(f"NO SIGNAL {strat_name}: no entry condition met")
        
        state.setdefault("last_bar_time", {})[strat_name] = last_bar
    
    save_state(state)
    print(f"\nPortfolio: ${state['portfolio_value']:.2f} | Trades: {state['total_trades']} | Win rate: {state['wins']/max(state['total_trades'],1):.0%}")


def show_summary():
    """Print daily summary."""
    state = load_state()
    
    print("=" * 60)
    print("PAPER TRADING SUMMARY v2 — ETH Momentum Asia + ETH Vol Breakout")
    print("=" * 60)
    print(f"Portfolio Value: ${state['portfolio_value']:.2f}")
    print(f"Starting Capital: ${STARTING_CAPITAL:.2f}")
    pnl_pct = (state['portfolio_value'] / STARTING_CAPITAL - 1) * 100
    print(f"Total PnL: ${state['total_pnl']:+.2f} ({pnl_pct:+.1f}%)")
    print(f"Total Trades: {state['total_trades']}")
    if state['total_trades'] > 0:
        print(f"Win Rate: {state['wins']/state['total_trades']:.0%}")
    print()
    
    if state['positions']:
        print("OPEN POSITIONS:")
        for strat, pos in state['positions'].items():
            print(f"  {strat}: {pos['pair']} @ ${pos['entry_price']:.4f} | Size: ${pos.get('position_size_usd', 0):.2f}")
    else:
        print("No open positions.")
    
    # Trade history
    if TRADES_LOG.exists():
        print(f"\nTRADE HISTORY ({TRADES_LOG}):")
        with open(TRADES_LOG) as f:
            lines = f.readlines()
        for line in lines[-10:]:  # Last 10 trades
            t = json.loads(line)
            print(f"  {t['strategy']}: {t['pnl_pct']:+.2%} (${t['pnl_usd']:+.2f}) — {t['exit_reason']}")


def reset_positions():
    """Reset all positions (paper reset)."""
    state = {
        "portfolio_value": STARTING_CAPITAL,
        "positions": {},
        "last_bar_time": {},
        "total_trades": 0,
        "wins": 0,
        "total_pnl": 0.0,
    }
    save_state(state)
    print(f"State reset. Starting capital: ${STARTING_CAPITAL}")


if __name__ == "__main__":
    if "--summary" in sys.argv:
        show_summary()
    elif "--reset" in sys.argv:
        reset_positions()
    else:
        run_scan()
