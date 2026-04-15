#!/usr/bin/env python3
"""
Paper Trading Engine v4 — Portfolio v5 (IG88060)
5-Edge Maximum Diversification System

Strategies:
  1. ETH Thu/Fri Keltner (30%, 2x leverage, 3.0x ATR trail)
  2. ETH Vol Breakout (25%, 2x leverage, 4.0x ATR trail)
  3. LINK Thu/Fri Keltner (15%, 1.5x leverage, 3.0x ATR trail)
  4. ETH Week 2 Keltner (15%, 2x leverage, 3.0x ATR trail)
  5. ETH MACD Histogram Cross (15%, 2x leverage, 3.0x ATR trail)

  Monte Carlo: median 8.17x/yr, P(2x)=99.8%, P(5x)=83.1%, P(loss)=0.0%

Usage:
  python3 scripts/paper_trader_v4.py           # Check signals
  python3 scripts/paper_trader_v4.py --summary  # Daily summary
  python3 scripts/paper_trader_v4.py --reset    # Reset all positions
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

AGENT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = AGENT_ROOT / "data" / "paper_v4"
STATE_FILE = DATA_DIR / "state.json"
TRADES_LOG = DATA_DIR / "trades.jsonl"

STARTING_CAPITAL = 1000.0  # CAD
FRICTION = 0.0050  # Kraken maker round-trip
MAX_HOLD_BARS = 30  # 4h bars = 5 days max hold


def fetch_binance_4h(pair: str, limit: int = 500) -> pd.DataFrame:
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
    return df.set_index('open_time')[['open', 'high', 'low', 'close', 'volume']]


def compute_atr(high, low, close, period=14):
    tr = np.maximum(high[1:]-low[1:], np.maximum(np.abs(high[1:]-close[:-1]), np.abs(low[1:]-close[:-1])))
    tr = np.concatenate([[0], tr])
    return pd.Series(tr).rolling(period).mean().values


def compute_adx(high, low, close, period=14):
    atr = compute_atr(high, low, close, period)
    plus_dm = np.where((high[1:]-high[:-1])>(low[:-1]-low[1:]), np.maximum(high[1:]-high[:-1],0),0)
    plus_dm = np.concatenate([[0], plus_dm])
    minus_dm = np.where((low[:-1]-low[1:])>(high[1:]-high[:-1]), np.maximum(low[:-1]-low[1:],0),0)
    minus_dm = np.concatenate([[0], minus_dm])
    plus_di = 100*pd.Series(plus_dm).rolling(period).mean().values/np.where(atr>0,atr,1)
    minus_di = 100*pd.Series(minus_dm).rolling(period).mean().values/np.where(atr>0,atr,1)
    dx = 100*np.abs(plus_di-minus_di)/np.where(plus_di+minus_di>0,plus_di+minus_di,1)
    return pd.Series(dx).rolling(period).mean().values


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


def check_exit(position: dict, df: pd.DataFrame) -> dict | None:
    close = df['close'].values; high = df['high'].values; low = df['low'].values
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
# Edge 1: ETH Thu/Fri Keltner Breakout (30%, PF 10.9)
# ---------------------------------------------------------------------------
def eth_keltner_thufri_signal(df: pd.DataFrame) -> dict | None:
    close = df['close'].values; high = df['high'].values; low = df['low'].values
    volume = df['volume'].values
    atr = compute_atr(high, low, close)
    adx = compute_adx(high, low, close)
    ema20 = pd.Series(close).ewm(span=20, adjust=False).mean().values
    keltner = ema20 + 2 * atr
    vol_sma = pd.Series(volume).rolling(20).mean().values
    i = len(close) - 2
    if i < 25: return None
    dow = df.index[i].weekday()
    if (dow in [3, 4] and close[i] > keltner[i] and volume[i] > 1.5 * vol_sma[i] and adx[i] > 25):
        return {"strategy": "eth_keltner_thufri", "pair": "ETHUSDT", "entry_price": close[-1],
                "trail_atr_mult": 3.0, "highest_since_entry": close[-1], "signal_bar": i,
                "allocation": 0.30, "leverage": 2.0}
    return None


# ---------------------------------------------------------------------------
# Edge 2: ETH Vol Breakout (25%, PF 3.54)
# ---------------------------------------------------------------------------
def eth_vol_breakout_signal(df: pd.DataFrame) -> dict | None:
    close = df['close'].values; high = df['high'].values; low = df['low'].values
    volume = df['volume'].values
    atr = compute_atr(high, low, close)
    atr_sma = pd.Series(atr).rolling(50).mean().values
    sma20 = pd.Series(close).rolling(20).mean().values
    vol_sma = pd.Series(volume).rolling(20).mean().values
    i = len(close) - 2
    if i < 50: return None
    if (atr[i] > 1.5 * atr_sma[i] and close[i] > sma20[i] and volume[i] > 1.5 * vol_sma[i]):
        return {"strategy": "eth_vol_breakout", "pair": "ETHUSDT", "entry_price": close[-1],
                "trail_atr_mult": 4.0, "highest_since_entry": close[-1], "signal_bar": i,
                "allocation": 0.25, "leverage": 2.0}
    return None


# ---------------------------------------------------------------------------
# Edge 3: LINK Thu/Fri Keltner (15%, PF 2.41)
# ---------------------------------------------------------------------------
def link_keltner_thufri_signal(df: pd.DataFrame) -> dict | None:
    close = df['close'].values; high = df['high'].values; low = df['low'].values
    volume = df['volume'].values
    atr = compute_atr(high, low, close)
    ema20 = pd.Series(close).ewm(span=20, adjust=False).mean().values
    keltner = ema20 + 2 * atr
    vol_sma = pd.Series(volume).rolling(20).mean().values
    i = len(close) - 2
    if i < 25: return None
    dow = df.index[i].weekday()
    if (dow in [3, 4] and close[i] > keltner[i] and volume[i] > 1.5 * vol_sma[i]):
        return {"strategy": "link_keltner_thufri", "pair": "LINKUSDT", "entry_price": close[-1],
                "trail_atr_mult": 3.0, "highest_since_entry": close[-1], "signal_bar": i,
                "allocation": 0.15, "leverage": 1.5}
    return None


# ---------------------------------------------------------------------------
# Edge 4: ETH Week 2 Keltner (15%, PF 4.16)
# ---------------------------------------------------------------------------
def eth_keltner_week2_signal(df: pd.DataFrame) -> dict | None:
    close = df['close'].values; high = df['high'].values; low = df['low'].values
    volume = df['volume'].values
    atr = compute_atr(high, low, close)
    ema20 = pd.Series(close).ewm(span=20, adjust=False).mean().values
    keltner = ema20 + 2 * atr
    vol_sma = pd.Series(volume).rolling(20).mean().values
    i = len(close) - 2
    if i < 25: return None
    day = df.index[i].day
    dow = df.index[i].weekday()
    # Week 2 = days 8-14, exclude Thu/Fri (already captured by edge 1)
    if (8 <= day <= 14 and dow not in [3, 4] and
        close[i] > keltner[i] and volume[i] > 1.5 * vol_sma[i]):
        return {"strategy": "eth_keltner_week2", "pair": "ETHUSDT", "entry_price": close[-1],
                "trail_atr_mult": 3.0, "highest_since_entry": close[-1], "signal_bar": i,
                "allocation": 0.15, "leverage": 2.0}
    return None


# ---------------------------------------------------------------------------
# Edge 5: ETH MACD Histogram Cross (15%, PF 2.94)
# ---------------------------------------------------------------------------
def eth_macd_hist_signal(df: pd.DataFrame) -> dict | None:
    close = df['close'].values; high = df['high'].values; low = df['low'].values
    volume = df['volume'].values
    atr = compute_atr(high, low, close)
    ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    signal_line = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    hist = macd - signal_line
    ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().values
    vol_sma = pd.Series(volume).rolling(20).mean().values
    i = len(close) - 2
    if i < 50: return None
    if (hist[i] > 0 and hist[i-1] <= 0 and close[i] > ema50[i] and volume[i] > 1.2 * vol_sma[i]):
        return {"strategy": "eth_macd_hist", "pair": "ETHUSDT", "entry_price": close[-1],
                "trail_atr_mult": 3.0, "highest_since_entry": close[-1], "signal_bar": i,
                "allocation": 0.15, "leverage": 2.0}
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_scan():
    state = load_state()
    
    strategies = {
        "eth_keltner_thufri": {"signal_fn": eth_keltner_thufri_signal, "pair": "ETHUSDT"},
        "eth_vol_breakout": {"signal_fn": eth_vol_breakout_signal, "pair": "ETHUSDT"},
        "link_keltner_thufri": {"signal_fn": link_keltner_thufri_signal, "pair": "LINKUSDT"},
        "eth_keltner_week2": {"signal_fn": eth_keltner_week2_signal, "pair": "ETHUSDT"},
        "eth_macd_hist": {"signal_fn": eth_macd_hist_signal, "pair": "ETHUSDT"},
    }
    
    # Fetch data
    data = {}
    for pair in set(s["pair"] for s in strategies.values()):
        try:
            data[pair] = fetch_binance_4h(pair)
        except Exception as e:
            print(f"ERROR fetching {pair}: {e}")
            return
    
    # Check exits
    for strat_name, strat in strategies.items():
        if strat_name in state["positions"]:
            pos = state["positions"][strat_name]
            exit_info = check_exit(pos, data[strat["pair"]])
            if exit_info:
                pnl_usd = exit_info["pnl_pct"] * pos["position_size_usd"] * pos.get("leverage", 1.0)
                trade_record = {
                    "strategy": strat_name, "pair": strat["pair"], "side": "long",
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
            position_size = state["portfolio_value"] * signal["allocation"]
            signal["position_size_usd"] = position_size
            signal["entry_time"] = datetime.now(tz=timezone.utc).isoformat()
            state["positions"][strat_name] = signal
            print(f"ENTRY {strat_name}: {signal['pair']} @ ${signal['entry_price']:.4f} | Size: ${position_size:.2f} | Leverage: {signal.get('leverage',1)}x")
        else:
            print(f"NO SIGNAL {strat_name}")
        state.setdefault("last_bar_time", {})[strat_name] = last_bar
    
    save_state(state)
    wr = state['wins'] / max(state['total_trades'], 1)
    print(f"\nPortfolio: ${state['portfolio_value']:.2f} | Trades: {state['total_trades']} | WR: {wr:.0%}")


def show_summary():
    state = load_state()
    print("=" * 60)
    print("PAPER TRADING v4 — Portfolio v5 (5-Edge Diversified)")
    print("=" * 60)
    print(f"Portfolio: ${state['portfolio_value']:.2f} | Capital: ${STARTING_CAPITAL:.2f}")
    pnl_pct = (state['portfolio_value'] / STARTING_CAPITAL - 1) * 100
    print(f"PnL: ${state['total_pnl']:+.2f} ({pnl_pct:+.1f}%) | Trades: {state['total_trades']}")
    if state['total_trades'] > 0:
        print(f"Win Rate: {state['wins']/state['total_trades']:.0%}")
    if state['positions']:
        print("\nOPEN POSITIONS:")
        for s, p in state['positions'].items():
            print(f"  {s}: {p['pair']} @ ${p['entry_price']:.4f} | ${p.get('position_size_usd',0):.2f} | {p.get('leverage',1)}x")
    else:
        print("\nNo open positions.")
    if TRADES_LOG.exists():
        print(f"\nRECENT TRADES:")
        with open(TRADES_LOG) as f:
            for line in f.readlines()[-10:]:
                t = json.loads(line)
                print(f"  {t['strategy']}: {t['pnl_pct']:+.2%} (${t['pnl_usd']:+.2f}) — {t['exit_reason']}")


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
