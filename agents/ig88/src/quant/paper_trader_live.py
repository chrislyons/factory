"""
paper_trader_live.py — Live paper trading engine for Kraken + Jupiter.

Tracks open positions, monitors exits, logs closed trades to paper_trades.jsonl.
Runs as part of the h3_scanner.py cycle every 4h.

Paper trade record schema:
  {
    "id": "PT-YYYYMMDD-HHMMSS-STRATEGY",
    "timestamp_entry": ISO,
    "timestamp_exit": ISO | null,
    "venue": "kraken_spot" | "jupiter_perps",
    "strategy": "H3-A" | "H3-B" | "H3-C" | "H3-D",
    "symbol": "SOL/USD",
    "interval": "4h",
    "entry_price": float,
    "initial_stop": float,     # 2x ATR below entry
    "target_cap": float,       # 5x ATR above entry
    "atr_at_entry": float,
    "position_size_pct": 2.0,  # % of paper wallet
    "leverage": 1.0,           # 1.0 for spot, 2.0+ for perps
    "status": "OPEN" | "CLOSED",
    "exit_price": float | null,
    "exit_reason": "atr_trail_stop" | "target_cap" | "kijun_exit" | "regime_exit" | "manual",
    "pnl_pct": float | null,
    "pnl_usd": float | null,   # on $10k paper wallet, 2% position
    "fees_pct": 0.32,          # 0.16% entry + 0.16% exit (maker both sides)
    "net_pnl_pct": float | null,
    "trail_stop_current": float | null,  # updated each scan cycle
    "borrow_fees_accrued": float,        # Jupiter perps only
    "signal_conditions": dict,           # what triggered entry
    "regime_at_entry": str,
    "btc_price_at_entry": float,
    "notes": str
  }
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_DIR  = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
PAPER_LOG = DATA_DIR / "paper_trades.jsonl"
PAPER_WALLET_USD = 10_000.0   # paper wallet size
POSITION_SIZE_PCT = 2.0        # % of wallet per trade
MAKER_FEE = 0.0016             # Kraken maker fee
PERP_FEE  = 0.0007             # Jupiter perp fee per side


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trade_id(strategy: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"PT-{ts}-{strategy}"


def open_paper_trade(
    strategy: str,
    symbol: str,
    entry_price: float,
    atr_at_entry: float,
    regime: str,
    btc_price: float,
    signal_conditions: dict,
    venue: str = "kraken_spot",
    leverage: float = 1.0,
    interval: str = "4h",
    notes: str = "",
) -> dict:
    """
    Create and log a new paper trade entry.
    Returns the trade record dict.
    """
    pos_size_usd = PAPER_WALLET_USD * (POSITION_SIZE_PCT / 100.0)
    initial_stop = entry_price - 2.0 * atr_at_entry
    target_cap   = entry_price + 5.0 * atr_at_entry
    fee_pct      = MAKER_FEE * 2 if venue == "kraken_spot" else PERP_FEE * 2

    record = {
        "id":                  _trade_id(strategy),
        "timestamp_entry":     _now(),
        "timestamp_exit":      None,
        "venue":               venue,
        "strategy":            strategy,
        "symbol":              symbol,
        "interval":            interval,
        "entry_price":         round(entry_price, 6),
        "initial_stop":        round(initial_stop, 6),
        "target_cap":          round(target_cap, 6),
        "trail_stop_current":  round(initial_stop, 6),
        "atr_at_entry":        round(atr_at_entry, 6),
        "position_size_pct":   POSITION_SIZE_PCT,
        "position_size_usd":   round(pos_size_usd, 2),
        "leverage":            leverage,
        "status":              "OPEN",
        "exit_price":          None,
        "exit_reason":         None,
        "pnl_pct":             None,
        "pnl_usd":             None,
        "fees_pct":            round(fee_pct * 100, 4),
        "net_pnl_pct":         None,
        "borrow_fees_accrued": 0.0,
        "signal_conditions":   signal_conditions,
        "regime_at_entry":     regime,
        "btc_price_at_entry":  round(btc_price, 2),
        "notes":               notes,
    }

    _append_record(record)
    return record


def update_trail_stop(trade_id: str, new_close: float, new_atr: float) -> Optional[dict]:
    """
    Update the trailing stop for an open trade.
    Raises stop to max(current_stop, close - 2×ATR).
    Returns updated record if stop was raised, None otherwise.
    """
    records = _load_all()
    for i, r in enumerate(records):
        if r["id"] == trade_id and r["status"] == "OPEN":
            new_stop = new_close - 2.0 * new_atr
            current_stop = r.get("trail_stop_current", r["initial_stop"])
            if new_stop > current_stop:
                records[i]["trail_stop_current"] = round(new_stop, 6)
                _save_all(records)
                return records[i]
            return None
    return None


def close_paper_trade(
    trade_id: str,
    exit_price: float,
    exit_reason: str,
    borrow_fees_pct: float = 0.0,
) -> Optional[dict]:
    """
    Close an open paper trade. Computes PnL including fees.
    exit_reason: 'atr_trail_stop' | 'target_cap' | 'kijun_exit' | 'regime_exit' | 'manual'
    Returns the closed trade record.
    """
    records = _load_all()
    for i, r in enumerate(records):
        if r["id"] == trade_id and r["status"] == "OPEN":
            entry = r["entry_price"]
            pos   = r["position_size_usd"]
            lev   = r["leverage"]

            # Gross P&L (leveraged)
            gross_pct = (exit_price - entry) / entry * lev
            # Fees
            fee_pct   = (r["fees_pct"] / 100.0)  # already both sides
            borrow    = borrow_fees_pct + r.get("borrow_fees_accrued", 0.0)
            net_pct   = gross_pct - fee_pct - borrow
            net_usd   = net_pct * pos

            records[i].update({
                "status":              "CLOSED",
                "timestamp_exit":      _now(),
                "exit_price":          round(exit_price, 6),
                "exit_reason":         exit_reason,
                "pnl_pct":             round(gross_pct * 100, 4),
                "net_pnl_pct":         round(net_pct * 100, 4),
                "pnl_usd":             round(net_usd, 4),
                "borrow_fees_accrued": round(borrow * 100, 4),
            })
            _save_all(records)
            return records[i]
    return None


def get_open_trades(venue: str | None = None) -> list[dict]:
    """Return all currently open paper trades, optionally filtered by venue."""
    records = _load_all()
    open_trades = [r for r in records if r["status"] == "OPEN"]
    if venue:
        open_trades = [r for r in open_trades if r["venue"] == venue]
    return open_trades


def get_trade_summary() -> dict:
    """Return paper trading statistics across all closed trades."""
    records = _load_all()
    closed = [r for r in records if r["status"] == "CLOSED" and r.get("net_pnl_pct") is not None]
    open_t = [r for r in records if r["status"] == "OPEN"]

    if not closed:
        return {
            "total_trades": 0, "open_trades": len(open_t),
            "win_rate": None, "profit_factor": None,
            "total_net_pnl_pct": 0.0, "total_net_pnl_usd": 0.0,
        }

    wins   = [r for r in closed if r["net_pnl_pct"] > 0]
    losses = [r for r in closed if r["net_pnl_pct"] <= 0]
    gross_wins   = sum(r["net_pnl_pct"] for r in wins)
    gross_losses = abs(sum(r["net_pnl_pct"] for r in losses))
    total_pnl    = sum(r["pnl_usd"] for r in closed)

    return {
        "total_trades":      len(closed),
        "open_trades":       len(open_t),
        "wins":              len(wins),
        "losses":            len(losses),
        "win_rate":          round(len(wins) / len(closed) * 100, 1),
        "profit_factor":     round(gross_wins / gross_losses, 3) if gross_losses > 0 else float("inf"),
        "total_net_pnl_pct": round(sum(r["net_pnl_pct"] for r in closed), 4),
        "total_net_pnl_usd": round(total_pnl, 2),
        "by_strategy": _breakdown_by(closed, "strategy"),
        "by_venue":    _breakdown_by(closed, "venue"),
    }


def check_and_update_open_trades(current_prices: dict[str, float], current_atrs: dict[str, float],
                                  current_kijuns: dict[str, float] | None = None) -> list[dict]:
    """
    Check all open trades against current market prices.
    Applies trailing stop logic, detects exits.
    Returns list of trades that were closed this cycle.

    current_prices: {"SOL/USD": 83.5, ...}
    current_atrs:   {"SOL/USD": 1.57, ...}
    current_kijuns: {"SOL/USD": 82.7, ...} optional — for Kijun exit
    """
    closed_this_cycle = []
    open_trades = get_open_trades()

    for trade in open_trades:
        symbol = trade["symbol"]
        price  = current_prices.get(symbol)
        atr    = current_atrs.get(symbol)
        if price is None or atr is None:
            continue

        trail_stop = trade.get("trail_stop_current", trade["initial_stop"])
        target_cap = trade["target_cap"]

        # Check stop hit
        if price <= trail_stop:
            closed = close_paper_trade(trade["id"], price, "atr_trail_stop")
            if closed:
                closed_this_cycle.append(closed)
                print(f"  [CLOSED] {trade['id']}: stop hit at ${price:.3f}  "
                      f"net={closed['net_pnl_pct']:+.2f}%")
            continue

        # Check target cap
        if price >= target_cap:
            closed = close_paper_trade(trade["id"], price, "target_cap")
            if closed:
                closed_this_cycle.append(closed)
                print(f"  [CLOSED] {trade['id']}: target hit at ${price:.3f}  "
                      f"net={closed['net_pnl_pct']:+.2f}%")
            continue

        # Check Kijun exit (if provided)
        if current_kijuns:
            kijun = current_kijuns.get(symbol)
            if kijun and price < kijun:
                closed = close_paper_trade(trade["id"], price, "kijun_exit")
                if closed:
                    closed_this_cycle.append(closed)
                    print(f"  [CLOSED] {trade['id']}: kijun exit at ${price:.3f}  "
                          f"net={closed['net_pnl_pct']:+.2f}%")
                continue

        # Update trailing stop
        update_trail_stop(trade["id"], price, atr)

    return closed_this_cycle


def print_open_positions():
    """Print current open paper positions with unrealized P&L."""
    open_trades = get_open_trades()
    if not open_trades:
        print("  No open paper positions.")
        return

    print(f"  {'ID':<28} {'Strategy':<8} {'Symbol':<10} {'Entry':>9} {'Stop':>9} {'Trail':>9}")
    print(f"  {'-'*28} {'-'*8} {'-'*10} {'-'*9} {'-'*9} {'-'*9}")
    for t in open_trades:
        print(f"  {t['id']:<28} {t['strategy']:<8} {t['symbol']:<10} "
              f"${t['entry_price']:>8.3f} ${t['initial_stop']:>8.3f} "
              f"${t.get('trail_stop_current', t['initial_stop']):>8.3f}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_all() -> list[dict]:
    if not PAPER_LOG.exists():
        return []
    records = []
    with open(PAPER_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _save_all(records: list[dict]):
    with open(PAPER_LOG, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _append_record(record: dict):
    with open(PAPER_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


def _breakdown_by(closed: list[dict], field: str) -> dict:
    breakdown = {}
    for r in closed:
        key = r.get(field, "unknown")
        if key not in breakdown:
            breakdown[key] = {"n": 0, "wins": 0, "total_net_pnl_pct": 0.0}
        breakdown[key]["n"] += 1
        if r["net_pnl_pct"] > 0:
            breakdown[key]["wins"] += 1
        breakdown[key]["total_net_pnl_pct"] += r["net_pnl_pct"]
    return breakdown


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== IG-88 Paper Trading Status ===")
    summary = get_trade_summary()
    if summary["total_trades"] == 0:
        print("No closed paper trades yet.")
    else:
        print(f"Closed trades: {summary['total_trades']}")
        print(f"Win rate:      {summary['win_rate']}%")
        print(f"Profit factor: {summary['profit_factor']}")
        print(f"Total net PnL: {summary['total_net_pnl_pct']:+.2f}%  (${summary['total_net_pnl_usd']:+.2f})")

    print(f"\nOpen positions: {summary['open_trades']}")
    print_open_positions()
