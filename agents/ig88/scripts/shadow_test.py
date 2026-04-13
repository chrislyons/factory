#!/usr/bin/env python3
"""
shadow_test.py — Validates the full live execution cycle.
Order: Market Buy 0.1 SOL -> Confirm Fill -> Market Sell 0.1 SOL -> Confirm Fill.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("/Users/nesbitt/dev/factory/agents/ig88")
sys.path.insert(0, str(ROOT))

from src.trading.kraken_executor import KrakenExecutor

def main():
    print(f"Starting Shadow Round-Trip Test: {datetime.now(timezone.utc)}")
    try:
        executor = KrakenExecutor()
        pair = "SOLCAD"
        volume = 0.1
        
        print(f"Step 1: Placing Market BUY order for {volume} {pair}...")
        buy_txid = executor.place_market_order(pair, 'buy', volume)
        print(f"  Order placed. TXID: {buy_txid}")
        
        print("Step 2: Polling for BUY fill...")
        buy_fill = executor.poll_order_status(buy_txid)
        print(f"  BUY Filled at: {buy_fill.get('weightedAvgPrice')}")
        
        print(f"Step 3: Placing Market SELL order for {volume} {pair}...")
        sell_txid = executor.place_market_order(pair, 'sell', volume)
        print(f"  Order placed. TXID: {sell_txid}")
        
        print("Step 4: Polling for SELL fill...")
        sell_fill = executor.poll_order_status(sell_txid)
        print(f"  SELL Filled at: {sell_fill.get('weightedAvgPrice')}")
        
        print("\nSUCCESS: Shadow round-trip completed and logged.")
        
    except Exception as e:
        print(f"\nFAILURE: Shadow test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
