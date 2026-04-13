import pandas as pd
from pathlib import Path
import json

def audit_vault():
    DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "NEARUSDT", "AVAXUSDT"]
    timeframes = [15, 60, 120, 240, 1440]
    
    report = {}
    all_found = True
    
    for asset in assets:
        asset_status = {}
        for tf in timeframes:
            filename = f"binance_{asset}_{tf}m.parquet"
            path = DATA_DIR / filename
            if path.exists():
                try:
                    df = pd.read_parquet(path)
                    count = len(df)
                    asset_status[f"{tf}m"] = f"OK ({count} bars)"
                except Exception as e:
                    asset_status[f"{tf}m"] = f"CORRUPT: {e}"
                    all_found = False
            else:
                asset_status[f"{tf}m"] = "MISSING"
                all_found = False
        report[asset] = asset_status
        
    return report, all_found

if __name__ == "__main__":
    report, success = audit_vault()
    print(json.dumps(report, indent=2))
    print(f"\nVAULT_COMPLETE: {success}")
