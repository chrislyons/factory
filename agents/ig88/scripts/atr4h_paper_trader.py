#!/usr/bin/env python3
"""
4H ATR Breakout Paper Trader.
Scans 12 pairs on 4H timeframe for LONG and SHORT signals.
Validated edges: LONG PF 3.39 OOS, SHORT PF 7.90 OOS.

Usage:
  .venv/bin/python3 scripts/atr4h_paper_trader.py scan       # Scan for signals
  .venv/bin/python3 scripts/atr4h_paper_trader.py positions   # Check open positions
  .venv/bin/python3 scripts/atr4h_paper_trader.py close ID    # Close a position
"""
import json, sys, os
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
STATE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/paper_4h")
STATE_DIR.mkdir(parents=True, exist_ok=True)

# === CONFIG ===
PAIRS = ["SOLUSDT", "BTCUSDT", "ETHUSDT", "AVAXUSDT", "ARBUSDT", "OPUSDT",
         "LINKUSDT", "RENDERUSDT", "NEARUSDT", "AAVEUSDT", "DOGEUSDT", "LTCUSDT"]

ATR_PERIOD = 14
DONCHIAN = 20
SMA_REGIME = 100
TRAIL_LONG = 0.015   # 1.5% trailing stop for 4H
TRAIL_SHORT = 0.025  # 2.5% trailing stop for 4H
MAX_HOLD_LONG = 30   # 120 hours = 5 days
MAX_HOLD_SHORT = 20  # 80 hours = 3.3 days
ATR_MULT_LONG = 0    # Just break Donchian
ATR_MULT_SHORT = 1.5 # Break Donchian - ATR*1.5
FRICTION = 0.0014    # Jupiter perps RT fee
POSITION_SIZE_USD = 1000  # Default position size


def load_pair(pair):
    f = DATA_DIR / f"binance_{pair}_60m.parquet"
    if not f.exists(): f = DATA_DIR / f"binance_{pair}_1h.parquet"
    if not f.exists(): return None
    df = pd.read_parquet(f)
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time').sort_index()
    return df

def resample_4h(df):
    return df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()

def compute_atr(df, period=14):
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    tr = np.zeros(len(c))
    for i in range(1, len(c)):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    return pd.Series(tr, index=df.index).rolling(period).mean().values

def load_state():
    p = STATE_DIR / "state.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"open_positions": [], "closed_trades": [], "scan_count": 0}

def save_state(state):
    (STATE_DIR / "state.json").write_text(json.dumps(state, indent=2))

def scan_signals():
    """Scan all pairs for 4H ATR LONG and SHORT signals."""
    state = load_state()
    state["scan_count"] += 1
    now = datetime.now(timezone.utc)
    signals = []

    for pair in PAIRS:
        # Skip if already in position
        open_for_pair = [p for p in state["open_positions"] if p["pair"] == pair]
        if open_for_pair:
            continue

        df = load_pair(pair)
        if df is None: continue
        df4h = resample_4h(df)
        if len(df4h) < SMA_REGIME + DONCHIAN: continue

        c = df4h['close'].values
        h = df4h['high'].values
        l = df4h['low'].values
        atr = compute_atr(df4h)
        sma = pd.Series(c).rolling(SMA_REGIME).mean().values
        upper_dc = pd.Series(h).rolling(DONCHIAN).max().values
        lower_dc = pd.Series(l).rolling(DONCHIAN).min().values

        i = len(c) - 1  # Latest bar

        # LONG signal: above SMA100 + break above Donchian20
        if c[i] > sma[i] and c[i] > upper_dc[i-1]:
            entry_price = c[i]
            stop_loss = entry_price * (1 - TRAIL_LONG)
            position_value = POSITION_SIZE_USD
            size = position_value / entry_price
            signal = {
                "pair": pair, "side": "LONG", "signal_time": now.isoformat(),
                "entry_price": round(entry_price, 6),
                "stop_loss": round(stop_loss, 6),
                "atr": round(atr[i], 6) if not np.isnan(atr[i]) else None,
                "sma100": round(sma[i], 6),
                "donchian20": round(upper_dc[i-1], 6),
                "size": round(size, 4),
                "position_usd": position_value,
                "strategy": "4H_ATR_L"
            }
            signals.append(signal)

        # SHORT signal: below SMA100 + break below Donchian20 - ATR*mult
        if c[i] < sma[i]:
            trigger = lower_dc[i-1] - atr[i-1] * ATR_MULT_SHORT
            if c[i] < trigger:
                entry_price = c[i]
                stop_loss = entry_price * (1 + TRAIL_SHORT)
                position_value = POSITION_SIZE_USD
                size = position_value / entry_price
                signal = {
                    "pair": pair, "side": "SHORT", "signal_time": now.isoformat(),
                    "entry_price": round(entry_price, 6),
                    "stop_loss": round(stop_loss, 6),
                    "atr": round(atr[i], 6) if not np.isnan(atr[i]) else None,
                    "sma100": round(sma[i], 6),
                    "donchian20": round(lower_dc[i-1], 6),
                    "trigger_price": round(trigger, 6),
                    "size": round(size, 4),
                    "position_usd": position_value,
                    "strategy": "4H_ATR_S"
                }
                signals.append(signal)

    # Log signals
    for sig in signals:
        sig_id = f"{sig['pair']}_{sig['side']}_{int(now.timestamp()*1000)}"
        sig["id"] = sig_id
        state["open_positions"].append(sig)
        print(f"\n*** SIGNAL: {sig['side']} {sig['pair']} ***")
        print(f"  Entry: ${sig['entry_price']}")
        print(f"  Stop:  ${sig['stop_loss']}")
        print(f"  Size:  {sig['size']} units (${sig['position_usd']})")
        print(f"  Strategy: {sig['strategy']}")
        if sig.get('atr'):
            print(f"  ATR:   ${sig['atr']}")

    if not signals:
        print(f"\nNo 4H ATR signals at {now.isoformat()}")
        # Print regime status
        print("\nRegime status (4H SMA100):")
        for pair in PAIRS:
            df = load_pair(pair)
            if df is None: continue
            df4h = resample_4h(df)
            if len(df4h) < SMA_REGIME: continue
            c = df4h['close'].values
            sma = pd.Series(c).rolling(SMA_REGIME).mean().values
            above = c[-1] > sma[-1]
            dist = (c[-1]/sma[-1]-1)*100
            h = df4h['high'].values
            upper_dc = pd.Series(h).rolling(DONCHIAN).max().values
            near_dc = (c[-1]/upper_dc[-2]-1)*100
            status = "ABOVE" if above else "BELOW"
            print(f"  {pair:>12s}: {status} SMA100 ({dist:+.1f}%), Donchian gap: {near_dc:+.1f}%")

    save_state(state)

    # Log to file
    log_file = STATE_DIR / f"signals_{now.strftime('%Y-%m-%d')}.jsonl"
    with open(log_file, 'a') as f:
        for sig in signals:
            f.write(json.dumps(sig) + '\n')

    return signals

def check_positions():
    """Check current open positions against latest prices."""
    state = load_state()
    if not state["open_positions"]:
        print("No open positions.")
        return

    print(f"\n{'='*70}")
    print(f"OPEN POSITIONS ({len(state['open_positions'])})")
    print(f"{'='*70}")

    for pos in state["open_positions"]:
        pair = pos["pair"]
        df = load_pair(pair)
        if df is None:
            print(f"\n{pos['id']}: Cannot load data for {pair}")
            continue
        df4h = resample_4h(df)
        c = df4h['close'].values
        current = c[-1]

        if pos["side"] == "LONG":
            pnl_pct = (current / pos["entry_price"] - 1) * 100
            trailing_stop = pos["entry_price"] * (1 - TRAIL_LONG)
            h = df4h['high'].values
            # Dynamic trailing: highest since entry * (1 - trail)
            # Simplified: use current trailing stop from state
        else:
            pnl_pct = (pos["entry_price"] / current - 1) * 100
            trailing_stop = pos["entry_price"] * (1 + TRAIL_SHORT)

        pnl_usd = pnl_pct / 100 * pos["position_usd"]
        hit_stop = (pos["side"] == "LONG" and current <= trailing_stop) or \
                   (pos["side"] == "SHORT" and current >= trailing_stop)

        status = "STOP HIT" if hit_stop else "OPEN"
        print(f"\n{pos['side']} {pair} ({pos['id'][:30]})")
        print(f"  Entry: ${pos['entry_price']:.6f} | Current: ${current:.6f}")
        print(f"  P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
        print(f"  Stop: ${trailing_stop:.6f} | Status: {status}")

    save_state(state)

def close_position(pos_id):
    """Close a position and log the result."""
    state = load_state()
    pos = None
    for p in state["open_positions"]:
        if p["id"].startswith(pos_id):
            pos = p
            break
    if pos is None:
        print(f"Position {pos_id} not found.")
        return

    pair = pos["pair"]
    df = load_pair(pair)
    df4h = resample_4h(df)
    c = df4h['close'].values
    exit_price = c[-1]

    if pos["side"] == "LONG":
        pnl_pct = (exit_price / pos["entry_price"] - 1) * 100 - FRICTION * 100
    else:
        pnl_pct = (pos["entry_price"] / exit_price - 1) * 100 - FRICTION * 100

    pnl_usd = pnl_pct / 100 * pos["position_usd"]

    result = {
        **pos,
        "exit_price": round(exit_price, 6),
        "exit_time": datetime.now(timezone.utc).isoformat(),
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usd": round(pnl_usd, 2),
        "status": "CLOSED"
    }

    state["open_positions"] = [p for p in state["open_positions"] if p["id"] != pos["id"]]
    state["closed_trades"].append(result)
    save_state(state)

    print(f"\nClosed {pos['side']} {pair}:")
    print(f"  Entry: ${pos['entry_price']:.6f} → Exit: ${exit_price:.6f}")
    print(f"  P&L: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")

    # Log to file
    log_file = STATE_DIR / f"closed_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    with open(log_file, 'a') as f:
        f.write(json.dumps(result) + '\n')


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: atr4h_paper_trader.py [scan|positions|close ID]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "scan":
        scan_signals()
    elif cmd == "positions":
        check_positions()
    elif cmd == "close":
        if len(sys.argv) < 3:
            print("Usage: atr4h_paper_trader.py close <position_id>")
            sys.exit(1)
        close_position(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
