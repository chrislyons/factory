#!/usr/bin/env python3
"""
shadow_test_sell_only.py — Validates the exit leg of the live execution cycle.
Since previous BUY attempts filled, we now verify the SELL path.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("/Users/nesbitt/dev/factory/agents/ig88")
sys.path.insert(0, str(ROOT))

from src.trading.kraken_executor import KrakenExecutor

def main():
    print(f"Starting Shadow SELL-only Test: {datetime.now(timezone.utc)}")
    try:
        executor = KrakenExecutor()
        pair = "SOLCAD"
        volume = 0.1
        
        print(f"Step 1: Placing Market SELL order for {volume} {pair}...")
        sell_txid = executor.place_market_order(pair, 'sell', volume)
        print(f"  Order placed. TXID: {sell_txid}")
        
        print("Step 2: Polling for SELL fill...")
        sell_fill = executor.poll_order_status(sell_txid)
        print(f"  SELL Filled at: {sell_fill.get('weightedAvgPrice')}")
        
        print(f"\nFinal Balance: {executor.get_balance()}")
        print("\nSUCCESS: Shadow sell-leg completed and logged.")
        
    except Exception as e:
        print(f"\nFAILURE: Shadow test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
