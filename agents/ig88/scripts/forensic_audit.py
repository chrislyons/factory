import pandas as pd
import numpy as np
from pathlib import Path
import json
from src.quant.indicators import ichimoku, rsi, atr, sma

class StrategyForensics:
    def __init__(self, asset_list: List[str], data_dir: Path):
        self.asset_list = asset_list
        self.data_dir = data_dir
        self.data = self._load_all_data()

    def _load_all_data(self) -> Dict[str, pd.DataFrame]:
        data = {}
        for asset in self.asset_list:
            symbol = asset.replace('/', '_')
            path = self.data_dir / f"binance_{symbol}_240m.parquet"
            if path.exists():
                data[asset] = pd.read_parquet(path)
        return data

    def audit_asset(self, asset: str):
        df = self.data[asset]
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        
        # Recompute basics
        atr_v = atr(h, l, c, 14)
        ma20 = sma(c, 20)
        rolling_std = pd.Series(c).rolling(window=20).std().values
        bb_upper = ma20 + 2 * rolling_std
        bb_lower = ma20 - 2 * rolling_std
        
        # Calculate ATR as % of price to check for normalization anomalies
        # This is a key check: if ETH ATR is 0.1% and SOL is 5%, the logic behaves differently.
        atr_pct = (atr_v / c) * 100
        
        # Sample a few trades from the logic
        # We'll look for "wins" in the validation set (last 20%)
        split_idx = int(len(df) * 0.8)
        val_c = c[split_idx:]
        val_atr = atr_v[split_idx:]
        
        # Let's look for a specific "winning" trade pattern in the validation set
        wins = []
        losses = []
        
        # Simple H3-like trigger for sampling
        # (Using a simplified version to find trades to audit)
        for i in range(20, len(val_c)-1):
            # Trigger: Price > MA20 (simplest trend)
            if val_c[i] > ma20[split_idx + i]:
                entry = val_c[i]
                stop = entry - 2 * val_atr[i]
                target = entry + 5 * val_atr[i]
                
                for j in range(i+1, len(val_c)):
                    if val_c[j] <= stop:
                        losses.append({"entry": entry, "exit": val_c[j], "type": "stop"})
                        break
                    if val_c[j] >= target:
                        wins.append({"entry": entry, "exit": val_c[j], "type": "target"})
                        break
        
        return {
            "avg_atr_pct": np.nanmean(atr_pct),
            "std_atr_pct": np.nanstd(atr_pct),
            "trade_count": len(wins) + len(losses),
            "win_rate": len(wins) / (len(wins) + len(losses)) if (len(wins) + len(losses)) > 0 else 0,
            "sample_win": wins[0] if wins else None,
            "sample_loss": losses[0] if losses else None
        }

if __name__ == "__main__":
    from typing import List, Dict
    assets = ["SOL/USDT", "ETH/USDT"]
    forensics = StrategyForensics(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    
    results = {}
    for a in assets:
        results[a] = forensics.audit_asset(a)
        
    print(json.dumps(results, indent=2))
