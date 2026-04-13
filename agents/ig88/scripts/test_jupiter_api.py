"""
Test Jupiter Perps API: Check Available Markets
=================================================
"""
import urllib.request
import json

# Jupiter Perps API
# https://docs.jup.ag/docs/apis/perpetuals-api

def fetch_perp_markets():
    """Fetch available perp markets from Jupiter."""
    url = 'https://api.jup.ag/perps/v1/markets'
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        return {'error': str(e)}


def fetch_perp_prices():
    """Fetch perp prices."""
    url = 'https://api.jup.ag/perps/v1/prices'
    
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        return {'error': str(e)}


print("JUPITER PERPS API CHECK")
print("=" * 60)

# Check markets
print("\nFetching markets...")
markets = fetch_perp_markets()

if 'error' in markets:
    print(f"Error: {markets['error']}")
else:
    print(f"Response type: {type(markets)}")
    if isinstance(markets, dict):
        print(f"Keys: {list(markets.keys())[:10]}")
        if 'data' in markets:
            print(f"Markets count: {len(markets['data'])}")
            for m in markets['data'][:5]:
                print(f"  {m.get('symbol', m.get('market', 'unknown'))}")
    elif isinstance(markets, list):
        print(f"Markets count: {len(markets)}")
        for m in markets[:5]:
            print(f"  {m}")

# Check prices
print("\nFetching prices...")
prices = fetch_perp_prices()

if 'error' in prices:
    print(f"Error: {prices['error']}")
else:
    print(f"Response type: {type(prices)}")
    if isinstance(prices, dict):
        print(f"Keys: {list(prices.keys())[:10]}")
    elif isinstance(prices, list):
        print(f"Prices count: {len(prices)}")
        for p in prices[:3]:
            print(f"  {p}")
