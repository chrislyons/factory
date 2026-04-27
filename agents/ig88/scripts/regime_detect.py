#!/usr/bin/env python3
import json
import sys
import requests
import os
from datetime import datetime, timezone

DATA_DIR = '/Users/nesbitt/dev/factory/agents/ig88/data'
REGIME_FILE = os.path.join(DATA_DIR, 'current_regime.json')

# BTC trend
btc = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT').json()
btc_price = float(btc['price'])
print(f"BTC Price: ${btc_price:,.2f}")

# Fear & Greed
fg = requests.get('https://api.alternative.me/fng/?limit=1').json()
fg_value = int(fg['data'][0]['value'])
print(f"Fear & Greed: {fg_value}")

# Simple regime scoring
score = 5  # neutral baseline
if fg_value > 60:
    score += 1
elif fg_value < 30:
    score -= 1

state = 'RISK_ON' if score >= 7 else 'RISK_OFF' if score <= 3 else 'NEUTRAL'

result = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'regime': {'state': state, 'score': score, 'confidence': 0.6},
    'btc_price': btc_price,
    'fear_greed': fg_value
}

# Read old regime if exists
old_state = None
old_regime = None
if os.path.exists(REGIME_FILE):
    try:
        with open(REGIME_FILE, 'r') as f:
            content = f.read()
            # Handle single quotes
            content = content.replace("'", '"')
            old_regime = json.loads(content)
            old_state = old_regime.get('regime', {}).get('state')
            print(f"Previous regime: {old_state}")
    except Exception as e:
        print(f"Warning: Could not read previous regime: {e}")
        old_state = None

# Write new regime
with open(REGIME_FILE, 'w') as f:
    json.dump(result, f, indent=2)

# Compare and output
if old_state is None:
    print("No previous regime found. New regime:")
    print(json.dumps(result, indent=2))
elif old_state != state:
    print(f"REGIME CHANGED: {old_state} -> {state}")
    print(json.dumps(result, indent=2))
else:
    print(f"Regime stable. Current state: {state}")
