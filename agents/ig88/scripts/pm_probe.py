#!/usr/bin/env python3
"""
Polymarket Wolf Hour Validation — Live Orderbook Probe
Tests the thesis: BTC contract spreads widen during 02:30-04:00 UTC.

This script:
1. Fetches active BTC markets from Gamma API
2. Gets orderbook from CLOB API
3. Computes bid-ask spread
4. Compares to typical spread during active hours
"""

import json
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/polymarket")

def fetch_btc_markets():
    """Get active BTC price markets from Gamma API."""
    url = f"{GAMMA_API}/events"
    params = {"limit": 100, "active": True, "closed": False}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        print(f"Gamma API error: {e}")
        return []
    
    btc_markets = []
    for event in events:
        title = event.get("title", "").lower()
        if any(kw in title for kw in ["btc", "bitcoin"]):
            for market in event.get("markets", []):
                if market.get("active") and not market.get("closed"):
                    token_id = market.get("clobTokenId") or market.get("token_id")
                    if token_id:
                        btc_markets.append({
                            "event": event.get("title"),
                            "question": market.get("question"),
                            "token_id": token_id,
                            "best_bid": market.get("bestBid"),
                            "best_ask": market.get("bestAsk"),
                            "last_price": market.get("lastTradePrice"),
                            "volume": market.get("volume", 0),
                        })
    
    # Sort by volume descending
    btc_markets.sort(key=lambda m: float(m.get("volume", 0) or 0), reverse=True)
    return btc_markets


def fetch_orderbook(token_id):
    """Fetch orderbook from CLOB API."""
    url = f"{CLOB_API}/book"
    params = {"token_id": str(token_id)}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  CLOB API error for {token_id[:16]}...: {e}")
        return None


def compute_spread(book):
    """Compute bid-ask spread from orderbook."""
    if not book:
        return None
    
    bids = book.get("bids", [])
    asks = book.get("asks", [])
    
    if not bids or not asks:
        return None
    
    best_bid = float(bids[0].get("price", 0))
    best_ask = float(asks[0].get("price", 0))
    
    if best_bid <= 0 or best_ask <= 0:
        return None
    
    spread = best_ask - best_bid
    spread_pct = spread / best_bid * 100 if best_bid > 0 else 0
    
    # Depth within 5% of mid
    mid = (best_bid + best_ask) / 2
    bid_depth = sum(float(b.get("size", 0)) for b in bids if float(b.get("price", 0)) >= mid * 0.95)
    ask_depth = sum(float(a.get("size", 0)) for a in asks if float(a.get("price", 0)) <= mid * 1.05)
    
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "spread_pct": round(spread_pct, 4),
        "mid": round(mid, 6),
        "bid_depth": round(bid_depth, 2),
        "ask_depth": round(ask_depth, 2),
        "total_depth": round(bid_depth + ask_depth, 2),
        "bid_levels": len(bids),
        "ask_levels": len(asks),
    }


def main():
    now = datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60
    is_wolf = 2.5 <= hour < 4.0
    
    print(f"=== Polymarket Wolf Hour Probe ===")
    print(f"UTC Time: {now.strftime('%Y-%m-%d %H:%M:%S')} (hour={hour:.2f})")
    print(f"Wolf Hour: {'YES' if is_wolf else 'NO'}")
    print()
    
    # Step 1: Find BTC markets
    print("Fetching BTC markets from Gamma API...")
    markets = fetch_btc_markets()
    print(f"Found {len(markets)} active BTC markets")
    
    if not markets:
        print("No BTC markets found. Exiting.")
        sys.exit(1)
    
    # Show top markets
    for i, m in enumerate(markets[:5]):
        print(f"  {i+1}. {m['question'][:60]}")
        print(f"     Volume: ${float(m.get('volume', 0) or 0):,.0f} | Bid: {m['best_bid']} Ask: {m['best_ask']}")
    
    # Step 2: Fetch orderbooks for top markets
    print(f"\nFetching orderbooks...")
    results = []
    
    for m in markets[:10]:  # Top 10 by volume
        token_id = m["token_id"]
        if not token_id or token_id == "0":
            continue
        
        time.sleep(0.3)  # Rate limit
        book = fetch_orderbook(token_id)
        spread_data = compute_spread(book)
        
        if spread_data:
            result = {
                "timestamp": now.isoformat(),
                "utc_hour": now.hour,
                "is_wolf_hour": is_wolf,
                "event": m["event"][:80],
                "question": m["question"][:80],
                "token_id": token_id[:20] + "...",
                **spread_data,
            }
            results.append(result)
            print(f"  {m['question'][:40]:40} | Spread: {spread_data['spread_pct']:.3f}% | Depth: ${spread_data['total_depth']:.0f}")
        else:
            print(f"  {m['question'][:40]:40} | NO ORDERBOOK")
    
    # Summary
    if results:
        spreads = [r["spread_pct"] for r in results]
        depths = [r["total_depth"] for r in results]
        
        print(f"\n=== SUMMARY ===")
        print(f"Markets with orderbooks: {len(results)}")
        print(f"Median spread: {sorted(spreads)[len(spreads)//2]:.4f}%")
        print(f"Mean spread: {sum(spreads)/len(spreads):.4f}%")
        print(f"Spread range: {min(spreads):.4f}% - {max(spreads):.4f}%")
        print(f"Median depth: ${sorted(depths)[len(depths)//2]:.0f}")
        print(f"Mean depth: ${sum(depths)/len(depths):.0f}")
        
        # Save snapshot
        snapshot_file = DATA_DIR / "spread_snapshots.jsonl"
        with open(snapshot_file, "a") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")
        print(f"\nSaved {len(results)} snapshots to {snapshot_file}")
    else:
        print("\nNo orderbook data available.")


if __name__ == "__main__":
    main()
