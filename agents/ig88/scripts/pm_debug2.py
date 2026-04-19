#!/usr/bin/env python3
"""Debug Polymarket Gamma API - search for crypto markets"""
import requests
import json

GAMMA_API = "https://gamma-api.polymarket.com"

# Try search and crypto-specific endpoints
searches = [
    "/markets?limit=20&active=true&closed=false&order=volume24hr&ascending=false",
    "/events?limit=20&active=true&closed=false",
]

# Also try text search
search_terms = ["bitcoin", "btc", "crypto", "ethereum", "sol"]

for path in searches:
    url = f"{GAMMA_API}{path}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if isinstance(data, list):
            print(f"\nGET {path}: {len(data)} items")
            for item in data[:8]:
                title = item.get("title", item.get("question", item.get("description", "?")))
                vol = item.get("volume", item.get("volume24hr", "?"))
                end = item.get("endDate", item.get("end_date_iso", ""))
                active = item.get("active", "?")
                desc = item.get("description", "")[:80]
                print(f"  [{active}] vol={vol:>12} end={end[:10]:10} | {str(title)[:70]}")
                if desc:
                    print(f"         desc: {desc}")
    except Exception as e:
        print(f"\nGET {path} ERROR: {e}")

# Text search via different API
print("\n=== CLOB API market search ===")
for term in ["BTC", "ETH", "crypto", "Solana"]:
    try:
        url = f"https://clob.polymarket.com/markets?next_cursor=MA%3D%3D"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            markets = data.get("data", [])
            matching = [m for m in markets if term.lower() in str(m.get("question", "")).lower() or term.lower() in str(m.get("description", "")).lower()]
            print(f"  '{term}' in {len(markets)} markets: {len(matching)} matches")
            for m in matching[:3]:
                q = m.get("question", "?")
                print(f"    -> {str(q)[:70]}")
        else:
            print(f"  CLOB {term}: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  CLOB {term}: {e}")
