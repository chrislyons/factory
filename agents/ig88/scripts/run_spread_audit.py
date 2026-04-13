import urllib.request
import json
import numpy as np
from pathlib import Path
from typing import List, Dict, Any

class KrakenSpreadAuditor:
    def __init__(self, assets: List[str]):
        self.assets = assets
        self.base_url = "https://api.kraken.com/0/public/Ticker"

    def get_spread(self, pair: str) -> Dict[str, Any]:
        try:
            # Kraken Ticker API provides: 
            # 'a': ask [price, whole lot volume, lot volume]
            # 'b': bid [price, whole lot volume, lot volume]
            url = f"{self.base_url}?pair={pair}"
            req = urllib.request.Request(url, headers={"User-Agent": "IG-88/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
                
                if data.get("error"):
                    return {"error": data["error"]}
                
                # The result is keyed by the pair name Kraken uses (e.g., 'XXSOLZCAD')
                # We extract the first key in 'result'
                result_key = list(data["result"].keys())[0]
                ticker = data["result"][result_key]
                
                ask = float(ticker['a'][0])
                bid = float(ticker['b'][0])
                mid = (ask + bid) / 2
                
                spread_pct = ((ask - bid) / mid) * 100
                
                return {
                    "pair": pair,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "spread_pct": spread_pct
                }
        except Exception as e:
            return {"error": str(e)}

if __name__ == "__main__":
    # We must use Kraken's pair naming. 
    # For CAD pairs, they often use XXXXXCAD (e.g., SOLCAD, BTC_CAD)
    # Based on previous logs, we are using SOLCAD, BTC_CAD, ETH_CAD, etc.
    pairs_to_test = ["SOLCAD", "BTC_CAD", "ETH_CAD", "LINKCAD", "AVAXCAD", "NEARCAD"]
    
    auditor = KrakenSpreadAuditor(pairs_to_test)
    final_results = {}
    
    for p in pairs_to_test:
        print(f"Auditing spread for {p}...")
        final_results[p] = auditor.get_spread(p)
        
    print("\n--- KRAKEN REAL-TIME SPREAD AUDIT ---")
    print(json.dumps(final_results, indent=2))
