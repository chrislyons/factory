#!/usr/bin/env python3
"""
IG-88 Portfolio Overview — quick status of all venues.
Shows: 4H ATR positions, Polymarket positions, wallet balance.
"""
import json, sys
from pathlib import Path
from datetime import datetime, timezone

BASE = Path("/Users/nesbitt/dev/factory/agents/ig88")
CRYPTO_STATE = BASE / "data" / "paper_4h" / "state.json"
PM_STATE = BASE / "data" / "polymarket" / "paper_trader_state.json"


def load_json(p):
    try:
        return json.loads(p.read_text())
    except:
        return {}


def main():
    print("=" * 60)
    print("  IG-88 PORTFOLIO OVERVIEW")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # === 4H ATR CRYPTO ===
    print("\n[4H ATR CRYPTO — Kraken Spot]")
    crypto = load_json(CRYPTO_STATE)
    if crypto:
        equity = crypto.get("equity", 0)
        cash = crypto.get("cash", 0)
        trades = len(crypto.get("trade_history", []))
        wins = sum(1 for t in crypto.get("trade_history", []) if t.get("pnl", 0) > 0)
        positions = crypto.get("open_positions", [])
        print(f"  Equity:  ${equity:,.2f}")
        print(f"  Cash:    ${cash:,.2f}")
        print(f"  Trades:  {trades} ({wins}W/{trades-wins}L = {wins/max(trades,1)*100:.0f}%)")
        print(f"  PnL:     ${equity - 10000:+,.2f} ({(equity/10000 - 1)*100:+.2f}%)")
        if positions:
            print(f"  Open Positions ({len(positions)}):")
            for p in positions:
                age = ""
                try:
                    t = datetime.fromisoformat(p.get("time", "").replace("Z", "+00:00"))
                    age = f" ({(datetime.now(timezone.utc) - t).total_seconds()/3600:.1f}h)"
                except:
                    pass
                print(f"    {p['side']:>5s} {p['pair']:<12s} @ ${p['entry_price']:.4f}  SL=${p['stop_loss']:.4f}{age}")
    else:
        print("  No state file found")

    # === POLYMARKET ===
    print("\n[POLYMARKET — Prediction Markets]")
    pm = load_json(PM_STATE)
    if pm:
        pm_eq = pm.get("cash", 0)
        pm_positions = pm.get("positions", {})
        pm_trades = len(pm.get("trade_history", []))
        pm_wins = sum(1 for t in pm.get("trade_history", []) if t.get("pnl", 0) > 0)
        print(f"  Cash:    ${pm_eq:,.2f}")
        print(f"  Trades:  {pm_trades} ({pm_wins}W/{pm_trades-pm_wins}L)")
        if pm_positions:
            print(f"  Open Positions ({len(pm_positions)}):")
            for pid, p in list(pm_positions.items())[:5]:
                q = p.get("question", "N/A")[:50]
                print(f"    {p['side']:>4s} ${p['position_size_usd']:.0f} | {q}")
    else:
        print("  No state file found")

    # === TOTAL ===
    print("\n[COMBINED]")
    crypto_eq = crypto.get("equity", 10000) if crypto else 10000
    pm_eq = pm.get("cash", 1000) if pm else 1000
    total = crypto_eq + pm_eq
    invested = 11000  # 10000 + 1000
    print(f"  Total Equity: ${total:,.2f}")
    print(f"  Combined PnL:  ${total - invested:+,.2f} ({(total/invested - 1)*100:+.2f}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
