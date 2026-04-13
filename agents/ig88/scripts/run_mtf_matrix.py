import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import json
from src.trading.mtf_engine import MTFExecutionEngine

class MTFMatrixTester:
    def __init__(self, asset_list: List[str], data_dir: Path):
        self.asset_list = asset_list
        self.data_dir = data_dir
        self.timeframes = {
            "slow": 240, # 4h
            "fast_1h": 60,
            "fast_2h": 120
        }

    def _load_df(self, asset: str, tf: int) -> pd.DataFrame:
        symbol = asset.replace('/', '_')
        path = self.data_dir / f"binance_{symbol}_{tf}m.parquet"
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def run_matrix(self, friction: float = 0.01):
        results = {}
        engine = MTFExecutionEngine(config={})
        
        for asset in self.asset_list:
            asset_res = {}
            df_slow = self._load_df(asset, self.timeframes["slow"])
            if df_slow is None: continue
            
            # Test 4h -> 1h
            df_1h = self._load_df(asset, self.timeframes["fast_1h"])
            if df_1h is not None:
                res_1h = engine.backtest_mtf(df_slow, df_1h, friction=friction)
                asset_res["4h_to_1h"] = res_1h
                
            # Test 4h -> 2h
            df_2h = self._load_df(asset, self.timeframes["fast_2h"])
            if df_2h is not None:
                res_2h = engine.backtest_mtf(df_slow, df_2h, friction=friction)
                asset_res["4h_to_2h"] = res_2h
                
            results[asset] = asset_res
        return results

if __name__ == "__main__":
    assets = ["SOL/USDT", "BTC/USDT", "ETH/USDT", "LINK/USDT", "AVAX/USDT", "NEAR/USDT"]
    tester = MTFMatrixTester(assets, Path("/Users/nesbitt/dev/factory/agents/ig88/data"))
    # Test with 1% realistic friction
    matrix_results = tester.run_matrix(friction=0.01)
    print(json.dumps(matrix_results, indent=2))
