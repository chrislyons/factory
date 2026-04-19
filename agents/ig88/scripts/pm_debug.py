#!/usr/bin/env python3
"""Debug Polymarket API — what's available?"""
import requests
import json

GAMMA_API = "https://gamma-api.polymarket.com"

# Try different endpoints
endpoints = [
    ("/events", {"limit": 20}),
    ("/events", {"limit": 20, "tag": "crypto"}),
    ("/events", {"limit": 20, "tag": "bitcoin"}),
    ("/markets", {"limit": 20}),
    ("/markets", {"limit": 20, "active": True}),
]

for path, params in endpoints:
    url = f"{GAMMA_API}{path}"
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if isinstance(data, list):
            print(f"\n{path} params={params}: {len(data)} items")
            for item in data[:5]:
                if isinstance(item, dict):
                    title = item.get("title", item.get("question", item.get("id", "?")))
                    active = item.get("active", "?")
                    closed = item.get("closed", "?")
                    vol = item.get("volume", "?")
                    print(f"  [{active}/{closed}] {str(title)[:70]} vol={vol}")
                    # Show markets within events
                    for m in item.get("markets", [])[:2]:
                        q = m.get("question", "?")
                        print(f"    -> {str(q)[:60]}")
        elif isinstance(data, dict):
            print(f"\n{path} params={params}: dict with keys {list(data.keys())[:5]}")
        else:
            print(f"\n{path}: {type(data)}")
    except Exception as e:
        print(f"\n{path} ERROR: {e}")
