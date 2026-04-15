import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.trading.mtf_engine import MTFExecutionEngine

class MTF_2H_Specialist:
    def __init__(self, asset_list: List[str], data_dir: Path):
        self.asset_list = asset_list
        self.data_dir = data_dir
        self.timeframes = {
            "slow": 240, # 4h
            "fast": 120  # 2h
        }

    def _load_df(self, asset: str, tf: int) -> pd.DataFrame:
        symbol = asset.replace('/', '_')
        path = self.data_dir / f"binance_{symbol}_{tf}m.parquet"
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def run_test(self, friction: float = 0.01):
        results = {}
        engine = MTFExecutionEngine(config={})
        
        for asset in self.asset_list:
            df_slow = self._load_df(asset, self.timeframes["slow"])
            df_fast = self._load_df(asset, self.timeframes["fast"])
            
            if df_slow is None or df_fast is None:
                continue
            
            # We use the a slightly relaxed vol_gate to see if we can increase sample size
            # Modified params for this specific run
            engine.signal_params['vol_gate'] = 1.1 # Relaxed from 1.2
            
            # The mtf_engine.backtest_mtf handles the alignment and logic
            res = engine.backtest_mtf(df_slow, df_fast, friction=friction)
            results[asset] = res
            
        return results

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    tester = MTF_2H_Specialist(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    # Test with 1% realistic friction
    results = tester.run_test(friction=0.01)
    print(json.dumps(results, indent=2))
