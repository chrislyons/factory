# dYdX Venue Testing Workflow

## Overview
When spot strategies fail due to high friction, test the same strategies on dYdX v4 perps where maker rebates reduce effective friction to ~0.5%.

## dYdX API Endpoints

### Markets
```
GET https://indexer.dydx.trade/v4/perpetualMarkets
```
Returns all available markets with current prices.

### Historical Candles
```
GET https://indexer.dydx.trade/v4/candles/perpetualMarkets/{market}?resolution={resolution}&limit={limit}
```

**Resolution values**: `1MIN`, `5MINS`, `15MINS`, `30MINS`, `1HOUR`, `4HOURS`, `1DAY`
**Max limit**: 1000 candles

**Note**: Use `curl` not `urllib.request` - Python's urllib sometimes fails with this API.

### Example: Fetch via curl
```bash
curl -s "https://indexer.dydx.trade/v4/candles/perpetualMarkets/BTC-USD?resolution=4HOURS&limit=1000"
```

## Data Fetching Script

```bash
#!/bin/bash
# fetch_dydx.sh - Fetch 4H candles for target pairs
TARGETS="BTC-USD ETH-USD SOL-USD AVAX-USD ARB-USD LINK-USD UNI-USD MATIC-USD ATOM-USD AAVE-USD SUI-USD INJ-USD ADA-USD ALGO-USD LTC-USD NEAR-USD DOT-USD FIL-USD"

for market in $TARGETS; do
  echo -n "Fetching $market... "
  curl -s "https://indexer.dydx.trade/v4/candles/perpetualMarkets/${market}?resolution=4HOURS&limit=1000" > "dydx_${market}.json"
  size=$(wc -c < "dydx_${market}.json")
  echo "${size} bytes"
  sleep 0.5
done
```

## JSON to DataFrame Conversion

```python
import json
import pandas as pd

def load_dydx_json(filepath):
    with open(filepath) as f:
        data = json.load(f)
    
    if 'candles' not in data or not data['candles']:
        return None
    
    df = pd.DataFrame(data['candles'])
    
    # Convert numeric columns
    for col in ['open', 'high', 'low', 'close', 'usdVolume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Set timestamp index
    df['timestamp'] = pd.to_datetime(df['startedAt'])
    df = df.set_index('timestamp').sort_index()
    
    return df[['open', 'high', 'low', 'close', 'usdVolume']]
```

## Fee Structure

| Order Type | Fee | Effect |
|------------|-----|--------|
| Market (taker) | +0.05% | Small cost |
| Limit (maker) | -0.025% | **Rebate (you get paid)** |

**Practical implication**: Using limit orders on dYdX reduces friction from ~2% (spot) to ~0.5% (perps with rebates).

## Results Summary (2026-04-13)

At 0.5% friction, 11 pairs became viable vs only 5 at 2% friction:

| Pair | PF | N | R:R |
|------|------|---|-----|
| INJ | 13.63 | 8 | 1:4 |
| FIL | 5.35 | 9 | 1:3 |
| BTC | 4.12 | 9 | 1:4 |
| ADA | 4.12 | 10 | 1:2 |
| LTC | 3.80 | 8 | 1:2 |
| DOT | 3.36 | 9 | 1:4 |
| ALGO | 3.27 | 10 | 1:2 |
| ETH | 2.53 | 9 | 1:4 |
| SOL | 2.37 | 8 | 1:2 |
| ARB | 1.97 | 8 | 1:2 |
| AVAX | 1.94 | 12 | 1:3 |

## Caveats

1. **Sample sizes are small** (8-12 trades per pair from 1000 candles) - need longer history or paper trading to validate
2. **dYdX API can be inconsistent** - use curl, not Python urllib
3. **Perps require margin/collateral management** - not just spot trading
4. **Cross-margin vs isolated margin** affects liquidation risk
