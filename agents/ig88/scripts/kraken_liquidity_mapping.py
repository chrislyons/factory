
import sys
sys.path.insert(0, '/Users/nesbitt/dev/factory/agents/ig88/.venv/lib/python3.11/site-packages')

import json
import urllib.request
import time

def http_get(url, timeout=15, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "IG-88-LiquidityAnalysis/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except Exception as e:
            raise

# Step 1: Get all active Kraken pairs
print("Fetching Kraken asset pairs...")
pairs_data = http_get("https://api.kraken.com/0/public/AssetPairs")
all_pairs = pairs_data.get("result", {})

# Filter active USD/USDT pairs
kraken_active = {}
for key, info in all_pairs.items():
    if info.get("status", "").upper() == "ONLINE":
        quote = info.get("quote", "")
        if quote in ["USD", "USDT", "ZUSD"]:
            kraken_active[key] = info

print(f"Active Kraken USD/USDT pairs: {len(kraken_active)}")

# Build a mapping from base asset to all quote variants
base_to_kraken = {}
for k, v in kraken_active.items():
    base = v.get("base", "")
    quote = v.get("quote", "")
    if base not in base_to_kraken:
        base_to_kraken[base] = []
    base_to_kraken[base].append({"pair": k, "quote": quote})

# Show some examples
print("\nSample mapping (base -> Kraken pairs):")
for base in sorted(base_to_kraken.keys())[:15]:
    print(f"  {base:10s}: {[x['pair'] for x in base_to_kraken[base]]}")

# Step 2: Load our Binance volume analysis results
with open("/Users/nesbitt/dev/factory/agents/ig88/memory/ig88/liquidity_analysis_2yr.json") as f:
    liquidity_data = json.load(f)

binance_results = liquidity_data['all_pairs']

# Step 3: Map Binance symbols to Kraken equivalents
# Binance uses combined symbols like BTCUSDT; Kraken uses BASE/QUOTE format
def binance_to_kraken_mapping(binance_symbol):
    """Convert Binance symbol (e.g., BTCUSDT) to potential Kraken pair(s)."""
    # Known Kraken quote currencies
    quote_currencies = ["USD", "USDT", "ZUSD"]
    
    # Try to split symbol into base + quote
    for quote in quote_currencies:
        if binance_symbol.endswith(quote):
            base = binance_symbol[:-len(quote)]
            return base, quote
    
    # Special cases
    special_cases = {
        "BTCUSD": ("XBT", "USD"),  # Kraken uses XBT for Bitcoin
        "BTCUSDT": ("BTC", "USDT"),
        "ETHUSD": ("ETH", "USD"),
        "ETHUSDT": ("ETH", "USDT"),
    }
    if binance_symbol in special_cases:
        return special_cases[binance_symbol]
    
    # Fallback: try to parse
    return None, None

# Build mapping of Binance top pairs to Kraken availability
print("\n" + "="*110)
print("KRAKEN LIQUIDITY RANKING — TOP PAIRS AVAILABLE ON KRAKEN")
print("="*110)

kraken_ranked = []
unavailable_on_kraken = []

for r in binance_results:
    binance_symbol = r['symbol']
    base, quote = binance_to_kraken_mapping(binance_symbol)
    
    if not base:
        unavailable_on_kraken.append((binance_symbol, "cannot parse"))
        continue
    
    # Look for matching Kraken pairs
    matching_kraken = []
    if base in base_to_kraken:
        matching_kraken = [x for x in base_to_kraken[base]]
    else:
        # Try alternative base names (e.g., XBT vs BTC)
        alt_base = None
        if base == "BTC":
            alt_base = "XBT"
        elif base == "XBT":
            alt_base = "BTC"
        
        if alt_base and alt_base in base_to_kraken:
            matching_kraken = [x for x in base_to_kraken[alt_base]]
    
    if matching_kraken:
        # Find best matching quote (prefer same quote currency)
        best_match = None
        for mk in matching_kraken:
            if mk['quote'] == quote:
                best_match = mk
                break
        if not best_match:
            best_match = matching_kraken[0]  # take first available
        
        kraken_pair = best_match['pair']
        r_copy = r.copy()
        r_copy['kraken_pair'] = kraken_pair
        r_copy['base_asset'] = base
        r_copy['binance_symbol'] = binance_symbol
        kraken_ranked.append(r_copy)
    else:
        unavailable_on_kraken.append((binance_symbol, f"base '{base}' not found in Kraken"))

print(f"\nTop pairs available on Kraken: {len(kraken_ranked)}")
print(f"Unavailable on Kraken: {len(unavailable_on_kraken)}")

if unavailable_on_kraken:
    print("\nNot available on Kraken (top volume):")
    for sym, reason in unavailable_on_kraken[:10]:
        print(f"  {sym}: {reason}")

# Sort and display final ranking
kraken_ranked.sort(key=lambda x: x['avg_daily_volume_usd'], reverse=True)

print("\n" + "-"*110)
print(f"{'Rank':<5} {'Kraken Pair':<20} {'Base':<10} {'Avg Daily Vol':>18} {'CV':>7}")
print("-"*110)
for i, r in enumerate(kraken_ranked[:25], 1):
    print(f"{i:<5} {r['kraken_pair']:<20} {r['base_asset']:<10} ${r['avg_daily_volume_usd']:>16,.0f}  {r['volume_cv']:>6.2f}")

# Categorize by IG-88's current coverage
ig88_current = {
    "BTC/USD", "ETH/USDT", "SOL/USDT", "JUP/USDT", "LINK/USDT", 
    "RENDER/USDT", "POL/USDT", "HOT/USDT", "NEAR/USDT", "THETA/USDT",
    "AR/USDT", "FIL/USDT", "INJ/USDT", "SEI/USDT", "AKT/USDT",
    "IP/USDT", "DYM/USDT", "PYTH/USDT", "TIA/USDT", "UNI/USDT",
    "FET/USDT", "GRT/USDT", "W/USDT", "DOGE/USDT", "WIF/USDT",
    "BONK/USDT", "MOODENG/USDT", "KAS/USDT", "XRP/USDT", "AVAX/USDT",
    "ORDI/USDT", "TAO/USDT", "GTC/USDT", "ATOM/USDT", "OSMO/USDT",
    "AUDIO/USDT",
}

print("\n\nIG-88 CURRENT COVERAGE vs. TOP LIQUIDITY PAIRS:")
print("-"*110)
covered = []
missing = []
for r in kraken_ranked[:30]:
    if r['kraken_pair'] in ig88_current:
        covered.append(r)
    else:
        missing.append(r)

print(f"\nCovered in top 30: {len(covered)} pairs")
for r in covered:
    print(f"  ✓ {r['kraken_pair']:<20} ${r['avg_daily_volume_usd']:>12,.0f}")

print(f"\nNOT covered (top 30): {len(missing)} pairs")
for r in missing:
    print(f"  ✗ {r['kraken_pair']:<20} ${r['avg_daily_volume_usd']:>12,.0f}  (base: {r['base_asset']})")
