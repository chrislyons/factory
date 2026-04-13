import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.trading.mtf_engine import MTFExecutionEngine

class MTF_2H_Surgical_Audit:
    def __init__(self, asset_list: List[str], data_dir: Path):
        self.asset_list = asset_list
        self.data_dir = data_dir
        self.timeframes = {
            "slow": 240, # 4h
            "fast": 120  # 2h
        }

    def _load_df(self, asset: str, tf: int) -> pd.DataFrame:
        # standardized to binance_{ASSET}USDT_{TF}m.parquet
        symbol = asset.replace('/', '').replace('_', '') # BTC/USD -> BTCUSD
        if not symbol.endswith('USDT'):
            # Handle the case where the file is binance_BTCUSDT_... but asset is BTC/USD
            # We need to ensure the symbol matches the vault files
            # Based on vault_fill.py: safe = binance_sym (e.g. BTCUSDT)
            # I'll try to find the file that matches the asset name
            pass
        
        # Actual file mapping based on the vault_fill.py results
        # BTC/USD -> BTCUSDT, etc.
        mapping = {
            "BTC/USD": "BTCUSDT",
            "ETH/USDT": "ETHUSDT",
            "SOL/USDT": "SOLUSDT",
            "LINK/USD": "LINKUSDT",
            "NEAR/USD": "NEARUSDT",
            "AVAX/USD": "AVAXUSDT",
        }
        binance_sym = mapping.get(asset, asset.replace('/', ''))
        path = self.data_dir / f"binance_{binance_sym}_{tf}m.parquet"
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def run_audit(self, friction: float = 0.01):
        results = {}
        engine = MTFExecutionEngine(config={})
        
        for asset in self.asset_list:
            df_slow = self._load_df(asset, self.timeframes["slow"])
            df_fast = self._load_df(asset, self.timeframes["fast"])
            
            if df_slow is None or df_fast is None:
                continue
            
            # Use the Surgical params defined in mtf_engine.py
            # we can tweak the vol_gate here if needed, but starting with 1.2
            engine.signal_params['vol_gate'] = 1.2
            
            res = engine.backtest_mtf(df_slow, df_fast, friction=friction)
            results[asset] = res
            
        return results

if __name__ == "__main__":
    assets = ["BTC/USD", "ETH/USDT", "SOL/USDT", "LINK/USD", "NEAR/USD", "AVAX/USD"]
    auditor = MTF_2H_Surgical_Audit(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    results = auditor.run_audit(friction=0.01)
    print(json.dumps(results, indent=2))
